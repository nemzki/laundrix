from flask import Blueprint

bp = Blueprint(
    "landing", __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/landing/static",
)

from app.landing import routes  # noqa: E402,F401
