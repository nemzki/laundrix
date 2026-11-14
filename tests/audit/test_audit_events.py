"""Business operations leave an audit record, in the same transaction, without secrets."""
import itertools
from decimal import Decimal

import pytest

from app.audit import services as audit
from app.extensions import db
from app.models import AuditLog, Order, Payment, Service
from tests.laundry.conftest import svc

_n = itertools.count(1)
FULL_CASH = {"arrangement": "full", "entries": [{"method": "cash", "amount": "160"}]}
PARTIAL = {"arrangement": "partial", "entries": [{"method": "cash", "amount": "60"}]}


def logs(**filters):
    q = db.select(AuditLog).order_by(AuditLog.id)
    for key, value in filters.items():
        q = q.where(getattr(AuditLog, key) == value)
    return db.session.scalars(q).all()


def place(client, payment=FULL_CASH):
    n = next(_n)
    body = {"items": [{"kind": "service", "id": svc("wash").id, "quantity": "2"}], "extras": [],
            "customer": {"new": {"full_name": f"Customer {n}", "contact_number": f"0917{n:07d}"}},
            "payment": payment}
    r = client.post("/orders/new/confirm", json=body)
    assert r.status_code == 200, r.get_json()
    return db.session.execute(db.select(Order).filter_by(reference=r.get_json()["redirect"].split("/")[2])).scalar_one()


# ----------------------------------------------------------------------------- orders & payments
def test_creating_an_order_with_a_payment_is_audited(staff_client, staff, pay):
    order = place(staff_client)
    created = logs(module="orders", action="create")
    assert len(created) == 1 and created[0].resource_id == order.reference
    assert created[0].actor_id == staff.id and created[0].actor_role == "staff"
    assert created[0].new_values["total"] == "160.00"
    pay_row = logs(module="payments", action="payment")[0]
    assert pay_row.resource_label == f"Order {order.reference}"
    assert pay_row.old_values == {"balance": "160.00"}
    assert pay_row.new_values == {"amount": "160.00", "method": "Cash", "balance": "0.00"}
    assert logs(module="customers", action="create")           # the new customer too


def test_partial_payment_then_balance_payment_track_the_balance(staff_client, pay):
    order = place(staff_client, PARTIAL)
    r = staff_client.post(f"/orders/{order.reference}/payments",
                          json={"entries": [{"method": "cash", "amount": "100"}]})
    assert r.status_code == 200
    last = logs(module="payments", action="payment")[-1]
    assert last.old_values == {"balance": "100.00"} and last.new_values["balance"] == "0.00"


def test_status_change_records_old_and_new_status(staff_client, pay):
    order = place(staff_client)
    staff_client.post(f"/orders/{order.reference}/confirm-received")
    r = staff_client.post(f"/orders/{order.reference}/status", data={"status": "pending_processing"})
    assert r.status_code == 302
    row = logs(action="status_change")[0]
    assert row.old_values == {"status": "Order Received"} and row.new_values["status"] == "Pending Processing"
    assert row.resource_id == order.reference
    assert logs(module="orders", action="update")                # laundry received


def test_admin_reversal_is_audited(admin_client, pay):
    order = place(admin_client)
    payment = db.session.scalars(db.select(Payment).filter_by(order_id=order.id)).first()
    r = admin_client.post(f"/payments/{payment.id}/reverse", json={"reason": "Entered twice"})
    assert r.status_code in (200, 302), r.status_code
    row = logs(action="reversal")[0]
    assert row.new_values["reason"] == "Entered twice" and row.module == "payments"


def test_payment_settings_change_never_copies_account_details(admin_client, pay):
    admin_client.post("/payments/settings", data={
        "partial_enabled": "on", "gcash_account_name": "Private Name", "gcash_account_number": "09171234567"})
    row = logs(module="settings", action="update")[0]
    blob = " ".join(str(v) for v in (row.description, row.old_values, row.new_values))
    assert "Private Name" not in blob and "09171234567" not in blob
    assert "gcash_account_number" in row.description                # field *names* only


# ----------------------------------------------------------------------------- customers & catalog
def test_customer_edit_records_only_changes_and_masks_the_phone(admin_client, pay):
    r = admin_client.post("/orders/customers", json={"full_name": "Ana Cruz", "contact_number": "0917 555 1234"})
    cid = r.get_json()["customer"]["id"]
    assert logs(module="customers", action="create")[0].new_values["contact_number"].endswith("1234")
    admin_client.post(f"/orders/customers/{cid}", json={"full_name": "Ana C. Cruz", "contact_number": "0917 555 1234"})
    row = logs(module="customers", action="update")[0]
    assert row.old_values == {"name": "Ana Cruz"} and row.new_values == {"name": "Ana C. Cruz"}
    assert "5551234" not in str(logs(module="customers"))


