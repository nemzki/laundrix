"""Shared pieces: base layout, global CSS, error pages, decorators."""
from flask import Blueprint

bp = Blueprint(
    "core", __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/core/static",
)

from app.core import context, errors  # noqa: E402,F401
