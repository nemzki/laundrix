"""Forecasting algorithms.  Pure tests (Ridge tests need scikit-learn)."""
import json
from datetime import date, timedelta

import numpy as np
import pytest

from app.analytics.ml import forecasting as fc

START = date(2026, 1, 5)          # a Monday


def test_naive_and_moving_average():
    y = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert fc.predict_baseline("naive", y, "day", 3) == [10.0, 10.0, 10.0]
    assert fc.predict_baseline("moving_average", y, "day", 2) == [7.0, 7.0]                  # mean of last 7 = (4..10)
    assert fc.predict_baseline("moving_average", y, "week", 1) == [8.5]                      # mean of last 4 = (7..10)


def test_seasonal_naive_repeats_last_week():
    y = list(range(1, 15))                                   # 14 days
    assert fc.predict_baseline("seasonal_naive", y, "day", 7) == [8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0]
    assert fc.predict_baseline("seasonal_naive", y, "day", 9)[7:] == [8.0, 9.0]              # wraps the weekly pattern


def test_weekday_mean_uses_the_same_weekday_of_the_last_four_weeks():
    y = [float(i % 7 + 10 * (i // 7)) for i in range(35)]    # week w, weekday d -> d + 10w
    out = fc.predict_baseline("weekday_mean_4", y, "day", 7)
    # weekday 0 of weeks 1..4 = 10, 20, 30, 40 -> mean 25
    assert out[0] == 25.0 and out[6] == 31.0


def test_baselines_are_never_negative_and_reject_bad_input():
    assert fc.predict_baseline("naive", [-5.0], "day", 2) == [0.0, 0.0]
    for call in (lambda: fc.predict_baseline("naive", [], "day", 1),
                 lambda: fc.predict_baseline("naive", [1.0], "day", 0),
                 lambda: fc.predict_baseline("seasonal_naive", [1.0] * 6, "day", 1),
                 lambda: fc.predict_baseline("seasonal_naive", [1.0] * 30, "week", 1),
                 lambda: fc.predict_baseline("weekday_mean_4", [1.0] * 20, "day", 1),
                 lambda: fc.predict_baseline("magic", [1.0] * 30, "day", 1)):
        with pytest.raises(ValueError):
            call()


def test_reference_is_the_historical_mean():
    assert fc.reference_forecast([2, 4, 6], 2) == [4.0, 4.0]


def test_baseline_catalogue():
    assert fc.BASELINES["day"] == ("naive", "moving_average", "seasonal_naive", "weekday_mean_4")
    assert fc.BASELINES["week"] == ("naive", "moving_average")           # no annual season is estimable yet
    assert all(fc.baseline_spec(n).is_baseline for n in fc.BASELINES["day"])


# ---- Ridge ----------------------------------------------------------------------------------

def _series(n=100, seed=1):
    week = np.array([4, 5, 6, 5, 8, 10, 3], float)
    return np.random.default_rng(seed).poisson(np.tile(week, n // 7 + 1)[:n] + 0.05 * np.arange(n)).astype(float)


def test_ridge_is_stored_as_plain_json_and_predicts_from_it():
    pytest.importorskip("sklearn")
    y = _series()
    spec = fc.fit_ridge(y, START, "day", 10.0)
    assert spec.kind == "ml" and spec.algorithm == "ridge" and spec.label.endswith("(machine learning)")
    revived = fc.ModelSpec(spec.algorithm, spec.kind, json.loads(json.dumps(spec.params)))      # what the database does
    assert fc.predict(revived, y, START, "day", 7) == fc.predict(spec, y, START, "day", 7)


def test_ridge_matches_the_closed_form_solution():
    pytest.importorskip("sklearn")
    from app.analytics.ml.features import build_training_matrix, config_for
    y = _series()
    spec = fc.fit_ridge(y, START, "day", 10.0)
    X, t, _ = build_training_matrix(y, START, config_for("day"))
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1
    Z = (X - mu) / sd
    w = np.linalg.solve(Z.T @ Z + 10.0 * np.eye(Z.shape[1]), Z.T @ (t - t.mean()))
    assert np.allclose(w, spec.params["coef"], atol=1e-8)
    assert abs(spec.params["intercept"] - t.mean()) < 1e-9
    assert spec.params["n_rows"] == len(y) - 14


def test_ridge_is_deterministic():
    pytest.importorskip("sklearn")
    y = _series()
    assert fc.fit_ridge(y, START, "day", 1.0).params == fc.fit_ridge(y, START, "day", 1.0).params


def test_ridge_forecast_shape_and_non_negativity():
    pytest.importorskip("sklearn")
    declining = np.maximum(0, 30 - 0.4 * np.arange(80)).astype(float)
    spec = fc.fit_ridge(declining, START, "day", 1.0)
    out = fc.predict(spec, declining, START, "day", 14)
    assert len(out) == 14 and all(v >= 0 for v in out)


def test_ridge_weekly():
    pytest.importorskip("sklearn")
    y = np.random.default_rng(2).poisson(30 + 0.8 * np.arange(40)).astype(float)
    spec = fc.fit_ridge(y, START, "week", 1.0)
    out = fc.predict(spec, y, START, "week", 4)
    assert len(out) == 4 and "weekday_0" not in spec.params["feature_names"]


def test_ridge_rejects_unusable_input():
    pytest.importorskip("sklearn")
    with pytest.raises(ValueError):
        fc.fit_ridge([1.0] * 15, START, "day", 1.0)                   # 15 values - 14 warm-up = one usable row
    spec = fc.fit_ridge(_series(), START, "day", 1.0)
    with pytest.raises(ValueError):
        fc.predict(spec, [1.0] * 5, START, "day", 7)                  # shorter than the warm-up


def test_trend_is_measured_from_the_training_start():
    pytest.importorskip("sklearn")
    y = _series(120)
    spec = fc.fit_ridge(y[:100], START, "day", 1.0)
    # the same model applied later (more history) must keep counting trend from START, not restart at 0
    later = fc.predict(spec, y, START, "day", 7)
    wrong = fc.predict(fc.ModelSpec("ridge", "ml", {**spec.params, "series_start": (START + timedelta(days=50)).isoformat()}), y, START, "day", 7)
    assert later != wrong


def test_make_forecast_dates_and_range():
    y = [5.0] * 30
    f = fc.make_forecast(fc.baseline_spec("naive"), y, START, "day", 7)
    assert f.dates[0] == START + timedelta(days=30) and f.dates[-1] == START + timedelta(days=36) and f.lower is None
    f = fc.make_forecast(fc.baseline_spec("naive"), y, START, "day", 3, half_width=8.0)
    assert f.lower == (0.0, 0.0, 0.0) and f.upper == (13.0, 13.0, 13.0)       # lower bound floored at zero
    w = fc.make_forecast(fc.baseline_spec("naive"), [1.0, 2.0], START, "week", 4)
    assert w.dates[1] - w.dates[0] == timedelta(days=7)
