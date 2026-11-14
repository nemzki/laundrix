"""Business logic for the staff portal.

Staff sign in with email + password, Google, or Face Login (Didit Face Search).
Didit identity verification is performed once, during enrollment.
Laundrix stores password hashes, but no face data and no Staff ID.
"""
import hashlib
import re
import secrets
from datetime import timedelta

from flask import current_app, request
from werkzeug.security import check_password_hash, generate_password_hash

from app.audit.services import audit_auth_event
from app.extensions import db
from app.models import AccountStatus, AuthEvent, Role, StaffCredential, User
from app.models.staff_credential import utcnow

ENROLL_KEY = "staff_enroll"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$")



# ---- normalisation / tokens ---------------------------------------------------------------
def normalize_email(value) -> str:
    return (value or "").strip().lower()[:255]


def valid_email(value: str) -> bool:
    return bool(EMAIL_RE.match(value))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_dummy = None


def dummy_hash() -> str:
    """Used for unknown emails so response time doesn't reveal whether an account exists."""
    global _dummy
    if _dummy is None:
        _dummy = generate_password_hash("not-a-real-password")
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


def create_staff(email: str, full_name=None, account_status=None):
    email = normalize_email(email)
    if not valid_email(email):
        raise ValueError("Invalid email address.")
    if db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none():
        raise ValueError("A user with this email already exists.")

    token, token_hash, expires = _new_token_fields()
    if account_status is not None and account_status not in AccountStatus.ALL:
        raise ValueError("Unknown account status.")
    user = User(email=email, full_name=full_name, role=Role.STAFF, is_active=True)
    if account_status is not None:           # Staff Management starts accounts at pending_verification
        user.account_status = account_status
    user.staff_credential = StaffCredential(
        enroll_token_hash=token_hash,
        enroll_token_expires_at=expires,
    )
    db.session.add(user)
    db.session.commit()
    return user, token


def _credential_or_error(user: User) -> StaffCredential:
    if user.staff_credential is None:
        raise ValueError("This user is not a staff member.")
    return user.staff_credential


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
    audit_auth_event(event, success=success, actor=user, target=user, email=email)
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


def verify_staff_password(cred, entered: str) -> bool:
    """Verify a staff password without revealing whether an account exists."""
    stored = (
        cred.password_hash
        if cred and cred.password_hash
        else dummy_hash()
    )

    ok = check_password_hash(stored, entered or "")
    return bool(ok and cred and cred.password_hash)