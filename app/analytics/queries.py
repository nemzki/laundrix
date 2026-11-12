"""SQL aggregation for Analytics.  The only analytics module that touches the DB.

Conventions
* Every period query takes ``start``/``end`` as naive-UTC datetimes
  (inclusive start, exclusive end) taken from ``DateRange.start_utc/end_utc``.
* Aggregation happens in SQL.  No query joins two one-to-many relations, so
  totals cannot be multiplied by join fan-out.
* Per-order net payments reuse ``payments.services._net_subquery`` so the
  ledger rules (reversals cancel payments) live in exactly one place.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import and_, case, distinct, func, literal_column, select

from app.analytics.calculations import ZERO, money
from app.core.timeutil import SHOP_TZ
from app.extensions import db
from app.models import Customer, Order, OrderItem, Payment, PaymentKind
from app.payments.services import _net_subquery as ledger_net_subquery

# The shop is on a fixed UTC offset (Philippines has no DST), so a constant
# offset in SQL is exact.
_OFFSET_HOURS = int(SHOP_TZ.utcoffset(None).total_seconds() // 3600)


def local_date(column):
    """SQL expression: the Philippine calendar date of a naive-UTC column."""
    dialect = db.session.get_bind().dialect.name
    if dialect in ("mysql", "mariadb"):
        return func.date(func.date_add(column, literal_column(f"INTERVAL {_OFFSET_HOURS} HOUR")))
    if dialect == "sqlite":
        return func.date(column, f"{_OFFSET_HOURS:+d} hours")
    raise NotImplementedError(f"Analytics date grouping is not implemented for {dialect!r}")


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _n(value) -> int:
    return int(value or 0)


# ---- orders ----------------------------------------------------------------

def order_summary(start: datetime, end: datetime) -> dict:
    row = db.session.execute(
        select(
            func.count(Order.id),
            func.coalesce(func.sum(Order.total), 0),
            func.coalesce(func.sum(case((Order.received_at.is_(None), 1), else_=0)), 0),
        ).where(Order.created_at >= start, Order.created_at < end)
    ).one()
    return {"count": _n(row[0]), "gross": money(row[1]), "awaiting_receipt": _n(row[2])}


def orders_by_status(start: datetime, end: datetime) -> dict[str, int]:
    rows = db.session.execute(
        select(Order.status, func.count(Order.id))
        .where(Order.created_at >= start, Order.created_at < end)
        .group_by(Order.status)
    ).all()
    return {status: _n(n) for status, n in rows}


def orders_by_day(start: datetime, end: datetime) -> dict[date, dict]:
    day = local_date(Order.created_at).label("day")
    rows = db.session.execute(
        select(day, func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
        .where(Order.created_at >= start, Order.created_at < end)
        .group_by(day)
    ).all()
    return {_as_date(d): {"orders": _n(n), "gross_order_value": money(g)} for d, n, g in rows}


# ---- payment ledger --------------------------------------------------------

def _ledger_columns():
    is_rev = Payment.kind == PaymentKind.REVERSAL
    is_pay = Payment.kind == PaymentKind.PAYMENT
    return (
        func.coalesce(func.sum(case((is_pay, Payment.amount), else_=0)), 0),
        func.coalesce(func.sum(case((is_rev, Payment.amount), else_=0)), 0),
        func.coalesce(func.sum(case((is_pay, 1), else_=0)), 0),
        func.coalesce(func.sum(case((is_rev, 1), else_=0)), 0),
    )


def _ledger_dict(payments, reversals, n_pay, n_rev) -> dict:
    p, r = money(payments), money(reversals)
    return {"payments": p, "reversals": r, "net": p - r,
            "payment_count": _n(n_pay), "reversal_count": _n(n_rev)}


def ledger_summary(start: datetime, end: datetime) -> dict:
    """Collections dated by Payment.paid_at.  A reversal counts in the period it
    was recorded, never in the period of the payment it cancels."""
    row = db.session.execute(
        select(*_ledger_columns()).where(Payment.paid_at >= start, Payment.paid_at < end)
    ).one()
    return _ledger_dict(*row)


def ledger_by_method(start: datetime, end: datetime) -> list[dict]:
    """Per payment method, read dynamically from the ledger snapshots."""
    rows = db.session.execute(
        select(Payment.method_code, func.max(Payment.method_label), *_ledger_columns())
        .where(Payment.paid_at >= start, Payment.paid_at < end)
        .group_by(Payment.method_code)
    ).all()
    out = [{"code": code, "label": label or code, **_ledger_dict(*rest)} for code, label, *rest in rows]
    out.sort(key=lambda r: (-r["net"], r["code"]))
    return out


def ledger_by_day(start: datetime, end: datetime) -> dict[date, dict]:
    day = local_date(Payment.paid_at).label("day")
    rows = db.session.execute(
        select(day, *_ledger_columns())
        .where(Payment.paid_at >= start, Payment.paid_at < end)
        .group_by(day)
    ).all()
    return {_as_date(d): {"payments": money(p), "reversals": money(r)} for d, p, r, _, _ in rows}


# ---- outstanding balances --------------------------------------------------

def outstanding(start: datetime | None = None, end: datetime | None = None) -> dict:
    """Balances on payment-tracked orders, from today's ledger.

    With start/end: only orders *created* in that window.  Without: all orders.
    Legacy orders (payment_arrangement IS NULL) are reported separately and are
    never counted as confirmed unpaid.
    """
    net = ledger_net_subquery()
    received = func.coalesce(net.c.net, 0)
    tracked = Order.payment_arrangement.is_not(None)
    owing = and_(tracked, received < Order.total)
    unpaid = and_(owing, received <= 0)
    partial = and_(owing, received > 0)

    stmt = (
        select(
            func.coalesce(func.sum(case((unpaid, 1), else_=0)), 0),
            func.coalesce(func.sum(case((partial, 1), else_=0)), 0),
            func.coalesce(func.sum(case((unpaid, Order.total - received), else_=0)), 0),
            func.coalesce(func.sum(case((partial, Order.total - received), else_=0)), 0),
            func.count(distinct(case((owing, Order.customer_id)))),
            func.coalesce(func.sum(case((tracked, 0), else_=1)), 0),
            func.coalesce(func.sum(case((tracked, 0), else_=Order.total)), 0),
        )
        .select_from(Order)
        .outerjoin(net, net.c.order_id == Order.id)
    )
    if start is not None and end is not None:
        stmt = stmt.where(Order.created_at >= start, Order.created_at < end)
    u_n, p_n, u_amt, p_amt, customers, legacy_n, legacy_total = db.session.execute(stmt).one()
    u_amt, p_amt = money(u_amt), money(p_amt)
    return {
        "unpaid_orders": _n(u_n),
        "partial_orders": _n(p_n),
        "unpaid_amount": u_amt,
        "partial_amount": p_amt,
        "balance_total": u_amt + p_amt,
        "customers_owing": _n(customers),
        "untracked_orders": _n(legacy_n),
        "untracked_order_value": money(legacy_total),
    }


# ---- services --------------------------------------------------------------

def service_breakdown(start: datetime, end: datetime) -> list[dict]:
    """Order-item snapshots grouped by (type, name, unit).  Joins only
    OrderItem -> Order, so orders are counted with COUNT(DISTINCT)."""
    rows = db.session.execute(
        select(
            OrderItem.item_type, OrderItem.name, OrderItem.unit,
            func.coalesce(func.sum(OrderItem.quantity), 0),
            func.count(distinct(OrderItem.order_id)),
            func.coalesce(func.sum(OrderItem.line_total), 0),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.created_at >= start, Order.created_at < end)
        .group_by(OrderItem.item_type, OrderItem.name, OrderItem.unit)
    ).all()
    return [
        {"item_type": t, "name": name, "unit": unit, "quantity": q,
         "orders": _n(n), "item_revenue": money(rev)}
        for t, name, unit, q, n, rev in rows
    ]


def service_daily(start: datetime, end: datetime) -> list[dict]:
    """Orders per day per non-addon item name (for demand-trend charts)."""
    day = local_date(Order.created_at).label("day")
    rows = db.session.execute(
        select(day, OrderItem.name, func.count(distinct(OrderItem.order_id)))
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.created_at >= start, Order.created_at < end, OrderItem.item_type != "addon")
        .group_by(day, OrderItem.name)
    ).all()
    return [{"date": _as_date(d), "name": name, "orders": _n(n)} for d, name, n in rows]


# ---- customers -------------------------------------------------------------

def customer_counts(start: datetime, end: datetime) -> dict:
    registered = db.session.execute(
        select(func.count(Customer.id)).where(Customer.created_at < end)
    ).scalar()
    new_registered = db.session.execute(
        select(func.count(Customer.id)).where(Customer.created_at >= start, Customer.created_at < end)
    ).scalar()

    per_customer = (
        select(
            Order.customer_id.label("cid"),
            func.min(Order.created_at).label("first_at"),
            func.count(Order.id).label("lifetime"),
            func.sum(case((Order.created_at >= start, 1), else_=0)).label("in_range"),
        )
        .where(Order.created_at < end)
        .group_by(Order.customer_id)
        .subquery()
    )
    active = per_customer.c.in_range > 0
    row = db.session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(case((per_customer.c.lifetime >= 2, 1), else_=0)), 0),
            func.coalesce(func.sum(case((active, 1), else_=0)), 0),
            func.coalesce(func.sum(case((and_(active, per_customer.c.first_at < start), 1), else_=0)), 0),
            func.coalesce(func.sum(case((and_(active, per_customer.c.first_at >= start), 1), else_=0)), 0),
        ).select_from(per_customer)
    ).one()
    return {
        "registered": _n(registered),
        "new_registered": _n(new_registered),
        "with_orders": _n(row[0]),
        "repeat": _n(row[1]),
        "active": _n(row[2]),
        "returning": _n(row[3]),
        "new_active": _n(row[4]),
    }


def top_customers(start: datetime, end: datetime, limit: int = 10) -> list[dict]:
    """Display name only; no phone numbers in aggregate reports."""
    rows = db.session.execute(
        select(Customer.id, Customer.full_name, func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
        .join(Customer, Customer.id == Order.customer_id)
        .where(Order.created_at >= start, Order.created_at < end)
        .group_by(Customer.id, Customer.full_name)
        .order_by(func.count(Order.id).desc(), func.sum(Order.total).desc(), Customer.full_name)
        .limit(limit)
    ).all()
    return [{"customer_id": cid, "name": name, "orders": _n(n), "total": money(t)} for cid, name, n, t in rows]
