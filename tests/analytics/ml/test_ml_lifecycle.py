"""Model lifecycle against the database: registry, training, serving, failure handling, CLI.

Needs the Flask fixtures and scikit-learn.  The histories are deterministic SYNTHETIC test data built from
tests/analytics/ml/synthetic.py (their evaluation outcomes were verified when the tests were written).
Reference moments: NOW = Wed 2026-11-11 12:00 Manila (history ends Tue Nov 10); NOW2 = a week later.
"""
import json
from datetime import date, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy.exc import IntegrityError

pytest.importorskip("sklearn")

from app.analytics.ml import data_preparation as dp
from app.analytics.ml import evaluation as ev
from app.analytics.ml import forecasting as fc
from app.analytics.ml import model_registry as reg
from app.analytics.ml import readiness as rd
from app.analytics.ml import serving, training
from app.analytics.ml.schemas import ModelStatus
from app.extensions import db
from app.models import AnalyticsModelRun

from tests.analytics import factories as f
from tests.analytics.ml import synthetic as sy

NOW = datetime(2026, 11, 11, 4, 0)
NOW2 = datetime(2026, 11, 18, 4, 0)
ORDERS_DAY = reg.ModelKey("orders", "day")


# ---- helpers ------------------------------------------------------------------------------------------

def seed(kind, seed_, days, first_day=0, customer=None):
    """One order per synthetic count, received at 10:xx on each local day (D0 + index)."""
    customer = customer or f.make_customer("Test Customer", f.local(2026, 6, 1, 9))
    counts = sy.counts(kind, seed_, days)
    for i in range(first_day, days):
        day = sy.D0 + timedelta(days=i)
        for k in range(int(counts[i])):
            f.make_order(customer, 100, f.local(day.year, day.month, day.day, 9, k % 50),
                         received_at=f.local(day.year, day.month, day.day, 10, k % 50))
    db.session.commit()
    return customer


def by_key(report):
    return {(o.key.target, o.key.granularity): o for o in report.outcomes}


def n_runs(**where):
    stmt = db.select(db.func.count()).select_from(AnalyticsModelRun)
    for col, value in where.items():
        stmt = stmt.where(getattr(AnalyticsModelRun, col) == value)
    return db.session.scalar(stmt)


def target(overview, name, granularity):
    return next(t for t in overview["targets"] if t["target"] == name and t["granularity"] == granularity)


def open_and_activate(key, spec, now=NOW, **kw):
    run = reg.begin_run(key, trained_by="cli", now_utc=now, lock_minutes=120)
    reg.finish_run(run, status="trained", now_utc=now, spec=spec, metrics=kw.pop("metrics", {"selected": {}}),
                   data_start=date(2026, 7, 6), data_end=date(2026, 11, 10), n_observations=128, n_events=700,
                   activate=True, **kw)
    return run


@pytest.fixture()
def clock(monkeypatch):
    """Pin the application clock used by the CLI and training so tests do not depend on today's date."""
    state = {"now": NOW}
    monkeypatch.setattr("app.models.staff_credential.utcnow", lambda: state["now"])
    return state


# ---- registry -------------------------------------------------------------------------------------------

def test_versions_increase_and_only_one_model_is_active(app):
    r1 = open_and_activate(ORDERS_DAY, fc.baseline_spec("naive"))
    assert r1.version == 1 and r1.is_active and reg.active_run(ORDERS_DAY).id == r1.id
    r2 = open_and_activate(ORDERS_DAY, fc.baseline_spec("moving_average"))
    db.session.refresh(r1)
    assert r2.version == 2 and r1.is_active is False and reg.active_run(ORDERS_DAY).id == r2.id
    assert n_runs(is_active=True) == 1 and [r.version for r in reg.list_runs(ORDERS_DAY)] == [2, 1]      # history is kept
    other = reg.begin_run(reg.ModelKey("orders", "week"), trained_by="cli", now_utc=NOW, lock_minutes=120)
    assert other.version == 1                                                                              # versions are per model


