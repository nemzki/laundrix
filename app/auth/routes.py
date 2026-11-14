from sqlalchemy.exc import SQLAlchemyError
from authlib.integrations.base_client.errors import OAuthError
from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import (
    current_user,
    login_required,
    login_user,
    logout_user,
)

from app.auth import bp
from app.auth.credentials import authenticate, establish_session
from app.auth.services import authorize_google_user
from app.extensions import db, limiter, oauth
from app.models import Role
from app.core.audit import record_event
from app.identity.face_login import authenticate_with_face
from app.identity.provider.base import FaceNotDetected, ProviderError
from app.models.staff_credential import utcnow

MAX_FACE_LOGIN_IMAGE_BYTES = 1400 * 1024

def _dashboard_endpoint(user):
    """Return the correct dashboard endpoint for an authorized role."""
    if user.role == Role.ADMIN:
        return "dashboard.admin_dashboard"

    if user.role == Role.STAFF:
        return "dashboard.staff_dashboard"

    return None


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 40 per hour", methods=["POST"])
def login():
    """One sign-in page for everyone: Google, or username/email + password (admins and staff)."""
    if current_user.is_authenticated:
        endpoint = _dashboard_endpoint(current_user)

        if endpoint:
            return redirect(url_for(endpoint))

        logout_user()
        session.clear()
        flash("Your account has an unsupported role.", "error")

    if request.method == "POST":
        identifier = request.form.get("identifier", "")
        outcome = authenticate(identifier, request.form.get("password", ""))
        if not outcome.ok:
            flash(outcome.message, "error")
            return render_template("auth/login.html", identifier=identifier[:254]), outcome.http_status

        endpoint = _dashboard_endpoint(outcome.user)
        if endpoint is None or not establish_session(outcome.user):
            session.clear()
            flash("Unable to sign in. Please contact your administrator.", "error")
            return render_template("auth/login.html", identifier=identifier[:254]), 403
        return redirect(url_for(endpoint))

    return render_template("auth/login.html")


@bp.route("/face-login", methods=["POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def face_login():
    """Authenticate an enrolled staff member using passive liveness and face search."""

    def response(message, status):
        return jsonify({"ok": status == 200, "message": message}), status

    if current_user.is_authenticated:
        return response(
            "Please sign out before using Face Login.",
            409,
        )

    if not current_app.config.get("IDV_ENABLED", False):
        return response("Face Login is currently unavailable.", 404)

    # Reject oversized requests before parsing multipart form data.
    if request.content_length and request.content_length > 1536 * 1024:
        return response("The captured image is too large. Please try again.", 413)

    image_file = request.files.get("image")

    if image_file is None:
        return response("Please provide a face image.", 400)

    filename = image_file.filename or ""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if extension not in {"jpg", "jpeg", "png"}:
        return response("Please provide a JPEG or PNG image.", 400)

    image_bytes = image_file.read(MAX_FACE_LOGIN_IMAGE_BYTES + 1)

    current_app.logger.info("Face Login image received: %d bytes", len(image_bytes))

    if not image_bytes:
        return response("The captured image is empty.", 400)

    if len(image_bytes) > MAX_FACE_LOGIN_IMAGE_BYTES:
        return response("The captured image is too large. Please try again.", 413)

    try:
        user = authenticate_with_face(
            image_bytes,
            filename=filename,
        )
    except FaceNotDetected:
        return response(
            "We couldn't see a clear face. Face the camera in good light and try again.",
            422,
        )
    except (ProviderError, NotImplementedError, RuntimeError) as exc:
        # Do not log provider messages, biometric data, or raw reports.
        current_app.logger.warning(
            "Face Login service failure (%s)",
            type(exc).__name__,
        )
        return response(
            "Face Login is temporarily unavailable. Please use another sign-in method.",
            503,
        )
    except ValueError:
        return response("The captured image could not be processed.", 400)

    if user is None:
        return response(
            "We couldn't recognise your face. Look straight at the camera in good light, "
            "or use another sign-in method.",
            401,
        )

    if not establish_session(user):
        session.clear()
        return response("Unable to sign in. Please try again.", 500)

    try:
        user.last_login_at = utcnow()
        record_event(
            "face_login_success",
            actor=user,
            target=user,
        )
        db.session.commit()


    except SQLAlchemyError as exc:
        db.session.rollback()
        session.clear()
        current_app.logger.error(
            "Face Login audit transaction failed (%s)",
            type(exc).__name__,
        )

        return response(
            "Unable to complete sign-in. Please try again.",
            500,
        )

    return jsonify({
        "ok": True,
        "message": "Face Login successful.",
        "redirect_url": url_for(_dashboard_endpoint(user) or "dashboard.staff_dashboard"),
    }), 200


@bp.route("/google")
@limiter.limit("20 per minute")
def google_login():
    redirect_uri = url_for("auth.callback", _external=True)

    return oauth.google.authorize_redirect(
        redirect_uri,
        prompt="select_account",
    )


@bp.route("/callback")
@limiter.limit("20 per minute")
def callback():
    try:
        token = oauth.google.authorize_access_token()
    except OAuthError as exc:
        current_app.logger.warning("Google OAuth error: %s", exc)
        flash("Google sign-in failed. Please try again.", "error")
        return redirect(url_for("auth.login"))

    userinfo = token.get("userinfo") or {}
    user, error = authorize_google_user(userinfo)

    if error:
        current_app.logger.warning(
            "Sign-in denied for %s",
            userinfo.get("email"),
        )
        flash(error, "error")
        return redirect(url_for("auth.login"))

    endpoint = _dashboard_endpoint(user)

    if endpoint is None:
        flash("Your account has an unsupported role.", "error")
        return redirect(url_for("auth.login"))

    # Prevent session fixation before establishing the authenticated session.
    session.clear()

    if not login_user(user):
        session.clear()
        flash("Unable to sign in. Please contact your administrator.", "error")
        return redirect(url_for("auth.login"))

    session.permanent = True

    current_app.logger.info(
        "User signed in: %s (%s)",
        user.email,
        user.role,
    )

    return redirect(url_for(endpoint))


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()

    flash("You have been signed out.", "success")

    return redirect(url_for("landing.index"))
