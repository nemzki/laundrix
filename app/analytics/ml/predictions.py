"""Score the orders that are waiting for pickup. Read-only: nothing is written."""
from app.analytics.ml import model as ml
from app.analytics.ml.features import FEATURE_LABELS
from app.analytics.ml.policy import DISPOSAL_DAYS, HIGH_RISK, MEDIUM_RISK
from app.models import OrderStatus


def risk_band(score):
    if score is None:
        return None
    if score >= HIGH_RISK:
        return "High"
    if score >= MEDIUM_RISK:
        return "Medium"
    return "Low"


def summarize_model(run):
    """Plain dict for the template, or None when there is no usable model."""
    if run is None:
        return None
    factors = sorted(
        (
            {"label": FEATURE_LABELS.get(name, name), "raises_risk": weight > 0, "strength": abs(weight)}
            for name, weight in zip(run.features, run.params["coefficients"])
        ),
        key=lambda item: item["strength"], reverse=True,
    )
    return {
        "version": run.version, "trained_at": run.trained_at, "n_orders": run.n_orders,
        "n_disposed": run.n_disposed, "data_start": run.data_start, "data_end": run.data_end,
        "disposal_days": run.disposal_days, "metrics": run.metrics, "factors": factors,
    }


def get_waiting_orders(run, today, records=None):
    """Orders waiting for pickup (still 'Ready for Pickup', not marked disposed).

    Each gets a disposal-risk score ONLY when a reliable model exists; otherwise the score is None.
    """
    if records is None:
        from app.analytics.ml.system_data import load_records
        records, _ = load_records(today)
    params = run.params if run else None
    items = []
    for r in records:
        if r["outcome"] is not None or r["status"] != OrderStatus.READY:
            continue
        score = ml.predict_probability(params, r["features"]) if params else None
        waited = max(0, (today - r["ready_date"]).days)
        items.append({
            "order_id": r["id"], "reference": r["reference"], "customer_name": r["customer_name"],
            "ready_date": r["ready_date"], "total": r["total"],
            "score_percent": None if score is None else round(score * 100, 1),
            "band": risk_band(score), "days_waiting": waited, "days_left": DISPOSAL_DAYS - waited,
        })
    items.sort(key=lambda i: (-(i["score_percent"] or 0), i["days_left"], i["reference"]))
    return items
