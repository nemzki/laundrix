from flask import abort, render_template
from flask_login import current_user, login_required

from app.core.decorators import role_required
from app.dashboard import bp
from app.models import Role
from app.orders.services import dashboard_stats


def _render(admin_area: bool):
    return render_template(
        "dashboard/index.html",
        dashboard_title="Admin Dashboard" if admin_area else "Staff Dashboard",
        dashboard_description=(
            "Orders and activity across the shop." if admin_area
            else "Today's laundry operations at a glance."
        ),
        admin_area=admin_area,
        stats=dashboard_stats(),
    )


@bp.route("/")
@login_required
def index():
    """Keep the existing dashboard URL working for signed-in users."""
    if current_user.role == Role.ADMIN:
        return _render(True)
    if current_user.role == Role.STAFF:
        return _render(False)
    abort(403)


@bp.route("/admin")
@login_required
@role_required(Role.ADMIN)
def admin_dashboard():
    return _render(True)


@bp.route("/staff")
@login_required
@role_required(Role.STAFF)
def staff_dashboard():
    return _render(False)
