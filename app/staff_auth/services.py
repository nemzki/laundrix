"""Business logic for the staff portal (no HTTP rendering here).

Sign-in = email + Staff ID + a live face check performed by Didit (Biometric Authentication).
Laundrix stores no face data: only a hashed Staff ID, lockout state and audit events.
"""
import hashlib
import re
import secrets
import time
from datetime import timedelta

from flask import current_app, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import AuthEvent, Role, StaffCredential, User
from app.models.staff_credential import utcnow

WIZARD_KEY = "staff_login"
ENROLL_KEY = "staff_enroll"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$")

LOCKED_MSG = "Too many failed attempts. This account is temporarily locked. Try again later."
GENERIC_FAIL = "We couldn't verify those details. Please check and try again."


# ---- normalisation / tokens ---------------------------------------------------------------
def normalize_email(value) -> str:
    return (value or "").strip().lower()[:255]


def valid_email(value: str) -> bool:
    return bool(EMAIL_RE.match(value))


def normalize_staff_id(value) -> str:
    return re.sub(r"\s+", "", value or "").upper()[:64]


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}{'*' * max(len(name) - 1, 2)}@{domain}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_staff_id() -> str:
    return f"LX-{secrets.randbelow(10**8):08d}"


_dummy = None


def dummy_hash() -> str:
    """Used for unknown emails so response time doesn't reveal whether an account exists."""
    global _dummy
    if _dummy is None:
        _dummy = generate_password_hash("not-a-real-staff-id")
    return _dummy


def is_enrolled(user: User) -> bool:
    """Enrolled = the person's one-time Didit ID verification was approved."""
    from app.identity.services import has_verified_identity

    return has_verified_identity(user)


# ---- provisioning (used by the CLI now, an admin dashboard later) -------------------------
def _new_token_fields():
    token = secrets.token_urlsafe(32)
    hours = current_app.config["STAFF_ENROLL_TOKEN_HOURS"]
    return token, hash_token(token), utcnow() + timedelta(hours=hours)


def _checked_staff_id(staff_id):
    staff_id = normalize_staff_id(staff_id) if staff_id else generate_staff_id()
    if len(staff_id) < 6:
        raise ValueError("Staff ID must be at least 6 characters.")
    return staff_id


def create_staff(email: str, full_name=None, staff_id=None):
    email = normalize_email(email)
    if not valid_email(email):
        raise ValueError("Invalid email address.")
    if db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none():
        raise ValueError("A user with this email already exists.")

    staff_id = _checked_staff_id(staff_id)
    token, token_hash, expires = _new_token_fields()
    user = User(email=email, full_name=full_name, role=Role.STAFF, is_active=True)
    user.staff_credential = StaffCredential(
        staff_id_hash=generate_password_hash(staff_id),
        enroll_token_hash=token_hash,
        enroll_token_expires_at=expires,
    )
    db.session.add(user)
    db.session.commit()
    return user, staff_id, token


def _credential_or_error(user: User) -> StaffCredential:
    if user.staff_credential is None:
        raise ValueError("This user is not a staff member.")
    return user.staff_credential


def reset_staff_id(user: User, staff_id=None) -> str:
    """Lost Staff ID: issue a new one and clear any lockout. Their verified identity is unaffected."""
    cred = _credential_or_error(user)
    staff_id = _checked_staff_id(staff_id)
    cred.staff_id_hash = generate_password_hash(staff_id)
    cred.failed_attempts, cred.locked_until = 0, None
    db.session.commit()
    return staff_id


def new_enroll_link(user: User) -> str:
    """Issue a fresh single-use onboarding link (first-time Didit verification, or re-verification)."""
    cred = _credential_or_error(user)
    token, token_hash, expires = _new_token_fields()
    cred.enroll_token_hash, cred.enroll_token_expires_at = token_hash, expires
    db.session.commit()
    return token


def deactivate_staff(user: User):
    """Offboarding: no more sign-in. Didit still holds the person's data; see the CLI reminder."""
    user.is_active = False
    cred = user.staff_credential
    if cred:
        cred.enroll_token_hash = cred.enroll_token_expires_at = None
    db.session.commit()


# ---- audit + lockout ----------------------------------------------------------------------
def log_event(event: str, success: bool, user=None, email=None):
    db.session.add(AuthEvent(
        user_id=user.id if user else None,
        email=email or (user.email if user else None),
        event=event,
        success=success,
        ip=(request.remote_addr or "")[:45],
        user_agent=(request.user_agent.string or "")[:255],
    ))
    db.session.commit()


def register_failure(cred: StaffCredential) -> bool:
    """Count a failed attempt. Returns True if the account just became locked."""
    cfg = current_app.config
    cred.failed_attempts += 1
    locked = cred.failed_attempts >= cfg["STAFF_MAX_FAILED_ATTEMPTS"]
    if locked:
        cred.locked_until = utcnow() + timedelta(minutes=cfg["STAFF_LOCKOUT_MINUTES"])
        cred.failed_attempts = 0
    db.session.commit()
    return locked


def register_success(cred: StaffCredential):
    cred.failed_attempts, cred.locked_until = 0, None
    cred.last_verified_at = utcnow()
    db.session.commit()


# ---- login wizard state (server-side, in the signed session) -------------------------------
def start_wizard(user, email: str):
    window = current_app.config["STAFF_LOGIN_WINDOW_SECONDS"]
    eligible = user is not None and user.role == Role.STAFF and user.is_active
    session[WIZARD_KEY] = {
        "uid": user.id if eligible else None,
        "email": email,
        "stage": "id",
        "exp": time.time() + window,
        "fails": 0,
        "vid": None,      # id of the Didit face-check attempt in flight
        "t0": 0.0,        # when that attempt started (a stale approval can't be reused)
        "polls": 0,
    }


def get_wizard(stage: str):
    wiz = session.get(WIZARD_KEY)
    if not wiz or wiz.get("exp", 0) < time.time() or wiz.get("stage") != stage:
        return None
    return wiz


def save_wizard(wiz: dict):
    session[WIZARD_KEY] = wiz  # reassign so Flask notices the change


def clear_wizard():
    session.pop(WIZARD_KEY, None)


# ---- enrollment tokens ----------------------------------------------------------------------
def find_credential_by_token(token: str):
    """A valid link = an unexpired token on an active account. (An already-verified person may be
    sent a new link by an administrator to re-verify, so being verified does not invalidate it.)"""
    cred = db.session.execute(
        db.select(StaffCredential).filter_by(enroll_token_hash=hash_token(token))
    ).scalar_one_or_none()
    if (
        cred is None
        or cred.enroll_token_expires_at is None
        or cred.enroll_token_expires_at < utcnow()
        or not cred.user.is_active
    ):
        return None
    return cred


def verify_staff_id(cred, entered: str) -> bool:
    stored = cred.staff_id_hash if cred else dummy_hash()
    ok = check_password_hash(stored, entered)
    return bool(ok and cred)
