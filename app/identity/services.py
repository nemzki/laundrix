"""Identity verification business logic: provider <-> database orchestration.

Principles
* A provider/API failure is NEVER recorded as a failed verification. Only a provider *decision*
  (Declined, etc.) can reject a person.
* We keep status + audit data only; no images, ID numbers, names, DOBs or biometric templates.
* Every query that returns a record for a user is filtered by that user's id.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import current_app, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.identity import statuses as st
from app.identity.provider import get_idv_provider
from app.identity.provider.base import ProviderError, SessionNotFound
from app.models import IdentityVerification, IdentityVerificationEvent, User
from app.models.staff_credential import utcnow

log = logging.getLogger(__name__)

# Bump when the consent text in consent.html changes materially; it is stored with each attempt.
CONSENT_VERSION = "2026-10-v1"

PURPOSE_KYC = "kyc"                      # one-time ID + liveness + face match
PURPOSE_BIOMETRIC = "biometric_auth"     # a returning staff member's sign-in selfie check

START_MESSAGES = {
    "consent_required": "Please confirm that you've read the notice to continue.",
    "already_verified": "You're already verified.",
    "under_review": "Your verification is already under review. No action is needed.",
    "too_many_attempts": ("You've reached the limit of verification attempts for now. "
                          "Please try again later or contact your administrator."),
    "provider_unavailable": ("The verification service is temporarily unavailable. This is not a "
                             "problem with your ID. Please try again in a few minutes."),
    "provider_rate_limited": ("The verification service is busy. This is not a problem with your ID. "
                              "Please try again in a few minutes."),
    "provider_auth": "Verification is temporarily unavailable. Please contact your administrator.",
    "provider_rejected_request": "Verification is temporarily unavailable. Please contact your administrator.",
    "session_not_found": "Verification is temporarily unavailable. Please try again shortly.",
    "provider_error": "Verification is temporarily unavailable. Please try again shortly.",
    "not_enrolled": ("Your identity verification isn't complete. Ask your administrator "
                     "for an enrollment link."),
    "biometric_workflow_missing": "Face verification isn't configured. Please contact your administrator.",
    "too_many_face_checks": ("Too many face checks were started recently. "
                             "Please wait a while and try again."),
}


@dataclass
class StartResult:
    redirect_url: Optional[str] = None
    error: Optional[str] = None
    verification: Optional[IdentityVerification] = None

    @property
    def message(self):
        return START_MESSAGES.get(self.error, START_MESSAGES["provider_error"]) if self.error else None


@dataclass
class ReconcileResult:
    outcome: str                      # an st.* outcome, "cooldown", "not_open" or "provider_error"
    error_code: Optional[str] = None


# ----------------------------------------------------------------------------- lookups
def user_ref(user_id: int) -> str:
    """Opaque reference sent to the provider as `vendor_data` and checked on every webhook."""
    return f"laundrix:{user_id}"


def latest_verification(user: User, purpose: str = PURPOSE_KYC) -> Optional[IdentityVerification]:
    return db.session.execute(
        db.select(IdentityVerification).filter_by(user_id=user.id, purpose=purpose)
        .order_by(IdentityVerification.id.desc()).limit(1)
    ).scalar_one_or_none()


def has_verified_identity(user: User) -> bool:
    """True once the person's one-time ID verification has been approved ("enrolled")."""
    latest = latest_verification(user)
    return latest is not None and latest.status == st.IdvStatus.VERIFIED


def get_owned_verification(
    user: User, public_id: str, purpose: Optional[str] = None
) -> Optional[IdentityVerification]:
    """Ownership enforced in the query itself: someone else's record simply doesn't exist for you."""
    q = db.select(IdentityVerification).filter_by(public_id=public_id, user_id=user.id)
    if purpose:
        q = q.filter_by(purpose=purpose)
    return db.session.execute(q).scalar_one_or_none()


def history_for(user: User, limit: int = 10, purpose: Optional[str] = PURPOSE_KYC):
    q = db.select(IdentityVerification).filter_by(user_id=user.id)
    if purpose:
        q = q.filter_by(purpose=purpose)
    return db.session.execute(q.order_by(IdentityVerification.id.desc()).limit(limit)).scalars().all()


