"""Chronological evaluation, model selection and the promotion decision (pure).

Method (rolling-origin backtest, no shuffling, no future information)
    The LAST ``folds x horizon`` observations are held back.  Fold k has an origin o_k; every model is
    fitted ONLY on values[:o_k] and asked to forecast the next ``horizon`` values, which are then
    compared with what really happened.  More history means more folds (up to a maximum).

    The folds are split in time order into VALIDATION folds (earlier) and TEST folds (later):
      * validation folds choose the best baseline and the best Ridge strength;
      * test folds are never used to pick a winner.  They only (a) can VETO the ML model, falling
        back to the baseline, and (b) provide the figures reported and used for promotion.

Promotion criteria (all must hold; thresholds live in policy.py)
    1. error metrics are defined (the test window contained actual activity);
    2. SKILL: test MAE beats the "historical mean" reference by at least ``min_skill``, the candidate
       also beats it on the validation folds, and in a majority of the test folds.  (Simulation showed a
       single-margin rule promoted pure random noise far too often; see tests/analytics/ml.)
    3. a Ridge model is used only if it beats the best baseline by ``ml_min_improvement`` on validation
       AND test, and wins a majority of test folds; otherwise the baseline is the candidate and is
       labelled as a statistical baseline, never as machine learning;
    4. the active model's RECIPE (algorithm and Ridge strength) competes on the same test folds, scored
       out-of-sample exactly like every candidate (its stored parameters are never used: they were fitted
       on data overlapping the test window and would be unfairly favoured).  If that recipe still meets
       criteria 1-3 and is better on the test window, IT is refitted on all the history and activated
       (retraining); if it no longer meets them, it does not block a candidate that does.  So the active
       model is always the best recipe that currently qualifies, never an inferior one.

Metrics: MAE (same unit as the target) and WAPE = sum|error| / sum|actual| (undefined, reported as
None, when actual values sum to zero).  Accuracy percentages are never reported.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from app.analytics.ml import forecasting as fc
from app.analytics.ml.policy import Policy, WindowRule

EPS = 1e-9


# ----------------------------------------------------------------------------- metrics

def mae(actual, pred) -> float:
    return float(np.mean(np.abs(np.asarray(actual, float) - np.asarray(pred, float))))


def wape(actual, pred) -> float | None:
    a, p = np.asarray(actual, float), np.asarray(pred, float)
    denom = float(np.sum(np.abs(a)))
    return None if denom == 0 else float(np.sum(np.abs(a - p)) / denom)


def mean_error(actual, pred) -> float:
    """Average signed error (forecast minus actual): positive means the model over-forecasts."""
    return float(np.mean(np.asarray(pred, float) - np.asarray(actual, float)))


def _r(x, nd=4):
    return None if x is None else round(float(x), nd)


# ----------------------------------------------------------------------------- folds

def n_folds_for(n: int, rule: WindowRule) -> int:
    spare = n - rule.warmup - rule.min_train
    return max(0, min(rule.max_backtest_folds, spare // rule.horizon))


def make_origins(n: int, rule: WindowRule) -> list[int]:
    """Forecast origins, oldest first; the last fold ends exactly at the end of the series."""
    folds = n_folds_for(n, rule)
    return [n - (folds - k) * rule.horizon for k in range(folds)]


def split_folds(folds: int) -> tuple[list[int], list[int]]:
    """(validation indices, test indices): later folds are the test folds."""
    n_test = max(1, folds // 2)
    return list(range(folds - n_test)), list(range(folds - n_test, folds))


# ----------------------------------------------------------------------------- candidates

@dataclass(frozen=True)
class Candidate:
    algorithm: str
    alpha: float | None = None

    @property
    def key(self) -> str:
        return self.algorithm if self.alpha is None else f"{self.algorithm}@{self.alpha:g}"


def candidates_for(granularity: str, policy: Policy) -> list[Candidate]:
    out = [Candidate(name) for name in fc.BASELINES[granularity]]
    out += [Candidate("ridge", a) for a in policy.ridge_alphas]
    return out


def fit_candidate(cand: Candidate, history, start: date, granularity: str) -> fc.ModelSpec:
    if cand.algorithm == "ridge":
        return fc.fit_ridge(history, start, granularity, cand.alpha)
    return fc.baseline_spec(cand.algorithm)


# ----------------------------------------------------------------------------- result

@dataclass(frozen=True)
class Evaluation:
    passed: bool                         # criteria 1-3 met (a model may be saved)
    promote: bool                        # passed AND not worse than the current active model
    reasons: tuple                       # human-readable explanations (why it failed / notes)
    selected: fc.ModelSpec | None        # final model, fitted on ALL data (None when it failed)
    baseline: fc.ModelSpec | None        # best statistical baseline (shown beside ML forecasts)
    metrics: dict                        # JSON-serialisable evaluation record
    interval: dict | None                # {"level", "half_width", "n_residuals"} or None
    champion_check: dict | None = None


def _failed(reasons, metrics, baseline=None) -> Evaluation:
    return Evaluation(False, False, tuple(reasons), None, baseline, metrics, None, None)


# ----------------------------------------------------------------------------- main entry point

def evaluate(values, start: date, granularity: str, policy: Policy,
             champion: fc.ModelSpec | None = None) -> Evaluation:
    values = [float(v) for v in values]
    n = len(values)
    rule = policy.rule(granularity)
    horizon = rule.horizon
    step = fc.step_of(granularity)
    metrics: dict = {"n_observations": n, "criteria": {"min_skill": policy.min_skill,
                                                      "ml_min_improvement": policy.ml_min_improvement}}

    origins = make_origins(n, rule)
    folds = len(origins)
    if folds < rule.backtest_folds:
        return _failed([f"Not enough history for {rule.backtest_folds} backtest folds ({n} observations)."], metrics)
    val_idx, test_idx = split_folds(folds)
    actual = [values[o:o + horizon] for o in origins]
    metrics["folds"] = {
        "count": folds, "horizon": horizon, "validation": len(val_idx), "test": len(test_idx),
        "test_window": [(start + step * origins[test_idx[0]]).isoformat(), (start + step * (n - 1)).isoformat()],
    }

    # ---- forecasts of every candidate for every fold (each fitted on past data only) ----
    cands = candidates_for(granularity, policy)
    preds: dict[str, list] = {}
    unavailable: dict[str, str] = {}
    for cand in cands:
        try:
            preds[cand.key] = [fc.predict(fit_candidate(cand, values[:o], start, granularity),
                                          values[:o], start, granularity, horizon) for o in origins]
        except (ValueError, np.linalg.LinAlgError) as exc:
            unavailable[cand.key] = str(exc)
    ref = [fc.reference_forecast(values[:o], horizon) for o in origins]

    def pooled(per_fold, idx):
        return (np.concatenate([actual[i] for i in idx]), np.concatenate([per_fold[i] for i in idx]))

    def scores(per_fold, idx):
        a, p = pooled(per_fold, idx)
        return {"mae": mae(a, p), "wape": wape(a, p), "bias": mean_error(a, p)}

    def fold_mae(per_fold, i):
        return mae(actual[i], per_fold[i])

    table = {c.key: {"label": fc.LABELS.get(c.algorithm, c.algorithm),
                     "validation": scores(preds[c.key], val_idx), "test": scores(preds[c.key], test_idx)}
             for c in cands if c.key in preds}
    ref_scores = {"validation": scores(ref, val_idx), "test": scores(ref, test_idx)}
    metrics["candidates"] = {k: {"label": v["label"],
                                 "validation": {m: _r(x) for m, x in v["validation"].items()},
                                 "test": {m: _r(x) for m, x in v["test"].items()}} for k, v in table.items()}
    metrics["reference"] = {s: {m: _r(x) for m, x in ref_scores[s].items()} for s in ("validation", "test")}
    if unavailable:
        metrics["unavailable"] = unavailable

    def ensure_scored(cand: Candidate) -> bool:
        """Make sure ``cand`` has fold forecasts and scores (a champion's recipe may be outside the grid)."""
        if cand.key in preds:
            return True
        try:
            preds[cand.key] = [fc.predict(fit_candidate(cand, values[:o], start, granularity), values[:o], start, granularity, horizon)
                               for o in origins]
        except (ValueError, KeyError, TypeError, np.linalg.LinAlgError):
            return False
        table[cand.key] = {"label": fc.LABELS.get(cand.algorithm, cand.algorithm),
                           "validation": scores(preds[cand.key], val_idx), "test": scores(preds[cand.key], test_idx)}
        return True

    # ---- selection on VALIDATION folds only ----
    baselines = [c for c in cands if c.algorithm != "ridge" and c.key in preds]
    if not baselines:
        return _failed(["No baseline could be evaluated on this history."], metrics)
    best_b = min(baselines, key=lambda c: table[c.key]["validation"]["mae"])
    ridges = [c for c in cands if c.algorithm == "ridge" and c.key in preds]
    best_r = min(ridges, key=lambda c: table[c.key]["validation"]["mae"]) if ridges else None
    baseline_spec = fc.baseline_spec(best_b.algorithm)
    margin = 1.0 - policy.ml_min_improvement

    def ml_gate(ridge_cand: Candidate):
        """Ridge is allowed only if it clearly beats the best baseline on validation AND test and in most test folds.
        The test folds can therefore only VETO the ML model; they never pick among candidates."""
        on_val = table[ridge_cand.key]["validation"]["mae"] <= margin * table[best_b.key]["validation"]["mae"] + EPS
        on_test = table[ridge_cand.key]["test"]["mae"] <= margin * table[best_b.key]["test"]["mae"] + EPS
        wins = sum(1 for i in test_idx if fold_mae(preds[ridge_cand.key], i) < fold_mae(preds[best_b.key], i))
        return (on_val and on_test and wins > len(test_idx) / 2), f"{wins} of {len(test_idx)}"

    def judge(cand: Candidate):
        """Criteria 1-2 for one recipe: (problems, test skill, validation skill, test folds beating the reference)."""
        v, t = table[cand.key]["validation"], table[cand.key]["test"]
        skill = None if ref_scores["test"]["mae"] <= EPS else 1.0 - t["mae"] / ref_scores["test"]["mae"]
        val_skill = None if ref_scores["validation"]["mae"] <= EPS else 1.0 - v["mae"] / ref_scores["validation"]["mae"]
        wins = sum(1 for i in test_idx if fold_mae(preds[cand.key], i) < fold_mae(ref, i))
        problems: list[str] = []
        if t["wape"] is None:
            problems.append("The test window contained no activity, so the error percentage (WAPE) is undefined.")
        if skill is None:
            problems.append("Skill cannot be judged: the historical-average reference had no error on the test window.")
        elif skill < policy.min_skill - EPS:
            problems.append(f"The best model beats the historical average by only {max(skill, 0):.1%} on the test window "
                            f"(at least {policy.min_skill:.0%} is required), so it has no demonstrated skill.")
        if skill is not None:
            if val_skill is None or val_skill <= 0:
                problems.append("The best model shows no skill over the historical average on the validation window.")
            if wins <= len(test_idx) / 2:
                problems.append(f"The best model beat the historical average in only {wins} of {len(test_idx)} test folds.")
        return problems, skill, val_skill, wins

    notes: list[str] = []
    candidate, ml_wins = best_b, None
    if best_r is not None:
        ok, ml_wins = ml_gate(best_r)
        if ok:
            candidate = best_r
        else:
            notes.append(f"Ridge did not beat the best baseline ({fc.LABELS[best_b.algorithm]}) by at least "
                         f"{policy.ml_min_improvement:.0%} on validation and test and in most test folds, "
                         "so the statistical baseline is used and labelled as such.")

    # ---- the active model's recipe competes on the SAME folds (never its stored parameters) ----
    champ, champ_error, champ_valid = None, None, False
    if champion is not None:
        champ = Candidate(champion.algorithm, champion.params.get("alpha") if champion.algorithm == "ridge" else None)
        valid_recipe = ((champ.algorithm == "ridge" and champ.alpha is not None and champ.alpha > 0)
                        or champ.algorithm in fc.BASELINES[granularity])
        if not valid_recipe or not ensure_scored(champ):
            champ, champ_error = None, "current model could not be scored"
        else:
            champ_valid = (champ.algorithm != "ridge" or ml_gate(champ)[0]) and not judge(champ)[0]
            if (champ_valid and champ.key != candidate.key
                    and table[champ.key]["test"]["mae"] + EPS < table[candidate.key]["test"]["mae"]):
                candidate = champ
                notes.append("The current model's recipe still qualifies and is the best on the newest data, "
                             "so it was refitted on all of the history.")

    problems, skill, val_skill, ref_wins = judge(candidate)
    c_val, c_test = table[candidate.key]["validation"], table[candidate.key]["test"]
    metrics["selected"] = {
        "algorithm": candidate.algorithm, "alpha": candidate.alpha,
        "kind": fc.Kind.ML if candidate.algorithm == "ridge" else fc.Kind.BASELINE,
        "validation": {m_: _r(x) for m_, x in c_val.items()}, "test": {m_: _r(x) for m_, x in c_test.items()},
        "skill_vs_reference": _r(skill), "skill_vs_reference_validation": _r(val_skill),
        "reference_test_fold_wins": f"{ref_wins} of {len(test_idx)}", "ridge_test_fold_wins": ml_wins,
    }
    metrics["candidates"] = {k: {"label": v["label"], "validation": {m: _r(x) for m, x in v["validation"].items()},
                                 "test": {m: _r(x) for m, x in v["test"].items()}} for k, v in table.items()}
    if problems:
        return _failed(problems + notes, metrics, baseline_spec)

    # ---- forecast range from the candidate's backtest errors (only when there are enough of them) ----
    errors = np.concatenate([np.abs(np.asarray(actual[i]) - np.asarray(preds[candidate.key][i])) for i in range(folds)])
    interval = None
    if len(errors) >= policy.min_interval_residuals:
        interval = {"level": policy.interval_level, "half_width": float(np.quantile(errors, policy.interval_level)),
                    "n_residuals": int(len(errors))}
    else:
        notes.append(f"No forecast range is shown: only {len(errors)} backtest errors exist "
                     f"({policy.min_interval_residuals} are needed to estimate one).")
    metrics["interval"] = None if interval is None else {k: _r(v) for k, v in interval.items()}

    # ---- final model: refit on ALL history ----
    try:
        selected = fit_candidate(candidate, values, start, granularity)
    except (ValueError, np.linalg.LinAlgError) as exc:
        return _failed([f"The final model could not be fitted: {exc}"] + notes, metrics, baseline_spec)

    # ---- the active model: the best qualifying recipe wins, so a passing evaluation always replaces it ----
    check, promote = None, True
    if champion is not None:
        if champ is None:
            check = {"champion_algorithm": champion.algorithm, "error": champ_error, "promote": True}
            notes.append("The current model could not be scored and is replaced.")
        else:
            same = champ.key == candidate.key
            check = {"champion_algorithm": champion.algorithm, "champion_alpha": champ.alpha, "same_recipe": same,
                     "champion_recipe_valid": bool(champ_valid), "champion_test_mae": _r(table[champ.key]["test"]["mae"]),
                     "challenger_test_mae": _r(c_test["mae"]), "promote": True}
            if same and not any("refitted" in n for n in notes):
                notes.append("The same recipe was refitted on newer data and replaces the current model.")
            elif not same and not champ_valid:
                notes.append("The current model's recipe no longer meets the evaluation criteria, so a recipe that does replaces it.")
    metrics["champion_check"] = check
    return Evaluation(True, promote, tuple(notes), selected, baseline_spec, metrics, interval, check)
