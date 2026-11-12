"""The only ML module that queries the database.

Privacy by construction: every query is an aggregate (counts and sums per day, per item).  Customer
names, contact numbers, e-mail addresses, identity-verification data and staff data are never
selected.  ``Order.customer_id`` appears only inside a grouped duplicate count; no identifier ever
leaves this module.

Eligibility rule for demand and gross-value history (documented in docs/):
    * received_at IS NOT NULL            the laundry was confirmed received (actual acceptance time)
    * received_at is not earlier than created_at by more than the tolerance in the policy
    * received_at is not in the future (beyond the tolerance)
All order statuses count after receipt.  The date used is the shop-local date of ``received_at``.
There is no soft-delete, test or cancelled marker in the schema, so none can be filtered on.

Payment collections are cash actually recorded in the ledger and do NOT depend on order
eligibility (money can be taken before the laundry is received).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import and_, case, distinct, exists, func, literal_column, select

from app.analytics.calculations import money
from app.analytics.ml.data_preparation import RawData
from app.analytics.ml.policy import Policy
from app.analytics.queries import _as_date, _ledger_columns, local_date
from app.core.timeutil import to_local
from app.extensions import db
from app.models import Order, OrderItem, Payment


def seconds_between(start_col, end_col):
    """SQL expression: seconds from ``start_col`` to ``end_col`` (MySQL and SQLite)."""
    dialect = db.session.get_bind().dialect.name
    if dialect in ("mysql", "mariadb"):
        return func.timestampdiff(literal_column("SECOND"), start_col, end_col)
    if dialect == "sqlite":
        return (func.julianday(end_col) - func.julianday(start_col)) * 86400.0
    raise NotImplementedError(f"ML data preparation is not implemented for {dialect!r}")


def eligible_orders(now_utc: datetime, policy: Policy):
    """SQL condition selecting valid, received orders."""
    return and_(
        Order.received_at.is_not(None),
        seconds_between(Order.created_at, Order.received_at) >= -policy.received_before_created_tolerance_seconds,
        Order.received_at <= now_utc + timedelta(seconds=policy.received_in_future_tolerance_seconds),
    )


def fetch_orders_by_day(now_utc: datetime, policy: Policy) -> dict[date, tuple]:
    day = local_date(Order.received_at).label("day")
    rows = db.session.execute(
        select(day, func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
        .where(eligible_orders(now_utc, policy))
        .group_by(day)
    ).all()
    return {_as_date(d): (int(n), float(money(total))) for d, n, total in rows}


def fetch_collections_by_day() -> dict[date, tuple]:
    """Ledger entries by the local date of ``paid_at``: (payments, reversals, n_payments, n_reversals).
    A reversal lands on the day it was recorded, exactly like the descriptive dashboard."""
    day = local_date(Payment.paid_at).label("day")
    rows = db.session.execute(select(day, *_ledger_columns()).group_by(day)).all()
    return {_as_date(d): (float(money(p)), float(money(r)), int(a or 0), int(b or 0)) for d, p, r, a, b in rows}


def fetch_ledger_start() -> date | None:
    """First day payments were tracked: the earlier of the first ledger entry and the first order
    created with a payment arrangement.  Before it, 'no collections' only means 'not recorded'."""
    first_payment = db.session.scalar(select(func.min(Payment.paid_at)))
    first_tracked = db.session.scalar(
        select(func.min(Order.created_at)).where(Order.payment_arrangement.is_not(None)))
    candidates = [d for d in (first_payment, first_tracked) if d is not None]
    return to_local(min(candidates)).date() if candidates else None


def fetch_service_rows(now_utc: datetime, policy: Policy) -> list[dict]:
    """Order-item snapshots per local day: distinct orders and summed quantity (catalog-independent)."""
    day = local_date(Order.received_at).label("day")
    keys = (OrderItem.item_type, OrderItem.service_id, OrderItem.package_id, OrderItem.addon_id,
            OrderItem.name, OrderItem.description, OrderItem.unit)
    rows = db.session.execute(
        select(day, *keys, func.count(distinct(OrderItem.order_id)), func.coalesce(func.sum(OrderItem.quantity), 0))
        .join(Order, Order.id == OrderItem.order_id)
        .where(eligible_orders(now_utc, policy))
        .group_by(day, *keys)
    ).all()
    return [
        {"date": _as_date(d), "item_type": t, "service_id": sid, "package_id": pid, "addon_id": aid,
         "name": name, "description": desc, "unit": unit, "orders": int(n), "quantity": float(q)}
        for d, t, sid, pid, aid, name, desc, unit, n, q in rows
    ]


def fetch_quality(now_utc: datetime, policy: Policy) -> dict:
    """Record counts for the data-quality report.  Numbers only."""
    eligible = eligible_orders(now_utc, policy)
    received = Order.received_at.is_not(None)
    before = and_(received, seconds_between(Order.created_at, Order.received_at) < -policy.received_before_created_tolerance_seconds)
    future = and_(received, Order.received_at > now_utc + timedelta(seconds=policy.received_in_future_tolerance_seconds))
    total, awaiting, n_before, n_future, n_eligible = db.session.execute(select(
        func.count(Order.id),
        func.coalesce(func.sum(case((Order.received_at.is_(None), 1), else_=0)), 0),
        func.coalesce(func.sum(case((before, 1), else_=0)), 0),
        func.coalesce(func.sum(case((future, 1), else_=0)), 0),
        func.coalesce(func.sum(case((eligible, 1), else_=0)), 0),
    )).one()

    no_items = db.session.scalar(
        select(func.count(Order.id)).where(eligible, ~exists().where(OrderItem.order_id == Order.id)))

    day = local_date(Order.received_at).label("day")
    dup = (select(Order.customer_id, Order.total, day).where(eligible)
           .group_by(Order.customer_id, Order.total, day).having(func.count(Order.id) > 1)).subquery()
    dup_groups = db.session.scalar(select(func.count()).select_from(dup))

    return {
        "total_orders": int(total), "awaiting_receipt": int(awaiting),
        "invalid_received_before_created": int(n_before), "invalid_received_future": int(n_future),
        "eligible_orders": int(n_eligible), "eligible_without_items": int(no_items or 0),
        "possible_duplicate_groups": int(dup_groups or 0),
    }


def fetch_raw(now_utc: datetime, policy: Policy) -> RawData:
    return RawData(
        orders_by_day=fetch_orders_by_day(now_utc, policy),
        collections_by_day=fetch_collections_by_day(),
        ledger_start=fetch_ledger_start(),
        service_rows=fetch_service_rows(now_utc, policy),
        quality=fetch_quality(now_utc, policy),
    )
