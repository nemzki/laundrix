import time
from datetime import datetime, timedelta, timezone

from flask import (
    current_app, flash, redirect, render_template, request, session, url_for,
)
from flask_login import current_user, login_user

from app.extensions import db, limiter
from app.identity import services as idv
from app.identity.statuses import IdvStatus
from app.models import IdentityVerification, StaffCredential, User
from app.models.staff_credential import utcnow
from app.staff_auth import bp
from app.staff_auth.services import (
    ENROLL_KEY, GENERIC_FAIL, LOCKED_MSG,
    clear_wizard, find_credential_by_token, get_wizard, is_enrolled, log_event, mask_email,
    normalize_email, normalize_staff_id, register_failure, register_success, save_wizard,
    start_wizard, valid_email, verify_staff_id,
)

LOGIN_LIMIT = "10 per minute; 40 per hour"
START_LIMIT = "6 per minute; 30 per hour"
MAX_FACE_TRIES = 3     # failed face matches per sign-in before the wizard restarts
MAX_POLLS = 25         # ~100 s of waiting (4 s refresh) before we ask the person to retry
ENROLL_WINDOW_SECONDS = 1800
LOGIN_STEPS = ["Email", "Staff ID", "Face"]
ENROLL_STEPS = ["Consent", "Verify", "Done"]



@bp.before_request
def _fail_closed_without_didit():
    """Require Didit configuration before allowing access to the staff portal."""
    if request.endpoint and request.endpoint.endswith(".static"):
        return None

    cfg = current_app.config

    if not cfg["IDV_ENABLED"] or not cfg.get("DIDIT_BIOMETRIC_WORKFLOW_ID"):
        current_app.logger.error(
            "Staff identity verification unavailable: configure IDV_ENABLED and "
            "DIDIT_BIOMETRIC_WORKFLOW_ID."
        )
        return render_template("staff_auth/unavailable.html"), 503

    return None


def _expired():
    flash("Your sign-in session expired. Please start again.", "info")
    return redirect(url_for("staff_auth.login"))


def _naive_utc(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None)


# =========================================================================================
# LOGIN WIZARD:  1) email   2) Staff ID   3) face check by Didit
# =========================================================================================
@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(LOGIN_LIMIT, methods=["POST"])
def login():
    """Step 1 — email."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = normalize_email(request.form.get("email"))
        if not valid_email(email):
            flash("Please enter a valid email address.", "error")
            return render_template("staff_auth/login_email.html"), 400

        user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
        start_wizard(user, email)  # always continue, so we never reveal whether the email exists
        log_event("email_submitted", True, user=user, email=email)
        return redirect(url_for("staff_auth.verify_id"))

    clear_wizard()
    return render_template("staff_auth/login_email.html")


@bp.route("/verify-id", methods=["GET", "POST"])
@limiter.limit(LOGIN_LIMIT, methods=["POST"])
def verify_id():
    """Step 2 — Staff ID."""
    wiz = get_wizard("id")
    if not wiz:
        return _expired()

    user = db.session.get(User, wiz["uid"]) if wiz["uid"] else None
    cred = user.staff_credential if user else None
    ctx = {"email_hint": mask_email(wiz["email"])}

    if request.method == "POST":
        if cred and cred.is_locked:
            clear_wizard()
            log_event("blocked_locked", False, user=user)
            flash(LOCKED_MSG, "error")
            return redirect(url_for("staff_auth.login"))

        entered = normalize_staff_id(request.form.get("staff_id"))
        if not verify_staff_id(cred, entered):
            if cred:
                register_failure(cred)
            log_event("id_failed", False, user=user, email=wiz["email"])
            wiz["fails"] += 1

            if cred and cred.is_locked:
                clear_wizard()
                flash(LOCKED_MSG, "error")
                return redirect(url_for("staff_auth.login"))
            if wiz["fails"] >= MAX_FACE_TRIES:
                clear_wizard()
                flash(GENERIC_FAIL, "error")
                return redirect(url_for("staff_auth.login"))

            save_wizard(wiz)
            flash(GENERIC_FAIL, "error")
            return render_template("staff_auth/login_id.html", **ctx), 401

        if not is_enrolled(user):
            clear_wizard()
            log_event("not_enrolled", False, user=user)
            flash("Your identity verification isn't finished yet. Use the enrollment link "
                  "from your administrator.", "info")
            return redirect(url_for("staff_auth.login"))

        wiz.update(stage="face", fails=0, vid=None, polls=0)
        save_wizard(wiz)
        log_event("id_ok", True, user=user)
        return redirect(url_for("staff_auth.verify_face"))

    return render_template("staff_auth/login_id.html", **ctx)


def _face_context(wiz):
    user = db.session.get(User, wiz["uid"]) if wiz["uid"] else None
    cred = user.staff_credential if user else None
    if not user or not cred or not user.is_active:
        return None, None
    return user, cred


@bp.route("/verify-face")
def verify_face():
    """Step 3 — explain, then send the person to Didit's secure selfie page."""
    wiz = get_wizard("face")
    if not wiz:
        return _expired()
    return render_template("staff_auth/login_face.html", in_progress=bool(wiz.get("vid")))


