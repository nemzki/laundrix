"""Admin-only analytics and reporting routes."""
from flask import current_app, render_template
from flask_login import login_required

from app.analytics import bp
from app.analytics.ml.demo_training import load_demo_training_summary
from app.analytics.ml.production_training import (
    get_current_ready_order_predictions,
    load_production_model_summary,
)
from app.analytics.ml.unclaimed_orders import get_unclaimed_order_readiness
from app.analytics.services import get_analytics_report
from app.core.decorators import role_required
from app.models import Role
from app.orders.services import dashboard_stats


@bp.route("/", endpoint="index")
@login_required
@role_required(Role.ADMIN)
def index():
    """Render the admin analytics and reports workspace."""
    return render_template(
        "analytics/index.html",
        dashboard_title="Analytics & Reports",
        dashboard_description="Business performance, operational trends, and machine-learning insights.",
        admin_area=True,
        stats=dashboard_stats(),
        report=get_analytics_report(),
        ml_status=get_unclaimed_order_readiness(),
        demo_model=load_demo_training_summary(current_app.instance_path),
        production_model=load_production_model_summary(current_app.instance_path),
        production_predictions=get_current_ready_order_predictions(current_app.instance_path),
    )