def _by_session_id(session_id: str) -> Optional[IdentityVerification]:
    return db.session.execute(
        db.select(IdentityVerification).filter_by(provider_session_id=session_id)
    ).scalar_one_or_none()


def attempts_in_window(user: User) -> int:
    cutoff = utcnow() - timedelta(hours=current_app.config["IDV_ATTEMPT_WINDOW_HOURS"])
    return db.session.execute(
        db.select(func.count()).select_from(IdentityVerification).where(
            IdentityVerification.user_id == user.id,
            IdentityVerification.purpose == PURPOSE_KYC,
            IdentityVerification.provider_session_id.is_not(None),  # provider errors never count
            IdentityVerification.created_at >= cutoff,
        )
    ).scalar_one()


def start_block_reason(user: User, allow_reverify: bool = False) -> Optional[str]:
    """Why a NEW attempt can't be started right now (None = allowed).

    `allow_reverify` is for administrator-issued re-onboarding links only."""
    latest = latest_verification(user)
    if latest and latest.status == st.IdvStatus.VERIFIED and not allow_reverify:
        return "already_verified"
    if latest and latest.status == st.IdvStatus.PENDING_REVIEW:
        return "under_review"
    resuming = latest is not None and latest.status == st.IdvStatus.IN_PROGRESS
    if not resuming and attempts_in_window(user) >= current_app.config["IDV_MAX_ATTEMPTS"]:
        return "too_many_attempts"
    return None


# ----------------------------------------------------------------------------- display
def summary_for(user: User) -> dict:
    latest = latest_verification(user)
    status = latest.status if latest else st.IdvStatus.NOT_STARTED
    copy = st.STATUS_COPY[status]
    hint = None
    if latest and status in (st.IdvStatus.REJECTED, st.IdvStatus.ACTION_REQUIRED) and latest.reason_codes:
        hint = st.CATEGORY_HINTS[st.reason_category(latest.reason_codes)]
    block = start_block_reason(user)
    return {
        "status": status,
        "ui": copy,
        "hint": hint,
        "verification": latest,
        "can_start": bool(copy["can_start"]) and block in (None,),
        "blocked_message": START_MESSAGES.get(block) if (copy["can_start"] and block) else None,
        "can_refresh": status in (st.IdvStatus.IN_PROGRESS, st.IdvStatus.PENDING_REVIEW),
    }


# ----------------------------------------------------------------------------- starting
def _audit(v, *, source, provider_status, from_status, to_status, outcome, event_id=None):
    db.session.add(IdentityVerificationEvent(
        verification_id=v.id, event_id=event_id, source=source, provider_status=provider_status,
        from_status=from_status, to_status=to_status, outcome=outcome,
    ))


def _record_provider_failure(user: User, latest, error_code: str):
    """Remember that starting failed on OUR side. Never touches an open attempt, never rejects."""
    if latest is not None and latest.status == st.IdvStatus.IN_PROGRESS:
        return  # the earlier session may still be perfectly valid; leave it alone
    if latest is not None and latest.status == st.IdvStatus.ERROR:
        latest.error_code = error_code          # reuse the row so repeated failures don't pile up
        db.session.commit()
        return
    row = IdentityVerification(
        user_id=user.id, provider=current_app.config["IDV_PROVIDER"],
        environment=current_app.config["DIDIT_ENVIRONMENT"],
        status=st.IdvStatus.ERROR, error_code=error_code[:40],
    )
    db.session.add(row)
    db.session.flush()
    _audit(row, source="system", provider_status=None, from_status=st.IdvStatus.NOT_STARTED,
           to_status=st.IdvStatus.ERROR, outcome=st.APPLIED)
    db.session.commit()