@bp.route("/verify-face/start", methods=["POST"])
@limiter.limit(START_LIMIT)
def face_start():
    wiz = get_wizard("face")
    if not wiz:
        return _expired()
    user, cred = _face_context(wiz)
    if not user:
        clear_wizard()
        flash(GENERIC_FAIL, "error")
        return redirect(url_for("staff_auth.login"))
    if cred.is_locked:
        clear_wizard()
        flash(LOCKED_MSG, "error")
        return redirect(url_for("staff_auth.login"))

    result = idv.start_biometric_auth(user, url_for("staff_auth.face_return"))
    if result.error:
        log_event("face_start_failed", False, user=user)
        flash(result.message, "info")
        if result.error == "not_enrolled":
            clear_wizard()
            return redirect(url_for("staff_auth.login"))
        return redirect(url_for("staff_auth.verify_face"))

    wiz.update(vid=result.verification.id, t0=time.time(), polls=0)
    save_wizard(wiz)
    log_event("face_started", True, user=user)
    return redirect(result.redirect_url)   # Didit's hosted page; host was validated in the provider


@bp.route("/verify-face/return")
@limiter.limit("40 per minute")
def face_return():
    """Where Didit sends the person back (and where the waiting page refreshes itself).

    The query string Didit appends is attacker-controllable and is IGNORED. The outcome comes only
    from Didit's signed webhook or a server-side call to its API.
    """
    wiz = get_wizard("face")
    if not wiz:
        return _expired()
    user, cred = _face_context(wiz)
    v = db.session.get(IdentityVerification, wiz["vid"]) if wiz.get("vid") else None
    if not user or v is None or v.user_id != user.id or v.purpose != idv.PURPOSE_BIOMETRIC:
        flash("Please start the face check again.", "info")
        return redirect(url_for("staff_auth.verify_face"))

    idv.reconcile(v)                   # skips finished checks; a provider failure leaves status untouched
    db.session.refresh(v)

    if v.status == IdvStatus.VERIFIED:
        fresh = v.decided_at is not None and v.decided_at >= _naive_utc(wiz["t0"]) - timedelta(seconds=5)
        if not fresh or cred.is_locked:  # never accept an approval that predates this sign-in
            clear_wizard()
            flash(GENERIC_FAIL, "error")
            return redirect(url_for("staff_auth.login"))
        register_success(cred)
        if cred.enroll_token_hash:       # onboarding is finished; a leftover link must not stay valid
            cred.enroll_token_hash = cred.enroll_token_expires_at = None
            db.session.commit()
        log_event("login_ok", True, user=user)
        session.clear()                  # new session -> prevents fixation
        login_user(user)
        session.permanent = True
        current_app.logger.info("Staff signed in: %s", user.email)
        return redirect(url_for("dashboard.index"))

    if v.status == IdvStatus.REJECTED:   # a clear "this is not the enrolled person"
        register_failure(cred)
        wiz["fails"] += 1
        log_event("face_failed", False, user=user)
        if cred.is_locked or wiz["fails"] >= MAX_FACE_TRIES:
            clear_wizard()
            flash(LOCKED_MSG if cred.is_locked else "Face verification failed. Please start again.", "error")
            return redirect(url_for("staff_auth.login"))
        wiz["vid"] = None
        save_wizard(wiz)
        flash(f"Your face didn't match. {MAX_FACE_TRIES - wiz['fails']} attempt(s) left.", "error")
        return redirect(url_for("staff_auth.verify_face"))

    if v.status == IdvStatus.ACTION_REQUIRED:   # abandoned / timed out: NOT a failed match
        wiz["vid"] = None
        save_wizard(wiz)
        flash("The face check wasn't completed. Please try again.", "info")
        return redirect(url_for("staff_auth.verify_face"))

    # still in progress (or under review): wait a little, then give up politely
    wiz["polls"] += 1
    if wiz["polls"] > MAX_POLLS:
        wiz["vid"] = None
        save_wizard(wiz)
        flash("The face check is taking longer than usual. Please try again.", "info")
        return redirect(url_for("staff_auth.verify_face"))
    save_wizard(wiz)
    return render_template(
        "staff_auth/wait.html", refresh_url=url_for("staff_auth.face_return"),
        title="Checking your face…", message="This usually takes a few seconds.",
        steps=LOGIN_STEPS, current=3,
    )


@bp.route("/restart")
def restart():
    clear_wizard()
    return redirect(url_for("staff_auth.login"))


