"""Minimum-data policy is derived, documented and configurable."""
from app.analytics.ml.features import DAILY_FEATURES, WEEKLY_FEATURES
from app.analytics.ml.policy import (
    DEFAULT_POLICY, INSUFFICIENT_DATA_MESSAGE, Policy, WindowRule, get_policy,
)


def test_required_observations_are_derived_from_the_method():
    d, w = DEFAULT_POLICY.daily, DEFAULT_POLICY.weekly
    assert d.required_observations == d.warmup + d.min_train + d.backtest_folds * d.horizon == 14 + 42 + 28 == 84
    assert w.required_observations == w.warmup + w.min_train + w.backtest_folds * w.horizon == 4 + 12 + 8 == 24
    assert (d.backtest_span, w.backtest_span) == (28, 8)


def test_horizons_match_the_requirements():
    assert DEFAULT_POLICY.daily.horizon == 7 and DEFAULT_POLICY.weekly.horizon == 4
    assert DEFAULT_POLICY.daily.unit_word == "days" and DEFAULT_POLICY.weekly.unit_word == "weeks"


def test_policy_warmup_matches_the_feature_warmup():
    # If someone changes a lag without changing the policy, readiness would silently be wrong.
    assert DEFAULT_POLICY.daily.warmup == DAILY_FEATURES.warmup
    assert DEFAULT_POLICY.weekly.warmup == WEEKLY_FEATURES.warmup


def test_thresholds_are_configurable():
    custom = Policy(daily=WindowRule("day", 7, 7, 14, 2, 10), max_inactive_gap_days=21, service_min_orders=5)
    assert custom.daily.required_observations == 7 + 14 + 14
    assert custom.rule("day") is custom.daily and custom.rule("week") is custom.weekly
    assert (custom.max_inactive_gap_days, custom.service_min_orders) == (21, 5)
    assert DEFAULT_POLICY.daily.required_observations == 84          # defaults are untouched


def test_invalid_policy_values_are_rejected():
    bad = [
        lambda: WindowRule("hour", 7, 14, 42, 4, 30),
        lambda: WindowRule("day", 0, 14, 42, 4, 30),
        lambda: WindowRule("day", 7, 14, -1, 4, 30),
        lambda: WindowRule("day", 7, 14, 42, 0, 30),
        lambda: WindowRule("day", 7, 14, 42, 1, 30),                 # needs a validation AND a test fold
        lambda: WindowRule("day", 7, 14, 42, 4, 30, 3),              # max folds below the minimum
        lambda: Policy(min_skill=1.0),
        lambda: Policy(ml_min_improvement=-0.1),
        lambda: Policy(interval_level=0.3),
        lambda: Policy(ridge_alphas=()),
        lambda: Policy(ridge_alphas=(1.0, -2.0)),
        lambda: WindowRule("day", 7, 14, 42, 4, -5),
        lambda: Policy(max_inactive_gap_days=0),
        lambda: Policy(service_min_orders=-1),
    ]
    for make in bad:
        try:
            make()
        except ValueError:
            continue
        raise AssertionError("expected ValueError")


def test_get_policy_and_message():
    assert get_policy() is DEFAULT_POLICY
    assert "sufficient historical records" in INSUFFICIENT_DATA_MESSAGE
    assert "reliable model training" in INSUFFICIENT_DATA_MESSAGE


def test_evaluation_settings_have_documented_defaults():
    p = DEFAULT_POLICY
    assert p.min_skill == 0.10 and p.ml_min_improvement == 0.05 and p.interval_level == 0.8
    assert p.min_interval_residuals == 20 and p.ridge_alphas == (0.1, 1.0, 10.0, 100.0)
    assert p.daily.max_backtest_folds == 8 and p.weekly.max_backtest_folds == 6
    assert p.training_lock_minutes == 120 and p.outdated_after_horizons == 1.0
