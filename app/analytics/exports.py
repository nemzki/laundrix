"""CSV and Excel exports of real Laundrix records (admin only).

What the admin can customise
    * the file format (CSV or Excel .xlsx),
    * the date range,
    * the filters (order status, payment status, item type, payment kind),
    * which columns are included (e.g. only name, id, date and status).

Privacy: customer phone numbers are deliberately NOT exported. Customers are identified by name
and customer ID. Every text cell is neutralised against spreadsheet formula injection.

Adding a new column later = add ONE Column(...) line to the right list in COLUMNS below.
The export form, the CSV, the Excel file and the validation all pick it up automatically.
"""
import csv
import io
from collections import namedtuple
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Callable

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import selectinload

from app.core.timeutil import SHOP_TZ, local_day_bounds_utc, to_local
from app.extensions import db
from app.models import (
    Order,
    OrderDisposal,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    Payment,
    PaymentKind,
    PaymentStatus,
)

MAX_ROWS = 20000
MAX_RANGE_DAYS = 366
DATASETS = {
    "orders": "Orders (one row per order)",
    "items": "Order items / services (one row per line)",
    "payments": "Payments (one row per payment or reversal)",
}
FORMATS = {"csv": "CSV", "xlsx": "Excel"}
XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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


def _clean_text(value):
    """Plain single-line text with control characters removed."""
    text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return "".join(ch for ch in text if ch >= " " and ch != "\x7f").strip()


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
    text = _clean_text(value)
    return "'" + text if text.startswith(_DANGEROUS) else text


# =========================================================================== column registry
# kind decides how Excel stores/format the value:
#   text | int | number | money | datetime | date | bool
@dataclass(frozen=True)
class Column:
    key: str                  # stable id used in the URL (?columns=reference)
    label: str                # header text in the file and the checkbox label in the form
    getter: Callable          # row context -> raw value
    kind: str = "text"
    group: str = "Other"      # heading the checkbox is shown under
    default: bool = True      # ticked by default in the form / used when no columns are chosen
    width: int = 0            # Excel column width (0 = pick one from kind)


# What each row builder hands to the getters.
OrderCtx = namedtuple("OrderCtx", "order ready_at picked_at disposed")
ItemCtx = namedtuple("ItemCtx", "order item")
PaymentCtx = namedtuple("PaymentCtx", "payment reference")


def _payment_methods(order):
    return ", ".join(sorted({p.method_label for p in order.payments if p.kind == PaymentKind.PAYMENT}))


