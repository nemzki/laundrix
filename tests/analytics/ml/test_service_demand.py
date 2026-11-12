"""Service demand: per-entity evaluation and separate rankings.  Pure tests."""
from datetime import date

import numpy as np
import pytest

from app.analytics.ml import data_preparation as dp
from app.analytics.ml import service_demand as sd
from app.analytics.ml.policy import DEFAULT_POLICY as P
from app.analytics.ml.schemas import Series, Target, Unit

START = date(2026, 1, 5)


def entity(key, item_type, weeks, per_week, label=None, growth=0.0, seed=1):
    vals = np.random.default_rng(seed).poisson(per_week + growth * np.arange(weeks)).astype(float)
    s = Series(Target.SERVICE_DEMAND, "week", Unit.ORDERS, START, tuple(vals), int(vals.sum()), key, label or key)
    return dp.ServiceEntity(key, item_type, label or key, "load", s, None, int(vals.sum()), START)


def test_only_services_with_enough_history_of_their_own_are_evaluated():
    ents = [entity("service:1", "service", 40, 30, "Wash", growth=1.0),
            entity("service:2", "service", 10, 30, "Dry"),               # too few weeks
            entity("package:3", "package", 40, 0.2, "Rare pkg", seed=4)]  # too few orders
    ready, waiting = sd.split_by_readiness(ents, P)
    assert [e.label for e, _ in ready] == ["Wash"]
    assert {e.label for e, _ in waiting} == {"Dry", "Rare pkg"}
    assert any("complete weeks" in r.message for _, r in waiting)
    results = sd.evaluate_entities(ents, P)
    assert set(results) == {"service:1"} and results["service:1"].passed


def test_new_services_get_no_prediction_only_a_reason():
    fresh = entity("service:9", "service", 3, 50, "Brand new")
    assert sd.evaluate_entities([fresh], P) == {}
    _, waiting = sd.split_by_readiness([fresh], P)
    assert "3 of 24 complete weeks" in waiting[0][1].message


def item(key, label, kind, weekly, recent, item_type="service"):
    return sd.DemandItem(key, label, item_type, recent, tuple(weekly), "ridge", "ml")


def test_ranking_by_predicted_demand_with_addons_kept_separate():
    items = [item("a", "Wash", "service", [10, 10, 10, 10], 8.0), item("b", "Fold", "service", [20, 20, 20, 20], 25.0),
             item("c", "Pkg", "package", [15, 15, 15, 15], 15.0, "package"), item("d", "Fabcon", "addon", [99] * 4, 90.0, "addon"),
             item("e", "Dry", "service", [10, 10, 10, 10], 10.0)]
    r = sd.rank(items)
    assert [x["label"] for x in r["primary"]] == ["Fold", "Pkg", "Dry", "Wash"]       # ties broken by name
    assert [x["rank"] for x in r["primary"]] == [1, 2, 3, 4]
    assert [x["label"] for x in r["addons"]] == ["Fabcon"]                           # never in the primary ranking
    assert r["primary"][0]["predicted_total"] == 80.0 and r["primary"][0]["change_pct"] == -20.0   # 20/wk vs 25/wk
    assert r["primary"][3]["change_pct"] == 25.0                                                      # 10/wk vs 8/wk


def test_change_is_undefined_without_recent_demand():
    assert item("a", "Wash", "service", [4, 4, 4, 4], 0.0).change_pct is None
    assert sd.rank([item("a", "Wash", "service", [4, 4, 4, 4], 0.0)])["primary"][0]["change_pct"] is None
