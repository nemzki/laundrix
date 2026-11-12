"""Leakage-safe features for forecasting (pure: numpy only, no database).

The rule that prevents data leakage: the feature row for time ``t`` is computed ONLY from
observations strictly before ``t`` (``values[:t]``).  Lags and rolling means are therefore always
"what was already known when the forecast was made".  Calendar features depend only on the date.

Features (all explainable):
    lag_k            the value k steps ago
    roll_mean_w      the mean of the previous w values
    trend            number of steps since the series started (captures slow growth or decline)
    weekday_0..6     one-hot weekday (daily series only; Monday = 0)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from app.analytics.ml.schemas import Granularity


@dataclass(frozen=True)
class FeatureConfig:
    granularity: str
    lags: tuple
    rolling_windows: tuple
    include_trend: bool = True
    include_calendar: bool = True

    @property
    def warmup(self) -> int:
        """Rows at the start of a series that cannot be used as training examples."""
        return max(tuple(self.lags) + tuple(self.rolling_windows))

    @property
    def has_weekday(self) -> bool:
        return self.include_calendar and self.granularity == Granularity.DAY

    def feature_names(self) -> list[str]:
        names = [f"lag_{k}" for k in self.lags] + [f"roll_mean_{w}" for w in self.rolling_windows]
        if self.include_trend:
            names.append("trend")
        if self.has_weekday:
            names += [f"weekday_{i}" for i in range(7)]
        return names

    def as_dict(self) -> dict:
        return {
            "granularity": self.granularity, "lags": list(self.lags),
            "rolling_windows": list(self.rolling_windows), "include_trend": self.include_trend,
            "include_calendar": self.include_calendar,
        }


DAILY_FEATURES = FeatureConfig(Granularity.DAY, lags=(1, 7, 14), rolling_windows=(7, 14))
WEEKLY_FEATURES = FeatureConfig(Granularity.WEEK, lags=(1, 2, 4), rolling_windows=(4,))


def config_for(granularity: str) -> FeatureConfig:
    return DAILY_FEATURES if granularity == Granularity.DAY else WEEKLY_FEATURES


def feature_row(history, position: int, when: date, config: FeatureConfig, trend=None) -> np.ndarray:
    """Features for the observation at ``position`` (0-based index in the full series) dated ``when``.

    ``history`` must contain at least the ``position`` values that precede it; anything at or after
    ``position`` is never read.  Used for training rows and, with predicted values appended to
    ``history``, for multi-step forecasting.  ``trend`` overrides the trend feature (steps since the
    series the model was TRAINED on began); by default it is ``position``.
    """
    if position < config.warmup:
        raise ValueError(f"position {position} is inside the warm-up of {config.warmup}")
    if len(history) < position:
        raise ValueError("history is shorter than the position being predicted")
    past = np.asarray(history[:position], dtype=float)
    row = [past[position - k] for k in config.lags]
    row += [past[position - w:position].mean() for w in config.rolling_windows]
    if config.include_trend:
        row.append(float(position if trend is None else trend))
    if config.has_weekday:
        row += [1.0 if when.weekday() == i else 0.0 for i in range(7)]
    return np.asarray(row, dtype=float)


def build_training_matrix(values, start: date, config: FeatureConfig):
    """(X, y, dates) for every position that has a full set of past values.

    ``y[i]`` is the observed value at ``dates[i]``; ``X[i]`` uses only values before it.
    Returns empty arrays when the series is no longer than the warm-up.
    """
    values = np.asarray(values, dtype=float)
    step = timedelta(days=1 if config.granularity == Granularity.DAY else 7)
    rows, targets, dates = [], [], []
    for t in range(config.warmup, len(values)):
        when = start + step * t
        rows.append(feature_row(values, t, when, config))
        targets.append(values[t])
        dates.append(when)
    width = len(config.feature_names())
    X = np.vstack(rows) if rows else np.empty((0, width))
    return X, np.asarray(targets, dtype=float), dates
