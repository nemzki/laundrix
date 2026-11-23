"""Payments blueprint: manual payment recording, outstanding balances, collections summary and payment settings."""

from flask import Blueprint

bp = Blueprint("payments", __name__, template_folder="templates")

from app.payments import routes  # noqa: E402,F401
