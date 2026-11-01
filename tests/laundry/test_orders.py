import re
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import (
    Customer, Order, OrderItem, OrderStatus, OrderStatusHistory, ServiceAddon, ServicePackage,
)
from config import TestingConfig
from tests.laundry.conftest import NEW_CUSTOMER, _login, _make_app, svc

REF_RE = re.compile(r"^LX-\d{6}-[A-HJ-NP-Z2-9]{5}$")


def payload(**over):
    p = {
        "items": [{"kind": "service", "id": svc("wash").id, "quantity": "2"}],
        "extras": [],
        "customer": NEW_CUSTOMER,
    }
    p.update(over)
    return p


def place(client, **over):
    return client.post("/orders/new/confirm", json=payload(**over))


def order_by(ref):
    return db.session.execute(db.select(Order).filter_by(reference=ref)).scalar_one()


def ref_from(resp):
    return resp.get_json()["redirect"].split("/")[2]


# ----------------------------------------------------------------------------- access
def test_orders_require_login(anon_client):
    for url in ("/orders/", "/orders/new", "/orders/LX-1", "/dashboard/"):
        r = anon_client.get(url)
        assert r.status_code == 302 and "/auth/login" in r.headers["Location"], url
    assert anon_client.post("/orders/new/confirm", json={}).status_code == 302


def test_customers_page_is_admin_only(admin_client, staff_client, catalog):
    assert admin_client.get("/orders/customers").status_code == 200
    assert staff_client.get("/orders/customers").status_code == 403


# ----------------------------------------------------------------------------- creation
def test_staff_creates_order_with_server_side_totals(staff_client, staff, catalog):
    fabcon = db.session.execute(db.select(ServiceAddon).filter_by(code="fabcon")).scalar_one()
    r = place(staff_client,
              extras=[{"id": fabcon.id, "mode": "paid", "quantity": "2"}],
              items=[{"kind": "service", "id": svc("wash").id, "quantity": "2", "instructions": "Cold wash", "price": "0.01"}],
              total="1.00")
    assert r.status_code == 200 and r.get_json()["ok"]
    order = order_by(ref_from(r))
    assert REF_RE.match(order.reference)
    assert order.total == Decimal("190.00") and order.subtotal == Decimal("190.00")  # 2 x 80 + 2 x 15
    assert order.status == OrderStatus.RECEIVED and order.created_by_id == staff.id
    assert order.customer_name == "Ana Cruz"
    names = [(i.name, i.unit_price, i.line_total) for i in order.items]
    assert names == [("Wash", Decimal("80.00"), Decimal("160.00")), ("Fabcon", Decimal("15.00"), Decimal("30.00"))]
    assert order.items[0].instructions == "Cold wash"
    assert [h.to_status for h in order.history] == [OrderStatus.RECEIVED]
    assert order.history[0].changed_by_id == staff.id


def test_confirmation_and_stub_pages_render(staff_client, catalog):
    ref = ref_from(place(staff_client))
    assert ref in staff_client.get(f"/orders/{ref}/confirmation").get_data(as_text=True)
    stub = staff_client.get(f"/orders/{ref}/stub").get_data(as_text=True)
    assert ref in stub and "\u20b1160.00" in stub


def test_references_are_unique(staff_client, catalog):
    refs = {ref_from(place(staff_client, customer={"new": {**NEW_CUSTOMER["new"]}, "confirm_duplicate": True}))
            for _ in range(6)}
    assert len(refs) == 6


def test_invalid_orders_create_nothing(staff_client, catalog):
    cases = [
        payload(items=[]),
        payload(items=[{"kind": "service", "id": svc("wash").id, "quantity": "-1"}]),
        payload(customer=None),
        payload(customer={"new": {"full_name": "", "contact_number": "0917"}}),
        payload(customer={"new": {"full_name": "Ana", "contact_number": "not a phone"}}),
        payload(customer={"id": 424242}),
        payload(notes="x" * 501),
    ]
    for body in cases:
        r = staff_client.post("/orders/new/confirm", json=body)
        assert r.status_code == 422 and not r.get_json()["ok"], body
    assert db.session.scalar(db.select(db.func.count(Order.id))) == 0
    assert db.session.scalar(db.select(db.func.count(Customer.id))) == 0
    assert staff_client.post("/orders/new/confirm", data="not json", content_type="text/plain").status_code == 400