def start_verification(
    user: User, consent_given: bool, callback_path: Optional[str] = None, allow_reverify: bool = False
) -> StartResult:
    if not consent_given:
        return StartResult(error="consent_required")
    block = start_block_reason(user, allow_reverify=allow_reverify)
    if block:
        return StartResult(error=block)

    cfg = current_app.config
    latest = latest_verification(user)
    callback = cfg["APP_BASE_URL"] + (callback_path or url_for("identity.return_from_provider"))
    try:
        session = get_idv_provider().create_session(user_ref(user.id), callback)
    except ProviderError as exc:
        log.warning("Could not create verification session for user_id=%s: %s", user.id, exc.code)
        _record_provider_failure(user, latest, exc.code)
        return StartResult(error=exc.code)

    v = _by_session_id(session.session_id)
    if v is not None and (v.user_id != user.id or v.purpose != PURPOSE_KYC):
        # must never happen; refuse rather than share or cross-wire a session
        log.error("Provider returned a session belonging to another user (user_id=%s)", user.id)
        return StartResult(error="provider_error")
    if v is None:
        v = IdentityVerification(
            user_id=user.id, provider=get_idv_provider().name, provider_session_id=session.session_id,
            environment=cfg["DIDIT_ENVIRONMENT"], status=st.IdvStatus.IN_PROGRESS,
            purpose=PURPOSE_KYC, consent_version=CONSENT_VERSION, consent_at=utcnow(),
        )
        db.session.add(v)
        db.session.flush()
        _audit(v, source="system", provider_status=session.status,
               from_status=st.IdvStatus.NOT_STARTED, to_status=st.IdvStatus.IN_PROGRESS,
               outcome=st.APPLIED)
    else:  # the provider handed back the user's still-open session (idempotent by vendor_data)
        v.consent_version, v.consent_at = CONSENT_VERSION, utcnow()
    db.session.commit()
    return StartResult(redirect_url=session.url, verification=v)


# ----------------------------------------------------------------------------- sign-in face check
def biometric_sessions_last_hour(user: User) -> int:
    cutoff = utcnow() - timedelta(hours=1)
    return db.session.execute(
        db.select(func.count()).select_from(IdentityVerification).where(
            IdentityVerification.user_id == user.id,
            IdentityVerification.purpose == PURPOSE_BIOMETRIC,
            IdentityVerification.created_at >= cutoff,
        )
    ).scalar_one()


def start_biometric_auth(user: User, callback_path: str) -> StartResult:
    """Begin a sign-in face check (Didit "Biometric Authentication") for an already-verified person.

    The same `vendor_data` as the person's ID verification tells Didit which stored portrait to
    compare against, so no portrait or document is sent from or stored by Laundrix.
    Provider failures are returned as errors and are NEVER counted as a failed face match.
    """
    cfg = current_app.config
    workflow = cfg.get("DIDIT_BIOMETRIC_WORKFLOW_ID")
    if not workflow:
        return StartResult(error="biometric_workflow_missing")
    if not has_verified_identity(user):
        return StartResult(error="not_enrolled")

    open_row = latest_verification(user, PURPOSE_BIOMETRIC)
    resuming = open_row is not None and open_row.status == st.IdvStatus.IN_PROGRESS
    if not resuming and biometric_sessions_last_hour(user) >= cfg["IDV_BIOMETRIC_MAX_PER_HOUR"]:
        return StartResult(error="too_many_face_checks")   # stops a stolen Staff ID burning credits

    callback = cfg["APP_BASE_URL"] + callback_path
    try:
        session = get_idv_provider().create_session(user_ref(user.id), callback, workflow_id=workflow)
    except ProviderError as exc:
        log.warning("Could not create face-check session for user_id=%s: %s", user.id, exc.code)
        return StartResult(error=exc.code)

    v = _by_session_id(session.session_id)
    if v is not None and (v.user_id != user.id or v.purpose != PURPOSE_BIOMETRIC):
        log.error("Provider returned a session that is not this user's face check (user_id=%s)", user.id)
        return StartResult(error="provider_error")
    if v is None:
        v = IdentityVerification(
            user_id=user.id, provider=get_idv_provider().name, provider_session_id=session.session_id,
            environment=cfg["DIDIT_ENVIRONMENT"], status=st.IdvStatus.IN_PROGRESS,
            purpose=PURPOSE_BIOMETRIC,
        )
        db.session.add(v)
        db.session.flush()
        _audit(v, source="system", provider_status=session.status,
               from_status=st.IdvStatus.NOT_STARTED, to_status=st.IdvStatus.IN_PROGRESS,
               outcome=st.APPLIED)
    elif v.status != st.IdvStatus.IN_PROGRESS:
        if v.status in (st.IdvStatus.ACTION_REQUIRED, st.IdvStatus.ERROR):  # provider still has it open
            old, v.status, v.completed_at = v.status, st.IdvStatus.IN_PROGRESS, None
            _audit(v, source="system", provider_status=session.status, from_status=old,
                   to_status=v.status, outcome=st.APPLIED)
        else:                                  # already decided: never reuse a finished check
            log.error("Provider returned an already-decided face-check session")
            return StartResult(error="provider_error")
    db.session.commit()
    return StartResult(redirect_url=session.url, verification=v)