def test_a_second_concurrent_run_is_refused_and_a_stale_lock_is_released(app):
    first = reg.begin_run(ORDERS_DAY, trained_by="cli", now_utc=NOW, lock_minutes=120)
    assert reg.training_in_progress(ORDERS_DAY, NOW, 120) is True
    with pytest.raises(reg.TrainingInProgress):
        reg.begin_run(ORDERS_DAY, trained_by="cli", now_utc=NOW + timedelta(minutes=5), lock_minutes=120)
    second = reg.begin_run(ORDERS_DAY, trained_by="cli", now_utc=NOW + timedelta(hours=3), lock_minutes=120)
    db.session.refresh(first)
    assert first.status == "error" and "Abandoned" in first.message and second.version == 2


def test_only_a_trained_run_with_a_model_can_be_activated(app):
    run = reg.begin_run(ORDERS_DAY, trained_by="cli", now_utc=NOW, lock_minutes=120)
    with pytest.raises(ValueError):
        reg.finish_run(run, status="evaluation_failed", now_utc=NOW, spec=fc.baseline_spec("naive"), activate=True)
    with pytest.raises(ValueError):
        reg.finish_run(run, status="trained", now_utc=NOW, spec=None, activate=True)
    run.is_active = True                                              # the database itself also refuses it
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_unexpected_failures_are_recorded_without_leaking_details(app):
    run = reg.begin_run(ORDERS_DAY, trained_by="cli", now_utc=NOW, lock_minutes=120)
    reg.mark_error(run.id, "Unexpected error: RuntimeError", NOW)
    db.session.refresh(run)
    assert run.status == "error" and run.message == "Unexpected error: RuntimeError" and not run.is_active


def test_a_stored_model_survives_the_database_round_trip_intact(app):
    y = sy.counts("trend", 1, 128).astype(float)
    spec = fc.fit_ridge(y, sy.D0, "day", 1.0)
    open_and_activate(ORDERS_DAY, spec)
    db.session.expire_all()                                            # force a real reload from the database
    loaded = reg.load_model(reg.active_run(ORDERS_DAY))
    assert np.allclose(fc.predict(loaded, y, sy.D0, "day", 7), fc.predict(spec, y, sy.D0, "day", 7))


def test_missing_model_means_no_forecast_and_a_clear_status(app):
    status, spec, run = reg.key_status(ORDERS_DAY, ready=True, series_end=date(2026, 11, 10), now_utc=NOW)
    assert spec is None and run is None and status.status == ModelStatus.READY_FOR_TRAINING and not status.usable
    assert reg.key_status(ORDERS_DAY, ready=False, series_end=None, now_utc=NOW)[0].status == ModelStatus.INSUFFICIENT_DATA


# ---- training --------------------------------------------------------------------------------------------

def test_insufficient_data_is_reported_and_nothing_is_trained_or_stored(app, payment_methods):
    seed("trend", 1, 20)                                               # far below the 84-day minimum
    report = training.train(now_utc=NOW)
    assert len(report.outcomes) == 6 and all(o.outcome == training.Outcome.INSUFFICIENT for o in report.outcomes)
    assert n_runs() == 0 and report.exit_code() == 0 and report.exit_code(strict=True) == 2
    assert all("complete" in o.message or "no eligible history" in o.message for o in report.outcomes)


