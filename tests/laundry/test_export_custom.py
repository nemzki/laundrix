"""Custom exports: Excel files, column picking and filters.

Uses the same in-memory SQLite test database as test_analytics_system.py.
Run: pytest tests/laundry/test_export_custom.py -q
"""
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from app.analytics import exports
from app.analytics.ml.system_data import shop_today
from app.extensions import db
from app.models import AuditLog, OrderItem, OrderStatus, Payment
from app.models.staff_credential import utcnow
from tests.laundry.test_analytics_system import _export, make_order, method  # noqa: F401  (method = fixture)


def _sheet(resp):
    """Open a downloaded .xlsx response and return its first (data) sheet as a list of row tuples."""
    wb = load_workbook(io.BytesIO(resp.get_data()))
    return wb, list(wb.worksheets[0].iter_rows(values_only=True))


def _csv_header(resp):
    return resp.get_data(as_text=True).lstrip("\ufeff").splitlines()[0]


# ------------------------------------------------------------------ Excel
def test_excel_export_has_real_numbers_dates_and_a_details_sheet(app, admin_client, method):
    order = make_order(days_ago=0, paid=True, method=method, name="Ana Cruz", total=185)
    resp = _export(admin_client, format="xlsx")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith(exports.XLSX_MIMETYPE)
    assert ".xlsx" in resp.headers["Content-Disposition"] and "no-store" in resp.headers["Cache-Control"]

    wb, rows = _sheet(resp)
    assert wb.sheetnames == ["Orders", "Export details"]
    header, first = rows[0], rows[1]
    assert header[:3] == ("Order Reference", "Created At", "Customer Name")
    assert first[0] == order.reference and first[2] == "Ana Cruz"
    total_col = header.index("Total")
    assert first[total_col] == 185                       # a number, not the text "185.00"
    assert hasattr(first[1], "year")                     # a real date/time, not text
    assert "09170000" not in str(rows)                   # still no phone numbers


def test_excel_export_is_audited_as_excel(app, admin_client, method):
    make_order(days_ago=0, method=method)
    assert _export(admin_client, format="xlsx").status_code == 200
    log = db.session.execute(db.select(AuditLog).filter_by(action="export")).scalars().all()
    assert len(log) == 1 and "orders Excel" in log[0].description


def test_excel_neutralises_formulas(app, admin_client, method):
    make_order(days_ago=0, name='=HYPERLINK("http://evil")', method=method)
    wb, _ = _sheet(_export(admin_client, format="xlsx"))
    cell = next(c for row in wb.worksheets[0].iter_rows(min_row=2) for c in row if str(c.value).startswith("="))
    assert cell.data_type == "s"                         # stored as text, so Excel never runs it


def test_unknown_format_is_rejected(app, admin_client, method):
    make_order(days_ago=0, method=method)
    assert _export(admin_client, format="pdf").status_code == 302


# ------------------------------------------------------------------ column picking
def test_only_the_chosen_columns_are_exported(app, admin_client, method):
    make_order(days_ago=0, method=method)
    picked = ["customer_name", "reference", "status", "created_at", "customer_id"]    # any order
    resp = _export(admin_client, columns=picked, custom="1")
    assert _csv_header(resp) == "Order Reference,Created At,Customer Name,Customer ID,Status"
    assert "Total" not in resp.get_data(as_text=True)

    _wb, rows = _sheet(_export(admin_client, columns=picked, custom="1", format="xlsx"))
    assert rows[0] == ("Order Reference", "Created At", "Customer Name", "Customer ID", "Status")


def test_extra_columns_can_be_added(app, admin_client, method):
    make_order(days_ago=0, method=method)
    resp = _export(admin_client, columns=["order_id", "reference"], custom="1")
    assert _csv_header(resp) == "Order Reference,Order ID"


def test_no_columns_ticked_or_unknown_column_is_rejected(app, admin_client, method):
    make_order(days_ago=0, method=method)
    assert _export(admin_client, custom="1").status_code == 302                       # form used, nothing ticked
    assert _export(admin_client, columns=["nope"], custom="1").status_code == 302
    assert _export(admin_client, columns=["customer_contact"], custom="1").status_code == 302   # phone never exportable


def test_old_links_without_columns_still_export_the_standard_set(app, admin_client, method):
    make_order(days_ago=0, method=method)
    assert _csv_header(_export(admin_client)).startswith("Order Reference,Created At,Customer Name")


# ------------------------------------------------------------------ filters
def test_status_filter(app, admin_client, method):
    ready = make_order(days_ago=0, method=method)                                   # Ready for Pickup
    done = make_order(days_ago=0, picked_after=1, method=method)                    # Picked Up
    text = _export(admin_client, status=[OrderStatus.READY]).get_data(as_text=True)
    assert ready.reference in text and done.reference not in text
    both = _export(admin_client, status=[OrderStatus.READY, OrderStatus.RELEASED]).get_data(as_text=True)
    assert ready.reference in both and done.reference in both


