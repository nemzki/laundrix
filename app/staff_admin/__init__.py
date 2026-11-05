from flask import Blueprint

bp = Blueprint(
    "staff_admin", __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/assets",
)

from app.staff_admin import routes  # noqa: E402,F401