def test_training_end_to_end_activates_only_what_passes_evaluation(app, payment_methods):
    seed("trend", 1, 128)
    report = training.train(now_utc=NOW)
    out = by_key(report)
    assert out[("orders", "day")].outcome == training.Outcome.PROMOTED and out[("gross_order_value", "day")].outcome == training.Outcome.PROMOTED
    for k in (("orders", "week"), ("gross_order_value", "week"), ("net_collections", "day"), ("net_collections", "week")):
        assert out[k].outcome == training.Outcome.INSUFFICIENT                 # 18 weeks < 24; no payment history at all
    assert n_runs() == 2 and n_runs(is_active=True) == 2 and report.exit_code() == 0
    run = reg.active_run(ORDERS_DAY)
    assert (run.status, run.version, run.trained_by, run.n_observations) == ("trained", 1, "cli", 128)
    assert run.data_start == sy.D0 and run.data_end == date(2026, 11, 10) and len(run.checksum) == 64
    assert run.algorithm == "ridge" and run.kind == "ml"                       # verified on this exact series
    assert run.metrics["selected"]["skill_vs_reference"] >= 0.10 and run.metrics["folds"]["count"] == 8
    json.dumps(run.params, allow_nan=False)


def test_forecasts_are_served_only_from_a_validated_model_and_are_honestly_labelled(app, payment_methods):
    customer = seed("trend", 1, 128)
    training.train(now_utc=NOW)
    data = serving.forecast_overview(now_utc=NOW)
    t = target(data, "orders", "day")
    assert t["usable"] and t["status_label"] == "TRAINED"
    fcst = t["forecast"]
    assert len(fcst["values"]) == 7 and all(v >= 0 for v in fcst["values"]) and fcst["dates"][0] == "2026-11-11"
    assert t["model"]["kind_label"] == "Machine learning" and t["model"]["version"] == 1
    assert fcst["range_level"] == 0.8 and len(fcst["lower"]) == 7
    assert all(lo <= v <= hi for lo, v, hi in zip(fcst["lower"], fcst["values"], fcst["upper"]))
    assert fcst["baseline_values"] and len(fcst["baseline_values"]) == 7 and fcst["baseline_label"]
    assert t["history"]["dates"][-1] == "2026-11-10" and len(t["history"]["values"]) == 28
    assert "estimates" in t["disclaimer"]
    money = target(data, "gross_order_value", "day")["forecast"]
    assert all(float(v).is_integer() for v in money["values"]) and money["currency"] == "PHP"      # no false precision
    for k in (("orders", "week"), ("net_collections", "day"), ("net_collections", "week")):
        blocked = target(data, *k)
        assert blocked["forecast"] is None and blocked["model"] is None and blocked["status_label"] == "INSUFFICIENT DATA"
    text = json.dumps(data)
    assert "Test Customer" not in text and customer.contact_normalized not in text and "TESTCONTACT" not in text


def test_structure_free_history_fails_evaluation_and_nothing_is_activated(app, payment_methods):
    seed("noise", 1, 128)
    report = training.train(now_utc=NOW)
    out = by_key(report)
    for k in (("orders", "day"), ("gross_order_value", "day")):
        assert out[k].outcome == training.Outcome.EVALUATION_FAILED and "historical average" in out[k].message
    assert n_runs(status="evaluation_failed") == 2 and n_runs(is_active=True) == 0 and report.exit_code() == 0
    t = target(serving.forecast_overview(now_utc=NOW), "orders", "day")
    assert t["status_label"] == "EVALUATION FAILED" and t["forecast"] is None and not t["usable"]


def test_a_failed_retraining_never_displaces_the_working_model(app, payment_methods, monkeypatch):
    seed("trend", 1, 128)
    training.train(now_utc=NOW)
    v1 = reg.active_run(ORDERS_DAY).id
    forced = ev.Evaluation(False, False, ("forced failure",), None, None, {"n_observations": 128}, None, None)
    monkeypatch.setattr(training.ev, "evaluate", lambda *a, **k: forced)
    out = by_key(training.train(now_utc=NOW))
    assert out[("orders", "day")].outcome == training.Outcome.EVALUATION_FAILED
    assert reg.active_run(ORDERS_DAY).id == v1                                         # the previous model is untouched
    assert [r.status for r in reg.list_runs(ORDERS_DAY)] == ["evaluation_failed", "trained"]
    t = target(serving.forecast_overview(now_utc=NOW), "orders", "day")
    assert t["usable"] and t["status_label"] == "TRAINED" and t["forecast"] is not None


