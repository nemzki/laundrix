"""Staff Management: the staff account lifecycle, driven by administrators.

    create (admin) ──> pending_verification ──[Didit approves the ID]──> pending_approval
                                                                              │ approve
        reject <─ (either pending state)                                      v
                                                                           active <──reactivate── suspended
                                                                             │ suspend ─────────────^
        deactivate <─ (any state except deactivated)

Rules enforced here (never in the browser):
* only an active administrator may act, and never on their own account;
* only STAFF accounts are touched, so roles can never be changed from this module;
* `is_active` (can hold a session at all) and `account_status` (where the account is in its
  lifecycle) are set together, deliberately, in `_set_status`; the account gate and the credential
  service then refuse blocked or unapproved accounts everywhere;
* every action is one transaction that also writes the audit row;
* enrollment links are stored only as hashes, shown once at creation, and revoked whenever an
  account is rejected, suspended or deactivated.
"""
import re

from flask import current_app
from sqlalchemy import or_

from app.core.audit import record_event
from app.extensions import db
from app.identity import services as idv
from app.models import AccountStatus, AuthEvent, Role, User
from app.models.staff_credential import utcnow
from app.staff_auth import services as staff_services

PAGE_SIZE = 15
SORTS = {
    "newest": User.created_at.desc(), "oldest": User.created_at.asc(),
    "name": db.func.lower(db.func.coalesce(User.full_name, User.email)), "email": User.email.asc(),
}
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

IDV_LABELS = {
    None: ("Not started", "neutral"), "not_started": ("Not started", "neutral"),
    "in_progress": ("In progress", "progress"), "pending_review": ("In review", "warn"),
    "action_required": ("Action required", "warn"), "verified": ("Verified", "success"),
    "rejected": ("Rejected", "neutral"), "error": ("Error", "warn"),
}


class ActionError(Exception):
    """A refused action. The message is safe to show to the administrator."""


# ----------------------------------------------------------------------------- helpers
def identity_summary(user):
    """(label, tone, verification-or-None). Status only: no documents, no provider payloads."""
    v = idv.latest_verification(user)
    label, tone = IDV_LABELS.get(v.status if v else None, IDV_LABELS[None])
    return label, tone, v


def _clean(text, limit):
    return _CONTROL.sub("", str(text or "")).strip()[:limit + 1]


def _reason(value):
    reason = _clean(value, 255)
    if len(reason) < 3 or len(reason) > 255:
        raise ActionError("Enter a reason (3 to 255 characters).")
    return reason


def _acting_admin(actor):
    if getattr(actor, "role", None) != Role.ADMIN or not actor.is_operational:
        raise ActionError("Only an active administrator can manage staff accounts.")


