"""Forecast generation from ACTIVE, validated models (read-only; never trains, never writes).

Returns plain dictionaries ready for JSON.  A forecast is produced only when a usable active model
exists; otherwise the payload says why (insufficient data, not trained, evaluation failed, model
outdated/unusable) and carries NO forecast values.  Values are rounded to avoid false precision
(orders to 0.1, money to whole pesos).  Every forecast states whether it came from machine learning
or from a statistical baseline, and that it is an estimate.
"""
from __future__ import annotations

from datetime import datetime

from app.analytics.ml import forecasting as fc
from app.analytics.ml import model_registry as reg
from app.analytics.ml import readiness as rd
from app.analytics.ml import service_demand as sd
from app.analytics.ml.data_preparation import PreparedData, prepare_all
from app.analytics.ml.policy import DEFAULT_POLICY, Policy
from app.analytics.ml.schemas import ModelStatus, Series, Target, Unit

DISCLAIMER = ("Forecasts are estimates based on historical business activity. Actual results may differ, "
              "and nothing here is a guarantee.")
KIND_LABEL = {fc.Kind.ML: "Machine learning", fc.Kind.BASELINE: "Statistical baseline (not machine learning)"}
HISTORY_TAIL = {"day": 28, "week": 12}


def _round(value: float, unit: str) -> float:
    return round(value, 0 if unit == Unit.PESO else 1)


def _series_payload(dates, values, unit):
    return {"dates": [d.isoformat() for d in dates], "values": [_round(v, unit) for v in values]}


def _model_info(run, spec) -> dict:
    sel = (run.metrics or {}).get("selected", {}) if run is not None else {}
    return {
        "version": run.version, "algorithm": spec.algorithm, "algorithm_label": spec.label, "kind": spec.kind,
        "kind_label": KIND_LABEL[spec.kind], "trained_at": run.finished_at.isoformat() if run.finished_at else None,
        "data_start": run.data_start.isoformat() if run.data_start else None,
        "data_end": run.data_end.isoformat() if run.data_end else None,
        "n_observations": run.n_observations,
        "evaluation": {"test_mae": (sel.get("test") or {}).get("mae"), "test_wape": (sel.get("test") or {}).get("wape"),
                       "skill_vs_historical_average": sel.get("skill_vs_reference"),
                       "folds": (run.metrics or {}).get("folds")},
    }


def forecast_for(series: Series, readiness: rd.TargetReadiness, key: reg.ModelKey, now_utc: datetime,
                 policy: Policy = DEFAULT_POLICY) -> dict:
    """Status + (when usable) forecast for one model key, from the current history in ``series``."""
    status, spec, run = reg.key_status(key, ready=readiness.ready, series_end=series.end, now_utc=now_utc, policy=policy)
    payload = {
        "target": key.target, "granularity": key.granularity, "entity": key.entity or None, "label": readiness.label,
        "unit": series.unit, "status": status.status, "status_label": ModelStatus.LABELS[status.status],
        "message": status.message or readiness.message, "usable": status.usable,
        "readiness": readiness.as_dict(), "model": None, "forecast": None, "history": None, "disclaimer": DISCLAIMER,
    }
    if series.n:
        tail = HISTORY_TAIL[key.granularity]
        payload["history"] = _series_payload(series.dates()[-tail:], series.values[-tail:], series.unit)
    if spec is None or run is None or not series.n:
        return payload

    horizon = policy.rule(key.granularity).horizon
    half_width = ((run.metrics or {}).get("interval") or {}).get("half_width")
    try:
        forecast = fc.make_forecast(spec, series.values, series.start, key.granularity, horizon, half_width)
    except ValueError:
        payload.update(usable=False, message="The stored model could not be applied to the current history. Retrain it.")
        return payload

    baseline_values = None
    base_name = (run.metrics or {}).get("baseline_algorithm")
    if spec.kind == fc.Kind.ML and base_name:
        try:
            baseline_values = [_round(v, series.unit) for v in fc.predict_baseline(base_name, series.values, key.granularity, horizon)]
        except ValueError:
            baseline_values = None
    payload["model"] = _model_info(run, spec)
    payload["forecast"] = {
        **_series_payload(forecast.dates, forecast.values, series.unit),
        "lower": None if forecast.lower is None else [_round(v, series.unit) for v in forecast.lower],
        "upper": None if forecast.upper is None else [_round(v, series.unit) for v in forecast.upper],
        "range_level": None if half_width is None else policy.interval_level,
        "range_note": None if half_width is None else
        f"Approximate range: {policy.interval_level:.0%} of past backtest errors were no larger than this. Not a guarantee.",
        "baseline_label": None if baseline_values is None else fc.LABELS[base_name], "baseline_values": baseline_values,
        "horizon": horizon, "currency": "PHP" if series.unit == Unit.PESO else None,
    }
    return payload


