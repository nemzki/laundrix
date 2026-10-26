
from flask import abort, render_template
from flask_login import current_user, login_required

from app.core.decorators import role_required
from app.dashboard import bp
from app.models import Role


@bp.route("/")
@login_required
def index():
    """Keep the existing dashboard URL working for signed-in users."""
    if current_user.role == Role.ADMIN:
        return render_template(
            "dashboard/index.html",
            dashboard_title="Admin Dashboard",
            dashboard_description=(
                "Admin access confirmed. Admin features will be added here."
            ),
            admin_area=True,
        )

    if current_user.role == Role.STAFF:
        return render_template(
            "dashboard/index.html",
            dashboard_title="Staff Dashboard",
            dashboard_description=(
                "Staff access confirmed. Staff features will be added here."
            ),
            admin_area=False,
        )

    abort(403)


@bp.route("/admin")
@login_required
@role_required(Role.ADMIN)
def admin_dashboard():
    return render_template(
        "dashboard/index.html",
        dashboard_title="Admin Dashboard",
        dashboard_description=(
            "Admin access confirmed. Admin features will be added here."
        ),
        admin_area=True,
    )


@bp.route("/staff")
@login_required
@role_required(Role.STAFF)
def staff_dashboard():
    return render_template(
        "dashboard/index.html",
        dashboard_title="Staff Dashboard",
        dashboard_description=(
            "Staff access confirmed. Staff features will be added here."
        ),
        admin_area=False,
    )
