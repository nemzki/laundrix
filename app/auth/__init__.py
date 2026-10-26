from flask import Blueprint

bp = Blueprint(
    "auth", __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/auth/static",
)

from app.auth import routes  # noqa: E402,F401
