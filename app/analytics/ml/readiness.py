"""Data-readiness assessment (pure: works on prepared series, never touches the database).

Decides, per forecasting target, whether the history can support honest model training and says in
plain language what is missing.  "READY FOR TRAINING" only means the data is sufficient to *attempt*
training; it says nothing about whether any model will pass evaluation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from app.analytics.ml import data_validation as dv
from app.analytics.ml.data_preparation import PreparedData, ServiceEntity
from app.analytics.ml.policy import DEFAULT_POLICY, INSUFFICIENT_DATA_MESSAGE, Policy
from app.analytics.ml.schemas import (
    Granularity, Issue, ModelStatus, ReadinessStatus, Series, Severity, Target,
)

_EVENT_WORD = {Target.ORDERS: "orders", Target.GROSS_VALUE: "orders",
               Target.COLLECTIONS: "payment entries", Target.SERVICE_DEMAND: "orders"}
_COUNT_TARGETS = (Target.ORDERS, Target.SERVICE_DEMAND)


def poisson_noise_floor_wape(mean_per_step: float) -> float | None:
    """Lowest WAPE any model could reach on Poisson-like counts: MAD ~ 0.7979 * sd, sd = sqrt(mean).

    A perfect model of the underlying rate still misses by chance.  Shown so low-volume, daily
    forecasts are not mistaken for model failures.  ``None`` when the mean is zero.
    """
    return None if mean_per_step <= 0 else 0.7979 / math.sqrt(mean_per_step)


@dataclass(frozen=True)
class TargetReadiness:
    target: str
    granularity: str
    label: str
    unit: str
    status: str
    observations: int
    required: int
    shortfall: int
    events: int
    required_events: int
    event_shortfall: int
    first_date: date | None
    last_date: date | None
    zero_steps: int
    completeness_pct: float | None
    longest_zero_run: int
    excluded_history: int
    noise_floor_wape: float | None
    message: str
    issues: tuple = ()
    entity: str | None = None
    item_type: str | None = None

    @property
    def ready(self) -> bool:
        return self.status == ReadinessStatus.READY

    def as_dict(self) -> dict:
        return {
            "target": self.target, "granularity": self.granularity, "label": self.label, "unit": self.unit,
            "status": self.status, "ready": self.ready,
            "observations": self.observations, "required": self.required, "shortfall": self.shortfall,
            "events": self.events, "required_events": self.required_events, "event_shortfall": self.event_shortfall,
            "first_date": self.first_date.isoformat() if self.first_date else None,
            "last_date": self.last_date.isoformat() if self.last_date else None,
            "zero_steps": self.zero_steps, "completeness_pct": self.completeness_pct,
            "longest_zero_run": self.longest_zero_run, "excluded_history": self.excluded_history,
            "noise_floor_wape": None if self.noise_floor_wape is None else round(self.noise_floor_wape, 3),
            "message": self.message, "issues": [i.as_dict() for i in self.issues],
            "entity": self.entity, "item_type": self.item_type,
        }


def assess_series(series: Series, policy: Policy = DEFAULT_POLICY, *, required_events: int | None = None,
                  label: str | None = None, excluded_history: int = 0, issues=()) -> TargetReadiness:
    rule = policy.rule(series.granularity)
    required = rule.required_observations
    need_events = rule.min_events if required_events is None else required_events
    n, events = series.n, series.events
    values = list(series.values)

    shortfall = max(required - n, 0)
    event_shortfall = max(need_events - events, 0)
    ready = shortfall == 0 and event_shortfall == 0
    word = rule.unit_word
    name = label or Target.LABELS[series.target]
    step_word = "daily" if series.granularity == Granularity.DAY else "weekly"
    event_word = _EVENT_WORD[series.target]

    if n == 0:
        message = f"{name} ({step_word}): no eligible history yet. {required} complete {word} are needed."
    elif not ready:
        parts = []
        if shortfall:
            parts.append(f"{n} of {required} complete {word} available ({shortfall} more needed)")
        if event_shortfall:
            parts.append(f"{events} of {need_events} {event_word} recorded ({event_shortfall} more needed)")
        message = f"{name} ({step_word}): " + "; ".join(parts) + "."
    else:
        message = f"{name} ({step_word}): {n} complete {word} available (minimum {required}); enough history to attempt training."

    zeros = sum(1 for v in values if v == 0)
    mean = (sum(values) / n) if n else 0.0
    floor = poisson_noise_floor_wape(mean) if series.target in _COUNT_TARGETS and n else None
    return TargetReadiness(
        target=series.target, granularity=series.granularity, label=name, unit=series.unit,
        status=ReadinessStatus.READY if ready else ReadinessStatus.INSUFFICIENT, observations=n, required=required,
        shortfall=shortfall, events=events, required_events=need_events, event_shortfall=event_shortfall,
        first_date=series.start if n else None, last_date=series.end, zero_steps=zeros,
        completeness_pct=round(100 * (n - zeros) / n, 1) if n else None,
        longest_zero_run=dv.longest_zero_run(values), excluded_history=excluded_history,
        noise_floor_wape=floor, message=message, issues=tuple(issues), entity=series.entity,
        item_type=None,
    )


@dataclass(frozen=True)
class ServiceReadiness:
    status: str
    message: str
    total_entities: int
    ready_entities: int
    entities: tuple = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {"status": self.status, "message": self.message, "total_entities": self.total_entities,
                "ready_entities": self.ready_entities, "entities": [e.as_dict() for e in self.entities]}


def assess_service_entity(entity: ServiceEntity, policy: Policy) -> TargetReadiness:
    base = assess_series(entity.orders_weekly, policy, required_events=policy.service_min_orders,
                         label=entity.label, issues=entity.issues)
    return TargetReadiness(**{**base.__dict__, "item_type": entity.item_type})


def assess_services(entities, policy: Policy = DEFAULT_POLICY) -> ServiceReadiness:
    """Per-service readiness.  Add-ons are assessed but never counted toward the primary ranking."""
    assessed = tuple(assess_service_entity(e, policy) for e in entities)
    primary = [a for a in assessed if a.item_type in ("service", "package")]
    ready = [a for a in primary if a.ready]
    rule = policy.weekly
    if not primary:
        status, msg = ReadinessStatus.INSUFFICIENT, "Service demand: no eligible service or package orders yet."
    elif ready:
        status = ReadinessStatus.READY
        msg = f"Service demand: {len(ready)} of {len(primary)} services/packages have enough history."
    else:
        status = ReadinessStatus.INSUFFICIENT
        msg = (f"Service demand: none of {len(primary)} services/packages has the {rule.required_observations} complete weeks "
               f"and {policy.service_min_orders} orders of its own history needed for an individual prediction.")
    return ServiceReadiness(status, msg, len(primary), len(ready), assessed)


@dataclass(frozen=True)
class ReadinessOverview:
    generated_at: str
    as_of: date
    status: str
    model_status: str
    message: str
    targets: tuple
    services: ServiceReadiness
    quality: dict
    issues: tuple
    ledger_start: date | None
    policy: dict

    def as_dict(self) -> dict:
        return {
            "generated_at": self.generated_at, "as_of": self.as_of.isoformat(),
            "status": self.status, "model_status": self.model_status,
            "model_status_label": ModelStatus.LABELS[self.model_status], "message": self.message,
            "targets": [t.as_dict() for t in self.targets], "services": self.services.as_dict(),
            "quality": self.quality, "issues": [i.as_dict() for i in self.issues],
            "ledger_start": self.ledger_start.isoformat() if self.ledger_start else None,
            "policy": self.policy,
        }


def policy_summary(policy: Policy) -> dict:
    def rule(r):
        return {"horizon": r.horizon, "warmup": r.warmup, "min_train": r.min_train, "backtest_folds": r.backtest_folds,
                "min_events": r.min_events, "required_observations": r.required_observations, "unit": r.unit_word}
    return {"daily": rule(policy.daily), "weekly": rule(policy.weekly),
            "max_inactive_gap_days": policy.max_inactive_gap_days, "service_min_orders": policy.service_min_orders}


def assess(prepared: PreparedData, policy: Policy = DEFAULT_POLICY, generated_at: datetime | None = None) -> ReadinessOverview:
    """Readiness for every target.  Deterministic for given prepared data."""
    ledger_note = ()
    if prepared.ledger_start:
        ledger_note = (Issue("collections_start", Severity.INFO,
                             f"Payment collections are counted from {prepared.ledger_start:%b %d, %Y}, when payment "
                             "tracking began. Earlier days are not zero collections; they were simply not recorded.", 0),)
    gap = prepared.excluded_history
    targets = (
        assess_series(prepared.orders_daily, policy, excluded_history=gap.get(Target.ORDERS, 0)),
        assess_series(prepared.orders_weekly, policy, excluded_history=gap.get(Target.ORDERS, 0)),
        assess_series(prepared.gross_daily, policy, excluded_history=gap.get(Target.GROSS_VALUE, 0)),
        assess_series(prepared.gross_weekly, policy, excluded_history=gap.get(Target.GROSS_VALUE, 0)),
        assess_series(prepared.collections_daily, policy, excluded_history=gap.get(Target.COLLECTIONS, 0), issues=ledger_note),
        assess_series(prepared.collections_weekly, policy, excluded_history=gap.get(Target.COLLECTIONS, 0), issues=ledger_note),
    )
    services = assess_services(prepared.services, policy)
    any_ready = any(t.ready for t in targets) or services.status == ReadinessStatus.READY
    status = ReadinessStatus.READY if any_ready else ReadinessStatus.INSUFFICIENT
    message = ("At least one forecasting target has enough history to attempt training. "
               "Training does not guarantee a usable model: it must still pass evaluation."
               if any_ready else INSUFFICIENT_DATA_MESSAGE)
    stamp = (generated_at or datetime.now(timezone.utc)).replace(microsecond=0)
    return ReadinessOverview(
        generated_at=stamp.isoformat(), as_of=prepared.as_of, status=status,
        model_status=ModelStatus.READY_FOR_TRAINING if any_ready else ModelStatus.INSUFFICIENT_DATA,
        message=message, targets=targets, services=services, quality=prepared.quality, issues=prepared.issues,
        ledger_start=prepared.ledger_start, policy=policy_summary(policy),
    )


def assess_now(policy: Policy = DEFAULT_POLICY) -> ReadinessOverview:
    """Read the database (read-only aggregates) and assess readiness."""
    from app.analytics.ml.data_preparation import prepare_all
    return assess(prepare_all(policy=policy), policy)
