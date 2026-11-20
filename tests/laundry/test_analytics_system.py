"""Analytics & Reports: system-trained model, charts and CSV export.

The test database is an in-memory SQLite that exists only while a test runs. Orders created here
exercise the real code paths; nothing is written to your real database.
Run: pytest tests/laundry/test_analytics_system.py -q
"""
import itertools
from datetime import timedelta
from decimal import Decimal

import pytest

from app.analytics import exports
from app.analytics.charts import get_chart_data, parse_period
from app.analytics.ml.system_data import load_records, shop_today, summarize
from app.extensions import db
from app.models import (
    AuditLog, Customer, HistoricalTransaction, Order, OrderDisposal, OrderItem, OrderStatus,
    OrderStatusHistory, Payment, PaymentMethod, UnclaimedModelRun,
)
from app.models.staff_credential import utcnow

_n = itertools.count(1)
NOT_READY = "Machine learning is not ready. More order records are needed for reliable training."


@pytest.fixture()
def method(app):
    m = PaymentMethod(code="cash", label="Cash")
    db.session.add(m)
    db.session.commit()
    return m


def make_order(*, days_ago, ready_after=1, picked_after=None, disposed=False, paid=False, total=185,
               customer_key=None, status=None, name=None, method=None):
    """One real order row with the history/payment/disposal records the system would have created."""
    n = next(_n)
    key = customer_key if customer_key is not None else n
    customer = db.session.execute(db.select(Customer).filter_by(contact_normalized=f"0917{key:07d}")).scalar_one_or_none()
    if customer is None:
        customer = Customer(full_name=f"Customer {key}", contact_number=f"0917{key:07d}",
                            contact_normalized=f"0917{key:07d}")
        db.session.add(customer)
        db.session.flush()
    created = utcnow() - timedelta(days=days_ago)
    ready = created + timedelta(days=ready_after)
    if status is None:
        status = OrderStatus.RELEASED if picked_after is not None else OrderStatus.READY
    order = Order(reference=f"T{n:06d}", customer_id=customer.id, customer_name=name or customer.full_name,
                  customer_contact=customer.contact_number, status=status, subtotal=Decimal(total),
                  total=Decimal(total), created_at=created, received_at=created, payment_arrangement="full")
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderStatusHistory(order_id=order.id, to_status=OrderStatus.READY, created_at=ready))
    if picked_after is not None:
        db.session.add(OrderStatusHistory(order_id=order.id, from_status=OrderStatus.READY,
                                          to_status=OrderStatus.RELEASED,
                                          created_at=ready + timedelta(days=picked_after)))
    if disposed:
        db.session.add(OrderDisposal(order_id=order.id, disposed_at=ready + timedelta(days=15)))
    if paid and method is not None:
        db.session.add(Payment(order_id=order.id, kind="payment", method_id=method.id, method_code="cash",
                               method_label="Cash", amount=Decimal(total), paid_at=created))
    db.session.commit()
    return order


def seed_history(method, n=120):
    """Mature orders with confirmed outcomes: every 5th was disposed (and unpaid), the rest picked up."""
    for i in range(n):
        disposed = i % 5 == 0
        make_order(days_ago=200 - i, picked_after=None if disposed else 2, disposed=disposed,
                   paid=not disposed, customer_key=i % 25 + 1000, method=method)


def system_runs():
    return db.session.execute(
        db.select(UnclaimedModelRun).filter_by(data_source="system").order_by(UnclaimedModelRun.version)
    ).scalars().all()


# ------------------------------------------------------------------ machine learning
def test_not_ready_with_few_orders(app, admin_client, method):
    for i in range(5):
        make_order(days_ago=60 + i, picked_after=1, paid=True, method=method)
    html = admin_client.get("/admin/analytics/").get_data(as_text=True)
    assert NOT_READY in html
    assert "Not ready" in html
    assert system_runs() == []


def test_trains_automatically_when_enough_confirmed_orders(app, admin_client, method):
    seed_history(method)
    make_order(days_ago=3, method=method)                      # a waiting order to score
    html = admin_client.get("/admin/analytics/").get_data(as_text=True)
    runs = system_runs()
    assert len(runs) == 1 and runs[0].is_active
    assert runs[0].n_orders == 120 and runs[0].n_disposed == 24 and runs[0].labels_simulated is False
    assert "Trained" in html and "<th>Risk</th>" in html
    admin_client.get("/admin/analytics/")                      # no new data -> no retraining
    assert len(system_runs()) == 1


