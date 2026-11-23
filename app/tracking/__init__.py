"""Tracking blueprint: the public order-tracking page that customers open from their QR code."""

from flask import Blueprint

bp = Blueprint(
    "tracking",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/tracking/static",
)

from app.tracking import routes  # noqa: E402,F401