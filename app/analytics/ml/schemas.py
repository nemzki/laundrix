"""Shared constants and small immutable data structures."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta


class Target:
    ORDERS = "orders"                        # eligible orders accepted per day / week
    GROSS_VALUE = "gross_order_value"        # sum of Order.total of those orders (billed, not collected)
    COLLECTIONS = "net_collections"          # ledger: payments minus reversals, by paid_at
    SERVICE_DEMAND = "service_demand"        # distinct orders containing a service / package per week

    ALL = (ORDERS, GROSS_VALUE, COLLECTIONS, SERVICE_DEMAND)
    LABELS = {
        ORDERS: "Order demand",
        GROSS_VALUE: "Gross order value",
        COLLECTIONS: "Net payment collections",
        SERVICE_DEMAND: "Service demand",
    }


class Granularity:
    DAY = "day"
    WEEK = "week"


class Unit:
    ORDERS = "orders"
    PESO = "PHP"


class ReadinessStatus:
    """Decided from the DATA alone."""
    INSUFFICIENT = "insufficient_data"
    READY = "ready_for_training"


class ModelStatus:
    """Overall status shown to the administrator.  The first two come from readiness; the rest
    from the model registry (added with the model lifecycle)."""
    NOT_TRAINED = "not_trained"
    INSUFFICIENT_DATA = "insufficient_data"
    READY_FOR_TRAINING = "ready_for_training"
    TRAINING = "training"
    TRAINED = "trained"
    EVALUATION_FAILED = "evaluation_failed"
    OUTDATED = "model_outdated"

    LABELS = {
        NOT_TRAINED: "NOT TRAINED",
        INSUFFICIENT_DATA: "INSUFFICIENT DATA",
        READY_FOR_TRAINING: "READY FOR TRAINING",
        TRAINING: "TRAINING",
        TRAINED: "TRAINED",
        EVALUATION_FAILED: "EVALUATION FAILED",
        OUTDATED: "MODEL OUTDATED",
    }


class Severity:
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Issue:
    """A data-quality observation.  ``count`` is a number of records/days, never personal data."""
    code: str
    severity: str
    message: str
    count: int = 0

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "message": self.message, "count": self.count}


@dataclass(frozen=True)
class Series:
    """A complete, gap-free time series (zero-filled, whole days or whole Monday-Sunday weeks)."""
    target: str
    granularity: str
    unit: str
    start: date
    values: tuple
    events: int = 0                    # underlying orders / ledger entries inside the window
    entity: str | None = None          # service/package key for service-demand series
    label: str | None = None

    @property
    def n(self) -> int:
        return len(self.values)

    @property
    def step(self) -> timedelta:
        return timedelta(days=1 if self.granularity == Granularity.DAY else 7)

    @property
    def end(self) -> date | None:
        return None if not self.values else self.start + self.step * (self.n - 1)

    def dates(self) -> list[date]:
        return [self.start + self.step * i for i in range(self.n)]

    def total(self) -> float:
        return float(sum(self.values))


EMPTY_NOTE = "No eligible history yet."
