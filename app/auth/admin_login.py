"""Legacy administrator sign-in page (/auth/admin). It is no longer linked anywhere: the public login
page accepts administrator credentials directly. Kept as a thin wrapper over the same shared
service (app/auth/credentials.py) so existing bookmarks and tests keep working. It can be switched
off with ADMIN_PASSWORD_LOGIN_ENABLED=false."""
from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.auth import bp
from app.auth.credentials import authenticate, establish_session
from app.extensions import limiter
from app.models import Role

LOGIN_LIMIT = "10 per minute; 40 per hour"


@bp.route("/admin", methods=["GET", "POST"])
@limiter.limit(LOGIN_LIMIT, methods=["POST"])
def admin_login():
    if not current_app.config.get("ADMIN_PASSWORD_LOGIN_ENABLED"):
        abort(404)
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method == "GET":
        return render_template("auth/admin_login.html")

    outcome = authenticate(request.form.get("username"), request.form.get("password"), only_role=Role.ADMIN)
    if not outcome.ok:
        flash(outcome.message, "error")
        return render_template("auth/admin_login.html"), outcome.http_status
    if not establish_session(outcome.user):
        flash("Unable to sign in. Please contact your administrator.", "error")
        return render_template("auth/admin_login.html"), 403
    current_app.logger.info("Administrator signed in: %s", outcome.user.username)
    return redirect(url_for("dashboard.admin_dashboard"))
