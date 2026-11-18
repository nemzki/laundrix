"""Read-only business analytics queries for the admin Analytics & Reports page.

All figures are derived from existing Laundrix tables. This module never writes
orders, customers, payments, or catalog records.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.models import (
    Customer,
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    PaymentKind,
    HistoricalTransaction,
)



def _month_start(value):
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _shift_month(value, months):
    month_index = value.year * 12 + value.month - 1 + months
    year, month0 = divmod(month_index, 12)
    return value.replace(year=year, month=month0 + 1, day=1)


def _money(value):
    return Decimal(str(value or 0))


def get_analytics_report(as_of=None):
    """Return admin-safe aggregate metrics and chart series from production data."""
    now = as_of or datetime.now(timezone.utc).replace(tzinfo=None)
    first_month = _shift_month(_month_start(now), -5)
    twelve_months_ago = _shift_month(_month_start(now), -11)

    orders = db.session.execute(
        db.select(Order.id, Order.status, Order.total, Order.created_at, Order.customer_id, Order.payment_arrangement)
        .order_by(Order.created_at)
    ).all()
    all_payments = db.session.execute(
        db.select(Payment.order_id, Payment.kind, Payment.amount, Payment.paid_at, Payment.method_label)
        .order_by(Payment.paid_at)
    ).all()
    payments = [row for row in all_payments if row.paid_at >= twelve_months_ago]

    total_orders = len(orders)
    total_order_value = sum((_money(row.total) for row in orders), Decimal("0.00"))
    current_month_start = _month_start(now)
    orders_this_month = sum(1 for row in orders if row.created_at >= current_month_start)
    customers_count = db.session.scalar(db.select(func.count(Customer.id))) or 0

    month_keys = []
    cursor = first_month
    for _ in range(6):
        month_keys.append(cursor.strftime("%Y-%m"))
        cursor = _shift_month(cursor, 1)

    historical_totals = db.session.execute(
        db.select(
            func.count(HistoricalTransaction.id),
            func.coalesce(func.sum(HistoricalTransaction.total_amount), 0),
        )
    ).one()

    historical_monthly = {
        key: {
            "key": key,
            "label": datetime.strptime(key, "%Y-%m").strftime("%b %Y"),
            "transactions": 0,
            "revenue": Decimal("0.00"),
        }
        for key in month_keys
    }

    historical_rows = db.session.execute(
        db.select(
            HistoricalTransaction.transaction_date,
            HistoricalTransaction.total_amount,
        ).where(
            HistoricalTransaction.transaction_date >= first_month.date(),
            HistoricalTransaction.transaction_date < _shift_month(
                _month_start(now), 1
            ).date(),
        )
    ).all()

    for row in historical_rows:
        key = row.transaction_date.strftime("%Y-%m")
        if key in historical_monthly:
            historical_monthly[key]["transactions"] += 1
            historical_monthly[key]["revenue"] += _money(row.total_amount)

    monthly = {
        key: {"key": key, "label": datetime.strptime(key, "%Y-%m").strftime("%b %Y"),
              "orders": 0, "collected": Decimal("0.00")}
        for key in month_keys
    }
    status_counts = defaultdict(int)
    for row in orders:
        status_counts[row.status] += 1
        key = row.created_at.strftime("%Y-%m")
        if key in monthly:
            monthly[key]["orders"] += 1

    collected_12m = Decimal("0.00")
    payments_by_order = defaultdict(lambda: Decimal("0.00"))
    for row in all_payments:
        sign = Decimal("-1.00") if row.kind == PaymentKind.REVERSAL else Decimal("1.00")
        payments_by_order[row.order_id] += _money(row.amount) * sign

    method_totals = defaultdict(lambda: Decimal("0.00"))
    for row in payments:
        amount = _money(row.amount)
        sign = Decimal("-1.00") if row.kind == PaymentKind.REVERSAL else Decimal("1.00")
        net = amount * sign
        collected_12m += net
        method_totals[row.method_label or "Other"] += net
        key = row.paid_at.strftime("%Y-%m")
        if key in monthly:
            monthly[key]["collected"] += net

    tracked_balances = []
    for row in orders:
        # Only orders with payment tracking configured are included in balance totals.
        if row.payment_arrangement is not None:
            balance = _money(row.total) - payments_by_order.get(row.id, Decimal("0.00"))
            if balance > Decimal("0.005"):
                tracked_balances.append(balance)

    status_labels = {
        OrderStatus.RECEIVED: "Order Received",
        OrderStatus.PENDING: "Pending Processing",
        OrderStatus.PROCESSING: "Processing",
        OrderStatus.READY: "Ready for Pickup",
        OrderStatus.RELEASED: "Picked Up",
        OrderStatus.COMPLETED: "Completed",
    }
    status_data = [
        {"label": status_labels.get(status, status.replace("_", " ").title()), "count": count}
        for status, count in sorted(status_counts.items(), key=lambda item: item[0])
    ]

    service_rows = db.session.execute(
        db.select(
            OrderItem.name,
            func.count(OrderItem.id),
            func.coalesce(func.sum(OrderItem.quantity), 0),
            func.coalesce(func.sum(OrderItem.line_total), 0),
        )
        .group_by(OrderItem.name)
        .order_by(func.count(OrderItem.id).desc(), func.sum(OrderItem.line_total).desc())
        .limit(6)
    ).all()
    services = [
        {"name": name, "lines": int(lines), "quantity": float(quantity or 0),
         "sales": _money(sales)}
        for name, lines, quantity, sales in service_rows
    ]

    monthly_data = [monthly[key] for key in month_keys]
    max_orders = max((item["orders"] for item in monthly_data), default=0) or 1
    max_collected = max((item["collected"] for item in monthly_data), default=Decimal("0.00")) or Decimal("1.00")
    for item in monthly_data:
        item["orders_height"] = round(item["orders"] / max_orders * 130)
        item["collected_height"] = round(max(item["collected"], Decimal("0.00")) / max(max_collected, Decimal("1.00")) * 130)

    max_service_lines = max((item["lines"] for item in services), default=0) or 1
    for item in services:
        item["bar_width"] = round(item["lines"] / max_service_lines * 100)

    methods = [
        {"name": name, "amount": round(amount, 2)}
        for name, amount in sorted(method_totals.items(), key=lambda item: item[1], reverse=True)
    ]
    max_method = max((max(item["amount"], Decimal("0.00")) for item in methods), default=Decimal("0.00")) or Decimal("1.00")
    for item in methods:
        item["bar_width"] = round(max(item["amount"], Decimal("0.00")) / max_method * 100)

    return {
        "summary": {
            "total_orders": total_orders,
            "orders_this_month": orders_this_month,
            "total_customers": int(customers_count),
            "order_value": total_order_value.quantize(Decimal("0.01")),
            "collected_12m": collected_12m.quantize(Decimal("0.01")),
            "outstanding_balance": sum(tracked_balances, Decimal("0.00")).quantize(Decimal("0.01")),
            "orders_with_balance": len(tracked_balances),
        },
        "monthly": monthly_data,
        "statuses": status_data,
        "services": services,
        "payment_methods": methods,
        "historical": {
            "summary": {
                "transaction_count": int(historical_totals[0] or 0),
                "recorded_revenue": _money(historical_totals[1]).quantize(
                    Decimal("0.01")
                ),
            },
            "monthly": [
                {
                    **item,
                    "revenue": item["revenue"].quantize(Decimal("0.01")),
                }
                for item in historical_monthly.values()
            ],
        },
        "report_period": f"{first_month.strftime('%b %Y')} – {now.strftime('%b %Y')}",
    }
