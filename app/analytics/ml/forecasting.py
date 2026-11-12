"""Forecasting algorithms (pure: numpy, plus scikit-learn only when FITTING Ridge).

Every model is a ``ModelSpec``: an algorithm name plus plain-number parameters.  Ridge's fitted
state is just coefficients and scaling constants, so it is stored as JSON and predicted with numpy.
Nothing is ever pickled, so there is no untrusted-deserialisation risk and no scikit-learn version
compatibility problem when a stored model is loaded.

Candidates
    baselines (no training):
        naive             repeat the last value
        moving_average    mean of the last 7 days / 4 weeks
        seasonal_naive    daily only: the same weekday one week earlier
        weekday_mean_4    daily only: mean of the same weekday over the last 4 weeks
    machine learning:
        ridge             regularised linear regression on lag / rolling / trend / weekday features
    reference (never promoted, only the yardstick for "skill"):
        historical_mean   always predict the average of all history

Predictions are never negative: orders, billed value and net collections are floored at zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from app.analytics.ml.features import build_training_matrix, config_for, feature_row
from app.analytics.ml.schemas import Granularity


class Kind:
    BASELINE = "baseline"
    ML = "ml"


LABELS = {
    "naive": "Naive (repeat last value)",
    "moving_average": "Moving average",
    "seasonal_naive": "Seasonal naive (same weekday last week)",
    "weekday_mean_4": "Weekday average (last 4 weeks)",
    "ridge": "Ridge regression (machine learning)",
    "historical_mean": "Historical mean (reference)",
}
BASELINES = {
    Granularity.DAY: ("naive", "moving_average", "seasonal_naive", "weekday_mean_4"),
    Granularity.WEEK: ("naive", "moving_average"),
}
MOVING_WINDOW = {Granularity.DAY: 7, Granularity.WEEK: 4}


@dataclass(frozen=True)
class ModelSpec:
    algorithm: str
    kind: str
    params: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return LABELS.get(self.algorithm, self.algorithm)

    @property
    def is_baseline(self) -> bool:
        return self.kind == Kind.BASELINE


def step_of(granularity: str) -> timedelta:
    return timedelta(days=1 if granularity == Granularity.DAY else 7)


def baseline_spec(name: str) -> ModelSpec:
    return ModelSpec(name, Kind.BASELINE, {})


def _check(history, horizon: int):
    if horizon < 1:
        raise ValueError("horizon must be positive")
    if len(history) == 0:
        raise ValueError("history is empty")
    return np.asarray(history, dtype=float)


def predict_baseline(name: str, history, granularity: str, horizon: int) -> list[float]:
    y = _check(history, horizon)
    n = len(y)
    if name == "naive":
        out = [y[-1]] * horizon
    elif name == "moving_average":
        out = [float(y[-MOVING_WINDOW[granularity]:].mean())] * horizon
    elif name == "seasonal_naive":
        if granularity != Granularity.DAY or n < 7:
            raise ValueError("seasonal_naive needs a daily series of at least 7 values")
        out = [y[n - 7 + (i % 7)] for i in range(horizon)]
    elif name == "weekday_mean_4":
        if granularity != Granularity.DAY or n < 28:
            raise ValueError("weekday_mean_4 needs a daily series of at least 28 values")
        out = []
        for i in range(horizon):
            same_weekday = [y[n + i - 7 * k] for k in range(1, 5) if 0 <= n + i - 7 * k < n]
            out.append(float(np.mean(same_weekday)))
    else:
        raise ValueError(f"unknown baseline: {name}")
    return [max(0.0, float(v)) for v in out]


def reference_forecast(history, horizon: int) -> list[float]:
    """The yardstick for skill: always predict the average of everything seen so far."""
    y = _check(history, horizon)
    return [max(0.0, float(y.mean()))] * horizon


def fit_ridge(history, start: date, granularity: str, alpha: float) -> ModelSpec:
    """Fit Ridge on lag / rolling / trend / weekday features of ``history`` only.

    scikit-learn is imported here (not at module import) so the application, readiness checks and
    prediction from stored models work even where scikit-learn is not installed.
    """
    cfg = config_for(granularity)
    X, y, _ = build_training_matrix(history, start, cfg)
    if len(y) < 2:
        raise ValueError("not enough training rows for Ridge")
    mean = X.mean(axis=0)
    scale = X.std(axis=0)
    scale[scale == 0] = 1.0                      # constant columns (e.g. a weekday never seen) stay at 0
    from sklearn.linear_model import Ridge       # noqa: PLC0415  (deliberately lazy)

    model = Ridge(alpha=float(alpha))
    model.fit((X - mean) / scale, y)
    return ModelSpec("ridge", Kind.ML, {
        "alpha": float(alpha),
        "series_start": start.isoformat(),
        "feature_names": cfg.feature_names(),
        "mean": [float(v) for v in mean],
        "scale": [float(v) for v in scale],
        "coef": [float(v) for v in model.coef_],
        "intercept": float(model.intercept_),
        "n_rows": int(len(y)),
    })


def predict_ridge(spec: ModelSpec, history, start: date, granularity: str, horizon: int) -> list[float]:
    """Recursive multi-step forecast: each prediction is appended to the history for the next step."""
    cfg = config_for(granularity)
    p = spec.params
    hist = [float(v) for v in history]
    if len(hist) < cfg.warmup:
        raise ValueError("history is shorter than the model's warm-up")
    trained_start = date.fromisoformat(p["series_start"])
    step = step_of(granularity)
    mean, scale, coef = np.asarray(p["mean"]), np.asarray(p["scale"]), np.asarray(p["coef"])
    out = []
    for _ in range(horizon):
        position = len(hist)
        when = start + step * position
        trend = (when - trained_start) / step                 # steps since the TRAINING series began
        row = feature_row(hist, position, when, cfg, trend=float(trend))
        value = max(0.0, float(p["intercept"] + coef @ ((row - mean) / scale)))
        out.append(value)
        hist.append(value)
    return out


def predict(spec: ModelSpec, history, start: date, granularity: str, horizon: int) -> list[float]:
    if spec.algorithm == "ridge":
        return predict_ridge(spec, history, start, granularity, horizon)
    return predict_baseline(spec.algorithm, history, granularity, horizon)


@dataclass(frozen=True)
class Forecast:
    dates: tuple
    values: tuple
    lower: tuple | None = None
    upper: tuple | None = None


def make_forecast(spec: ModelSpec, history, start: date, granularity: str, horizon: int,
                  half_width: float | None = None) -> Forecast:
    """Forecast the next ``horizon`` steps after ``history``.  The range (when given) is the point
    forecast +/- an empirical backtest error, floored at zero; it is not a statistical guarantee."""
    values = predict(spec, history, start, granularity, horizon)
    step = step_of(granularity)
    dates = tuple(start + step * (len(history) + i) for i in range(horizon))
    if half_width is None:
        return Forecast(dates, tuple(values))
    return Forecast(dates, tuple(values), tuple(max(0.0, v - half_width) for v in values),
                    tuple(v + half_width for v in values))