def test_retrains_after_enough_new_outcomes(app, admin_client, method):
    seed_history(method)
    admin_client.get("/admin/analytics/")
    for i in range(10):
        disposed = i % 5 == 0
        make_order(days_ago=40 - i, picked_after=None if disposed else 2, disposed=disposed,
                   paid=not disposed, customer_key=i + 2000, method=method)
    admin_client.get("/admin/analytics/")
    runs = system_runs()
    assert [r.version for r in runs] == [1, 2]
    assert [r.is_active for r in runs] == [False, True]


def test_unconfirmed_orders_are_never_training_labels(app, admin_client, method):
    seed_history(method)
    for _ in range(15):                                         # waiting 60 days, nothing recorded
        make_order(days_ago=60, method=method)
    html = admin_client.get("/admin/analytics/").get_data(as_text=True)
    assert system_runs()[0].n_orders == 120
    assert "waited more than 14 days with no outcome recorded" in html


def test_imported_history_is_ignored(app, admin_client, method):
    for i in range(150):
        db.session.add(HistoricalTransaction(
            transaction_date=utcnow().date() - timedelta(days=200 - i), source_transaction_no=1,
            total_amount=185, import_source="x", source_row_key=f"k{i}",
            ready_date=utcnow().date() - timedelta(days=199 - i),
            outcome_status="disposed" if i % 4 == 0 else "claimed", status_source="simulated",
        ))
    db.session.commit()
    html = admin_client.get("/admin/analytics/").get_data(as_text=True)
    assert NOT_READY in html and system_runs() == []


def test_unreliable_model_is_not_used(app, admin_client, method):
    # identical inputs for every order, so nothing can be learned: the model must not be used
    monday = shop_today() - timedelta(days=shop_today().weekday() + 7 * 30)
    for i in range(120):
        disposed = i % 5 == 0
        created = monday - timedelta(weeks=120 - i)
        make_order(days_ago=(shop_today() - created).days, picked_after=None if disposed else 2,
                   disposed=disposed, customer_key=5000 + i, method=method)
    make_order(days_ago=2, method=method)
    html = admin_client.get("/admin/analytics/").get_data(as_text=True)
    assert system_runs() == []
    assert "Not reliable yet" in html and "<th>Risk</th>" not in html


def test_payment_after_ready_is_not_a_feature(app, method):
    seed_history(method, n=3)
    records, today = load_records()
    claimed = [r for r in records if r["outcome"] == "claimed"][0]
    assert claimed["features"][1] == 1.0                        # paid at creation, before ready
    late = make_order(days_ago=100, picked_after=2, method=None)
    db.session.add(Payment(order_id=late.id, kind="payment", method_id=method.id, method_code="cash",
                           method_label="Cash", amount=Decimal("185"), paid_at=utcnow() - timedelta(days=95)))
    db.session.commit()
    rec = [r for r in load_records()[0] if r["id"] == late.id][0]
    assert rec["features"][1] == 0.0                            # money arrived after it was ready


def test_summary_counts_only_mature_confirmed_orders(app, method):
    make_order(days_ago=60, picked_after=1, paid=True, method=method)      # claimed, mature
    make_order(days_ago=60, disposed=True, method=method)                  # disposed, mature
    make_order(days_ago=3, picked_after=1, paid=True, method=method)       # claimed but too recent
    make_order(days_ago=60, method=method)                                 # unresolved
    records, today = load_records()
    info = summarize(records, today)
    assert (info["labelled"], info["claimed"], info["disposed"], info["overdue_unresolved"]) == (2, 1, 1, 1)
    assert not info["enough"]


# ------------------------------------------------------------------ disposal action
def test_mark_disposed_and_undo(app, admin_client, staff_client, method):
    order = make_order(days_ago=3, method=method)
    assert staff_client.post(f"/admin/analytics/orders/{order.id}/dispose").status_code == 403
    assert admin_client.post(f"/admin/analytics/orders/{order.id}/dispose").status_code == 302
    assert db.session.scalar(db.select(db.func.count(OrderDisposal.id))) == 1
    assert db.session.get(Order, order.id).status == OrderStatus.READY       # Orders pages unchanged
    admin_client.post(f"/admin/analytics/orders/{order.id}/dispose")          # double click is harmless
    assert db.session.scalar(db.select(db.func.count(OrderDisposal.id))) == 1
    assert admin_client.post(f"/admin/analytics/orders/{order.id}/undo-dispose").status_code == 302
    assert db.session.scalar(db.select(db.func.count(OrderDisposal.id))) == 0


def test_only_ready_orders_can_be_marked_disposed(app, admin_client, method):
    order = make_order(days_ago=30, picked_after=1, method=method)
    admin_client.post(f"/admin/analytics/orders/{order.id}/dispose")
    assert db.session.scalar(db.select(db.func.count(OrderDisposal.id))) == 0


