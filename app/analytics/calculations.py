"""Pure calculations: no database, no Flask.  Everything here is unit-tested."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
TENTH = Decimal("0.1")
ZERO = Decimal("0.00")

# Shown next to metrics in the UI so money meanings never get confused.
METRIC_DEFINITIONS = {
    "gross_order_value": "Sum of order totals for orders created in the period. Not money received.",
    "payments_collected": "Payments received minus reversals, dated by when each ledger entry was recorded.",
    "outstanding_balance": "Still owed on payment-tracked orders created in the period, using today's ledger. "
                           "Legacy orders without payment tracking are excluded.",
    "average_order_value": "Gross order value divided by the number of orders.",
    "returning_customers": "Customers who ordered in the period and placed their first-ever order before it began.",
    "repeat_customer": "A customer with two or more orders in total.",
    "item_revenue": "Sum of order-item line totals. Excludes nothing, but is not the same as order revenue.",
}


def to_decimal(value) -> Decimal:
    if value is None:
        return Decimal(0)
    return value if isinstance(value, Decimal) else Decimal(str(value))


def money(value) -> Decimal:
    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _fmt(d: Decimal) -> str:
    return format(d, "f")


def format_peso(value) -> str:
    """\u20b11,234.50 style (two decimals); negatives read -\u20b1100.00; None is an em dash."""
    if value is None:
        return "\u2014"
    d = to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
    return f"{'-' if d < 0 else ''}\u20b1{abs(d):,.2f}"


@dataclass(frozen=True)
class Change:
    current: Decimal
    previous: Decimal
    absolute: Decimal
    percent: Decimal | None  # None when a percentage is not meaningful
    direction: str           # "up" | "down" | "flat"

    def as_dict(self) -> dict:
        return {
            "current": _fmt(self.current),
            "previous": _fmt(self.previous),
            "absolute": _fmt(self.absolute),
            "percent": None if self.percent is None else _fmt(self.percent),
            "direction": self.direction,
        }


def compare(current, previous) -> Change:
    """Current vs previous period.

    The percentage is only produced when the previous value is positive;
    otherwise it is None (never a divide-by-zero, never a misleading figure).
    """
    cur, prev = to_decimal(current), to_decimal(previous)
    diff = cur - prev
    percent = None
    if prev > 0:
        percent = (diff / prev * 100).quantize(TENTH, rounding=ROUND_HALF_UP)
    direction = "up" if diff > 0 else "down" if diff < 0 else "flat"
    return Change(cur, prev, diff, percent, direction)


def average_order_value(gross, order_count) -> Decimal | None:
    if not order_count:
        return None
    return money(to_decimal(gross) / Decimal(order_count))


def balance_due(total, net_paid) -> Decimal:
    """max(total - net payments, 0): overpayment never yields a negative balance."""
    return money(max(to_decimal(total) - to_decimal(net_paid), Decimal(0)))


def share_percent(part, whole) -> Decimal | None:
    whole = to_decimal(whole)
    if whole <= 0:
        return None
    return (to_decimal(part) / whole * 100).quantize(TENTH, rounding=ROUND_HALF_UP)


# ---- time-series bucketing -------------------------------------------------

def bucket_key(d: date, granularity: str) -> date:
    if granularity == "day":
        return d
    if granularity == "week":  # Monday-to-Sunday business weeks
        return d - timedelta(days=d.weekday())
    if granularity == "month":
        return d.replace(day=1)
    raise ValueError(f"Unknown granularity: {granularity}")


def bucket_end(key: date, granularity: str) -> date:
    if granularity == "day":
        return key
    if granularity == "week":
        return key + timedelta(days=6)
    return key.replace(day=calendar.monthrange(key.year, key.month)[1])


def bucket_label(key: date, granularity: str) -> str:
    if granularity == "day":
        return f"{key:%b %d}"
    if granularity == "week":
        return f"Wk of {key:%b %d}"
    return f"{key:%b %Y}"


def bucket_series(daily: dict, start: date, end: date, granularity: str, zeros: dict) -> list[dict]:
    """Roll a {date: {metric: value}} mapping up to day/week/month buckets.

    Every day in [start, end] contributes (missing days count as zero), so
    zero-activity days are represented.  ``partial`` marks buckets clipped by
    the range edges (e.g. a week that began before ``start``).
    """
    buckets: dict[date, dict] = {}
    d = start
    while d <= end:
        key = bucket_key(d, granularity)
        b = buckets.setdefault(key, dict(zeros))
        for metric, value in daily.get(d, {}).items():
            b[metric] = b[metric] + value
        d += timedelta(days=1)

    out = []
    for key in sorted(buckets):
        nat_end = bucket_end(key, granularity)
        out.append({
            "key": key.isoformat(),
            "label": bucket_label(key, granularity),
            "start": max(key, start).isoformat(),
            "end": min(nat_end, end).isoformat(),
            "partial": key < start or nat_end > end,
            **buckets[key],
        })
    return out


def rank_items(rows: list[dict]) -> list[dict]:
    """Rank by number of orders, then quantity, then name (stable, deterministic)."""
    ordered = sorted(rows, key=lambda r: (-r["orders"], -to_decimal(r["quantity"]), r["name"].lower()))
    return [{**r, "rank": i} for i, r in enumerate(ordered, start=1)]