def test_duplicate_customer_requires_confirmation(staff_client, catalog):
    place(staff_client)
    r = place(staff_client, customer={"new": {"full_name": "Ana C.", "contact_number": "+63 917 123 4567"}})
    assert r.status_code == 422
    body = r.get_json()
    assert "customer_duplicate" in body["errors"] and body["duplicates"][0]["full_name"] == "Ana Cruz"
    assert db.session.scalar(db.select(db.func.count(Customer.id))) == 1
    ok = place(staff_client, customer={"new": {"full_name": "Ana C.", "contact_number": "+63 917 123 4567"}, "confirm_duplicate": True})
    assert ok.status_code == 200 and db.session.scalar(db.select(db.func.count(Customer.id))) == 2


def test_existing_customer_can_be_used_and_searched(staff_client, catalog):
    place(staff_client)
    cust = db.session.execute(db.select(Customer)).scalar_one()
    found = staff_client.get("/orders/customers/search?q=ana").get_json()["results"]
    assert found and found[0]["id"] == cust.id
    assert staff_client.get("/orders/customers/search?q=0917").get_json()["results"]
    assert staff_client.get("/orders/customers/search?q=a").get_json()["results"] == []
    r = place(staff_client, customer={"id": cust.id})
    assert r.status_code == 200
    assert db.session.scalar(db.select(db.func.count(Customer.id))) == 1


