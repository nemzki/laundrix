from flask import Blueprint

bp = Blueprint("payments", __name__, template_folder="templates")

from app.payments import routes  # noqa: E402,F401
