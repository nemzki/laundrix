"""Turns aggregated database rows into complete, honest time series (pure: no database here).

The database layer (``data_source``) returns already-aggregated numbers.  This module decides
which days/weeks are complete and usable.  Rules, all covered by tests:

* The current (incomplete) local day is never used; neither is the current (incomplete) week.
* Days with no activity are zero-filled; they are real observations.
* The shop's timezone is Asia/Manila; weeks run Monday to Sunday.
* After a run of ``max_inactive_gap_days`` zero days, only the history AFTER the last such gap is
  used (that stretch is a closure / system-not-in-use gap, not demand).
* Order and gross-value series start at the first eligible order.  The collections series starts at
  the payment-tracking go-live date: earlier zeros mean "not recorded", not "no money received".
* Nothing is ever invented: with no history the series are empty.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.analytics.ml import data_validation as dv
from app.analytics.ml.policy import DEFAULT_POLICY, Policy
from app.analytics.ml.schemas import Granularity, Issue, Series, Target, Unit
from app.core.timeutil import to_local


# ----------------------------------------------------------------------------- raw input

@dataclass
class RawData:
    """Aggregated rows exactly as the database returns them (numbers only, no personal data)."""
    orders_by_day: dict = field(default_factory=dict)       # date -> (orders, gross_value)
    collections_by_day: dict = field(default_factory=dict)  # date -> (payments, reversals, n_payments, n_reversals)
    ledger_start: date | None = None                        # first day payments were being tracked
    service_rows: list = field(default_factory=list)        # one dict per (day, item, unit)
    quality: dict = field(default_factory=dict)             # record counts for data-quality issues


@dataclass(frozen=True)
class ServiceEntity:
    key: str
    item_type: str
    label: str
    unit: str
    orders_weekly: Series
    quantity_weekly: Series | None
    total_orders: int
    first_date: date
    issues: tuple = ()


@dataclass(frozen=True)
class PreparedData:
    as_of: date                               # the shop-local "today"; excluded because incomplete
    orders_daily: Series
    orders_weekly: Series
    gross_daily: Series
    gross_weekly: Series
    collections_daily: Series
    collections_weekly: Series
    services: tuple
    excluded_history: dict                    # target -> days of history before the last gap
    issues: tuple
    quality: dict
    ledger_start: date | None

    def series(self, target: str, granularity: str) -> Series:
        return {
            (Target.ORDERS, Granularity.DAY): self.orders_daily,
            (Target.ORDERS, Granularity.WEEK): self.orders_weekly,
            (Target.GROSS_VALUE, Granularity.DAY): self.gross_daily,
            (Target.GROSS_VALUE, Granularity.WEEK): self.gross_weekly,
            (Target.COLLECTIONS, Granularity.DAY): self.collections_daily,
            (Target.COLLECTIONS, Granularity.WEEK): self.collections_weekly,
        }[(target, granularity)]


# ----------------------------------------------------------------------------- helpers

def local_today(now_utc: datetime) -> date:
    """The shop-local calendar date for a naive-UTC timestamp."""
    return to_local(now_utc).date()


def _monday_on_or_after(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7)


def _last_complete_sunday(last_full_day: date) -> date | None:
    """The latest Sunday that is <= ``last_full_day`` (a week is complete once its Sunday has passed)."""
    return last_full_day - timedelta(days=(last_full_day.weekday() + 1) % 7)


@dataclass(frozen=True)
class DailyBlock:
    start: date
    values: tuple
    events: tuple

    @property
    def n(self) -> int:
        return len(self.values)


def _empty_daily(target: str, unit: str, as_of: date) -> Series:
    return Series(target, Granularity.DAY, unit, as_of, (), 0)


def _empty_weekly(target: str, unit: str, as_of: date, entity=None, label=None) -> Series:
    return Series(target, Granularity.WEEK, unit, as_of, (), 0, entity, label)


def build_daily_block(values_by_day: dict, events_by_day: dict, first_day: date | None,
                      as_of: date, policy: Policy):
    """Zero-filled daily arrays from ``first_day`` to yesterday, restarted after the last long gap.

    Returns (DailyBlock | None, days_excluded_before_gap, ended_in_gap).
    """
    if first_day is None:
        return None, 0, False
    last_day = as_of - timedelta(days=1)             # today is incomplete and never used
    if first_day > last_day:
        return None, 0, False
    n = (last_day - first_day).days + 1
    days = [first_day + timedelta(days=i) for i in range(n)]
    values = [float(values_by_day.get(d, 0.0)) for d in days]
    events = [int(events_by_day.get(d, 0)) for d in days]

    cut = dv.active_window_start(values, policy.max_inactive_gap_days)
    if cut >= n:                                      # history ends inside a gap: nothing recent to learn from
        return None, n, True
    return DailyBlock(days[cut], tuple(values[cut:]), tuple(events[cut:])), cut, False


def daily_series(block: DailyBlock | None, target: str, unit: str, as_of: date) -> Series:
    if block is None:
        return _empty_daily(target, unit, as_of)
    return Series(target, Granularity.DAY, unit, block.start, block.values, sum(block.events))


def weekly_series(block: DailyBlock | None, target: str, unit: str, as_of: date,
                  entity=None, label=None) -> Series:
    """Roll daily data up to COMPLETE Monday-Sunday weeks (partial first/last weeks are dropped)."""
    if block is None:
        return _empty_weekly(target, unit, as_of, entity, label)
    first_monday = _monday_on_or_after(block.start)
    last_day = block.start + timedelta(days=block.n - 1)
    last_sunday = _last_complete_sunday(last_day)
    if last_sunday is None or last_sunday < first_monday + timedelta(days=6):
        return _empty_weekly(target, unit, as_of, entity, label)
    n_weeks = ((last_sunday - first_monday).days + 1) // 7
    offset = (first_monday - block.start).days
    values, events = [], 0
    for w in range(n_weeks):
        lo = offset + 7 * w
        values.append(float(sum(block.values[lo:lo + 7])))
        events += sum(block.events[lo:lo + 7])
    return Series(target, Granularity.WEEK, unit, first_monday, tuple(values), events, entity, label)


# ----------------------------------------------------------------------------- service demand

def entity_key(item_type: str, service_id, package_id, addon_id, name: str, description: str | None) -> str:
    """Stable identity for a service/package/add-on.

    Uses the catalog id when the order item still has one.  If the catalog row was removed (the
    foreign key becomes NULL) it falls back to the item's own snapshot, so history is kept and a
    deleted reference never breaks anything.  Packages are identified by their description
    snapshot (e.g. "Clothes . 3KG-5KG") because every package shares the name "Wash, Dry & Fold".
    """
    ident = {"service": service_id, "package": package_id, "addon": addon_id}.get(item_type)
    if ident is not None:
        return f"{item_type}:{ident}"
    snapshot = (description if item_type == "package" and description else name) or ""
    return f"{item_type}:~{' '.join(snapshot.lower().split())}"


def _label(row: dict) -> str:
    if row["item_type"] == "package" and row.get("description"):
        return row["description"]
    return row["name"]


def build_service_entities(rows: list, window_start: date | None, as_of: date, policy: Policy) -> list:
    """One entity per service/package/add-on with weekly demand series (orders and quantity).

    A new service's history starts at its first COMPLETE week, so weeks before it existed are never
    counted as zero demand.  History before the shop-level data gap (``window_start``) is excluded.
    """
    if window_start is None or not rows:
        return []
    last_day = as_of - timedelta(days=1)
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        key = entity_key(r["item_type"], r.get("service_id"), r.get("package_id"), r.get("addon_id"),
                         r["name"], r.get("description"))
        groups[key].append(r)

    entities = []
    for key, rs in groups.items():
        rs = [r for r in rs if window_start <= r["date"] <= last_day]
        if not rs:
            continue
        units: dict[str, int] = defaultdict(int)
        for r in rs:
            units[r["unit"]] += r["orders"]
        unit = max(sorted(units), key=lambda u: units[u])
        issues = []
        if len(units) > 1:
            other = sum(v for u, v in units.items() if u != unit)
            issues.append(Issue("mixed_units", "warning",
                                f"Recorded in more than one unit; quantity uses '{unit}' only ({other} order(s) excluded from quantity).",
                                other))

        first_date = min(r["date"] for r in rs)
        orders_by_day: dict[date, int] = defaultdict(int)
        qty_by_day: dict[date, float] = defaultdict(float)
        for r in rs:
            orders_by_day[r["date"]] += int(r["orders"])
            if r["unit"] == unit:
                qty_by_day[r["date"]] += float(r["quantity"])

        start = _monday_on_or_after(first_date)
        n = (last_day - start).days + 1
        days = [start + timedelta(days=i) for i in range(max(n, 0))]
        orders_block = DailyBlock(start, tuple(float(orders_by_day.get(d, 0)) for d in days),
                                  tuple(int(orders_by_day.get(d, 0)) for d in days)) if days else None
        qty_block = DailyBlock(start, tuple(qty_by_day.get(d, 0.0) for d in days),
                               tuple(int(orders_by_day.get(d, 0)) for d in days)) if days else None

        newest = max(rs, key=lambda r: r["date"])
        label = _label(newest)
        orders_w = weekly_series(orders_block, Target.SERVICE_DEMAND, Unit.ORDERS, as_of, key, label)
        qty_w = weekly_series(qty_block, Target.SERVICE_DEMAND, unit, as_of, key, label) if qty_block else None
        entities.append(ServiceEntity(
            key=key, item_type=newest["item_type"], label=label, unit=unit, orders_weekly=orders_w,
            quantity_weekly=qty_w, total_orders=sum(orders_by_day.values()), first_date=first_date,
            issues=tuple(issues)))
    entities.sort(key=lambda e: (-e.total_orders, e.label.lower()))
    return entities


# ----------------------------------------------------------------------------- assembly

def assemble(raw: RawData, now_utc: datetime, policy: Policy = DEFAULT_POLICY) -> PreparedData:
    """Build every series from aggregated rows.  Pure and deterministic for a given ``now_utc``."""
    as_of = local_today(now_utc)

    ord_vals = {d: float(v[0]) for d, v in raw.orders_by_day.items()}
    ord_events = {d: int(v[0]) for d, v in raw.orders_by_day.items()}
    gross_vals = {d: float(v[1]) for d, v in raw.orders_by_day.items()}
    first_order = min(raw.orders_by_day) if raw.orders_by_day else None

    ord_block, ord_cut, ord_gap = build_daily_block(ord_vals, ord_events, first_order, as_of, policy)
    gross_block, gross_cut, _ = build_daily_block(gross_vals, ord_events, first_order, as_of, policy)

    # Collections: start at the payment-tracking go-live, never earlier (earlier zeros = not recorded).
    coll_vals = {d: float(v[0]) - float(v[1]) for d, v in raw.collections_by_day.items()}
    coll_events = {d: int(v[2]) + int(v[3]) for d, v in raw.collections_by_day.items()}
    candidates = [d for d in (raw.ledger_start, min(raw.collections_by_day) if raw.collections_by_day else None) if d]
    coll_start = min(candidates) if candidates else None
    coll_vals = {d: v for d, v in coll_vals.items() if coll_start and d >= coll_start}
    coll_block, coll_cut, _ = build_daily_block(coll_vals, coll_events, coll_start, as_of, policy)

    issues: list[Issue] = list(dv.quality_issues(raw.quality))
    if ord_block is not None:
        issues += dv.series_issues(ord_block.values, ord_block.start, policy, ord_cut)
    elif ord_gap:
        issues.append(Issue("no_recent_activity", "warning",
                            f"No eligible orders in the last {policy.max_inactive_gap_days}+ days; there is no recent "
                            "activity to learn from.", ord_cut))

    window_start = ord_block.start if ord_block else None
    services = build_service_entities(raw.service_rows, window_start, as_of, policy)

    return PreparedData(
        as_of=as_of,
        orders_daily=daily_series(ord_block, Target.ORDERS, Unit.ORDERS, as_of),
        orders_weekly=weekly_series(ord_block, Target.ORDERS, Unit.ORDERS, as_of),
        gross_daily=daily_series(gross_block, Target.GROSS_VALUE, Unit.PESO, as_of),
        gross_weekly=weekly_series(gross_block, Target.GROSS_VALUE, Unit.PESO, as_of),
        collections_daily=daily_series(coll_block, Target.COLLECTIONS, Unit.PESO, as_of),
        collections_weekly=weekly_series(coll_block, Target.COLLECTIONS, Unit.PESO, as_of),
        services=tuple(services),
        excluded_history={Target.ORDERS: ord_cut, Target.GROSS_VALUE: gross_cut, Target.COLLECTIONS: coll_cut},
        issues=tuple(issues),
        quality=dict(raw.quality),
        ledger_start=coll_start,
    )


def prepare_all(now_utc: datetime | None = None, policy: Policy = DEFAULT_POLICY) -> PreparedData:
    """Read the database (aggregates only) and build every series.  Read-only; never trains."""
    from app.analytics.ml import data_source          # imported here so the pure code above needs no database
    from app.models.staff_credential import utcnow

    now_utc = now_utc or utcnow()
    return assemble(data_source.fetch_raw(now_utc, policy), now_utc, policy)
