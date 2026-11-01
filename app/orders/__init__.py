from flask import Blueprint

bp = Blueprint(
    "orders", __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/assets",
)

from app.orders import routes  # noqa: E402,F401