COLUMNS = {
    "orders": [
        Column("reference", "Order Reference", lambda c: c.order.reference, group="Order", width=18),
        Column("order_id", "Order ID", lambda c: c.order.id, "int", "Order", default=False),
        Column("created_at", "Created At", lambda c: c.order.created_at, "datetime", "Order"),
        Column("customer_name", "Customer Name", lambda c: c.order.customer_name, group="Customer", width=28),
        Column("customer_id", "Customer ID", lambda c: c.order.customer_id, "int", "Customer"),
        Column("status", "Status", lambda c: OrderStatus.LABELS.get(c.order.status, c.order.status),
               group="Order", width=22),
        Column("services", "Services", lambda c: "; ".join(i.name for i in c.order.items),
               group="Order", width=40),
        Column("subtotal", "Subtotal", lambda c: c.order.subtotal, "money", "Amounts"),
        Column("discount_total", "Discount", lambda c: c.order.discount_total, "money", "Amounts"),
        Column("total", "Total", lambda c: c.order.total, "money", "Amounts"),
        Column("payment_arrangement", "Payment Arrangement", lambda c: c.order.payment_arrangement,
               group="Payment", width=20),
        Column("payment_status", "Payment Status",
               lambda c: PaymentStatus.LABELS.get(c.order.payment_status, c.order.payment_status),
               group="Payment", width=20),
        Column("amount_paid", "Amount Paid", lambda c: c.order.amount_paid, "money", "Payment"),
        Column("balance_due", "Balance Due", lambda c: c.order.balance_due, "money", "Payment"),
        Column("payment_methods", "Payment Methods", lambda c: _payment_methods(c.order),
               group="Payment", width=22),
        Column("received_at", "Laundry Received At", lambda c: c.order.received_at, "datetime", "Timeline"),
        Column("ready_at", "Ready For Pickup At", lambda c: c.ready_at, "datetime", "Timeline"),
        Column("picked_at", "Picked Up At", lambda c: c.picked_at, "datetime", "Timeline"),
        Column("disposed", "Marked Disposed", lambda c: c.disposed, "bool", "Timeline"),
    ],
    "items": [
        Column("reference", "Order Reference", lambda c: c.order.reference, group="Order", width=18),
        Column("order_created_at", "Order Created At", lambda c: c.order.created_at, "datetime", "Order"),
        Column("customer_name", "Customer Name", lambda c: c.order.customer_name,
               group="Order", default=False, width=28),
        Column("order_status", "Order Status", lambda c: OrderStatus.LABELS.get(c.order.status, c.order.status),
               group="Order", default=False, width=22),
        Column("item_type", "Item Type", lambda c: c.item.item_type, group="Item", width=12),
        Column("item_name", "Item Name", lambda c: c.item.name, group="Item", width=32),
        Column("quantity", "Quantity", lambda c: c.item.quantity, "number", "Item"),
        Column("unit", "Unit", lambda c: c.item.unit, group="Item", width=10),
        Column("unit_price", "Unit Price", lambda c: c.item.unit_price, "money", "Amounts"),
        Column("line_total", "Line Total", lambda c: c.item.line_total, "money", "Amounts"),
        Column("customer_supplied", "Customer Supplied", lambda c: c.item.customer_supplied, "bool", "Item"),
    ],
    "payments": [
        Column("payment_id", "Payment ID", lambda c: c.payment.id, "int", "Payment"),
        Column("reference", "Order Reference", lambda c: c.reference, group="Payment", width=18),
        Column("kind", "Type", lambda c: c.payment.kind, group="Payment", width=12),
        Column("method", "Method", lambda c: c.payment.method_label, group="Payment", width=18),
        Column("amount", "Amount", lambda c: c.payment.amount, "money", "Payment"),
        Column("paid_at", "Paid At", lambda c: c.payment.paid_at, "datetime", "Payment"),
        Column("payment_reference", "Reference No.", lambda c: c.payment.reference, group="Payment", width=22),
    ],
}

# One-click column sets shown as buttons in the form. Keys must exist in COLUMNS.
PRESETS = {
    "orders": [
        ("basic", "Basic (name, ID, date, status)",
         ["reference", "created_at", "customer_name", "customer_id", "status"]),
        ("money", "Money summary",
         ["reference", "created_at", "customer_name", "status", "total", "amount_paid", "balance_due",
          "payment_status"]),
        ("timeline", "Timeline",
         ["reference", "customer_name", "status", "created_at", "received_at", "ready_at", "picked_at"]),
    ],
    "items": [
        ("basic", "Basic (order, item, qty, total)", ["reference", "item_name", "quantity", "line_total"]),
    ],
    "payments": [
        ("basic", "Basic (order, method, amount, date)", ["reference", "method", "amount", "paid_at"]),
    ],
}

# Filters per dataset. "status" works on all three (it is the ORDER's status).
STATUS_OPTIONS = [(s, OrderStatus.LABELS[s]) for s in OrderStatus.FLOW]
FILTERS = {
    "status": ("Order status", STATUS_OPTIONS),
    "payment_status": ("Payment status", [
        (PaymentStatus.UNPAID, "Unpaid"), (PaymentStatus.PARTIAL, "Partially Paid"),
        (PaymentStatus.PAID, "Paid"), (PaymentStatus.NOT_TRACKED, "Payment not tracked")]),
    "item_type": ("Item type", [("service", "Service"), ("package", "Package"), ("addon", "Add-on")]),
    "kind": ("Payment type", [(PaymentKind.PAYMENT, "Payment"), (PaymentKind.REVERSAL, "Reversal")]),
}
DATASET_FILTERS = {
    "orders": ("status", "payment_status"),
    "items": ("status", "item_type"),
    "payments": ("status", "kind"),
}


