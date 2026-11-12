"""Service demand prediction (pure).

Demand = distinct eligible orders per Monday-Sunday week that contain the service/package/add-on
(order frequency, never revenue; quantities use mixed units and are shown as history only).
Each entity with enough history of its own is evaluated by the same engine as every other target.
An entity without enough history gets NO prediction, only the reason.  Services, packages and
add-ons are ranked separately: add-ons never appear in the primary ranking.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.analytics.ml import evaluation as ev
from app.analytics.ml import readiness as rd
from app.analytics.ml.data_preparation import ServiceEntity
from app.analytics.ml.policy import Policy
from app.analytics.ml.schemas import Granularity

PRIMARY_TYPES = ("service", "package")


def split_by_readiness(entities, policy: Policy):
    """([(entity, readiness)] that may be evaluated, [(entity, readiness)] that may not)."""
    ready, waiting = [], []
    for e in entities:
        r = rd.assess_service_entity(e, policy)
        (ready if r.ready else waiting).append((e, r))
    return ready, waiting


def evaluate_entities(entities, policy: Policy, champions: dict | None = None) -> dict:
    """{entity key: Evaluation} for entities that have enough history of their own."""
    champions = champions or {}
    ready, _ = split_by_readiness(entities, policy)
    return {e.key: ev.evaluate(e.orders_weekly.values, e.orders_weekly.start, Granularity.WEEK, policy,
                               champions.get(e.key)) for e, _r in ready}


@dataclass(frozen=True)
class DemandItem:
    key: str
    label: str
    item_type: str
    recent_weekly_mean: float            # mean orders per week over the last 4 complete weeks
    predicted_weekly: tuple              # forecast orders per week, next 4 weeks
    algorithm: str
    kind: str

    @property
    def predicted_total(self) -> float:
        return float(sum(self.predicted_weekly))

    @property
    def change_pct(self) -> float | None:
        """Predicted weekly average vs the recent weekly average (None when there was no recent demand)."""
        if self.recent_weekly_mean <= 0:
            return None
        return (self.predicted_total / len(self.predicted_weekly) - self.recent_weekly_mean) / self.recent_weekly_mean * 100


def rank(items) -> dict:
    """Separate rankings for services/packages (primary) and add-ons; highest predicted demand first."""
    def ordered(group):
        ranked = sorted(group, key=lambda i: (-i.predicted_total, i.label.lower()))
        return [{"rank": n, "key": i.key, "label": i.label, "item_type": i.item_type,
                 "recent_weekly_mean": round(i.recent_weekly_mean, 1),
                 "predicted_weekly": [round(v, 1) for v in i.predicted_weekly],
                 "predicted_total": round(i.predicted_total, 1),
                 "change_pct": None if i.change_pct is None else round(i.change_pct, 1),
                 "algorithm": i.algorithm, "kind": i.kind} for n, i in enumerate(ranked, start=1)]
    return {"primary": ordered([i for i in items if i.item_type in PRIMARY_TYPES]),
            "addons": ordered([i for i in items if i.item_type == "addon"])}
