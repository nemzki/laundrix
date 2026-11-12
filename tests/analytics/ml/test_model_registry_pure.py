"""Registry logic that needs no database: integrity checks, tamper detection, status table."""
import json
from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from app.analytics.ml import forecasting as fc
from app.analytics.ml import model_registry as reg
from app.analytics.ml.features import config_for
from app.analytics.ml.policy import DEFAULT_POLICY as P
from app.analytics.ml.schemas import ModelStatus

START = date(2026, 1, 5)
KEY = reg.ModelKey("orders", "day")


def make_run(spec, key=KEY, **over):
    """A stand-in for a database row (what load_model reads)."""
    params = json.loads(json.dumps(spec.params))                       # exactly what a JSON column round-trip does
    cfg = config_for(key.granularity).as_dict() if spec.algorithm == "ridge" else None
    run = SimpleNamespace(status="trained", schema_version=reg.SCHEMA_VERSION, algorithm=spec.algorithm, kind=spec.kind,
                          params=params, feature_config=cfg, target=key.target, granularity=key.granularity,
                          entity=key.stored_entity, checksum=None)
    run.checksum = reg.checksum_for(key, run.algorithm, run.kind, run.params, run.feature_config, run.schema_version)
    for k, v in over.items():
        setattr(run, k, v)
    return run


def ridge_spec():
    pytest.importorskip("sklearn")
    y = np.random.default_rng(1).poisson(5, 80).astype(float)
    return fc.fit_ridge(y, START, "day", 1.0)


def reseal(run):
    run.checksum = reg.checksum_for(KEY, run.algorithm, run.kind, run.params, run.feature_config, run.schema_version)
    return run


# ---- loading ---------------------------------------------------------------------------------------

def test_valid_models_load():
    spec = ridge_spec()
    loaded = reg.load_model(make_run(spec))
    assert loaded.algorithm == "ridge" and loaded.kind == "ml" and loaded.params == json.loads(json.dumps(spec.params))
    base = reg.load_model(make_run(fc.baseline_spec("seasonal_naive")))
    assert base.is_baseline and base.params == {}


def test_missing_or_unfinished_runs_do_not_load():
    for run in (None, make_run(fc.baseline_spec("naive"), status="evaluation_failed"),
                make_run(fc.baseline_spec("naive"), status="training"), make_run(fc.baseline_spec("naive"), status="error")):
        with pytest.raises(reg.ModelLoadError):
            reg.load_model(run)


def test_tampered_parameters_fail_the_integrity_check():
    run = make_run(ridge_spec())
    run.params["coef"][0] += 1.0                                       # a changed number with the old checksum
    with pytest.raises(reg.ModelLoadError, match="integrity"):
        reg.load_model(run)
    run2 = make_run(fc.baseline_spec("naive"))
    run2.algorithm = "moving_average"                                  # a swapped algorithm with the old checksum
    with pytest.raises(reg.ModelLoadError, match="integrity"):
        reg.load_model(run2)


def test_a_row_moved_to_another_key_fails():
    run = make_run(fc.baseline_spec("naive"))
    run.target = "gross_order_value"
    with pytest.raises(reg.ModelLoadError, match="integrity"):
        reg.load_model(run)


def test_incompatible_versions_and_feature_sets_must_be_retrained():
    run = make_run(ridge_spec(), schema_version=2)
    with pytest.raises(reg.ModelLoadError, match="incompatible"):
        reg.load_model(run)
    run = make_run(ridge_spec())
    run.params["feature_names"] = run.params["feature_names"][:-1]
    with pytest.raises(reg.ModelLoadError, match="different feature set"):
        reg.load_model(reseal(run))                                    # a self-consistent but outdated feature list
    run = make_run(ridge_spec())
    run.feature_config = {**run.feature_config, "lags": [1, 2]}
    with pytest.raises(reg.ModelLoadError, match="different feature set"):
        reg.load_model(reseal(run))


def test_malformed_parameters_are_rejected_even_with_a_valid_checksum():
    for mutate, why in [
        (lambda r: r.params.__setitem__("coef", r.params["coef"][:-1]), "wrong length"),
        (lambda r: r.params.__setitem__("intercept", float("nan")), "not finite"),
        (lambda r: r.params.__setitem__("mean", ["a"] * len(r.params["mean"])), "not numbers"),
        (lambda r: r.params.__setitem__("series_start", "not-a-date"), "bad date"),
        (lambda r: r.params.pop("scale"), "missing key"),
    ]:
        run = make_run(ridge_spec())
        mutate(run)
        try:
            run.checksum = reg.checksum_for(KEY, run.algorithm, run.kind, run.params, run.feature_config, run.schema_version)
        except ValueError:                                              # NaN cannot even be sealed
            run.checksum = "x"
        with pytest.raises(reg.ModelLoadError):
            reg.load_model(run)