def ui_config():
    """Everything the export form needs, as plain data (rendered by the template, read by the JS)."""
    out = {}
    for dataset, label in DATASETS.items():
        groups = {}                              # group name -> columns, in first-seen order
        for col in COLUMNS[dataset]:
            groups.setdefault(col.group, []).append(
                {"key": col.key, "label": col.label, "default": col.default})
        out[dataset] = {
            "label": label,
            "groups": [{"name": name, "columns": cols} for name, cols in groups.items()],
            "defaults": [c.key for c in COLUMNS[dataset] if c.default],
            "all": [c.key for c in COLUMNS[dataset]],
            "presets": [{"id": pid, "label": plabel, "columns": keys} for pid, plabel, keys in PRESETS[dataset]],
            "filters": [{"name": n, "label": FILTERS[n][0],
                         "options": [{"value": v, "label": l} for v, l in FILTERS[n][1]]}
                        for n in DATASET_FILTERS[dataset]],
        }
    return out


# =========================================================================== request parsing
@dataclass(frozen=True)
class Filters:
    status: tuple = ()
    payment_status: tuple = ()
    item_type: tuple = ()
    kind: tuple = ()

    def describe(self):
        """Short human text such as 'Order status: Ready for Pickup; Payment status: Unpaid'."""
        parts = []
        for name in FILTERS:
            values = getattr(self, name)
            if values:
                labels = dict(FILTERS[name][1])
                parts.append(f"{FILTERS[name][0]}: {', '.join(labels[v] for v in values)}")
        return "; ".join(parts)


def resolve_columns(dataset, keys=None):
    """Turn requested column keys into Column objects, in the standard file order.

    keys=None means 'no choice made' -> the default columns. Unknown keys are rejected.
    """
    available = COLUMNS[dataset]
    if keys is None:
        return [c for c in available if c.default]
    wanted = set(keys)
    unknown = wanted - {c.key for c in available}
    if unknown:
        raise ExportError("Unknown column: " + ", ".join(sorted(unknown)) + ".")
    chosen = [c for c in available if c.key in wanted]
    if not chosen:
        raise ExportError("Please tick at least one column to export.")
    return chosen


def parse_filters(dataset, getlist):
    """Read and validate the filter values. getlist is e.g. request.args.getlist."""
    values = {}
    for name in DATASET_FILTERS[dataset]:
        allowed = {v for v, _ in FILTERS[name][1]}
        picked = [v for v in getlist(name) if v != ""]
        bad = [v for v in picked if v not in allowed]
        if bad:
            raise ExportError(f"Invalid {FILTERS[name][0].lower()} filter.")
        # Ticking everything is the same as no filter.
        # Ticking every option is the same as no filter; keep display order so output is predictable.
        values[name] = () if set(picked) == allowed else tuple(v for v, _ in FILTERS[name][1] if v in picked)
    return Filters(**values)


def parse_format(raw):
    """'csv' (default) or 'xlsx'."""
    fmt = (raw or "csv").lower()
    if fmt not in FORMATS:
        raise ExportError("Choose CSV or Excel as the file format.")
    return fmt


# =========================================================================== queries
def _bounds(start, end):
    """Turn a start day and end day into UTC start/end datetimes that cover both whole days."""
    return local_day_bounds_utc(start)[0], local_day_bounds_utc(end)[1]


def _net_paid():
    """SQL twin of Order.amount_paid: payments minus reversals, per order."""
    signed = case((Payment.kind == PaymentKind.PAYMENT, Payment.amount), else_=-Payment.amount)
    return (db.select(func.coalesce(func.sum(signed), 0))
            .where(Payment.order_id == Order.id).correlate(Order).scalar_subquery())


