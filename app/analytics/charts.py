"""Numbers for the Analytics charts. Read-only, built from real orders and payments."""
from collections import Counter, OrderedDict
from datetime import timedelta
from decimal import Decimal

from app.analytics.ml.system_data import shop_today
from app.core.timeutil import local_day_bounds_utc, to_local
from app.extensions import db
from app.models import Order, OrderItem, OrderStatus, Payment, PaymentKind
from app.orders.services import status_counts

PERIODS = (7, 30, 90)
DEFAULT_PERIOD = 30
TOP_SERVICES = 6


def parse_period(raw):
    """Only the offered periods are accepted; anything else falls back to the default."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PERIOD
    return value if value in PERIODS else DEFAULT_PERIOD


def daily_buckets(days, today):
    """Ordered {date: 0} for the last `days` shop days, ending today."""
    return OrderedDict((today - timedelta(days=i), 0) for i in range(days - 1, -1, -1))


def bucket_orders(created_times, days, today):
    """Orders per shop-local day. Pure function."""
    buckets = daily_buckets(days, today)
    for moment in created_times:
        day = to_local(moment).date()
        if day in buckets:
            buckets[day] += 1
    return buckets


def bucket_revenue(payment_rows, days, today):
    """Money collected per shop-local day, net of reversals. Pure function."""
    buckets = OrderedDict((d, Decimal("0.00")) for d in daily_buckets(days, today))
    for kind, amount, paid_at in payment_rows:
        day = to_local(paid_at).date()
        if day in buckets:
            buckets[day] += Decimal(amount) if kind == PaymentKind.PAYMENT else -Decimal(amount)
    return buckets


def get_chart_data(days):
    today = shop_today()
    start_utc = local_day_bounds_utc(today - timedelta(days=days - 1))[0]
    end_utc = local_day_bounds_utc(today)[1]

    created = db.session.scalars(
        db.select(Order.created_at).where(Order.created_at >= start_utc, Order.created_at < end_utc)
    ).all()
    payments = db.session.execute(
        db.select(Payment.kind, Payment.amount, Payment.paid_at)
        .where(Payment.paid_at >= start_utc, Payment.paid_at < end_utc)
    ).all()
    used = db.func.count(db.distinct(OrderItem.order_id))
    services = db.session.execute(
        db.select(OrderItem.name, used.label("n"))
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.item_type != "addon", Order.created_at >= start_utc, Order.created_at < end_utc)
        .group_by(OrderItem.name).order_by(used.desc(), OrderItem.name).limit(TOP_SERVICES)
    ).all()

    orders = bucket_orders(created, days, today)
    revenue = bucket_revenue(payments, days, today)
    counts = status_counts()
    label = lambda d: f"{d:%b} {d.day}"  # noqa: E731  (e.g. "Nov 5")

    order_total = sum(orders.values())
    revenue_total = sum(revenue.values(), Decimal("0.00"))
    return {
        "days": days,
        "summary": {
            "orders": order_total,
            "revenue": revenue_total.quantize(Decimal("0.01")),
            "avg_order": (revenue_total / order_total).quantize(Decimal("0.01")) if order_total else None,
        },
        "orders": {"labels": [label(d) for d in orders], "values": list(orders.values())},
        "revenue": {"labels": [label(d) for d in revenue], "values": [float(v) for v in revenue.values()]},
        "status": {
            "labels": [OrderStatus.LABELS[s] for s in OrderStatus.FLOW],
            "values": [counts.get(s, 0) for s in OrderStatus.FLOW],
        },
        "services": {"labels": [r.name for r in services], "values": [int(r.n) for r in services]},
    }
