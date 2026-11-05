"""Unified username-or-email + password sign-in for administrators AND staff.

One orchestration point for every credential form (the public login page and the two legacy
pages). It reuses the existing primitives instead of re-implementing them:

* administrators: `check_admin_password` (constant-time hash check), User.failed_login_attempts /
  locked_until;
* staff: `verify_staff_password`, `register_failure`, StaffCredential lockout, `is_enrolled`
  (the one-time Didit identity verification still gates every staff sign-in).

Callers only ever see a generic failure for unknown, disabled, suspended, rejected or deactivated
accounts. Only someone who proves they know the password is told that setup or approval is still
pending. Google sign-in is separate (app/auth/services.py) and never goes through here."""
from dataclasses import dataclass
from datetime import timedelta

from flask import current_app, session
from flask_login import login_user

from app.auth.bootstrap import check_admin_password
from app.core.audit import record_event
from app.extensions import db
from app.models import AccountStatus, Role, User
from app.models.staff_credential import utcnow

OK, INVALID, LOCKED, PENDING, NOT_ENROLLED = "ok", "invalid", "locked", "pending", "not_enrolled"
HTTP_STATUS = {OK: 302, INVALID: 401, LOCKED: 423, PENDING: 403, NOT_ENROLLED: 403}

GENERIC_FAIL = "Invalid username or password."
LOCKED_MSG = "Too many failed attempts. This account is temporarily locked. Try again later."
SETUP_INCOMPLETE = "Your account setup is incomplete. Please contact your administrator."
AWAITING_APPROVAL = "Your account is awaiting administrator approval."


@dataclass
class AuthOutcome:
    kind: str
    user: object = None
    message: str = ""
    just_locked: bool = False

    @property
    def ok(self) -> bool:
        return self.kind == OK

    @property
    def http_status(self) -> int:
        return HTTP_STATUS[self.kind]


def _find_user(identifier, only_role):
    ident = (identifier or "").strip().lower()[:254]
    if not ident:
        return None, ident
    column = User.email if "@" in ident else User.username      # usernames can never contain "@"
    user = db.session.execute(db.select(User).where(column == ident)).scalar_one_or_none()
    if user is not None and only_role is not None and user.role != only_role:
        user = None
    return user, ident


def _password_enabled(user, cred) -> bool:
    if user is None:
        return False
    if user.role == Role.ADMIN:
        return bool(user.password_hash and current_app.config.get("ADMIN_PASSWORD_LOGIN_ENABLED"))
    if user.role == Role.STAFF:
        return cred is not None
    return False


def _may_try_password(user) -> bool:
    """Accounts allowed to even attempt a password sign-in (everything else fails generically)."""
    if not user.is_active or user.account_status in AccountStatus.BLOCKED:
        return False
    if user.role == Role.ADMIN:
        return user.account_status == AccountStatus.ACTIVE
    return user.account_status in (AccountStatus.ACTIVE, *AccountStatus.PENDING)


def _register_admin_failure(user) -> bool:
    cfg = current_app.config
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    locked = user.failed_login_attempts >= cfg["STAFF_MAX_FAILED_ATTEMPTS"]
    if locked:
        user.locked_until = utcnow() + timedelta(minutes=cfg["STAFF_LOCKOUT_MINUTES"])
        user.failed_login_attempts = 0
    db.session.commit()
    return locked


def authenticate(identifier, password, *, only_role=None) -> AuthOutcome:
    """Check credentials. Never logs anyone in: see `establish_session`."""
    from app.staff_auth import services as staff  # lazy: avoids an import cycle at start-up

    password = (password or "")[:256]
    user, ident = _find_user(identifier, only_role)
    cred = user.staff_credential if (user is not None and user.role == Role.STAFF) else None
    usable = user is not None and _password_enabled(user, cred) and _may_try_password(user)
    is_admin = user is not None and user.role == Role.ADMIN
    fail_event = "admin_login_failed" if is_admin else ("password_login_failed" if user else "login_failed")

    if usable and (user.is_locked if is_admin else cred.is_locked):
        record_event("admin_login_locked" if is_admin else "password_login_locked",
                     success=False, target=user, email=ident, commit=True)
        return AuthOutcome(LOCKED, message=LOCKED_MSG)

    # Always run exactly one hash comparison (a dummy one when the account can't be used).
    if is_admin:
        valid = check_admin_password(user if usable else None, password)
    else:
        valid = staff.verify_staff_password(cred if usable else None, password)

    if not valid:
        just_locked = False
        if usable:
            just_locked = _register_admin_failure(user) if is_admin else staff.register_failure(cred)
        record_event(fail_event, success=False, target=user if usable else None, email=ident, commit=True)
        return AuthOutcome(INVALID, message=LOCKED_MSG if just_locked else GENERIC_FAIL, just_locked=just_locked)

    # Correct password. Pending staff are told why they cannot continue yet.
    if user.account_status == AccountStatus.PENDING_APPROVAL:
        record_event("login_pending_approval", success=False, target=user, commit=True)
        return AuthOutcome(PENDING, message=AWAITING_APPROVAL)
    if user.account_status == AccountStatus.PENDING_VERIFICATION or (
            user.role == Role.STAFF and not staff.is_enrolled(user)):
        record_event("password_login_not_enrolled", success=False, target=user, commit=True)
        return AuthOutcome(NOT_ENROLLED, message=SETUP_INCOMPLETE)

    if is_admin:
        user.failed_login_attempts, user.locked_until = 0, None
    else:
        cred.failed_attempts, cred.locked_until = 0, None
    user.last_login_at = utcnow()
    record_event("admin_login" if is_admin else "password_login_success", actor=user, target=user)
    db.session.commit()
    return AuthOutcome(OK, user=user)


def establish_session(user) -> bool:
    """Start a brand-new authenticated session (the old one is discarded: no session fixation)."""
    session.clear()
    if not login_user(user):
        session.clear()
        return False
    session.permanent = True
    return True
