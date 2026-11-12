"""Features are leakage-safe: a row only ever uses values BEFORE its own date."""
from datetime import date, timedelta

import numpy as np

from app.analytics.ml.features import (
    DAILY_FEATURES, WEEKLY_FEATURES, FeatureConfig, build_training_matrix, feature_row,
)

START = date(2026, 1, 5)          # a Monday


def test_feature_names_match_row_width():
    for cfg in (DAILY_FEATURES, WEEKLY_FEATURES):
        values = list(range(60))
        row = feature_row(values, cfg.warmup, START, cfg)
        assert len(row) == len(cfg.feature_names())
    assert DAILY_FEATURES.feature_names() == (
        ["lag_1", "lag_7", "lag_14", "roll_mean_7", "roll_mean_14", "trend"] + [f"weekday_{i}" for i in range(7)])
    assert "weekday_0" not in WEEKLY_FEATURES.feature_names()          # weekly has no weekday columns


def test_lag_and_rolling_values_are_exact():
    values = list(range(41))                      # value == its index
    t = 20
    row = feature_row(values, t, START + timedelta(days=t), DAILY_FEATURES)
    assert row[0] == 19 and row[1] == 13 and row[2] == 6              # lag_1, lag_7, lag_14
    assert row[3] == np.mean(range(13, 20)) == 16                     # mean of previous 7
    assert row[4] == np.mean(range(6, 20)) == 12.5                    # mean of previous 14
    assert row[5] == 20                                               # trend = position


def test_weekday_one_hot_follows_the_date():
    values = [1.0] * 40
    for offset in range(7):
        when = START + timedelta(days=14 + offset)                    # START is Monday
        row = feature_row(values, 14, when, DAILY_FEATURES)
        weekday = row[-7:]
        assert weekday.sum() == 1 and weekday[when.weekday()] == 1


def test_no_data_leakage_future_values_never_change_a_row():
    rng = np.random.default_rng(7)
    values = rng.integers(0, 20, 60).astype(float)
    for t in range(DAILY_FEATURES.warmup, len(values)):
        original = feature_row(values, t, START + timedelta(days=t), DAILY_FEATURES)
        tampered = values.copy()
        tampered[t:] = 9999.0                                          # rewrite the present and the future
        again = feature_row(tampered, t, START + timedelta(days=t), DAILY_FEATURES)
        assert np.array_equal(original, again), f"row {t} depends on values at or after t"


def test_training_matrix_alignment():
    values = np.arange(50, dtype=float)
    X, y, dates = build_training_matrix(values, START, DAILY_FEATURES)
    assert X.shape == (50 - 14, len(DAILY_FEATURES.feature_names()))
    assert len(y) == len(dates) == len(X)
    assert dates[0] == START + timedelta(days=14) and y[0] == 14      # target at t is values[t]
    assert X[0][0] == 13                                              # its lag_1 is values[t-1]


def test_forecast_row_equals_training_row():
    # Multi-step forecasting appends predictions to the history and asks for the next row; it must
    # match what the training matrix used, otherwise the model would see different features.
    values = np.arange(50, dtype=float)
    X, _, dates = build_training_matrix(values, START, DAILY_FEATURES)
    for i in (0, 5, len(X) - 1):
        t = DAILY_FEATURES.warmup + i
        assert np.array_equal(feature_row(values[:t], t, dates[i], DAILY_FEATURES), X[i])


def test_short_series_gives_empty_matrix_not_an_error():
    X, y, dates = build_training_matrix([1, 2, 3], START, DAILY_FEATURES)
    assert X.shape == (0, len(DAILY_FEATURES.feature_names())) and len(y) == 0 and dates == []
    X, y, _ = build_training_matrix([], START, WEEKLY_FEATURES)
    assert X.shape[0] == 0


def test_invalid_requests_are_rejected():
    for args in (([1.0] * 30, 5), ([1.0] * 3, 20)):                   # inside warm-up / history too short
        try:
            feature_row(args[0], args[1], START, DAILY_FEATURES)
        except ValueError:
            continue
        raise AssertionError("expected ValueError")


def test_inputs_are_not_mutated():
    values = [float(i) for i in range(40)]
    snapshot = list(values)
    build_training_matrix(values, START, DAILY_FEATURES)
    feature_row(values, 20, START, DAILY_FEATURES)
    assert values == snapshot


def test_weekly_features():
    values = [float(i) for i in range(20)]
    row = feature_row(values, 10, START, WEEKLY_FEATURES)
    assert list(row) == [9, 8, 6, np.mean([6, 7, 8, 9]), 10]          # lag1, lag2, lag4, roll4, trend


def test_config_is_describable():
    d = FeatureConfig("day", (1, 7), (7,), include_trend=False, include_calendar=False).as_dict()
    assert d == {"granularity": "day", "lags": [1, 7], "rolling_windows": [7], "include_trend": False, "include_calendar": False}