def test_payment_status_filter_matches_the_order_property(app, admin_client, method):
    paid = make_order(days_ago=0, paid=True, method=method, total=100)
    unpaid = make_order(days_ago=0, paid=False, method=method, total=100)
    partial = make_order(days_ago=0, paid=False, method=method, total=100)
    db.session.add(Payment(order_id=partial.id, kind="payment", method_id=method.id, method_code="cash",
                           method_label="Cash", amount=Decimal("40"), paid_at=utcnow()))
    db.session.commit()
    assert (paid.payment_status, unpaid.payment_status, partial.payment_status) == ("paid", "unpaid", "partial")

    def refs(*statuses):
        text = _export(admin_client, payment_status=list(statuses)).get_data(as_text=True)
        return {o.reference for o in (paid, unpaid, partial) if o.reference in text}

    assert refs("paid") == {paid.reference}
    assert refs("unpaid") == {unpaid.reference}
    assert refs("partial") == {partial.reference}
    assert refs("unpaid", "partial") == {unpaid.reference, partial.reference}


def test_item_type_filter(app, admin_client, method):
    order = make_order(days_ago=0, method=method)
    db.session.add_all([
        OrderItem(order_id=order.id, item_type="service", name="Wash", quantity=1, unit="load", unit_price=80, line_total=80),
        OrderItem(order_id=order.id, item_type="addon", name="Fabcon", quantity=1, unit="pc", unit_price=10, line_total=10),
    ])
    db.session.commit()
    text = _export(admin_client, dataset="items", item_type=["addon"]).get_data(as_text=True)
    assert "Fabcon" in text and "Wash" not in text


def test_payment_kind_filter(app, admin_client, method):
    order = make_order(days_ago=0, paid=True, method=method)
    original = db.session.execute(db.select(Payment).filter_by(order_id=order.id)).scalar_one()
    db.session.add(Payment(order_id=order.id, kind="reversal", reverses_payment_id=original.id,  # a reversal must point at the payment it cancels
                           method_id=method.id, method_code="cash", method_label="Cash",
                           amount=Decimal("10"), paid_at=utcnow()))
    db.session.commit()
    rows = _export(admin_client, dataset="payments", kind=["reversal"]).get_data(as_text=True).splitlines()
    assert len(rows) == 2 and ",reversal," in rows[1]


def test_filters_with_no_matches_show_a_message_not_an_empty_file(app, admin_client, method):
    make_order(days_ago=0, method=method)                       # Ready for Pickup only
    assert _export(admin_client, status=[OrderStatus.COMPLETED]).status_code == 302
    assert _export(admin_client, status=["bogus"]).status_code == 302


# ------------------------------------------------------------------ live preview
def test_preview_counts_rows_and_is_admin_only(app, admin_client, staff_client, anon_client, method):
    make_order(days_ago=0, method=method)
    make_order(days_ago=0, picked_after=1, method=method)
    today = shop_today()
    query = {"start": (today - timedelta(days=1)).isoformat(), "end": (today + timedelta(days=1)).isoformat()}

    resp = admin_client.get("/admin/analytics/export/preview", query_string={**query, "dataset": "orders"})
    assert resp.get_json() == {"ok": True, "rows": 2, "limit": exports.MAX_ROWS, "too_many": False}
    resp = admin_client.get("/admin/analytics/export/preview",
                            query_string={**query, "dataset": "orders", "status": [OrderStatus.READY]})
    assert resp.get_json()["rows"] == 1
    bad = admin_client.get("/admin/analytics/export/preview", query_string={**query, "status": ["bogus"]})
    assert bad.status_code == 400 and bad.get_json()["ok"] is False

    assert staff_client.get("/admin/analytics/export/preview", query_string=query).status_code == 403
    assert anon_client.get("/admin/analytics/export/preview", query_string=query).status_code in (302, 401)


# ------------------------------------------------------------------ registry sanity (no database needed)
def test_registry_is_consistent():
    for dataset, presets in exports.PRESETS.items():
        keys = [c.key for c in exports.COLUMNS[dataset]]
        assert len(keys) == len(set(keys))
        for _pid, _label, preset_keys in presets:
            assert set(preset_keys) <= set(keys)
    assert not any("contact" in c.key or "phone" in c.key for cols in exports.COLUMNS.values() for c in cols)


def test_xlsx_value_conversion():
    assert exports.xlsx_value(Decimal("12.50"), "money") == 12.5
    assert exports.xlsx_value(True, "bool") == "Yes" and exports.xlsx_value(None, "text") is None
    assert exports.xlsx_value("a\nb", "text") == "a b"
