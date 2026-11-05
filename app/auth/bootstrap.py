"""Initial administrator setup and password handling (separate from the HTTP layer).

The initial administrator is created ONLY by `flask bootstrap-admin`, never by public sign-up and
never implicitly at app start-up. The password comes from the environment, is validated, hashed
with the same Werkzeug hasher the staff portal uses, and is never logged or stored in plaintext.
Once the account exists it is left strictly alone: a later run never changes its password."""
import re
from dataclasses import dataclass

from werkzeug.security import check_password_hash, generate_password_hash

from app.core.audit import record_event
from app.extensions import db
from app.models import AccountStatus, Role, User
from app.models.staff_credential import utcnow

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,39}$")
MIN_LENGTH, MAX_LENGTH = 12, 256
_COMMON = {
    "password1234", "password12345", "administrator", "admin1234567", "qwerty123456",
    "123456789012", "laundrix1234", "changeme1234", "letmein12345", "welcome12345",
}
_dummy = None


def dummy_hash() -> str:
    """Compared against when a username is unknown, so timing doesn't reveal which usernames exist."""
    global _dummy
    if _dummy is None:
        _dummy = generate_password_hash("not-a-real-admin-password")
    return _dummy


def password_problems(password, username=""):
    """Human-readable reasons a password is unacceptable (empty list = OK). Never echoes the password."""
    problems = []
    password = password or ""
    if len(password) < MIN_LENGTH:
        problems.append(f"must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        problems.append(f"must be at most {MAX_LENGTH} characters")
    classes = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if classes < 3:
        problems.append("must mix at least 3 of: lowercase, uppercase, digits, symbols")
    lowered = password.lower()
    if username and username.lower() in lowered:
        problems.append("must not contain the username")
    if lowered in _COMMON:
        problems.append("is too common")
    return problems


def check_admin_password(user, password) -> bool:
    stored = user.password_hash if user is not None and user.password_hash else dummy_hash()
    ok = check_password_hash(stored, password or "")
    return bool(ok and user is not None and user.password_hash)


@dataclass
class BootstrapResult:
    status: str          # created | exists | skipped_other_admin | invalid
    message: str
    user: object = None


def create_initial_admin(username, password, email=None, allow_additional=False) -> BootstrapResult:
    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        return BootstrapResult("invalid", "INITIAL_ADMIN_USERNAME must be 3-40 characters: "
                                          "lowercase letters, digits, dot, dash or underscore.")

    existing = db.session.execute(db.select(User).filter_by(username=username)).scalar_one_or_none()
    if existing is not None:
        if existing.role != Role.ADMIN:
            return BootstrapResult("invalid", f"The username '{username}' belongs to a non-administrator account.")
        return BootstrapResult("exists", f"Administrator '{username}' already exists; left unchanged.", existing)

    if not allow_additional and db.session.scalar(db.select(db.func.count(User.id)).filter_by(role=Role.ADMIN)):
        return BootstrapResult(
            "skipped_other_admin",
            "An administrator already exists, so no initial administrator was created "
            "(use --allow-additional to add this username anyway).")

    if not password:
        return BootstrapResult("invalid", "INITIAL_ADMIN_PASSWORD is not set.")
    problems = password_problems(password, username)
    if problems:
        return BootstrapResult("invalid", "INITIAL_ADMIN_PASSWORD " + "; ".join(problems) + ".")

    email = (email or f"{username}@laundrix.invalid").strip().lower()
    if db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none():
        return BootstrapResult("invalid", "A user with the administrator email already exists.")

    now = utcnow()
    admin = User(
        email=email, username=username, full_name="Administrator", role=Role.ADMIN,
        is_active=True, account_status=AccountStatus.ACTIVE, approved_at=now,
        password_hash=generate_password_hash(password),
    )
    db.session.add(admin)
    db.session.flush()
    record_event("admin_bootstrap", target=admin, detail="Initial administrator created")
    db.session.commit()
    return BootstrapResult("created", f"Administrator '{username}' created.", admin)


def rotate_password(user, new_password):
    """Set a new administrator password (validated + hashed) and clear any lockout."""
    if user is None or user.role != Role.ADMIN or not user.username:
        raise ValueError("That account is not a password administrator.")
    problems = password_problems(new_password, user.username)
    if problems:
        raise ValueError("The new password " + "; ".join(problems) + ".")
    user.password_hash = generate_password_hash(new_password)
    user.failed_login_attempts, user.locked_until = 0, None
    record_event("admin_password_rotated", target=user, detail="Password changed")
    db.session.commit()
