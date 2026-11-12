"""Chronological evaluation and the promotion decision.  Pure tests (need scikit-learn).

The synthetic series below exist only to test the machinery; they are never presented as business data.
"""
import json
from datetime import date

import numpy as np
import pytest

from app.analytics.ml import evaluation as ev
from app.analytics.ml import forecasting as fc
from app.analytics.ml.policy import DEFAULT_POLICY as P
from tests.analytics.ml import synthetic as sy

pytest.importorskip("sklearn")

START = date(2026, 1, 5)
WEEK = np.array([4, 5, 6, 5, 8, 10, 3], float)


def noise(n, seed, lam=5.0):
    return np.random.default_rng(seed).poisson(lam, n).astype(float)


def pattern(n, seed, mult=1.0):
    return np.random.default_rng(seed).poisson(np.tile(WEEK, n // 7 + 1)[:n] * mult).astype(float)


def trending(n, seed, slope=0.06):
    return np.random.default_rng(seed).poisson(np.tile(WEEK, n // 7 + 1)[:n] + slope * np.arange(n)).astype(float)


# ---- metrics ------------------------------------------------------------------------------------

def test_metrics():
    assert ev.mae([1, 2, 3], [2, 2, 5]) == 1.0
    assert ev.wape([10, 10], [8, 13]) == 0.25                        # (2 + 3) / 20
    assert ev.wape([0, 0], [1, 2]) is None                           # undefined, never 0 or infinity
    assert ev.mean_error([1, 2], [3, 4]) == 2.0                      # forecast above actual: positive bias


# ---- folds --------------------------------------------------------------------------------------------

def test_fold_layout_at_the_approved_minimums():
    d, w = P.daily, P.weekly
    assert ev.n_folds_for(84, d) == 4 and ev.make_origins(84, d) == [56, 63, 70, 77]
    assert ev.split_folds(4) == ([0, 1], [2, 3])
    assert ev.n_folds_for(24, w) == 2 and ev.make_origins(24, w) == [16, 20]
    assert ev.split_folds(2) == ([0], [1])                           # validation then test, in time order
    assert ev.n_folds_for(83, d) == 3 and ev.n_folds_for(10, d) == 0


def test_more_history_means_more_folds_up_to_the_maximum():
    assert ev.n_folds_for(100, P.daily) == 6          # (100 - 14 - 42) // 7
    assert ev.n_folds_for(120, P.daily) == 8 and ev.n_folds_for(400, P.daily) == 8      # capped at the maximum
    assert ev.n_folds_for(40, P.weekly) == 6 and ev.n_folds_for(200, P.weekly) == 6


def test_every_fold_ends_inside_the_series_and_the_last_ends_at_the_end():
    for n in (84, 100, 250):
        origins = ev.make_origins(n, P.daily)
        assert origins[-1] + 7 == n and all(b - a == 7 for a, b in zip(origins, origins[1:]))
        assert origins[0] >= P.daily.warmup + P.daily.min_train


# ---- no leakage ---------------------------------------------------------------------------------------------

def test_validation_scores_do_not_depend_on_the_test_window():
    y = trending(150, 1)
    base = ev.evaluate(y, START, "day", P)
    origins = ev.make_origins(len(y), P.daily)
    _, test_idx = ev.split_folds(len(origins))
    tampered = y.copy()
    tampered[origins[test_idx[0]]:] += 500.0                         # rewrite the whole test window
    other = ev.evaluate(tampered, START, "day", P)
    for key, rec in base.metrics["candidates"].items():
        assert rec["validation"] == other.metrics["candidates"][key]["validation"], key


def test_candidate_table_contains_every_baseline_and_every_ridge_strength():
    m = ev.evaluate(pattern(120, 1), START, "day", P).metrics
    assert set(m["candidates"]) == {"naive", "moving_average", "seasonal_naive", "weekday_mean_4",
                                    "ridge@0.1", "ridge@1", "ridge@10", "ridge@100"}
    w = ev.evaluate(np.random.default_rng(3).poisson(30 + 1.2 * np.arange(40)).astype(float), START, "week", P).metrics
    assert set(w["candidates"]) == {"naive", "moving_average", "ridge@0.1", "ridge@1", "ridge@10", "ridge@100"}
    assert "reference" in m and m["folds"]["validation"] + m["folds"]["test"] == m["folds"]["count"]


# ---- decisions --------------------------------------------------------------------------------------------------

def test_structure_free_noise_is_rejected_with_a_reason():
    e = ev.evaluate(noise(120, 1), START, "day", P)
    assert not e.passed and not e.promote and e.selected is None
    assert any("historical average" in r for r in e.reasons)


def test_a_real_weekday_pattern_is_accepted_and_labelled_by_what_it_is():
    e = ev.evaluate(pattern(120, 1), START, "day", P)
    assert e.passed and e.promote and e.selected is not None
    sel = e.metrics["selected"]
    assert sel["skill_vs_reference"] >= P.min_skill and sel["test"]["wape"] is not None
    assert (e.selected.kind == "ml") == (sel["algorithm"] == "ridge")                   # kind always matches the algorithm
    if e.selected.kind == "baseline":
        assert any("Ridge did not beat" in r for r in e.reasons)                       # the veto is explained


def test_ridge_wins_when_trend_and_weekday_structure_both_exist():
    e = ev.evaluate(trending(150, 1), START, "day", P)
    assert e.passed and e.selected.algorithm == "ridge" and e.selected.kind == "ml"
    assert e.selected.params["n_rows"] == 150 - 14                    # the final model is fitted on ALL the history
    assert e.baseline is not None and e.baseline.is_baseline          # the best baseline is kept for comparison charts


def test_promotion_gate_is_conservative_on_random_data_and_effective_on_real_structure():
    noise_promoted = sum(ev.evaluate(noise(120, s), START, "day", P).passed for s in range(40))
    pattern_promoted = sum(ev.evaluate(pattern(120, s), START, "day", P).passed for s in range(40))
    assert noise_promoted <= 4, f"{noise_promoted}/40 random series were promoted"      # measured about 0.7%
    assert pattern_promoted >= 20, f"only {pattern_promoted}/40 real patterns were promoted"   # measured about 70%


def test_all_zero_history_cannot_be_evaluated():
    e = ev.evaluate([0.0] * 100, START, "day", P)
    assert not e.passed and any("undefined" in r or "cannot be judged" in r or "no activity" in r for r in e.reasons)


def test_too_little_history_is_refused_not_guessed():
    e = ev.evaluate(pattern(50, 1), START, "day", P)
    assert not e.passed and "Not enough history" in e.reasons[0] and e.selected is None


def test_forecast_range_needs_enough_backtest_errors():
    daily = ev.evaluate(trending(150, 1), START, "day", P)
    assert daily.interval is not None and daily.interval["level"] == 0.8
    assert daily.interval["n_residuals"] == 8 * 7 >= P.min_interval_residuals and daily.interval["half_width"] > 0
    weekly = ev.evaluate(np.random.default_rng(3).poisson(30 + 1.2 * np.arange(24)).astype(float), START, "week", P)
    assert weekly.interval is None                                    # 2 folds x 4 weeks = 8 errors: too few to claim a range
    if weekly.passed:
        assert any("No forecast range" in r for r in weekly.reasons)


def test_metrics_are_strictly_json_serialisable():
    for e in (ev.evaluate(trending(150, 1), START, "day", P), ev.evaluate(noise(120, 1), START, "day", P)):
        json.dumps(e.metrics, allow_nan=False)


# ---- champion vs challenger ---------------------------------------------------------------------------------------

def test_a_weak_champion_is_replaced():
    e = ev.evaluate(pattern(120, 1), START, "day", P, champion=fc.baseline_spec("naive"))
    assert e.passed and e.promote and e.champion_check["promote"] is True
    assert e.champion_check["champion_test_mae"] > e.champion_check["challenger_test_mae"]


def test_an_unscorable_champion_is_ignored_with_a_note():
    broken = fc.ModelSpec("ridge", "ml", {"series_start": "2026-01-05"})        # parameters missing
    e = ev.evaluate(pattern(120, 1), START, "day", P, champion=broken)
    assert e.promote and e.champion_check["error"] and any("could not be scored" in r for r in e.reasons)


def test_retraining_the_same_recipe_on_newer_data_is_always_allowed():
    first = ev.evaluate(trending(150, 1), START, "day", P)
    again = ev.evaluate(trending(164, 1), START, "day", P, champion=first.selected)
    assert again.passed and again.promote
    check = again.champion_check
    assert check["same_recipe"] is True and check["champion_alpha"] == first.selected.params["alpha"]
    assert any("same recipe was refitted" in r for r in again.reasons)


def test_a_champion_recipe_that_still_qualifies_and_is_better_is_refitted_not_left_stale():
    # Frozen scenario: with no champion the weekday average is chosen (Ridge is vetoed), but the active
    # model's recipe, Ridge with strength 1, still qualifies and has the lower out-of-sample error on the
    # SAME test folds.  So that recipe is refitted on all the history and activated.
    plain = ev.evaluate(pattern(120, 1), START, "day", P)
    assert plain.selected.algorithm == "weekday_mean_4"
    e = ev.evaluate(pattern(120, 1), START, "day", P, champion=fc.ModelSpec("ridge", "ml", {"alpha": 1.0}))
    assert e.passed and e.promote and e.selected.algorithm == "ridge" and e.selected.params["alpha"] == 1.0
    check = e.champion_check
    assert check["same_recipe"] is True and check["champion_recipe_valid"] is True
    assert check["champion_test_mae"] < plain.metrics["selected"]["test"]["mae"]
    assert any("refitted on all of the history" in r for r in e.reasons)


def test_a_champion_that_no_longer_qualifies_does_not_block_a_recipe_that_does():
    # Frozen scenario: a week of new data arrives.  The active Ridge no longer clearly beats the best baseline
    # on validation, so it is not kept just because its test error happens to be lower.
    first = ev.evaluate(sy.counts("trend", 1, 128).astype(float), sy.D0, "day", P)
    assert first.selected.algorithm == "ridge"
    again = ev.evaluate(sy.counts("trend", 1, 135).astype(float), sy.D0, "day", P, champion=first.selected)
    assert again.passed and again.promote and again.selected.algorithm == "moving_average"
    assert again.champion_check["champion_recipe_valid"] is False and again.champion_check["same_recipe"] is False
    assert any("no longer meets the evaluation criteria" in r for r in again.reasons)


def test_the_champion_is_scored_out_of_sample_not_with_its_stored_parameters():
    # A champion carrying absurd stored parameters is still judged by its recipe (a ridge refitted per fold).
    first = ev.evaluate(trending(150, 1), START, "day", P)
    absurd = fc.ModelSpec("ridge", "ml", {**first.selected.params, "coef": [1e9] * len(first.selected.params["coef"])})
    e = ev.evaluate(trending(150, 1), START, "day", P, champion=absurd)
    assert e.promote and e.champion_check["same_recipe"] is True                  # recipe unchanged => refit allowed


def test_a_failing_challenger_never_touches_the_champion_decision():
    e = ev.evaluate(noise(120, 1), START, "day", P, champion=fc.baseline_spec("naive"))
    assert not e.passed and not e.promote and e.champion_check is None