def test_failed_transaction_leaves_no_partial_order(staff_client, catalog, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db exploded mid-transaction")
    monkeypatch.setattr("app.orders.services.OrderItem", boom)
    with pytest.raises(RuntimeError):
        place(staff_client)
    db.session.rollback()
    assert db.session.scalar(db.select(db.func.count(Order.id))) == 0
    assert db.session.scalar(db.select(db.func.count(OrderItem.id))) == 0
    assert db.session.scalar(db.select(db.func.count(OrderStatusHistory.id))) == 0
    assert db.session.scalar(db.select(db.func.count(Customer.id))) == 0


def test_quote_endpoint_uses_database_prices(staff_client, catalog):
    p = db.session.execute(db.select(ServicePackage).filter_by(category="Linens")).scalar_one()
    r = staff_client.post("/orders/new/quote", json={
        "items": [{"kind": "package", "id": p.id, "measurement": "4", "quantity": "1", "price": "1"}]})
    j = r.get_json()
    assert j["ok"] and j["total"] == "\u20b1205.00" and j["lines"][0]["unit_price"] == "\u20b1205.00"
    bad = staff_client.post("/orders/new/quote", json={"items": [{"kind": "package", "id": p.id, "measurement": "9"}]}).get_json()
    assert not bad["ok"] and bad["errors"]


def test_wizard_page_is_built_from_database(staff_client, catalog):
    html = staff_client.get("/orders/new").get_data(as_text=True)
    assert "Wash" in html and "Fabcon" in html and "3KG\u20135KG" in html
    assert "style=" not in html  # CSP: no inline styles
    svc("dry").is_active = False
    db.session.commit()
    assert 'data-code="dry"' not in staff_client.get("/orders/new").get_data(as_text=True)


def test_inactive_service_cannot_be_ordered(staff_client, catalog):
    svc("wash").is_active = False
    db.session.commit()
    assert place(staff_client).status_code == 422


# ----------------------------------------------------------------------------- history
def test_orders_keep_original_prices_after_catalog_changes(staff_client, admin_client, catalog):
    ref = ref_from(place(staff_client))
    wash = svc("wash")
    admin_client.post(f"/admin/services/services/{wash.id}/edit", data={
        "name": "Wash", "category": "Laundry service", "price": "90.00", "pricing_unit": "load",
        "icon_key": "wash", "is_active": "on"})
    db.session.expire_all()
    assert svc("wash").price == Decimal("90.00")
    order = order_by(ref)
    assert order.total == Decimal("160.00") and order.items[0].unit_price == Decimal("80.00")
    # new orders use the new price
    second = place(staff_client, customer={"id": order.customer_id})
    assert order_by(ref_from(second)).total == Decimal("180.00")


def test_orders_stay_readable_when_catalog_entry_is_deactivated(staff_client, admin_client, catalog):
    ref = ref_from(place(staff_client))
    admin_client.post(f"/admin/services/services/{svc('wash').id}/toggle")
    db.session.expire_all()
    r = staff_client.get(f"/orders/{ref}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Wash" in html and "\u20b180.00" in html and "\u20b1160.00" in html


# ----------------------------------------------------------------------------- viewing
def test_admin_and_staff_can_list_search_and_view(admin_client, staff_client, catalog):
    ref = ref_from(place(staff_client))
    for c in (admin_client, staff_client):
        assert c.get("/orders/").status_code == 200
        assert ref in c.get(f"/orders/?q={ref[3:9]}").get_data(as_text=True)
        assert ref in c.get("/orders/?q=ana").get_data(as_text=True)
        assert ref not in c.get("/orders/?q=zzzzzz").get_data(as_text=True)
        assert ref in c.get("/orders/?status=order_received").get_data(as_text=True)
        assert c.get(f"/orders/{ref}").status_code == 200
        assert c.get("/orders/LX-NOPE").status_code == 404
        assert c.get("/orders/?page=999").status_code == 200
        assert c.get("/dashboard/").status_code == 200


def test_dashboards_show_real_counts_and_empty_states(admin_client, staff_client, catalog):
    assert "No orders yet" in admin_client.get("/dashboard/").get_data(as_text=True)
    place(staff_client)
    html = staff_client.get("/dashboard/staff").get_data(as_text=True)
    assert "Ana Cruz" in html
    assert admin_client.get("/dashboard/admin").status_code == 200
    assert staff_client.get("/dashboard/admin").status_code == 403


# ----------------------------------------------------------------------------- status workflow
def test_status_updates_record_history(staff_client, staff, catalog):
    ref = ref_from(place(staff_client))
    r = staff_client.post(f"/orders/{ref}/status", data={"status": OrderStatus.PENDING, "note": "queued"})
    assert r.status_code == 302
    db.session.expire_all()
    order = order_by(ref)
    assert order.status == OrderStatus.PENDING
    last = order.history[-1]
    assert (last.from_status, last.to_status, last.changed_by_id, last.note) == (
        OrderStatus.RECEIVED, OrderStatus.PENDING, staff.id, "queued")
    assert len(order.history) == 2  # initial entry kept, nothing overwritten


def test_staff_can_only_move_forward_one_step(staff_client, catalog):
    ref = ref_from(place(staff_client))
    staff_client.post(f"/orders/{ref}/status", data={"status": OrderStatus.COMPLETED})   # skip ahead
    staff_client.post(f"/orders/{ref}/status", data={"status": "bogus"})
    staff_client.post(f"/orders/{ref}/status", data={"status": OrderStatus.RECEIVED})    # same
    db.session.expire_all()
    assert order_by(ref).status == OrderStatus.RECEIVED and len(order_by(ref).history) == 1
    for s in OrderStatus.FLOW[1:]:
        staff_client.post(f"/orders/{ref}/status", data={"status": s})
    db.session.expire_all()
    order = order_by(ref)
    assert order.status == OrderStatus.COMPLETED and len(order.history) == len(OrderStatus.FLOW)
    staff_client.post(f"/orders/{ref}/status", data={"status": OrderStatus.RELEASED, "note": "undo"})  # back: staff not allowed
    db.session.expire_all()
    assert order_by(ref).status == OrderStatus.COMPLETED


def test_admin_can_step_back_only_with_a_note(admin_client, staff_client, catalog):
    ref = ref_from(place(staff_client))
    staff_client.post(f"/orders/{ref}/status", data={"status": OrderStatus.PENDING})
    admin_client.post(f"/orders/{ref}/status", data={"status": OrderStatus.RECEIVED})
    db.session.expire_all()
    assert order_by(ref).status == OrderStatus.PENDING
    admin_client.post(f"/orders/{ref}/status", data={"status": OrderStatus.RECEIVED, "note": "entered wrong"})
    db.session.expire_all()
    order = order_by(ref)
    assert order.status == OrderStatus.RECEIVED
    assert order.history[-1].note == "entered wrong" and order.history[-1].changed_by.role == "admin"


def test_status_update_requires_login(anon_client, staff_client, catalog):
    ref = ref_from(place(staff_client))
    assert anon_client.post(f"/orders/{ref}/status", data={"status": OrderStatus.PENDING}).status_code == 302
    db.session.expire_all()
    assert order_by(ref).status == OrderStatus.RECEIVED


# ----------------------------------------------------------------------------- security regression
class CsrfOn(TestingConfig):
    WTF_CSRF_ENABLED = True


def test_csrf_protection_remains_enabled_for_new_endpoints():
    app = _make_app(CsrfOn)
    with app.app_context():
        db.create_all()
        from app.models import Role, User
        staff = User(email="s@example.com", role=Role.STAFF, is_active=True)
        admin = User(email="a@example.com", role=Role.ADMIN, is_active=True)
        db.session.add_all([staff, admin])
        db.session.commit()
        c = app.test_client()
        _login(c, staff)
        assert c.post("/orders/new/quote", json={}).status_code == 400
        assert c.post("/orders/new/confirm", json={}).status_code == 400
        assert c.post("/orders/LX-X/status", data={"status": "processing"}).status_code == 400
        a = app.test_client()
        _login(a, admin)
        assert a.post("/admin/services/services/new", data={"name": "x"}).status_code == 400
        db.session.remove()
        db.drop_all()