# ----------------------------------------------------------------------------- applying results
def apply_provider_status(
    v: IdentityVerification, provider_status: Optional[str], *, source: str,
    event_id: Optional[str] = None, event_time: Optional[datetime] = None,
    decision: Optional[dict] = None,
) -> str:
    """Evaluate and (if allowed) apply a provider status. Does NOT commit - the caller does, so the
    audit row (which carries the unique event_id) and the status change are one transaction."""
    plan = st.plan_transition(v.status, provider_status, event_time, v.provider_updated_at)
    if (plan.outcome == st.APPLIED and v.purpose == PURPOSE_BIOMETRIC
            and v.status == st.IdvStatus.ACTION_REQUIRED and plan.new_status == st.IdvStatus.IN_PROGRESS):
        plan = st.TransitionPlan(st.INVALID)   # abandoned/expired sign-in checks stay finished
    old = v.status

    if plan.outcome in (st.APPLIED, st.UNCHANGED):
        new = plan.new_status
        if event_time and (v.provider_updated_at is None or event_time > v.provider_updated_at):
            v.provider_updated_at = event_time
        codes = st.extract_reason_codes(decision)
        doc_type = st.extract_document_type(decision)
        if new == st.IdvStatus.VERIFIED:
            v.reason_codes = None
        elif codes:
            v.reason_codes = codes
        if doc_type:
            v.document_type = doc_type
        if plan.outcome == st.APPLIED:
            v.status, v.error_code = new, None
            if new in (st.IdvStatus.VERIFIED, st.IdvStatus.REJECTED):
                v.decided_at = utcnow()
            v.completed_at = None if new == st.IdvStatus.IN_PROGRESS else utcnow()

    elif plan.outcome == st.INVALID:
        log.warning("Ignored invalid transition %s -> %s (verification %s)",
                    old, st.map_provider_status(provider_status), v.public_id)
    elif plan.outcome == st.UNKNOWN:
        log.warning("Ignored unknown provider status %r (verification %s)", provider_status, v.public_id)

    _audit(v, source=source, provider_status=(provider_status or "")[:30], from_status=old,
           to_status=v.status, outcome=plan.outcome, event_id=event_id)
    return plan.outcome


def _from_epoch(value) -> Optional[datetime]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def process_webhook(payload: dict) -> str:
    """Apply an ALREADY-AUTHENTICATED webhook payload. Returns a short outcome label for logging.

    Safe to receive twice: `event_id` is unique in the audit table, so a retry/replay can't re-apply.
    """
    cfg = current_app.config
    # Didit's webhook reference uses "status.updated"; one of its product pages says
    # "session.status.updated". Same envelope is expected; anything malformed is ignored below.
    if payload.get("webhook_type") not in ("status.updated", "session.status.updated"):
        return "ignored_event_type"

    event_id, session_id, status = payload.get("event_id"), payload.get("session_id"), payload.get("status")
    if not (isinstance(event_id, str) and 0 < len(event_id) <= 64
            and isinstance(session_id, str) and isinstance(status, str)):
        return "ignored_malformed"

    if payload.get("environment") != cfg["DIDIT_ENVIRONMENT"]:
        log.warning("Ignored webhook from environment %r (expected %r)",
                    payload.get("environment"), cfg["DIDIT_ENVIRONMENT"])
        return "ignored_environment"

    if db.session.execute(
        db.select(IdentityVerificationEvent.id).filter_by(event_id=event_id)
    ).first():
        return "duplicate"

    v = _by_session_id(session_id)
    if v is None:
        return "ignored_unknown_session"
    if payload.get("vendor_data") != user_ref(v.user_id):
        log.warning("Ignored webhook: vendor_data does not match session owner (verification %s)", v.public_id)
        return "ignored_vendor_mismatch"

    try:
        outcome = apply_provider_status(
            v, status, source="webhook", event_id=event_id,
            event_time=_from_epoch(payload.get("created_at")), decision=payload.get("decision"),
        )
        db.session.commit()
    except IntegrityError:  # two deliveries raced; the unique event_id stopped the second one
        db.session.rollback()
        return "duplicate"
    return outcome


