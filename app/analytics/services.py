"""Read-only numbers for the Analytics & Reports page (unclaimed-order focus).

Nothing here writes to the database.
"""
from collections import OrderedDict
from decimal import Decimal

from app.analytics.ml.policy import DISPOSAL_DAYS
from app.analytics.ml.predictions import get_active_model, get_waiting_orders, summarize_model
from app.analytics.ml.training import shop_today
from app.extensions import db
from app.models import HistoricalTransaction, Order, OrderDisposal


def _money(value):
    return Decimal(str(value or 0))


def get_outcome_history(today):
    """Outcomes of imported orders: totals plus a by-month table (by ready month)."""
    rows = db.session.execute(
        db.select(
            HistoricalTransaction.ready_date,
            HistoricalTransaction.outcome_status,
            HistoricalTransaction.claimed_date,
            HistoricalTransaction.total_amount,
            HistoricalTransaction.status_source,
        ).where(
            HistoricalTransaction.outcome_status.in_(("claimed", "unclaimed", "disposed")),
            HistoricalTransaction.ready_date.is_not(None),
        ).order_by(HistoricalTransaction.ready_date)
    ).all()

    counts = {"claimed": 0, "unclaimed": 0, "disposed": 0}
    disposed_value = Decimal("0.00")
    pickup_days = []
    months = OrderedDict()
    simulated = False
    for row in rows:
        counts[row.outcome_status] += 1
        simulated = simulated or row.status_source != "recorded"
        month = months.setdefault(
            row.ready_date.strftime("%Y-%m"),
            {"label": row.ready_date.strftime("%b %Y"), "claimed": 0, "disposed": 0, "waiting": 0},
        )
        month["waiting" if row.outcome_status == "unclaimed" else row.outcome_status] += 1
        if row.outcome_status == "disposed":
            disposed_value += _money(row.total_amount)
        if row.outcome_status == "claimed" and row.claimed_date:
            pickup_days.append((row.claimed_date - row.ready_date).days)

    decided = counts["claimed"] + counts["disposed"]
    return {
        "has_data": bool(rows),
        "counts": counts,
        "disposal_rate": round(counts["disposed"] / decided * 100, 1) if decided else None,
        "disposed_value": disposed_value.quantize(Decimal("0.01")),
        "avg_pickup_days": round(sum(pickup_days) / len(pickup_days), 1) if pickup_days else None,
        "months": list(months.values())[-6:],
        "labels_simulated": simulated,
    }


def get_recent_disposals(limit=10):
    """Live orders an admin marked as disposed (newest first), so a mistake can be undone."""
    rows = db.session.execute(
        db.select(Order.id, Order.reference, Order.customer_name, Order.total, OrderDisposal.disposed_at)
        .join(OrderDisposal, OrderDisposal.order_id == Order.id)
        .order_by(OrderDisposal.disposed_at.desc(), OrderDisposal.id.desc())
        .limit(limit)
    ).all()
    total = db.session.scalar(db.select(db.func.count(OrderDisposal.id))) or 0
    return {
        "total": int(total),
        "rows": [
            {"order_id": r.id, "reference": r.reference, "customer_name": r.customer_name,
             "total": r.total, "disposed_at": r.disposed_at}
            for r in rows
        ],
    }


def get_unclaimed_report():
    """Everything the Analytics & Reports page shows."""
    today = shop_today()
    run = get_active_model()
    waiting = get_waiting_orders(run, today)
    high = [item for item in waiting if item["band"] == "High"]
    return {
        "today": today,
        "disposal_days": DISPOSAL_DAYS,
        "model": summarize_model(run),
        "waiting": waiting,
        "summary": {
            "waiting_count": len(waiting),
            "high_risk_count": len(high),
            "value_at_risk": sum((_money(item["total"]) for item in high), Decimal("0.00")).quantize(Decimal("0.01")),
            "overdue_count": sum(1 for item in waiting if item["days_left"] < 0),
        },
        "history": get_outcome_history(today),
        "disposals": get_recent_disposals(),
    }
