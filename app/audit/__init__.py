"""Admin Audit Logs: a central, append-only record of important actions (admin-only viewer)."""
from flask import Blueprint

bp = Blueprint(
    "audit", __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/audit/static",
)

from app.audit import routes  # noqa: E402,F401
