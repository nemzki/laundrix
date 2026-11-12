"""Analytics & Reports module (administrator only).

Mounted at ``/admin/analytics`` by ``app/__init__.py``. Module layout:

    routes.py        thin HTTP layer + admin-only guard
    services.py      assembles dashboard payloads (one function per section)
    queries.py       SQL aggregation (the only module that talks to the DB)
    calculations.py  pure maths: comparisons, bucketing, ranking (no DB, no Flask)
    periods.py       Philippine-time date ranges and validation (no DB, no Flask)
"""
from flask import Blueprint

bp = Blueprint(
    "analytics",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/assets",
)

from app.analytics import routes  # noqa: E402,F401
