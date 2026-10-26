"""Staff portal: email -> Staff ID -> face verification, plus one-time face enrollment."""
from flask import Blueprint

bp = Blueprint(
    "staff_auth", __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/staff-auth/static",
)

from app.staff_auth import routes  # noqa: E402,F401
