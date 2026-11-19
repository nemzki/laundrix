"""Score the orders that are currently waiting for pickup. Read-only: nothing is written."""
from collections import defaultdict
from datetime import timedelta

from app.analytics.ml import model as ml
from app.analytics.ml.features import FEATURE_LABELS, feature_vector, previous_order_counts
from app.analytics.ml.policy import DISPOSAL_DAYS, HIGH_RISK, MEDIUM_RISK
from app.core.timeutil import to_local
from app.extensions import db
from app.models import (
    HistoricalTransaction,
    Order,
    OrderDisposal,
    OrderStatus,
    OrderStatusHistory,
    PaymentStatus,
    UnclaimedModelRun,
)


def get_active_model():
    return db.session.execute(
        db.select(UnclaimedModelRun)
        .where(UnclaimedModelRun.is_active.is_(True))
        .order_by(UnclaimedModelRun.version.desc())
        .limit(1)
    ).scalar_one_or_none()


def risk_band(score):
    if score is None:
        return None
    if score >= HIGH_RISK:
        return "High"
    if score >= MEDIUM_RISK:
        return "Medium"
    return "Low"


def summarize_model(run):
    """Plain dict for the template, or None when no model has been trained."""
    if run is None:
        return None
    weights = run.params["coefficients"]
    factors = sorted(
        (
            {
                "label": FEATURE_LABELS.get(name, name),
                "raises_risk": weight > 0,
                "strength": abs(weight),
            }
            for name, weight in zip(run.features, weights)
        ),
        key=lambda item: item["strength"],
        reverse=True,
    )
    return {
        "version": run.version,
        "trained_at": run.trained_at,
        "n_orders": run.n_orders,
        "n_disposed": run.n_disposed,
        "data_start": run.data_start,
        "data_end": run.data_end,
        "disposal_days": run.disposal_days,
        "labels_simulated": run.labels_simulated,
        "metrics": run.metrics,
        "factors": factors,
    }


def _live_ready_orders():
    """Orders currently in 'Ready for Pickup', with the day they became ready."""
    orders = db.session.execute(
        db.select(Order).where(
            Order.status == OrderStatus.READY,
            Order.id.not_in(db.select(OrderDisposal.order_id)),  # already marked disposed
        )
    ).scalars().all()
    if not orders:
        return []

    ids = [order.id for order in orders]
    ready_rows = db.session.execute(
        db.select(OrderStatusHistory.order_id, OrderStatusHistory.created_at)
        .where(OrderStatusHistory.order_id.in_(ids), OrderStatusHistory.to_status == OrderStatus.READY)
        .order_by(OrderStatusHistory.order_id, OrderStatusHistory.created_at, OrderStatusHistory.id)
    ).all()
    ready_at = {}
    for order_id, created_at in ready_rows:
        ready_at[order_id] = created_at  # last one wins = latest Ready event

    customer_ids = {order.customer_id for order in orders}
    history = defaultdict(list)
    for customer_id, created_at in db.session.execute(
        db.select(Order.customer_id, Order.created_at).where(Order.customer_id.in_(customer_ids))
    ).all():
        history[customer_id].append(created_at)

    items = []
    for order in orders:
        moment = ready_at.get(order.id)
        if moment is None:       # never invent a waiting time
            continue
        items.append({
            "source": "Live order",
            "order_id": order.id,
            "reference": order.reference,
            "customer_name": order.customer_name,
            "ready_date": to_local(moment).date(),
            "total": order.total,
            "features": feature_vector(
                order.total,
                order.payment_status == PaymentStatus.PAID,
                sum(1 for created in history[order.customer_id] if created < order.created_at),
                to_local(moment).date(),
            ),
        })
    return items


def _imported_waiting_orders(today):
    """Imported history rows still waiting for pickup and not yet past their disposal date."""
    everyone = db.session.execute(
        db.select(
            HistoricalTransaction.id,
            HistoricalTransaction.customer_name,
            HistoricalTransaction.transaction_date,
            HistoricalTransaction.source_transaction_no,
        )
    ).all()
    previous = previous_order_counts(
        (r.id, r.customer_name, r.transaction_date, r.source_transaction_no) for r in everyone
    )
    rows = db.session.execute(
        db.select(HistoricalTransaction)
        .where(
            HistoricalTransaction.outcome_status == "unclaimed",
            HistoricalTransaction.ready_date.is_not(None),
            HistoricalTransaction.ready_date >= today - timedelta(days=DISPOSAL_DAYS),
        )
    ).scalars().all()
    return [
        {
            "source": "Imported history",
            "order_id": None,
            "reference": f"{row.transaction_date:%b %d} #{row.source_transaction_no}",
            "customer_name": row.customer_name or "—",
            "ready_date": row.ready_date,
            "total": row.total_amount,
            "features": feature_vector(
                row.total_amount, row.payment_status == "paid", previous.get(row.id, 0), row.ready_date
            ),
        }
        for row in rows
    ]


def get_waiting_orders(run, today):
    """Orders waiting for pickup, each with a disposal-risk score when a model exists."""
    params = run.params if run else None
    waiting = _live_ready_orders() + _imported_waiting_orders(today)
    for item in waiting:
        features = item.pop("features")
        score = ml.predict_probability(params, features) if params else None
        days_waiting = max(0, (today - item["ready_date"]).days)
        item.update({
            "score_percent": None if score is None else round(score * 100, 1),
            "band": risk_band(score),
            "days_waiting": days_waiting,
            "days_left": DISPOSAL_DAYS - days_waiting,
        })
    waiting.sort(key=lambda item: (-(item["score_percent"] or 0), item["days_left"], item["reference"]))
    return waiting