# ------------------------------------------------------------------ charts
def test_chart_numbers_come_from_real_orders(app, method):
    for _ in range(2):
        o = make_order(days_ago=0, paid=True, method=method, total=200)
        db.session.add(OrderItem(order_id=o.id, item_type="service", name="Wash", quantity=1, unit="load",
                                 unit_price=200, line_total=200))
    db.session.commit()
    data = get_chart_data(7)
    assert data["summary"]["orders"] == 2 and data["summary"]["revenue"] == Decimal("400.00")
    assert data["summary"]["avg_order"] == Decimal("200.00")
    assert data["services"]["labels"] == ["Wash"] and data["services"]["values"] == [2]
    assert sum(data["status"]["values"]) == 2 and len(data["orders"]["labels"]) == 7


def test_unknown_period_falls_back_to_default():
    assert [parse_period(x) for x in ("7", "30", "90", "5", "abc", None)] == [7, 30, 90, 30, 30, 30]


def test_page_renders_with_no_data(app, admin_client):
    html = admin_client.get("/admin/analytics/?days=90").get_data(as_text=True)
    assert "No orders in this period." in html and NOT_READY in html


# ------------------------------------------------------------------ CSV export
def _export(client, **params):
    today = shop_today()
    query = {"dataset": "orders", "start": (today - timedelta(days=1)).isoformat(),
             "end": (today + timedelta(days=1)).isoformat(), **params}
    return client.get("/admin/analytics/export", query_string=query)


def test_orders_csv_is_excel_friendly_and_has_no_phone_numbers(app, admin_client, method):
    order = make_order(days_ago=0, paid=True, method=method, name="Ana Cruz")
    db.session.add(OrderItem(order_id=order.id, item_type="service", name="Wash", quantity=2, unit="load",
                             unit_price=80, line_total=160))
    db.session.commit()
    resp = _export(admin_client)
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("text/csv")
    assert "attachment" in resp.headers["Content-Disposition"] and "no-store" in resp.headers["Cache-Control"]
    text = resp.get_data().decode("utf-8")
    assert text.startswith("\ufeffOrder Reference,Created At,Customer Name")
    assert order.reference in text and "Ana Cruz" in text and "paid" in text.lower()
    assert "\r\n" in text and "09170000" not in text        # customer phone numbers are not exported


def test_items_and_payments_csv(app, admin_client, method):
    order = make_order(days_ago=0, paid=True, method=method)
    db.session.add(OrderItem(order_id=order.id, item_type="service", name="Fold", quantity=3, unit="kg",
                             unit_price=20, line_total=60))
    db.session.commit()
    items = _export(admin_client, dataset="items").get_data(as_text=True)
    assert "Item Name" in items and "Fold" in items
    pays = _export(admin_client, dataset="payments").get_data(as_text=True)
    assert "Payment ID" in pays and order.reference in pays and "Cash" in pays


def test_csv_neutralises_spreadsheet_formulas(app, admin_client, method):
    make_order(days_ago=0, name="=HYPERLINK(\"http://evil\")", method=method)
    text = _export(admin_client).get_data(as_text=True)
    assert "'=HYPERLINK" in text and ",=HYPERLINK" not in text


def test_export_is_admin_only_and_audited(app, admin_client, staff_client, anon_client, method):
    make_order(days_ago=0, method=method)
    assert _export(staff_client).status_code == 403
    assert _export(anon_client).status_code in (302, 401)
    assert _export(admin_client).status_code == 200
    log = db.session.execute(db.select(AuditLog).filter_by(action="export")).scalars().all()
    assert len(log) == 1 and "orders CSV" in log[0].description


def test_export_validation(app, admin_client, method):
    make_order(days_ago=0, method=method)
    assert _export(admin_client, dataset="users").status_code == 404
    assert _export(admin_client, start="nope").status_code == 302
    assert _export(admin_client, start="2026-12-31", end="2026-01-01").status_code == 302
    assert _export(admin_client, start="2020-01-01", end="2026-01-01").status_code == 302
    far = (shop_today() - timedelta(days=1000)).isoformat()
    assert _export(admin_client, start=far, end=far).status_code == 302      # empty range -> message


def test_cell_and_range_helpers():
    assert exports.cell("=1+1") == "'=1+1" and exports.cell("-5") == "'-5" and exports.cell("@x") == "'@x"
    assert exports.cell("a\nb") == "a b" and exports.cell(None) == "" and exports.cell(Decimal("185")) == "185.00"
    assert exports.cell(Decimal("-5")) == "-5.00" and exports.cell(True) == "Yes"
    today = shop_today()
    assert exports.parse_range(None, None, today) == (today - timedelta(days=29), today)
    with pytest.raises(exports.ExportError):
        exports.parse_range("2026-02-01", "2026-01-01", today)
