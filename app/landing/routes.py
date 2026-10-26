from flask import redirect, render_template, url_for
from flask_login import current_user

from app.landing import bp


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    return render_template("landing/index.html")
