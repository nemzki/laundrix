"""Everything the Analytics & Reports page shows. Read-only apart from the automatic model
training described in app/analytics/ml/training.py."""
from app.analytics.charts import get_chart_data
from app.analytics.ml.policy import DISPOSAL_DAYS
from app.analytics.ml.predictions import get_waiting_orders, summarize_model
from app.analytics.ml.system_data import load_records
from app.analytics.ml.training import ensure_model
from app.extensions import db
from app.models import Order, OrderDisposal


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


def get_analytics_report(days):
    records, today = load_records()
    run, status, message, info = ensure_model(records, today)
    waiting = get_waiting_orders(run, today, records)
    high = [w for w in waiting if w["band"] == "High"]
    return {
        "today": today,
        "disposal_days": DISPOSAL_DAYS,
        "charts": get_chart_data(days),
        "ml": {
            "status": status,            # trained / not_ready / not_reliable / error
            "message": message,
            "info": info,
            "model": summarize_model(run),
            "scores_available": run is not None,
        },
        "waiting": waiting,
        "waiting_summary": {
            "count": len(waiting),
            "high_risk": len(high),
            "overdue": sum(1 for w in waiting if w["days_left"] < 0),
        },
        "disposals": get_recent_disposals(),
    }
