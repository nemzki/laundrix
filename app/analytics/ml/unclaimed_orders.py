"""Privacy-minimizing readiness assessment for unclaimed-order prediction.

This module deliberately reports readiness only. It does not train a model or
claim predictive accuracy. Orders are represented only by status-history events;
customer identity and contact fields are never queried.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import OrderStatus, OrderStatusHistory

OBSERVATION_DAYS = 30
MINIMUM_ELIGIBLE_SAMPLES = 100
MINIMUM_PER_CLASS = 20


def summarize_unclaimed_history(history_rows, as_of=None):
    """Summarize latest Ready spell per order into fully observed 30-day labels.

    history_rows contains tuples of (order_id, event_id, to_status, created_at).
    Label 0: picked_up within 30 days after latest Ready event.
    Label 1: not picked_up within 30 days after latest Ready event.

    Orders whose 30-day observation window has not elapsed are excluded.
    """
    cutoff = as_of or datetime.now(timezone.utc).replace(tzinfo=None)
    by_order = defaultdict(list)
    for order_id, event_id, to_status, created_at in history_rows:
        by_order[order_id].append((created_at, event_id, to_status))

    within_window = 0
    not_within_window = 0
    excluded_recent = 0
    orders_with_ready_event = 0

    for events in by_order.values():
        events.sort(key=lambda event: (event[0], event[1]))
        ready_positions = [
            index for index, event in enumerate(events)
            if event[2] == OrderStatus.READY
        ]
        if not ready_positions:
            continue
        orders_with_ready_event += 1

        latest_ready_position = ready_positions[-1]
        latest_ready_at = events[latest_ready_position][0]
        deadline = latest_ready_at + timedelta(days=OBSERVATION_DAYS)

        if deadline > cutoff:
            excluded_recent += 1
            continue

        pickup_after_latest_ready = next(
            (
                event for event in events[latest_ready_position + 1:]
                if event[2] == OrderStatus.RELEASED
            ),
            None,
        )
        if pickup_after_latest_ready and pickup_after_latest_ready[0] <= deadline:
            within_window += 1
        else:
            not_within_window += 1

    eligible = within_window + not_within_window
    enough_total = eligible >= MINIMUM_ELIGIBLE_SAMPLES
    enough_classes = (
        within_window >= MINIMUM_PER_CLASS
        and not_within_window >= MINIMUM_PER_CLASS
    )
    threshold_met = enough_total and enough_classes

    if threshold_met:
        message = (
            "The minimum data threshold has been reached. Model training and "
            "chronological validation are still required before predictions "
            "can be displayed."
        )
        status = "data_threshold_met"
    else:
        message = (
            "Insufficient data available to train and validate an unclaimed-order "
            "prediction model. The initial requirement is at least "
            f"{MINIMUM_ELIGIBLE_SAMPLES} eligible orders, including at least "
            f"{MINIMUM_PER_CLASS} examples in each outcome. Orders without a "
            f"complete {OBSERVATION_DAYS}-day observation window are excluded."
        )
        status = "insufficient_data"

    return {
        "status": status,
        "message": message,
        "eligible_samples": eligible,
        "minimum_samples": MINIMUM_ELIGIBLE_SAMPLES,
        "minimum_per_class": MINIMUM_PER_CLASS,
        "picked_up_within_30_days": within_window,
        "not_picked_up_within_30_days": not_within_window,
        "excluded_recent_orders": excluded_recent,
        "observed_ready_orders": orders_with_ready_event,
    }


def get_unclaimed_order_readiness(as_of=None):
    """Read only the minimum status-history columns needed for readiness."""
    rows = db.session.execute(
        db.select(
            OrderStatusHistory.order_id,
            OrderStatusHistory.id,
            OrderStatusHistory.to_status,
            OrderStatusHistory.created_at,
        )
        .where(
            OrderStatusHistory.to_status.in_(
                (OrderStatus.READY, OrderStatus.RELEASED)
            )
        )
        .order_by(
            OrderStatusHistory.order_id,
            OrderStatusHistory.created_at,
            OrderStatusHistory.id,
        )
    ).all()
    return summarize_unclaimed_history(rows, as_of=as_of)


def build_unclaimed_training_rows(order_rows, item_rows, history_rows, as_of=None):
    """Build privacy-minimizing feature rows and 30-day labels from genuine records.

    order_rows: (order_id, total, created_at)
    item_rows: (order_id, item_type, quantity)
    history_rows: (order_id, event_id, to_status, created_at)
    One sample is produced per order using its latest Ready for Pickup event.
    """
    cutoff = as_of or datetime.now(timezone.utc).replace(tzinfo=None)
    orders = {row[0]: row for row in order_rows}
    items_by_order = defaultdict(list)
    for order_id, item_type, quantity in item_rows:
        items_by_order[order_id].append((item_type, float(quantity or 0)))

    history_by_order = defaultdict(list)
    for order_id, event_id, to_status, created_at in history_rows:
        history_by_order[order_id].append((created_at, event_id, to_status))

    examples = []
    for order_id, events in history_by_order.items():
        order = orders.get(order_id)
        if order is None:
            continue
        events.sort(key=lambda event: (event[0], event[1]))
        ready_indexes = [i for i, event in enumerate(events) if event[2] == OrderStatus.READY]
        if not ready_indexes:
            continue
        ready_index = ready_indexes[-1]
        ready_at = events[ready_index][0]
        deadline = ready_at + timedelta(days=OBSERVATION_DAYS)
        if deadline > cutoff:
            continue

        picked_up = any(
            event[2] == OrderStatus.RELEASED and event[0] <= deadline
            for event in events[ready_index + 1:]
        )
        order_created_at = order[2]
        item_rows_for_order = items_by_order.get(order_id, [])
        total_quantity = sum(quantity for _, quantity in item_rows_for_order)
        item_count = len(item_rows_for_order)
        service_count = sum(1 for item_type, _ in item_rows_for_order if item_type == "service")
        features = {
            "order_total": float(order[1] or 0),
            "item_count": item_count,
            "total_quantity": total_quantity,
            "service_count": service_count,
            "days_to_ready": max(0, (ready_at - order_created_at).days),
            "ready_weekday": ready_at.weekday(),
            "ready_month": ready_at.month,
        }
        examples.append({
            "order_id": order_id,
            "ready_at": ready_at,
            "features": features,
            "label": 0 if picked_up else 1,
        })
    examples.sort(key=lambda item: item["ready_at"])
    return examples


def get_unclaimed_training_rows(as_of=None):
    """Read real production rows needed for unclaimed-order training; no PII selected."""
    from app.models import Order, OrderItem

    order_rows = db.session.execute(
        db.select(Order.id, Order.total, Order.created_at)
    ).all()
    item_rows = db.session.execute(
        db.select(OrderItem.order_id, OrderItem.item_type, OrderItem.quantity)
    ).all()
    history_rows = db.session.execute(
        db.select(
            OrderStatusHistory.order_id,
            OrderStatusHistory.id,
            OrderStatusHistory.to_status,
            OrderStatusHistory.created_at,
        ).where(OrderStatusHistory.to_status.in_((OrderStatus.READY, OrderStatus.RELEASED)))
        .order_by(OrderStatusHistory.order_id, OrderStatusHistory.created_at, OrderStatusHistory.id)
    ).all()
    return build_unclaimed_training_rows(order_rows, item_rows, history_rows, as_of=as_of)
