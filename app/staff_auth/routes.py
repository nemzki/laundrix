import time
from werkzeug.security import generate_password_hash

from flask import (
    current_app, flash, redirect, render_template, request, session, url_for,
)
from flask_login import current_user

from app.extensions import db, limiter
from app.identity import services as idv
from app.identity.statuses import IdvStatus
from app.models import StaffCredential
from app.models.staff_credential import utcnow
from app.auth.credentials import INVALID, authenticate, establish_session
from app.models import Role
from app.staff_auth import bp
from app.staff_auth.services import (
    ENROLL_KEY, find_credential_by_token, log_event, normalize_email, valid_email,
)

LOGIN_LIMIT = "10 per minute; 40 per hour"
START_LIMIT = "6 per minute; 30 per hour"
MAX_POLLS = 25         # ~100 s of waiting (4 s refresh) before we ask the person to retry
ENROLL_WINDOW_SECONDS = 1800
ENROLL_STEPS = ["Consent", "Verify", "Done"]



@bp.before_request
def _fail_closed_without_didit():
    """Require Didit only for identity-enrollment routes."""
    if request.endpoint and request.endpoint.endswith(".static"):
        return None

    # Password login must work without the old biometric-login workflow.
    endpoint = request.endpoint or ""
    if endpoint in {"staff_auth.login"}:
        return None

    # Identity enrollment must fail closed when Didit is unavailable.
    if endpoint.startswith("staff_auth.enroll"):
        cfg = current_app.config
        if (
            not cfg.get("IDV_ENABLED")
            or cfg.get("IDV_PROVIDER") != "didit"
            or not cfg.get("DIDIT_API_KEY")
            or not cfg.get("DIDIT_WORKFLOW_ID")
            or not cfg.get("DIDIT_WEBHOOK_SECRET")
        ):
            current_app.logger.error(
                "Staff enrollment unavailable: Didit identity verification "
                "is not fully configured."
            )
            return render_template("staff_auth/unavailable.html"), 503

    return None


# =========================================================================================
# LEGACY EMAIL + PASSWORD PAGE (the main sign-in page is /auth/login)
# =========================================================================================


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(LOGIN_LIMIT, methods=["POST"])
def login():
    """Legacy staff sign-in page (email + password). No longer linked from the public login page,
    which accepts the same credentials. Both use app/auth/credentials.py, so lockout, enrollment
    and account-status rules are identical."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = normalize_email(request.form.get("email"))
        password = request.form.get("password", "")

        if not valid_email(email) or not password:
            flash("Invalid email or password.", "error")
            return render_template("staff_auth/login_email.html"), 400

        outcome = authenticate(email, password, only_role=Role.STAFF)
        if not outcome.ok:
            message = "Invalid email or password." if outcome.kind == INVALID and not outcome.just_locked else outcome.message
            flash(message, "error")
            return render_template("staff_auth/login_email.html"), outcome.http_status

        if not establish_session(outcome.user):
            flash("Unable to sign in. Please contact your administrator.", "error")
            return render_template("staff_auth/login_email.html"), 403
        return redirect(url_for("dashboard.index"))

    return render_template("staff_auth/login_email.html")


# =========================================================================================
# ENROLLMENT (one-time link from an admin):  1) consent + password   2) Didit ID check   3) done
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

        consent = request.form.get("consent") == "on"

        if not consent:
            flash("You must agree to the notice to continue.", "error")
            return render_template(
                "staff_auth/enroll_consent.html",
                name=cred.user.full_name,
                has_password=bool(cred.password_hash),
            ), 400

        # Set a password only for accounts that do not have one yet.
        # An enrollment/re-verification link must not overwrite an existing password.
        if not cred.password_hash:
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

            if len(password) < 12 or len(password) > 256:
                flash("Your password must be between 12 and 256 characters.", "error")
                return render_template(
                    "staff_auth/enroll_consent.html",
                    name=cred.user.full_name,
                    has_password=False,
                ), 400

            if password != confirm_password:
                flash("The passwords do not match.", "error")
                return render_template(
                    "staff_auth/enroll_consent.html",
                    name=cred.user.full_name,
                    has_password=False,
                ), 400

            cred.password_hash = generate_password_hash(password)

        session[ENROLL_KEY] = {
            "cid": cred.id,
            "exp": time.time() + ENROLL_WINDOW_SECONDS,
            "consent": True,
            "polls": 0,
        }

        db.session.commit()
        log_event("enroll_started", True, user=cred.user)

        return redirect(url_for("staff_auth.enroll_verify"))

    return render_template(
        "staff_auth/enroll_consent.html",
        name=cred.user.full_name,
        has_password=bool(cred.password_hash),
    )



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
    """Didit sends the person back here. Query parameters are ignored: the outcome comes from Didit's webhook / API."""
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