# =========================================================================================
# ENROLLMENT (one-time link from an admin):  1) consent + Staff ID   2) Didit ID check   3) done
# =========================================================================================
@bp.route("/enroll/<token>", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def enroll(token):
    cred = find_credential_by_token(token)
    if cred is None:
        return render_template("staff_auth/enroll_invalid.html"), 404

    if request.method == "POST":
        if cred.is_locked:
            return render_template("staff_auth/enroll_invalid.html"), 423
        entered = normalize_staff_id(request.form.get("staff_id"))
        consent = request.form.get("consent") == "on"
        if not verify_staff_id(cred, entered):
            register_failure(cred)
            log_event("enroll_id_failed", False, user=cred.user)
            flash(GENERIC_FAIL, "error")
            return render_template("staff_auth/enroll_consent.html", name=cred.user.full_name), 401
        if not consent:
            flash("You must agree to the notice to continue.", "error")
            return render_template("staff_auth/enroll_consent.html", name=cred.user.full_name), 400

        session[ENROLL_KEY] = {"cid": cred.id, "exp": time.time() + ENROLL_WINDOW_SECONDS,
                               "consent": True, "polls": 0}
        log_event("enroll_started", True, user=cred.user)
        return redirect(url_for("staff_auth.enroll_verify"))

    return render_template("staff_auth/enroll_consent.html", name=cred.user.full_name)


def _enroll_session():
    data = session.get(ENROLL_KEY)
    if not data or data.get("exp", 0) < time.time() or not data.get("consent"):
        return None
    cred = db.session.get(StaffCredential, data["cid"])
    if (cred is None or not cred.user.is_active or not cred.enroll_token_hash
            or cred.enroll_token_expires_at is None or cred.enroll_token_expires_at < utcnow()):
        return None
    return cred


@bp.route("/enroll/verify")
def enroll_verify():
    if _enroll_session() is None:
        return render_template("staff_auth/enroll_invalid.html"), 403
    return render_template("staff_auth/enroll_verify.html")


@bp.route("/enroll/start", methods=["POST"])
@limiter.limit("5 per minute; 20 per hour")
def enroll_start():
    cred = _enroll_session()
    if cred is None:
        return render_template("staff_auth/enroll_invalid.html"), 403
    # consent was given on the previous page; allow_reverify = an admin asked for a fresh check
    result = idv.start_verification(
        cred.user, consent_given=True, allow_reverify=True,
        callback_path=url_for("staff_auth.enroll_return"),
    )
    if result.redirect_url:
        log_event("enroll_didit_started", True, user=cred.user)
        return redirect(result.redirect_url)
    flash(result.message, "info")
    return redirect(url_for("staff_auth.enroll_verify"))


@bp.route("/enroll/return")
@limiter.limit("40 per minute")
def enroll_return():
    """Didit sends the person back here. Query parameters are ignored (see face_return)."""
    cred = _enroll_session()
    if cred is None:
        return render_template("staff_auth/enroll_invalid.html"), 403
    v = idv.latest_verification(cred.user)
    if v is None:
        return redirect(url_for("staff_auth.enroll_verify"))

    if v.status in idv.OPEN_STATUSES:
        idv.reconcile(v, cooldown=current_app.config["IDV_BIOMETRIC_POLL_COOLDOWN_SECONDS"])
        db.session.refresh(v)

    if v.status == IdvStatus.VERIFIED:
        cred.enroll_token_hash = cred.enroll_token_expires_at = None   # the link is now dead
        cred.failed_attempts, cred.locked_until = 0, None
        db.session.commit()
        log_event("enrolled", True, user=cred.user)
        session.pop(ENROLL_KEY, None)
        return redirect(url_for("staff_auth.enroll_done"))

    if v.status == IdvStatus.REJECTED:
        log_event("enroll_rejected", False, user=cred.user)
        flash("We couldn't verify your identity. You can try again with a valid ID.", "error")
        return redirect(url_for("staff_auth.enroll_verify"))
    if v.status == IdvStatus.ACTION_REQUIRED:
        flash("The verification wasn't completed. Please start again.", "info")
        return redirect(url_for("staff_auth.enroll_verify"))

    data = session[ENROLL_KEY]
    data["polls"] = data.get("polls", 0) + 1
    session[ENROLL_KEY] = data
    if data["polls"] > MAX_POLLS * 3:     # manual review can take a while; stop auto-refreshing
        return render_template("staff_auth/enroll_pending.html")
    return render_template(
        "staff_auth/wait.html", refresh_url=url_for("staff_auth.enroll_return"),
        title="Checking your verification…", message="This usually takes less than a minute.",
        steps=ENROLL_STEPS, current=2,
    )


@bp.route("/enroll/done")
def enroll_done():
    return render_template("staff_auth/enroll_done.html")