def test_price_change_is_a_separate_action_with_old_and_new_price(admin_client, catalog):
    wash = svc("wash")
    form = {"name": wash.name, "category": wash.category, "price": "95.00", "pricing_unit": "load",
            "icon_key": wash.icon_key, "is_active": "on"}
    assert admin_client.post(f"/admin/services/services/{wash.id}/edit", data=form).status_code == 302
    row = logs(action="price_change")[0]
    assert row.module == "services" and row.old_values == {"price": "80.00"} and row.new_values == {"price": "95.00"}
    assert "95.00" in row.description


def test_unchanged_catalog_save_adds_no_record_and_toggle_is_audited(admin_client, catalog):
    wash = svc("wash")
    form = {"name": wash.name, "category": wash.category, "price": f"{wash.price:.2f}", "pricing_unit": "load",
            "icon_key": wash.icon_key, "is_active": "on", "description": wash.description or ""}
    admin_client.post(f"/admin/services/services/{wash.id}/edit", data=form)
    assert not logs(module="services", action="update") and not logs(action="price_change")
    admin_client.post(f"/admin/services/services/{wash.id}/toggle")
    assert logs(action="deactivate")[0].new_values == {"is_active": False}


# ----------------------------------------------------------------------------- sign-in / out
def test_failed_sign_in_is_recorded_without_the_password(anon_client):
    anon_client.post("/auth/login", data={"identifier": "ghost@example.com", "password": "Hunter2-Secret!"})
    row = logs(action="login_failed")[0]
    assert row.success is False and "ghost@example.com" in row.description
    assert "Hunter2" not in str(row.__dict__)


def test_a_non_email_identifier_is_not_stored(anon_client):
    anon_client.post("/auth/login", data={"identifier": "my password is Hunter2", "password": "x"})
    row = logs(action="login_failed")[0]
    assert "Hunter2" not in row.description and row.actor_name == "Unknown"


def test_logout_is_audited_and_still_works_if_auditing_fails(admin_client, admin, monkeypatch):
    assert admin_client.post("/auth/logout").status_code == 302
    assert logs(action="logout")[0].actor_id == admin.id

    def boom(*a, **k):
        raise RuntimeError("audit store down")
    monkeypatch.setattr("app.core.audit.audit_auth_event", boom)
    r = admin_client.post("/auth/logout")
    assert r.status_code in (302, 401)                            # signing out is never blocked


def test_profile_update_is_audited(staff_client, staff):
    r = staff_client.post("/settings/profile", data={"full_name": "New Name Here"})
    assert r.status_code == 303
    row = logs(module="accounts", action="update")[0]
    assert row.new_values == {"full_name": "New Name Here"} and row.actor_id == staff.id


# ----------------------------------------------------------------------------- failure handling
def test_if_the_audit_record_cannot_be_saved_the_payment_is_not_either(staff_client, pay, monkeypatch):
    order = place(staff_client, PARTIAL)
    monkeypatch.setattr("app.payments.services.audit_payment_event",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit store down")))
    before = db.session.scalar(db.select(db.func.count(Payment.id)))
    with pytest.raises(RuntimeError):
        staff_client.post(f"/orders/{order.reference}/payments",
                          json={"entries": [{"method": "cash", "amount": "50"}]})
    db.session.rollback()
    assert db.session.scalar(db.select(db.func.count(Payment.id))) == before


def test_if_the_audit_record_cannot_be_saved_the_order_is_not_created(staff_client, pay, monkeypatch):
    real = audit.record

    def fail_for_orders(action, module, *a, **k):
        if module == "orders":
            raise RuntimeError("audit store down")
        return real(action, module, *a, **k)
    monkeypatch.setattr("app.orders.services.audit.record", fail_for_orders)
    body = {"items": [{"kind": "service", "id": svc("wash").id, "quantity": "2"}], "extras": [],
            "customer": {"new": {"full_name": "No Audit", "contact_number": "09170001111"}}, "payment": FULL_CASH}
    with pytest.raises(RuntimeError):
        staff_client.post("/orders/new/confirm", json=body)
    db.session.rollback()
    assert db.session.scalar(db.select(db.func.count(Order.id))) == 0


def test_failed_sign_in_audit_failure_is_not_swallowed(anon_client, monkeypatch):
    monkeypatch.setattr("app.core.audit.audit_auth_event",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit store down")))
    with pytest.raises(RuntimeError):
        anon_client.post("/auth/login", data={"identifier": "x@example.com", "password": "y"})
