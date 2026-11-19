"""Admin-only analytics and reporting routes."""
from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.analytics import bp
from app.analytics.services import get_unclaimed_report
from app.audit import services as audit
from app.core.decorators import role_required
from app.extensions import db
from app.models import Order, OrderDisposal, OrderStatus, Role
from app.orders.services import dashboard_stats


@bp.route("/", endpoint="index")
@login_required
@role_required(Role.ADMIN)
def index():
    """Render the admin analytics and reports workspace."""
    return render_template(
        "analytics/index.html",
        dashboard_title="Analytics & Reports",
        dashboard_description="Unclaimed orders and disposal-risk predictions.",
        admin_area=True,
        stats=dashboard_stats(),  # needed by the shared dashboard navigation
        report=get_unclaimed_report(),
    )


@bp.post("/orders/<int:order_id>/dispose", endpoint="dispose")
@login_required
@role_required(Role.ADMIN)
def dispose(order_id):
    """Record that an unclaimed Ready-for-Pickup order was disposed of.

    Only writes to order_disposals (plus an audit row). The order's own status is not changed.
    """
    order = db.session.get(Order, order_id)
    if order is None:
        abort(404)
    if order.status != OrderStatus.READY:
        flash("Only orders that are Ready for Pickup can be marked as disposed.", "error")
    elif db.session.scalar(db.select(OrderDisposal.id).where(OrderDisposal.order_id == order.id)):
        flash(f"Order {order.reference} is already marked as disposed.", "info")
    else:
        try:
            db.session.add(OrderDisposal(order_id=order.id, disposed_by_id=current_user.id))
            audit.record(
                audit.AuditAction.UPDATE, audit.AuditModule.ORDERS,
                f"Marked unclaimed order {order.reference} as disposed",
                resource_id=order.id, resource_label=f"Order {order.reference}",
            )
            db.session.commit()
            flash(f"Order {order.reference} marked as disposed.", "success")
        except IntegrityError:  # double-click / two admins at once
            db.session.rollback()
            flash(f"Order {order.reference} is already marked as disposed.", "info")
    return redirect(url_for("analytics.index"))


@bp.post("/orders/<int:order_id>/undo-dispose", endpoint="undo_dispose")
@login_required
@role_required(Role.ADMIN)
def undo_dispose(order_id):
    """Remove a 'disposed' mark that was made by mistake."""
    disposal = db.session.scalar(db.select(OrderDisposal).where(OrderDisposal.order_id == order_id))
    if disposal is None:
        abort(404)
    reference = disposal.order.reference
    db.session.delete(disposal)
    audit.record(
        audit.AuditAction.UPDATE, audit.AuditModule.ORDERS,
        f"Undid the disposed mark on order {reference}",
        resource_id=order_id, resource_label=f"Order {reference}",
    )
    db.session.commit()
    flash(f"Disposed mark removed from order {reference}.", "success")
    return redirect(url_for("analytics.index"))
