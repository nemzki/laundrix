"""ML policy: minimum-data rules and validity thresholds.

Everything a business owner might want to tune lives here, and nowhere else.  Pass a custom
``Policy`` to any function that accepts ``policy=`` (tests do), or edit the defaults below.

How the minimum history is derived (not an arbitrary number)
------------------------------------------------------------
A forecasting method needs three consecutive stretches of history, in time order:

    warm-up           the first rows are consumed by the longest lag / rolling window, so they
                      cannot be used as training examples (daily: 14 days, weekly: 4 weeks)
    minimum training  enough examples to estimate the weekday pattern and a trend
                      (daily: 42 days = every weekday seen 6 times, weekly: 12 weeks)
    backtest span     chronological hold-out folds used to measure honest error
                      (daily: 4 folds x 7 days = 28 days, weekly: 2 folds x 4 weeks = 8 weeks)

    required observations = warm-up + minimum training + folds x horizon
        daily  = 14 + 42 + 28 = 84 complete days
        weekly =  4 + 12 +  8 = 24 complete weeks

These are *proposed starting values*.  They have not been validated against real Laundrix history
yet; once real data exists, review them (``flask analytics-readiness`` shows what is available).
``min_events`` is an additional guard: with very few underlying orders/payments the backtest error
is dominated by chance and WAPE is often undefined.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WindowRule:
    granularity: str          # "day" | "week"
    horizon: int              # steps forecast ahead: 7 days / 4 weeks
    warmup: int               # observations consumed by the longest lag / rolling window
    min_train: int            # minimum training examples after warm-up
    backtest_folds: int       # MINIMUM chronological hold-out folds (needs >= 2: validation + test)
    min_events: int           # minimum underlying events (orders or ledger entries) in the window
    max_backtest_folds: int = 8   # with more history, use more folds (better estimate), up to this many

    def __post_init__(self):
        if self.granularity not in ("day", "week"):
            raise ValueError("granularity must be 'day' or 'week'")
        for name in ("horizon", "warmup", "min_train", "backtest_folds"):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.backtest_folds < 2:
            raise ValueError("backtest_folds must be at least 2 (one validation fold and one test fold)")
        if self.max_backtest_folds < self.backtest_folds:
            raise ValueError("max_backtest_folds cannot be smaller than backtest_folds")
        if int(self.min_events) < 0:
            raise ValueError("min_events cannot be negative")

    @property
    def backtest_span(self) -> int:
        return self.backtest_folds * self.horizon

    @property
    def required_observations(self) -> int:
        return self.warmup + self.min_train + self.backtest_span

    @property
    def unit_word(self) -> str:
        return "days" if self.granularity == "day" else "weeks"


@dataclass(frozen=True)
class Policy:
    daily: WindowRule = field(default_factory=lambda: WindowRule("day", 7, 14, 42, 4, 30))
    weekly: WindowRule = field(default_factory=lambda: WindowRule("week", 4, 4, 12, 2, 30, 6))

    # A run of this many consecutive zero days is treated as a data gap (shop closed or the system
    # not in use), not as genuine zero demand.  Training uses only the history AFTER the last gap.
    max_inactive_gap_days: int = 14

    # Order validity: received_at may be earlier than created_at by at most this much (the legacy
    # order path stamps received_at a few milliseconds before created_at) and may not lie in the
    # future by more than this (clock skew).
    received_before_created_tolerance_seconds: int = 300
    received_in_future_tolerance_seconds: int = 300

    # Service demand: an individual service/package needs the weekly window rule above (counted
    # from its first complete week) AND at least this many orders in that window.
    service_min_orders: int = 20

    # Informational data-quality thresholds (never exclude data by themselves).
    zero_day_ratio_warning: float = 0.6

    # ---- evaluation and promotion (all proposed starting values, not yet validated on real data) ----
    # Ridge regularisation strengths tried; the best is chosen on VALIDATION folds only.
    ridge_alphas: tuple = (0.1, 1.0, 10.0, 100.0)
    # A model is promoted only if its TEST-fold MAE beats the "historical mean" reference by this fraction
    # (and also beats it on the validation folds and in most test folds).  A forecast that cannot beat
    # "always predict the historical average" has no skill.  10% was chosen from simulation: a 5% margin
    # promoted structure-free random data 6-27% of the time; the stricter gate promotes it 0.5-2% of the
    # time at 84+ daily observations (see docs/ and tests/analytics/ml/test_evaluation.py).
    min_skill: float = 0.10
    # The ML model must beat the best statistical baseline by this fraction (validation AND test)
    # and win a majority of test folds; otherwise the baseline is the candidate (and is labelled as one).
    ml_min_improvement: float = 0.05
    # Forecast range: the empirical quantile of past backtest absolute errors, only with enough errors.
    interval_level: float = 0.8
    min_interval_residuals: int = 20
    # A training run marked "training" longer than this is treated as abandoned.
    training_lock_minutes: int = 120
    # A model is OUTDATED once the data has advanced by this many forecast horizons past its training data.
    outdated_after_horizons: float = 1.0

    def __post_init__(self):
        if self.max_inactive_gap_days < 1:
            raise ValueError("max_inactive_gap_days must be positive")
        if self.service_min_orders < 0:
            raise ValueError("service_min_orders cannot be negative")
        if not 0 <= self.min_skill < 1 or not 0 <= self.ml_min_improvement < 1:
            raise ValueError("min_skill and ml_min_improvement must be in [0, 1)")
        if not 0.5 <= self.interval_level < 1:
            raise ValueError("interval_level must be in [0.5, 1)")
        if not self.ridge_alphas or any(a <= 0 for a in self.ridge_alphas):
            raise ValueError("ridge_alphas must be positive numbers")

    def rule(self, granularity: str) -> WindowRule:
        return self.daily if granularity == "day" else self.weekly


DEFAULT_POLICY = Policy()


def get_policy() -> Policy:
    """Single hook for the active policy (a future config override would go here)."""
    return DEFAULT_POLICY


INSUFFICIENT_DATA_MESSAGE = (
    "Machine learning forecasts are currently unavailable because the system does not have "
    "sufficient historical records. Additional verified historical order data is required "
    "before reliable model training can be performed."
)
