"""Identity verification (government ID + liveness + face match) via a hosted provider flow."""
from flask import Blueprint

bp = Blueprint(
    "identity", __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/identity/static",
)

from app.identity import routes  # noqa: E402,F401