def forecast_overview(now_utc: datetime | None = None, policy: Policy = DEFAULT_POLICY,
                      prepared: PreparedData | None = None) -> dict:
    """Everything the dashboard needs: readiness, per-target status/forecast, and service demand."""
    from app.models.staff_credential import utcnow

    now_utc = now_utc or utcnow()
    prepared = prepared or prepare_all(now_utc, policy)
    overview = rd.assess(prepared, policy)
    targets = [forecast_for(prepared.series(tr.target, tr.granularity), tr, reg.ModelKey(tr.target, tr.granularity), now_utc, policy)
               for tr in overview.targets]
    return {"generated_at": overview.generated_at, "as_of": prepared.as_of.isoformat(), "readiness": overview.as_dict(),
            "targets": targets, "services": service_demand_payload(prepared, overview, now_utc, policy), "disclaimer": DISCLAIMER}


def service_demand_payload(prepared: PreparedData, overview: rd.ReadinessOverview, now_utc: datetime,
                           policy: Policy = DEFAULT_POLICY) -> dict:
    """Per-service predictions only where a validated model exists; every other service says why not."""
    by_key = {e.key: e for e in prepared.services}
    items, unavailable = [], []
    for tr in overview.services.entities:
        entity = by_key[tr.entity]
        key = reg.ModelKey(Target.SERVICE_DEMAND, "week", entity.key)
        status, spec, run = reg.key_status(key, ready=tr.ready, series_end=entity.orders_weekly.end, now_utc=now_utc, policy=policy)
        if spec is None or run is None or not entity.orders_weekly.n:
            unavailable.append({"key": entity.key, "label": entity.label, "item_type": entity.item_type,
                                "status": status.status, "status_label": ModelStatus.LABELS[status.status],
                                "message": status.message or tr.message, "weeks_available": tr.observations,
                                "weeks_required": tr.required, "orders_available": tr.events,
                                "orders_required": tr.required_events})
            continue
        horizon = policy.weekly.horizon
        try:
            weekly = fc.predict(spec, entity.orders_weekly.values, entity.orders_weekly.start, "week", horizon)
        except ValueError:
            unavailable.append({"key": entity.key, "label": entity.label, "item_type": entity.item_type, "status": status.status,
                                "status_label": ModelStatus.LABELS[status.status],
                                "message": "The stored model could not be applied. Retrain it.",
                                "weeks_available": tr.observations, "weeks_required": tr.required,
                                "orders_available": tr.events, "orders_required": tr.required_events})
            continue
        recent = entity.orders_weekly.values[-4:]
        items.append(sd.DemandItem(entity.key, entity.label, entity.item_type, float(sum(recent) / len(recent)),
                                   tuple(weekly), spec.algorithm, spec.kind))
    return {"measure": "orders per week containing the item (order frequency, not revenue)", "horizon_weeks": policy.weekly.horizon,
            "rankings": sd.rank(items), "unavailable": unavailable, "disclaimer": DISCLAIMER}