def test_new_data_makes_the_model_outdated_then_retraining_replaces_it(app, payment_methods):
    customer = seed("trend", 1, 128)
    training.train(now_utc=NOW)
    seed("trend", 1, 135, first_day=128, customer=customer)                            # a week of new orders
    before = target(serving.forecast_overview(now_utc=NOW2), "orders", "day")
    assert before["status_label"] == "MODEL OUTDATED" and "Retraining" in before["message"]
    out = by_key(training.train(now_utc=NOW2))
    assert out[("orders", "day")].outcome == training.Outcome.PROMOTED and out[("orders", "day")].version == 2
    assert n_runs(is_active=True) == 2 and reg.active_run(ORDERS_DAY).version == 2          # one active model per target
    assert [r.is_active for r in reg.list_runs(ORDERS_DAY)] == [True, False]
    after = target(serving.forecast_overview(now_utc=NOW2), "orders", "day")
    assert after["status_label"] == "TRAINED" and after["model"]["version"] == 2 and after["model"]["data_end"] == "2026-11-17"
    assert after["model"]["kind_label"] == "Statistical baseline (not machine learning)"      # the validated winner on this data
    assert after["forecast"]["baseline_values"] is None


def test_dry_run_evaluates_but_writes_nothing(app, payment_methods):
    seed("trend", 1, 128)
    report = training.train(now_utc=NOW, dry_run=True)
    out = by_key(report)
    assert out[("orders", "day")].outcome == training.Outcome.PROMOTED and out[("orders", "day")].message.startswith("Dry run")
    assert n_runs() == 0


def test_an_unexpected_failure_is_contained_recorded_and_changes_nothing(app, payment_methods, monkeypatch):
    seed("trend", 1, 128)

    def boom(*args, **kwargs):
        raise RuntimeError("secret detail that must not be stored")
    monkeypatch.setattr(training.reg, "finish_run", boom)
    report = training.train(now_utc=NOW)
    out = by_key(report)
    assert out[("orders", "day")].outcome == training.Outcome.ERROR and report.exit_code() == 1
    runs = reg.list_runs(ORDERS_DAY)
    assert [r.status for r in runs] == ["error"] and runs[0].message == "Unexpected error: RuntimeError"
    assert "secret" not in out[("orders", "day")].message and n_runs(is_active=True) == 0


def test_a_model_already_being_trained_is_skipped_not_duplicated(app, payment_methods):
    seed("trend", 1, 128)
    reg.begin_run(ORDERS_DAY, trained_by="cli", now_utc=NOW, lock_minutes=120)
    report = training.train(now_utc=NOW)
    out = by_key(report)
    assert out[("orders", "day")].outcome == training.Outcome.IN_PROGRESS
    assert out[("gross_order_value", "day")].outcome == training.Outcome.PROMOTED and report.exit_code(strict=True) == 2


# ---- corrupted / incompatible models ---------------------------------------------------------------------------

def test_a_corrupted_model_is_never_used_and_never_crashes_the_dashboard(app, payment_methods):
    seed("trend", 1, 128)
    training.train(now_utc=NOW)
    run = reg.active_run(ORDERS_DAY)
    run.params = {**run.params, "coef": [c + 1.0 for c in run.params["coef"]]}      # tampered after training
    db.session.commit()
    t = target(serving.forecast_overview(now_utc=NOW), "orders", "day")
    assert t["usable"] is False and t["forecast"] is None and t["model"] is None
    assert t["status_label"] == "MODEL OUTDATED" and "integrity" in t["message"] and "retrained" in t["message"]
    assert "/" not in t["message"] and "\\" not in t["message"]                    # no paths or internals exposed
    assert target(serving.forecast_overview(now_utc=NOW), "gross_order_value", "day")["usable"]       # other models unaffected


