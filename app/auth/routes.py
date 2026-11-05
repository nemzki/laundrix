
from authlib.integrations.base_client.errors import OAuthError
from flask import (
    current_app,
    flash,
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
from app.extensions import limiter, oauth
from app.models import Role


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
