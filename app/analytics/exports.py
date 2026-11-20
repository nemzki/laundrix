"""CSV exports of real Laundrix records (admin only). Opens cleanly in Microsoft Excel.

Privacy: customer phone numbers are deliberately NOT exported. Customers are identified by name
and customer ID. Every cell is neutralised against spreadsheet formula injection.
"""
import csv
import io
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import selectinload

from app.core.timeutil import local_day_bounds_utc, to_local
from app.extensions import db
from app.models import (
    Order,
    OrderDisposal,
    OrderStatus,
    OrderStatusHistory,
    Payment,
    PaymentKind,
)

MAX_ROWS = 20000
MAX_RANGE_DAYS = 366
DATASETS = {
    "orders": "Orders (one row per order)",
    "items": "Order items / services (one row per line)",
    "payments": "Payments (one row per payment or reversal)",
}
_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


class ExportError(ValueError):
    """Invalid export request; the message is safe to show to the admin."""


def parse_range(raw_start, raw_end, today):
    """Validate the date range. Defaults to the last 30 days ending today."""
    try:
        end = date.fromisoformat(raw_end) if raw_end else today
        start = date.fromisoformat(raw_start) if raw_start else end - timedelta(days=29)
    except ValueError as exc:
        raise ExportError("Dates must be in the format YYYY-MM-DD.") from exc
    if start > end:
        raise ExportError("The start date must be on or before the end date.")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise ExportError(f"Please choose a range of at most {MAX_RANGE_DAYS} days.")
    return start, end


def cell(value):
    """Convert one value into a safe CSV cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if hasattr(value, "hour"):                      # datetime (stored as naive UTC)
        return to_local(value).strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = "".join(ch for ch in text if ch >= " " and ch != "\x7f").strip()
    return "'" + text if text.startswith(_DANGEROUS) else text


# --------------------------------------------------------------------------- row builders
ORDER_HEADERS = [
    "Order Reference", "Created At", "Customer Name", "Customer ID", "Status", "Services",
    "Subtotal", "Discount", "Total", "Payment Arrangement", "Payment Status", "Amount Paid",
    "Balance Due", "Payment Methods", "Laundry Received At", "Ready For Pickup At",
    "Picked Up At", "Marked Disposed",
]
ITEM_HEADERS = [
    "Order Reference", "Order Created At", "Item Type", "Item Name", "Quantity", "Unit",
    "Unit Price", "Line Total", "Customer Supplied",
]
PAYMENT_HEADERS = [
    "Payment ID", "Order Reference", "Type", "Method", "Amount", "Paid At", "Reference No.",
]


def order_row(order, ready_at, picked_at, disposed):
    methods = sorted({p.method_label for p in order.payments if p.kind == PaymentKind.PAYMENT})
    services = "; ".join(i.name for i in order.items)
    return [
        order.reference, order.created_at, order.customer_name, order.customer_id,
        OrderStatus.LABELS.get(order.status, order.status), services,
        order.subtotal, order.discount_total, order.total, order.payment_arrangement,
        order.payment_status, order.amount_paid, order.balance_due, ", ".join(methods),
        order.received_at, ready_at, picked_at, disposed,
    ]


def item_row(order, item):
    return [
        order.reference, order.created_at, item.item_type, item.name, item.quantity, item.unit,
        item.unit_price, item.line_total, item.customer_supplied,
    ]


def payment_row(payment, reference):
    return [
        payment.id, reference, payment.kind, payment.method_label, payment.amount,
        payment.paid_at, payment.reference,
    ]


# --------------------------------------------------------------------------- queries
def _bounds(start, end):
    return local_day_bounds_utc(start)[0], local_day_bounds_utc(end)[1]


def _order_query(start_utc, end_utc):
    return db.select(Order).where(Order.created_at >= start_utc, Order.created_at < end_utc)


def count_rows(dataset, start, end):
    start_utc, end_utc = _bounds(start, end)
    if dataset == "payments":
        stmt = db.select(db.func.count(Payment.id)).where(Payment.paid_at >= start_utc, Payment.paid_at < end_utc)
    elif dataset == "items":
        from app.models import OrderItem
        stmt = (db.select(db.func.count(OrderItem.id)).join(Order, Order.id == OrderItem.order_id)
                .where(Order.created_at >= start_utc, Order.created_at < end_utc))
    else:
        stmt = db.select(db.func.count(Order.id)).where(Order.created_at >= start_utc, Order.created_at < end_utc)
    return db.session.scalar(stmt) or 0


def _lifecycle(order_ids):
    """{order_id: ready_at/picked_at} and the set of disposed order ids for these orders."""
    ready, picked = {}, {}
    if not order_ids:
        return ready, picked, set()
    rows = db.session.execute(
        db.select(OrderStatusHistory.order_id, OrderStatusHistory.to_status, db.func.min(OrderStatusHistory.created_at))
        .where(OrderStatusHistory.order_id.in_(order_ids),
               OrderStatusHistory.to_status.in_((OrderStatus.READY, OrderStatus.RELEASED, OrderStatus.COMPLETED)))
        .group_by(OrderStatusHistory.order_id, OrderStatusHistory.to_status)
    ).all()
    for order_id, status, moment in rows:
        target = ready if status == OrderStatus.READY else picked
        if order_id not in target or moment < target[order_id]:
            target[order_id] = moment
    disposed = set(db.session.scalars(db.select(OrderDisposal.order_id).where(OrderDisposal.order_id.in_(order_ids))))
    return ready, picked, disposed


def iter_rows(dataset, start, end, chunk=500):
    """Yield the header row, then the data rows, read from the database as it is right now.

    Rows are read in small batches (never an open streaming cursor), so other queries can run
    safely in between on MySQL / TiDB.
    """
    start_utc, end_utc = _bounds(start, end)
    if dataset == "payments":
        yield PAYMENT_HEADERS
        rows = db.session.execute(
            db.select(Payment, Order.reference).join(Order, Order.id == Payment.order_id)
            .where(Payment.paid_at >= start_utc, Payment.paid_at < end_utc)
            .order_by(Payment.paid_at, Payment.id)
        ).all()
        for payment, reference in rows:
            yield payment_row(payment, reference)
        return

    yield ITEM_HEADERS if dataset == "items" else ORDER_HEADERS
    ids = db.session.scalars(
        _order_query(start_utc, end_utc).with_only_columns(Order.id).order_by(Order.created_at, Order.id)
    ).all()
    for offset in range(0, len(ids), chunk):
        batch_ids = ids[offset:offset + chunk]
        orders = db.session.scalars(
            db.select(Order).where(Order.id.in_(batch_ids))
            .options(selectinload(Order.items), selectinload(Order.payments))
        ).all()
        position = {order_id: n for n, order_id in enumerate(batch_ids)}
        orders.sort(key=lambda o: position[o.id])
        if dataset == "items":
            for order in orders:
                for item in order.items:
                    yield item_row(order, item)
        else:
            ready, picked, disposed = _lifecycle(batch_ids)
            for order in orders:
                yield order_row(order, ready.get(order.id), picked.get(order.id), order.id in disposed)


def csv_stream(dataset, start, end):
    """Yield the file in small pieces. Starts with a UTF-8 BOM so Excel shows peso signs/names correctly."""
    yield "\ufeff"
    for row in iter_rows(dataset, start, end):
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="\r\n").writerow([cell(v) for v in row])
        yield buffer.getvalue()