def _locked_target(user_id, actor):
    """Re-read the target under a row lock so two admins cannot apply conflicting actions."""
    _acting_admin(actor)
    target = db.session.execute(
        db.select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if target is None or target.role != Role.STAFF:          # admins are never reachable from here
        raise ActionError("Staff account not found.")
    if target.id == actor.id:
        raise ActionError("You cannot change your own account here.")
    return target


def _set_status(target, actor, status, *, reason=None, is_active):
    target.account_status = status
    target.is_active = is_active
    target.status_reason = reason
    target.status_changed_at = utcnow()
    target.status_changed_by_id = actor.id


def _revoke_enrollment(target):
    cred = target.staff_credential
    if cred is not None:
        cred.enroll_token_hash = cred.enroll_token_expires_at = None


def _enrollment_url(token):
    base = (current_app.config.get("APP_BASE_URL") or "").rstrip("/")
    return f"{base}/staff/enroll/{token}"


def _finish(action, actor, target, detail):
    record_event(action, actor=actor, target=target, detail=detail)
    db.session.commit()
    return target


def _transaction(fn):
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            db.session.rollback()
            raise
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


# ----------------------------------------------------------------------------- creation
def create_staff_account(full_name, email, actor):
    """Create a staff account through the existing `create_staff` service. Returns
    (user, enrollment_url, expires_at). The raw token exists only in this return value."""
    _acting_admin(actor)
    name = " ".join(_clean(full_name, 150).split())
    if len(name) < 2 or len(name) > 150:
        raise ActionError("Enter the staff member's full name (2 to 150 characters).")
    try:
        user, token = staff_services.create_staff(
            email, name, account_status=AccountStatus.PENDING_VERIFICATION)
    except ValueError as exc:
        raise ActionError(str(exc))
    record_event("staff_created", actor=actor, target=user, detail="Account created; enrollment link issued")
    db.session.commit()
    return user, _enrollment_url(token), user.staff_credential.enroll_token_expires_at


@_transaction
def issue_enrollment_link(user_id, actor):
    """A replacement single-use link (first-time or re-verification). Older links stop working."""
    target = _locked_target(user_id, actor)
    if target.account_status not in (AccountStatus.PENDING_VERIFICATION, AccountStatus.ACTIVE) or not target.is_active:
        raise ActionError("A new enrollment link can only be issued for pending or active staff.")
    if target.staff_credential is None:
        raise ActionError("This account has no staff credentials.")
    token = staff_services.new_enroll_link(target)       # replaces (and so invalidates) the previous link
    record_event("staff_enroll_link_issued", actor=actor, target=target, detail="Replacement link issued")
    db.session.commit()
    return _enrollment_url(token), target.staff_credential.enroll_token_expires_at


def mark_identity_verified(user):
    """Called (without commit) when Didit approves a staff member's ID: the account now waits for an
    administrator. Accounts that are not waiting for verification are left exactly as they are."""
    if user is not None and user.role == Role.STAFF and user.account_status == AccountStatus.PENDING_VERIFICATION:
        user.account_status = AccountStatus.PENDING_APPROVAL
        user.status_changed_at = utcnow()
        record_event("staff_verification_completed", target=user,
                     detail="Identity verified by Didit; awaiting administrator approval")


# ----------------------------------------------------------------------------- lifecycle actions
@_transaction
def approve(user_id, actor):
    target = _locked_target(user_id, actor)
    if target.account_status != AccountStatus.PENDING_APPROVAL:
        raise ActionError("Only accounts awaiting approval can be approved.")
    if not idv.has_verified_identity(target):
        raise ActionError("This account's identity verification is not complete.")
    _set_status(target, actor, AccountStatus.ACTIVE, is_active=True)
    target.approved_at, target.approved_by_id = utcnow(), actor.id
    return _finish("staff_approved", actor, target, "Account approved")


@_transaction
def reject(user_id, actor, reason):
    target = _locked_target(user_id, actor)
    reason = _reason(reason)
    if target.account_status not in AccountStatus.PENDING:
        raise ActionError("Only pending accounts can be rejected.")
    _set_status(target, actor, AccountStatus.REJECTED, reason=reason, is_active=False)
    _revoke_enrollment(target)
    return _finish("staff_rejected", actor, target, f"Rejected: {reason}")


@_transaction
def suspend(user_id, actor, reason):
    target = _locked_target(user_id, actor)
    reason = _reason(reason)
    if target.account_status != AccountStatus.ACTIVE:
        raise ActionError("Only active accounts can be suspended.")
    _set_status(target, actor, AccountStatus.SUSPENDED, reason=reason, is_active=False)
    _revoke_enrollment(target)
    return _finish("staff_suspended", actor, target, f"Suspended: {reason}")


@_transaction
def reactivate(user_id, actor):
    target = _locked_target(user_id, actor)
    if target.account_status != AccountStatus.SUSPENDED:
        raise ActionError("Only suspended accounts can be reactivated.")
    if not idv.has_verified_identity(target):             # never a way around verification
        raise ActionError("This account is not identity-verified. Issue a new enrollment link instead.")
    _set_status(target, actor, AccountStatus.ACTIVE, is_active=True)
    return _finish("staff_reactivated", actor, target, "Suspension lifted")


@_transaction
def deactivate(user_id, actor, reason):
    """Offboarding. The row is kept (orders, payments and receipts still point at it)."""
    target = _locked_target(user_id, actor)
    reason = _reason(reason)
    if target.account_status == AccountStatus.DEACTIVATED:
        raise ActionError("This account is already deactivated.")
    _set_status(target, actor, AccountStatus.DEACTIVATED, reason=reason, is_active=False)
    _revoke_enrollment(target)
    return _finish("staff_deactivated", actor, target, f"Deactivated: {reason}")


# ----------------------------------------------------------------------------- queries
def status_counts():
    rows = db.session.execute(
        db.select(User.account_status, db.func.count(User.id)).where(User.role == Role.STAFF)
        .group_by(User.account_status)
    ).all()
    counts = {s: 0 for s in AccountStatus.ALL}
    counts.update(dict(rows))
    counts["total"] = sum(counts[s] for s in AccountStatus.ALL)
    counts["suspended_deactivated"] = counts[AccountStatus.SUSPENDED] + counts[AccountStatus.DEACTIVATED]
    return counts


def staff_query(status=None, term=None, sort="newest"):
    q = db.select(User).where(User.role == Role.STAFF)
    if status in AccountStatus.ALL:
        q = q.where(User.account_status == status)
    term = (term or "").strip()[:100]
    if term:
        like = "%" + term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
        q = q.where(or_(User.full_name.ilike(like, escape="\\"), User.email.ilike(like, escape="\\")))
    return q.order_by(SORTS.get(sort, SORTS["newest"]), User.id.desc())


def recent_activity(user, limit=20):
    """Audit rows about this account (what admins did to it, and its own sign-ins)."""
    rows = db.session.execute(
        db.select(AuthEvent, User.email)
        .outerjoin(User, User.id == AuthEvent.user_id)
        .where(or_(AuthEvent.target_user_id == user.id, AuthEvent.user_id == user.id))
        .order_by(AuthEvent.id.desc()).limit(limit)
    ).all()
    return [(event, actor_email) for event, actor_email in rows]
