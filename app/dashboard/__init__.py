from flask import Blueprint

bp = Blueprint(
    "dashboard", __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/dashboard/static",
)

from app.dashboard import routes  # noqa: E402,F401