def test_unknown_algorithms_and_kind_mismatches_are_rejected():
    for run in (make_run(fc.baseline_spec("naive"), algorithm="magic"),
                make_run(fc.baseline_spec("seasonal_naive"), granularity="week")):
        with pytest.raises(reg.ModelLoadError):
            reg.load_model(reseal(run) if run.algorithm != "magic" else run)
    r = make_run(fc.baseline_spec("naive"))
    r.kind = "ml"
    with pytest.raises(reg.ModelLoadError):
        reg.load_model(reseal(r))
    r = make_run(ridge_spec())
    r.kind = "baseline"
    with pytest.raises(reg.ModelLoadError):
        reg.load_model(reseal(r))
    r = make_run(fc.baseline_spec("naive"), params="not a dict")
    with pytest.raises(reg.ModelLoadError):
        reg.load_model(r)


def test_error_messages_expose_no_internals():
    run = make_run(fc.baseline_spec("naive"))
    run.checksum = "0" * 64
    with pytest.raises(reg.ModelLoadError) as err:
        reg.load_model(run)
    text = str(err.value)
    assert "retrain" in text.lower() and "/" not in text and "\\" not in text and ".py" not in text and "Traceback" not in text


# ---- checksum / key -----------------------------------------------------------------------------------

def test_checksum_is_deterministic_and_sensitive():
    a = reg.checksum_for(KEY, "ridge", "ml", {"b": 1.0, "a": [1, 2]}, {"x": 1})
    assert a == reg.checksum_for(KEY, "ridge", "ml", {"a": [1, 2], "b": 1.0}, {"x": 1}) and len(a) == 64      # key order is irrelevant
    assert a != reg.checksum_for(KEY, "ridge", "ml", {"b": 1.0000001, "a": [1, 2]}, {"x": 1})
    assert a != reg.checksum_for(reg.ModelKey("orders", "week"), "ridge", "ml", {"b": 1.0, "a": [1, 2]}, {"x": 1})
    with pytest.raises(ValueError):
        reg.checksum_for(KEY, "ridge", "ml", {"b": float("nan")}, None)


def test_long_entity_keys_fit_the_column_and_stay_distinct():
    a = reg.ModelKey("service_demand", "week", "package:~" + "x" * 300)
    b = reg.ModelKey("service_demand", "week", "package:~" + "x" * 299 + "y")
    assert len(a.stored_entity) <= 160 and a.stored_entity != b.stored_entity and a.stored_entity == a.stored_entity
    assert reg.ModelKey("orders", "day").stored_entity == "" and reg.ModelKey("orders", "day").label == "orders/day"


# ---- status ------------------------------------------------------------------------------------------------------

def status(**kw):
    base = dict(ready=True, training=False, has_active=False, active_usable=False, outdated=False, latest_failed=False)
    base.update(kw)
    return reg.derive_status(**base)


def test_status_decision_table():
    S = ModelStatus
    assert status(training=True, has_active=True, active_usable=True) == S.TRAINING                 # training wins
    assert status(has_active=True, active_usable=True) == S.TRAINED
    assert status(has_active=True, active_usable=True, outdated=True) == S.OUTDATED
    assert status(has_active=True, active_usable=False) == S.OUTDATED                                # corrupt / incompatible
    assert status(latest_failed=True) == S.EVALUATION_FAILED
    assert status(has_active=True, active_usable=True, latest_failed=True) == S.TRAINED              # the previous model is preserved
    assert status() == S.READY_FOR_TRAINING
    assert status(ready=False) == S.INSUFFICIENT_DATA
    assert status(ready=None) == S.NOT_TRAINED


def test_outdated_after_one_forecast_horizon():
    assert reg.is_outdated(date(2026, 11, 3), date(2026, 11, 10), "day", P) is True              # 7 days = one horizon
    assert reg.is_outdated(date(2026, 11, 4), date(2026, 11, 10), "day", P) is False
    assert reg.is_outdated(date(2026, 10, 12), date(2026, 11, 9), "week", P) is True             # 4 weeks
    assert reg.is_outdated(date(2026, 10, 19), date(2026, 11, 9), "week", P) is False
    assert reg.is_outdated(None, date(2026, 11, 10), "day", P) is False and reg.is_outdated(date(2026, 1, 1), None, "day", P) is False