# ----------------------------------------------------------------------------- polling fallback
# ID verification can continue after "action required" (a reviewer asked for a resubmission in the
# same session), so it stays pollable. A sign-in face check cannot: once abandoned/expired it is
# finished, and trying again always starts a NEW session.
OPEN_STATUSES = (st.IdvStatus.IN_PROGRESS, st.IdvStatus.PENDING_REVIEW, st.IdvStatus.ACTION_REQUIRED)
BIOMETRIC_OPEN_STATUSES = (st.IdvStatus.IN_PROGRESS, st.IdvStatus.PENDING_REVIEW)


def open_statuses_for(purpose: str):
    return BIOMETRIC_OPEN_STATUSES if purpose == PURPOSE_BIOMETRIC else OPEN_STATUSES


def reconcile(
    v: IdentityVerification, *, force: bool = False, cooldown: Optional[int] = None
) -> ReconcileResult:
    """Ask the provider for the authoritative decision. Used when the user returns from the hosted
    page, on request, and by the CLI. A failure here changes NOTHING about the user's status."""
    if v.status not in open_statuses_for(v.purpose) or not v.provider_session_id:
        return ReconcileResult("not_open")

    if cooldown is None:
        cooldown = current_app.config[
            "IDV_BIOMETRIC_POLL_COOLDOWN_SECONDS" if v.purpose == PURPOSE_BIOMETRIC
            else "IDV_POLL_COOLDOWN_SECONDS"
        ]
    now = utcnow()
    if not force and v.last_polled_at and (now - v.last_polled_at).total_seconds() < cooldown:
        return ReconcileResult("cooldown")
    v.last_polled_at = now
    db.session.commit()  # record the attempt even if the provider call fails

    try:
        decision = get_idv_provider().get_decision(v.provider_session_id)
    except SessionNotFound:
        log.warning("Provider does not know session for verification %s", v.public_id)
        return ReconcileResult("provider_error", "session_not_found")
    except ProviderError as exc:
        log.warning("Reconcile failed for verification %s: %s", v.public_id, exc.code)
        return ReconcileResult("provider_error", exc.code)

    outcome = apply_provider_status(v, decision.status, source="poll", decision=decision.raw)
    db.session.commit()
    return ReconcileResult(outcome)


# ----------------------------------------------------------------------------- retention
def purge_old_records(days: int, dry_run: bool = False, biometric_days: Optional[int] = None) -> dict:
    """Delete verification records past their retention window.

    * KYC attempts: non-verified ones older than `days` are removed, and everything older than
      `days` that belongs to a deactivated user. A current VERIFIED record for an active user is
      kept (it is the proof they're verified, and it links them to their stored portrait).
    * Sign-in face checks (purpose=biometric_auth) are routine, one per login, so they are removed
      after `biometric_days` regardless of outcome.
    Audit events go with their record (ON DELETE CASCADE / ORM cascade).
    """
    if biometric_days is None:
        biometric_days = current_app.config["IDV_BIOMETRIC_RETENTION_DAYS"]
    now = utcnow()
    cutoff = now - timedelta(days=days)
    bio_cutoff = now - timedelta(days=biometric_days)
    inactive_ids = db.select(User.id).where(User.is_active.is_(False))
    q = db.select(IdentityVerification).where(
        db.or_(
            db.and_(
                IdentityVerification.purpose == PURPOSE_KYC,
                IdentityVerification.updated_at < cutoff,
                db.or_(
                    IdentityVerification.status != st.IdvStatus.VERIFIED,
                    IdentityVerification.user_id.in_(inactive_ids),
                ),
            ),
            db.and_(
                IdentityVerification.purpose == PURPOSE_BIOMETRIC,
                IdentityVerification.updated_at < bio_cutoff,
            ),
        )
    )
    rows = db.session.execute(q).scalars().all()
    if not dry_run:
        for row in rows:
            db.session.delete(row)
        db.session.commit()
    return {"matched": len(rows), "deleted": 0 if dry_run else len(rows), "cutoff": cutoff}