def _payment_status_condition(values):
    """SQL twin of Order.payment_status, so counts and rows always agree with the filter."""
    net, tracked = _net_paid(), Order.payment_arrangement.is_not(None)
    options = {
        PaymentStatus.PAID: and_(tracked, net >= Order.total),
        PaymentStatus.PARTIAL: and_(tracked, net > 0, net < Order.total),
        PaymentStatus.UNPAID: and_(tracked, net <= 0, net < Order.total),
        PaymentStatus.NOT_TRACKED: Order.payment_arrangement.is_(None),
    }
    return or_(*[options[v] for v in values])


def _order_conditions(dataset, start_utc, end_utc, filters):
    """WHERE conditions on Order shared by the count and the row queries."""
    conds = [Order.created_at >= start_utc, Order.created_at < end_utc]
    if filters.status:
        conds.append(Order.status.in_(filters.status))
    if dataset == "orders" and filters.payment_status:
        conds.append(_payment_status_condition(filters.payment_status))
    if dataset == "items" and filters.item_type:
        conds.append(Order.items.any(OrderItem.item_type.in_(filters.item_type)))
    return conds


def _payment_query(columns, start_utc, end_utc, filters):
    stmt = (db.select(*columns).join(Order, Order.id == Payment.order_id)
            .where(Payment.paid_at >= start_utc, Payment.paid_at < end_utc))
    if filters.status:
        stmt = stmt.where(Order.status.in_(filters.status))
    if filters.kind:
        stmt = stmt.where(Payment.kind.in_(filters.kind))
    return stmt


def count_rows(dataset, start, end, filters=None):
    """Count how many rows an export of 'orders', 'items' or 'payments' would contain."""
    filters = filters or Filters()
    start_utc, end_utc = _bounds(start, end)
    if dataset == "payments":
        stmt = _payment_query([func.count(Payment.id)], start_utc, end_utc, filters)
    elif dataset == "items":
        stmt = (db.select(func.count(OrderItem.id)).join(Order, Order.id == OrderItem.order_id)
                .where(*_order_conditions("items", start_utc, end_utc, filters)))
        if filters.item_type:
            stmt = stmt.where(OrderItem.item_type.in_(filters.item_type))
    else:
        stmt = db.select(func.count(Order.id)).where(*_order_conditions("orders", start_utc, end_utc, filters))
    return db.session.scalar(stmt) or 0


