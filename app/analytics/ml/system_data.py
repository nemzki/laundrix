"""Training data taken from Laundrix's own orders - never imported or generated records.

An order becomes a training example only when its outcome is CONFIRMED by the system:
  * claimed   - its status history shows it was picked up / completed after being ready
  * disposed  - an admin marked it as disposed on the Analytics page
and only once it is "mature" (ready at least DISPOSAL_DAYS ago), so recent orders, which could
not have been disposed yet, do not make the data look better than it is.
Orders still waiting, or waiting longer than the disposal period with nothing recorded, are
unconfirmed: they are never used as labels (they are reported as "needs review").
"""
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from app.analytics.ml.features import feature_vector
from app.analytics.ml.policy import (
    DISPOSAL_DAYS,
    MIN_PER_OUTCOME,
    MIN_TRAINING_ORDERS,
)
from app.core.timeutil import SHOP_TZ, to_local
from app.extensions import db
from app.models import (
    Order,
    OrderDisposal,
    OrderStatus,
    OrderStatusHistory,
    Payment,
    PaymentKind,
)

CLAIMED, DISPOSED = "claimed", "disposed"


def shop_today():
    return datetime.now(SHOP_TZ).date()


# --------------------------------------------------------------------------- pure logic
def classify(orders, payments, order_times, today):
    """Turn raw rows into labelled records. Pure function (no database access).

    orders:      list of dicts: id, reference, customer_id, customer_name, total, created_at,
                 status, ready_at, picked_at, disposed_at
    payments:    list of (order_id, kind, amount, paid_at)
    order_times: list of (customer_id, created_at) for ALL orders (to count earlier orders)
    Returns a list of dicts with the original fields plus: outcome, mature, features.
    """
    paid_rows = defaultdict(list)
    for order_id, kind, amount, paid_at in payments:
        sign = 1 if kind == PaymentKind.PAYMENT else -1
        paid_rows[order_id].append((paid_at, sign * Decimal(amount)))

    by_customer = defaultdict(list)
    for customer_id, created_at in order_times:
        by_customer[customer_id].append(created_at)
    for times in by_customer.values():
        times.sort()

    cutoff = today - timedelta(days=DISPOSAL_DAYS)
    records = []
    for order in orders:
        ready_at, picked_at, disposed_at = order["ready_at"], order["picked_at"], order["disposed_at"]
        ready_date = to_local(ready_at).date()

        if disposed_at is not None and picked_at is not None:
            outcome = None            # contradictory records: do not guess
        elif disposed_at is not None:
            outcome = DISPOSED
        elif picked_at is not None:
            outcome = CLAIMED
        else:
            outcome = None

        # Only money received by the moment the order became ready is a valid input,
        # otherwise the payment taken at pickup would leak the answer.
        paid_by_ready = sum(
            (amount for paid_at, amount in paid_rows[order["id"]] if paid_at <= ready_at),
            Decimal("0"),
        )
        total = Decimal(order["total"])
        earlier = bisect_left(by_customer[order["customer_id"]], order["created_at"])

        records.append({
            **order,
            "ready_date": ready_date,
            "outcome": outcome,
            "mature": ready_date <= cutoff,
            "features": feature_vector(total, total > 0 and paid_by_ready >= total, earlier, ready_date),
        })
    return records


def summarize(records, today):
    """Counts that decide whether training is allowed, plus data-quality notes."""
    labelled = [r for r in records if r["outcome"] and r["mature"]]
    claimed = sum(1 for r in labelled if r["outcome"] == CLAIMED)
    disposed = len(labelled) - claimed
    waiting = [r for r in records if r["outcome"] is None and r["status"] == OrderStatus.READY]
    overdue = [r for r in waiting if (today - r["ready_date"]).days >= DISPOSAL_DAYS]

    reasons = []
    if len(labelled) < MIN_TRAINING_ORDERS:
        reasons.append(f"{len(labelled)} of {MIN_TRAINING_ORDERS} confirmed orders")
    if claimed < MIN_PER_OUTCOME:
        reasons.append(f"{claimed} of {MIN_PER_OUTCOME} picked-up orders")
    if disposed < MIN_PER_OUTCOME:
        reasons.append(f"{disposed} of {MIN_PER_OUTCOME} disposed orders")

    return {
        "ready_orders": len(records),
        "labelled": len(labelled),
        "claimed": claimed,
        "disposed": disposed,
        "waiting": len(waiting),
        "overdue_unresolved": len(overdue),
        "enough": not reasons,
        "missing": reasons,
        "need_total": MIN_TRAINING_ORDERS,
        "need_each": MIN_PER_OUTCOME,
    }


# --------------------------------------------------------------------------- database layer
def load_records(today=None):
    """Every order that has ever been 'Ready for Pickup', labelled where the outcome is known."""
    today = today or shop_today()
    H = OrderStatusHistory
    ready = (
        db.select(H.order_id.label("order_id"), db.func.min(H.created_at).label("ready_at"))
        .where(H.to_status == OrderStatus.READY).group_by(H.order_id).subquery()
    )
    picked = (
        db.select(H.order_id.label("order_id"), db.func.min(H.created_at).label("picked_at"))
        .where(H.to_status.in_((OrderStatus.RELEASED, OrderStatus.COMPLETED)))
        .group_by(H.order_id).subquery()
    )
    rows = db.session.execute(
        db.select(
            Order.id, Order.reference, Order.customer_id, Order.customer_name, Order.total,
            Order.created_at, Order.status, ready.c.ready_at, picked.c.picked_at,
            OrderDisposal.disposed_at,
        )
        .join(ready, ready.c.order_id == Order.id)
        .outerjoin(picked, picked.c.order_id == Order.id)
        .outerjoin(OrderDisposal, OrderDisposal.order_id == Order.id)
        .order_by(ready.c.ready_at, Order.id)
    ).all()
    if not rows:
        return [], today

    orders = [dict(r._mapping) for r in rows]
    payments = [
        tuple(r) for r in db.session.execute(
            db.select(Payment.order_id, Payment.kind, Payment.amount, Payment.paid_at)
            .join(ready, ready.c.order_id == Payment.order_id)
        ).all()
    ]
    order_times = [tuple(r) for r in db.session.execute(db.select(Order.customer_id, Order.created_at)).all()]
    return classify(orders, payments, order_times, today), today


def training_rows(records):
    """Confirmed, mature records, oldest first (the order used for the time-based test split)."""
    return [r for r in records if r["outcome"] and r["mature"]]
