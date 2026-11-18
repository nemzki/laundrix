
"""Read-only dispatch prioritization for orders awaiting customer pickup."""

from datetime import datetime, timezone

from app.extensions import db
from app.models import Order, OrderStatus, OrderStatusHistory


def get_ready_dispatch_queue(as_of=None):
    """Return current Ready for Pickup orders, oldest ready event first.

    Waiting time is measured from the latest transition into Ready for Pickup,
    not from order creation. This is a rule-based queue, not an ML prediction.
    """
    now = as_of or datetime.now(timezone.utc).replace(tzinfo=None)

    ready_orders = db.session.execute(
        db.select(Order)
        .where(Order.status == OrderStatus.READY)
    ).scalars().all()

    if not ready_orders:
        return []

    order_ids = [order.id for order in ready_orders]

    history_rows = db.session.execute(
        db.select(
            OrderStatusHistory.order_id,
            OrderStatusHistory.created_at,
            OrderStatusHistory.id,
        )
        .where(
            OrderStatusHistory.order_id.in_(order_ids),
            OrderStatusHistory.to_status == OrderStatus.READY,
        )
        .order_by(
            OrderStatusHistory.order_id,
            OrderStatusHistory.created_at.desc(),
            OrderStatusHistory.id.desc(),
        )
    ).all()

    latest_ready = {}
    for row in history_rows:
        latest_ready.setdefault(row.order_id, row.created_at)

    queue = []

    for order in ready_orders:
        ready_at = latest_ready.get(order.id)

        # Do not invent a waiting time when historical status data is missing.
        if ready_at is None:
            continue

        elapsed_seconds = max(0, int((now - ready_at).total_seconds()))
        waiting_minutes = elapsed_seconds // 60
        waiting_days = waiting_minutes // (60 * 24)
        remaining_hours = (waiting_minutes % (60 * 24)) // 60
        remaining_minutes = waiting_minutes % 60

        queue.append({
            "order_id": order.id,
            "reference": order.reference,
            "customer_name": order.customer_name,
            "ready_at": ready_at,
            "waiting_minutes": waiting_minutes,
            "waiting_label": (
                f"{waiting_days}d {remaining_hours}h {remaining_minutes}m"
                if waiting_days
                else f"{remaining_hours}h {remaining_minutes}m"
            ),
            "total": order.total,
            "items": [
                {
                    "name": item.name,
                    "quantity": item.quantity,
                    "unit": item.unit,
                }
                for item in order.items
            ],
        })

    queue.sort(
        key=lambda item: (
            item["ready_at"],
            item["order_id"],
        )
    )

    for position, item in enumerate(queue, start=1):
        item["priority"] = position

    return queue