def _lifecycle(order_ids):
    """{order_id: ready_at/picked_at} and the set of disposed order ids for these orders."""
    ready, picked = {}, {}
    if not order_ids:
        return ready, picked, set()
    rows = db.session.execute(
        db.select(OrderStatusHistory.order_id, OrderStatusHistory.to_status, func.min(OrderStatusHistory.created_at))
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


def iter_rows(dataset, start, end, columns=None, filters=None, chunk=500):
    """Yield the header row (labels), then the data rows (raw values), for the chosen columns only.

    Rows are read in small batches (never an open streaming cursor), so other queries can run
    safely in between on MySQL / TiDB.
    """
    columns = columns or resolve_columns(dataset)
    filters = filters or Filters()
    start_utc, end_utc = _bounds(start, end)
    yield [c.label for c in columns]

    def build(ctx):
        return [c.getter(ctx) for c in columns]

    if dataset == "payments":
        rows = db.session.execute(
            _payment_query([Payment, Order.reference], start_utc, end_utc, filters)
            .order_by(Payment.paid_at, Payment.id)
        ).all()
        for payment, reference in rows:
            yield build(PaymentCtx(payment, reference))
        return

    ids = db.session.scalars(
        db.select(Order.id).where(*_order_conditions(dataset, start_utc, end_utc, filters))
        .order_by(Order.created_at, Order.id)
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
                    if filters.item_type and item.item_type not in filters.item_type:
                        continue
                    yield build(ItemCtx(order, item))
        else:
            ready, picked, disposed = _lifecycle(batch_ids)
            for order in orders:
                yield build(OrderCtx(order, ready.get(order.id), picked.get(order.id), order.id in disposed))


# =========================================================================== CSV
def csv_stream(dataset, start, end, columns=None, filters=None):
    """Yield the file in small pieces. Starts with a UTF-8 BOM so Excel shows peso signs/names correctly."""
    yield "\ufeff"
    for row in iter_rows(dataset, start, end, columns, filters):
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="\r\n").writerow([cell(v) for v in row])
        yield buffer.getvalue()


# =========================================================================== Excel
SHEET_NAMES = {"orders": "Orders", "items": "Order items", "payments": "Payments"}
_NUMBER_FORMATS = {
    "money": '"\u20b1"#,##0.00;[Red]-"\u20b1"#,##0.00',
    "number": "#,##0.##",
    "int": "0",
    "datetime": "yyyy-mm-dd hh:mm",
    "date": "yyyy-mm-dd",
}
_DEFAULT_WIDTHS = {"money": 14, "number": 11, "int": 12, "datetime": 18, "date": 12, "bool": 12, "text": 20}


def xlsx_value(value, kind):
    """Convert a raw value into what Excel should store (real numbers and dates, safe text)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return to_local(value).replace(tzinfo=None)      # Excel has no time zones
    if isinstance(value, (date, int, float)):
        return value
    return _clean_text(value)


def xlsx_bytes(dataset, start, end, columns=None, filters=None, generated_by=""):
    """Build the .xlsx file in memory (write-only mode keeps memory small) and return its bytes.

    Sheet 1 holds the data (bold frozen header row, filter arrows, real numbers/dates/peso format).
    Sheet 2 ("Export details") records what was exported, so the file explains itself later.
    """
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    columns = columns or resolve_columns(dataset)
    filters = filters or Filters()
    wb = Workbook(write_only=True)
    ws = wb.create_sheet(SHEET_NAMES[dataset])
    for index, col in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(index)].width = col.width or _DEFAULT_WIDTHS.get(col.kind, 20)
    ws.freeze_panes = "A2"

    def text_cell(value, **style):
        c = WriteOnlyCell(ws, value=value)
        c.data_type = "s"                   # always text -> "=1+1" can never run as a formula
        for attr, val in style.items():
            setattr(c, attr, val)
        return c

    header_style = {"font": Font(bold=True, color="FFFFFF"),
                    "fill": PatternFill("solid", start_color="1F4E79"),
                    "alignment": Alignment(vertical="center", wrap_text=True)}
    rows = iter_rows(dataset, start, end, columns, filters)
    next(rows)                              # header labels are written below, with styling
    ws.append([text_cell(c.label, **header_style) for c in columns])

    count = 0
    for raw in rows:
        out = []
        for col, value in zip(columns, raw):
            value = xlsx_value(value, col.kind)
            if isinstance(value, str):
                out.append(text_cell(value))
            elif value is None:
                out.append(None)
            else:
                c = WriteOnlyCell(ws, value=value)
                if col.kind in _NUMBER_FORMATS:
                    c.number_format = _NUMBER_FORMATS[col.kind]
                out.append(c)
        ws.append(out)
        count += 1
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{count + 1}"

    info = wb.create_sheet("Export details")
    info.column_dimensions["A"].width = 20
    info.column_dimensions["B"].width = 70
    generated = datetime.now(SHOP_TZ).strftime("%Y-%m-%d %H:%M")
    for label, value in (
        ("Records", DATASETS[dataset]),
        ("Date range", f"{start.isoformat()} to {end.isoformat()}"),
        ("Filters", filters.describe() or "None (all records in the date range)"),
        ("Columns", ", ".join(c.label for c in columns)),
        ("Rows exported", count),
        ("Generated", generated + " (Philippine time)"),
        ("Generated by", generated_by or "-"),
        ("Privacy", "Customer phone numbers are never included in exports."),
    ):
        info.append([text_cell(label, font=Font(bold=True)),
                     text_cell(value) if isinstance(value, str) else value])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
