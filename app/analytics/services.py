"""Assembles dashboard payloads from queries + calculations.

One builder per dashboard section; every builder takes (DateRange, granularity)
and returns a JSON-friendly dict (Decimals serialise as exact strings, dates
as ISO strings).  No SQL here and no Flask request handling.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.analytics import calculations as calc
from app.analytics import queries
from app.analytics.periods import DateRange, default_granularity
from app.models import OrderStatus

PRIMARY_TYPES = ("service", "package")

# Dashboard groupings of the real OrderStatus constants.
STATUS_GROUPS = (
    ("pending", "Pending", (OrderStatus.RECEIVED, OrderStatus.PENDING)),
    ("processing", "Processing", (OrderStatus.PROCESSING,)),
    ("ready", "Ready for pickup", (OrderStatus.READY,)),
    ("completed", "Completed / released", (OrderStatus.RELEASED, OrderStatus.COMPLETED)),
)


def kpi_metrics(rng: DateRange) -> dict:
    """The six headline metrics for one period (4 aggregate queries)."""
    start, end = rng.start_utc, rng.end_utc
    orders = queries.order_summary(start, end)
    ledger = queries.ledger_summary(start, end)
    owed = queries.outstanding(start, end)
    customers = queries.customer_counts(start, end)
    return {
        "orders": orders["count"],
        "gross_order_value": orders["gross"],
        "payments_collected": ledger["net"],
        "outstanding_balance": owed["balance_total"],
        "average_order_value": calc.average_order_value(orders["gross"], orders["count"]),
        "returning_customers": customers["returning"],
    }


KPI_SPEC = (
    ("orders", "Total Orders", "count", None),
    ("gross_order_value", "Gross Order Value", "currency", "gross_order_value"),
    ("payments_collected", "Payments Collected", "currency", "payments_collected"),
    ("outstanding_balance", "Outstanding Balances", "currency", "outstanding_balance"),
    ("average_order_value", "Average Order Value", "currency", "average_order_value"),
    ("returning_customers", "Returning Customers", "count", "returning_customers"),
)


def build_overview(rng: DateRange, granularity: str | None = None) -> dict:
    current = kpi_metrics(rng)
    previous = kpi_metrics(rng.previous())
    cards = []
    for key, label, fmt, definition in KPI_SPEC:
        cur, prev = current[key], previous[key]
        # Average order value is undefined with zero orders; compare only when both exist.
        change = calc.compare(cur, prev).as_dict() if cur is not None and prev is not None else None
        cards.append({
            "key": key,
            "label": label,
            "format": fmt,
            "value": None if cur is None else format(cur, "f") if not isinstance(cur, int) else cur,
            "previous": None if prev is None else format(prev, "f") if not isinstance(prev, int) else prev,
            "change": change,
            "definition": calc.METRIC_DEFINITIONS.get(definition) if definition else None,
        })
    return {"period": rng.as_dict(), "kpis": cards}


# An increase in what customers still owe is not good news, so its colour is inverted.
INVERTED_TONE = {"outstanding_balance"}


def _display(value, money: bool) -> str:
    if value is None:
        return "\u2014"
    return calc.format_peso(value) if money else f"{int(calc.to_decimal(value)):,}"


def present_kpis(cards: list[dict]) -> list[dict]:
    """Turn build_overview()['kpis'] into display strings for the server-rendered cards.

    Keeps formatting rules in Python (unit-testable) instead of in Jinja.
    """
    out = []
    for c in cards:
        money = c["format"] == "currency"
        ch, hint = c["change"], None
        if ch is None:
            arrow, text, tone, direction = "\u2013", "No comparison", "neutral", None
            hint = "A comparison needs at least one order in both periods."
        elif ch["direction"] == "flat":
            arrow, text, tone, direction = "\u2013", "No change", "neutral", None
        else:
            up = ch["direction"] == "up"
            arrow, direction = ("\u25b2" if up else "\u25bc"), ("Increase" if up else "Decrease")
            if ch["percent"] is not None:
                text = f"{abs(calc.to_decimal(ch['percent']))}%"
            else:
                text = ("+" if up else "\u2212") + _display(abs(calc.to_decimal(ch["absolute"])), money)
                hint = "No percentage is shown because the previous value was zero."
            tone = "good" if up != (c["key"] in INVERTED_TONE) else "bad"
        out.append({
            "key": c["key"],
            "label": c["label"],
            "value_display": _display(c["value"], money),
            "previous_display": _display(c["previous"], money),
            "arrow": arrow,
            "delta_text": text,
            "tone": tone,
            "hint": hint,
            "sr_text": f"{direction} compared with the previous period" if direction else None,
            "definition": c["definition"],
        })
    return out


def build_sales(rng: DateRange, granularity: str | None = None) -> dict:
    granularity = granularity or default_granularity(rng.days)
    start, end = rng.start_utc, rng.end_utc
    daily: dict = {}
    for d, row in queries.orders_by_day(start, end).items():
        daily.setdefault(d, {}).update(row)
    for d, row in queries.ledger_by_day(start, end).items():
        daily.setdefault(d, {}).update(row)

    zeros = {"orders": 0, "gross_order_value": calc.ZERO, "payments": calc.ZERO, "reversals": calc.ZERO}
    points = calc.bucket_series(daily, rng.start, rng.end, granularity, zeros)
    for p in points:
        p["net_collections"] = p["payments"] - p["reversals"]

    cur, prev = kpi_metrics(rng), kpi_metrics(rng.previous())
    return {
        "period": rng.as_dict(),
        "granularity": granularity,
        "points": points,
        "comparison": {
            "gross_order_value": calc.compare(cur["gross_order_value"], prev["gross_order_value"]).as_dict(),
            "payments_collected": calc.compare(cur["payments_collected"], prev["payments_collected"]).as_dict(),
        },
        "definitions": {k: calc.METRIC_DEFINITIONS[k] for k in ("gross_order_value", "payments_collected")},
    }


def build_orders(rng: DateRange, granularity: str | None = None) -> dict:
    granularity = granularity or default_granularity(rng.days)
    start, end = rng.start_utc, rng.end_utc
    summary = queries.order_summary(start, end)
    by_status = queries.orders_by_status(start, end)

    statuses = [
        {"status": s, "label": OrderStatus.LABELS[s], "count": by_status.get(s, 0)}
        for s in OrderStatus.FLOW
    ]
    known = set(OrderStatus.FLOW)
    for s, n in sorted(by_status.items()):  # never drop an unexpected status silently
        if s not in known:
            statuses.append({"status": s, "label": OrderStatus.LABELS.get(s, s), "count": n})

    groups = [
        {"key": key, "label": label, "count": sum(by_status.get(s, 0) for s in members)}
        for key, label, members in STATUS_GROUPS
    ]
    daily = {d: {"orders": row["orders"]} for d, row in queries.orders_by_day(start, end).items()}
    volume = calc.bucket_series(daily, rng.start, rng.end, granularity, {"orders": 0})
    prev = queries.order_summary(rng.previous().start_utc, rng.previous().end_utc)
    return {
        "period": rng.as_dict(),
        "granularity": granularity,
        "total": summary["count"],
        "awaiting_receipt": summary["awaiting_receipt"],
        "comparison": calc.compare(summary["count"], prev["count"]).as_dict(),
        "by_status": statuses,
        "groups": groups,
        "volume": volume,
    }


def _clean_service_rows(rows: list[dict]) -> list[dict]:
    return [{**r, "quantity": format(calc.to_decimal(r["quantity"]), "f"),
             "item_revenue": format(r["item_revenue"], "f")} for r in rows]


def build_services(rng: DateRange, granularity: str | None = None) -> dict:
    granularity = granularity or default_granularity(rng.days)
    rows = queries.service_breakdown(rng.start_utc, rng.end_utc)
    primary = calc.rank_items([r for r in rows if r["item_type"] in PRIMARY_TYPES])
    addons = calc.rank_items([r for r in rows if r["item_type"] == "addon"])

    # Trend for the five most-ordered services/packages only.
    top_names = list(dict.fromkeys(r["name"] for r in primary[:5]))
    daily: dict = {}
    for r in queries.service_daily(rng.start_utc, rng.end_utc):
        if r["name"] in top_names:
            daily.setdefault(r["date"], {})[r["name"]] = r["orders"]
    trend = calc.bucket_series(daily, rng.start, rng.end, granularity, {n: 0 for n in top_names})

    return {
        "period": rng.as_dict(),
        "granularity": granularity,
        "services": _clean_service_rows(primary),
        "addons": _clean_service_rows(addons),
        "most_ordered": _clean_service_rows(primary[:5]),
        "least_ordered": _clean_service_rows(primary[-5:][::-1]) if len(primary) > 5 else [],
        "trend": {"series": top_names, "points": trend},
        "notes": {
            "revenue": "Revenue here is item revenue (order-item line totals), not order revenue.",
            "scope": "Only services and packages that were ordered in the period appear. Add-ons are listed separately.",
            "definition": calc.METRIC_DEFINITIONS["item_revenue"],
        },
    }


def build_customers(rng: DateRange, granularity: str | None = None) -> dict:
    counts = queries.customer_counts(rng.start_utc, rng.end_utc)
    prev = queries.customer_counts(rng.previous().start_utc, rng.previous().end_utc)
    return {
        "period": rng.as_dict(),
        **counts,
        "repeat_rate": _str(calc.share_percent(counts["repeat"], counts["with_orders"])),
        "returning_comparison": calc.compare(counts["returning"], prev["returning"]).as_dict(),
        "top_customers": [{**c, "total": format(c["total"], "f")}
                          for c in queries.top_customers(rng.start_utc, rng.end_utc)],
        "definitions": {k: calc.METRIC_DEFINITIONS[k] for k in ("returning_customers", "repeat_customer")},
    }


def build_payments(rng: DateRange, granularity: str | None = None) -> dict:
    summary = queries.ledger_summary(rng.start_utc, rng.end_utc)
    methods = queries.ledger_by_method(rng.start_utc, rng.end_utc)
    for m in methods:
        m["share"] = _str(calc.share_percent(m["net"], summary["net"]))
    return {
        "period": rng.as_dict(),
        "summary": {k: format(v, "f") if not isinstance(v, int) else v for k, v in summary.items()},
        "methods": [{k: format(v, "f") if hasattr(v, "quantize") else v for k, v in m.items()} for m in methods],
        "definition": calc.METRIC_DEFINITIONS["payments_collected"],
    }


def build_balances(rng: DateRange | None = None, granularity: str | None = None) -> dict:
    """Point-in-time (as of now); intentionally ignores the date range."""
    data = queries.outstanding()
    return {
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        **{k: format(v, "f") if hasattr(v, "quantize") else v for k, v in data.items()},
        "notes": {
            "untracked": "Legacy orders without payment tracking are not confirmed unpaid and are excluded from balances.",
            "scope": "All payment-tracked orders, regardless of the selected date range.",
        },
    }


def _str(value):
    return None if value is None else format(value, "f")


SECTIONS = {
    "sales": build_sales,
    "orders": build_orders,
    "services": build_services,
    "customers": build_customers,
    "payments": build_payments,
    "balances": build_balances,
}