def test_an_incompatible_model_is_refused_with_a_retrain_message(app, payment_methods):
    seed("trend", 1, 128)
    training.train(now_utc=NOW)
    run = reg.active_run(ORDERS_DAY)
    run.schema_version = 99
    db.session.commit()
    with pytest.raises(reg.ModelLoadError, match="incompatible"):
        reg.load_model(run)
    t = target(serving.forecast_overview(now_utc=NOW), "orders", "day")
    assert not t["usable"] and t["forecast"] is None and "retrained" in t["message"]


# ---- service demand ---------------------------------------------------------------------------------------------------

def test_service_demand_gives_no_prediction_without_enough_history_of_its_own(app, payment_methods):
    c = f.make_customer("Test Customer", f.local(2026, 9, 1, 9))
    for i in range(40):
        day = date(2026, 10, 1) + timedelta(days=i % 40)
        for k in range(2):
            f.make_order(c, 80, f.local(day.year, day.month, day.day, 9, k), received_at=f.local(day.year, day.month, day.day, 10, k),
                         items=[{"item_type": "service", "name": "Wash", "quantity": 1, "unit": "load", "line_total": 80}])
    db.session.commit()
    prepared = dp.prepare_all(NOW)
    payload = serving.service_demand_payload(prepared, rd.assess(prepared), NOW)
    assert payload["rankings"] == {"primary": [], "addons": []}
    assert len(payload["unavailable"]) == 1
    item = payload["unavailable"][0]
    assert item["label"] == "Wash" and item["weeks_required"] == 24 and item["weeks_available"] < 24
    assert item["status_label"] == "INSUFFICIENT DATA" and "complete weeks" in item["message"]


# ---- no web exposure + CLI --------------------------------------------------------------------------------------------------

def test_no_web_route_can_train_or_expose_models(app):
    rules = [r.rule.lower() for r in app.url_map.iter_rules()]
    assert not [r for r in rules if "train" in r or "model" in r], rules


def test_cli_with_no_data_reports_insufficient_data_and_exits_cleanly(app, payment_methods, clock):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["analytics-train"])
    assert result.exit_code == 0 and "INSUFFICIENT DATA" in result.output and "Forecasts are estimates" in result.output
    assert runner.invoke(args=["analytics-train", "--strict"]).exit_code == 2
    assert n_runs() == 0


def test_cli_trains_dry_runs_and_reports_status(app, payment_methods, clock):
    seed("trend", 1, 128)
    runner = app.test_cli_runner()
    dry = runner.invoke(args=["analytics-train", "--dry-run"])
    assert dry.exit_code == 0 and "Dry run" in dry.output and "WOULD ACTIVATE" in dry.output and n_runs() == 0
    only = runner.invoke(args=["analytics-train", "--target", "orders"])
    assert only.exit_code == 0 and "Order demand" in only.output and "Gross order value" not in only.output and n_runs() == 1
    full = runner.invoke(args=["analytics-train"])
    assert full.exit_code == 0 and "ACTIVATED" in full.output and "machine learning" in full.output.lower()
    assert "Test Customer" not in full.output
    status = runner.invoke(args=["analytics-status"])
    assert status.exit_code == 0 and "TRAINED" in status.output and "Service demand:" in status.output
    assert runner.invoke(args=["analytics-train", "--strict"]).exit_code == 2                    # some targets still lack data


def test_cli_explains_a_missing_package_instead_of_hiding_it(app, payment_methods, clock, monkeypatch):
    seed("trend", 1, 128)

    def missing(*a, **k):
        raise ImportError("No module named 'sklearn'", name="sklearn")
    monkeypatch.setattr(fc, "fit_ridge", missing)
    result = app.test_cli_runner().invoke(args=["analytics-train"])
    assert result.exit_code == 1 and "pip install" in result.output and n_runs() == 0
