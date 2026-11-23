"""Route for the public landing page."""

from flask import redirect, render_template, url_for
from flask_login import current_user

from app.landing import bp


@bp.route("/")
def index():
    """Show the landing page, or send signed-in users straight to their dashboard."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    return render_template("landing/index.html")
