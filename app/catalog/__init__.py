from flask import Blueprint

bp = Blueprint(
    "catalog", __name__,
    template_folder="templates",
)

from app.catalog import routes  # noqa: E402,F401
