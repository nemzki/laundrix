"""Approved customer directory integration; original order snapshots and ledger remain authoritative."""
from decimal import Decimal

from app.extensions import db
from app.models import Customer, Order, Payment, PaymentMethod


def create(client, name="Directory QA", phone="09171234567", **extra):
    return client.post("/orders/customers", json={"full_name": name, "contact_number": phone, **extra})


def test_customer_writes_and_profiles_remain_admin_only(admin_client, staff_client, anon_client):
    saved = create(admin_client)
    assert saved.status_code == 200
    url = saved.json["customer"]["url"]
    for client, status in ((staff_client, 403), (anon_client, 302)):
        assert create(client).status_code == status
        assert client.get(url).status_code == status
        assert client.post(url, json={"full_name": "Forbidden", "contact_number": "09170000000"}).status_code == status


def test_original_validation_duplicate_confirmation_and_whitelisted_updates(admin_client):
    invalid = create(admin_client, "A", "invalid@phone")
    assert invalid.status_code == 422
    assert "customer_name" in invalid.json["errors"] and "customer_contact" in invalid.json["errors"]
    first = create(admin_client, "  Directory   QA  ").json["customer"]
    assert first["full_name"] == "Directory QA"
    duplicate = create(admin_client, "Another QA")
    assert duplicate.status_code == 422 and duplicate.json["duplicates"][0]["id"] == first["id"]
    confirmed = create(admin_client, "Another QA", confirm_duplicate=True)
    assert confirmed.status_code == 200 and confirmed.json["customer"]["id"] != first["id"]
    # Unchanged phone does not collide with itself; use a unique record for this check.
    unique = create(admin_client, "Unique QA", "09179999999").json["customer"]
    original = db.session.get(Customer, unique["id"])
    created_at, creator = original.created_at, original.created_by_id
    edited = admin_client.post(unique["url"], json={
        "full_name": "Updated QA", "contact_number": "09179999999",
        "created_by_id": None, "created_at": "1900-01-01", "notes": "Not stored", "email": "not-stored@example.test", "address": "Not stored",
    })
    assert edited.status_code == 200
    db.session.refresh(original)
    assert original.full_name == "Updated QA"
    assert original.created_at == created_at and original.created_by_id == creator
    assert not hasattr(original, "notes") and not hasattr(original, "email") and not hasattr(original, "address")
    assert admin_client.get("/orders/customers/999999").status_code == 404


def test_customer_history_totals_reversals_filters_and_snapshots(admin_client):
    first = create(admin_client).json["customer"]
    second = create(admin_client, "No Orders QA", "09170000001").json["customer"]
    method = PaymentMethod(code="cash", label="Cash")
    db.session.add(method)
    order = Order(reference="CUSTOMER-HISTORY", customer_id=first["id"], customer_name="Original Snapshot",
                  customer_contact="09171234567", subtotal=100, total=100, payment_arrangement="partial")
    legacy = Order(reference="CUSTOMER-LEGACY", customer_id=first["id"], customer_name="Legacy Snapshot",
                   customer_contact="09171234567", subtotal=500, total=500)
    db.session.add_all([order, legacy]); db.session.flush()
    payment = Payment(order_id=order.id, method_id=method.id, method_code="cash", method_label="Cash", amount=40)
    db.session.add(payment); db.session.flush()
    db.session.add(Payment(order_id=order.id, method_id=method.id, method_code="cash", method_label="Cash",
                           amount=40, kind="reversal", reverses_payment_id=payment.id))
    db.session.add(Payment(order_id=order.id, method_id=method.id, method_code="cash", method_label="Cash", amount=25))
    db.session.commit()
    result = admin_client.get(first["url"])
    html = result.json["customer"]["profile_html"]
    assert "CUSTOMER-HISTORY" in html and "CUSTOMER-LEGACY" in html
    assert "\u20b125.00" in html and "\u20b175.00" in html
    assert "CUSTOMER-HISTORY" not in admin_client.get(second["url"]).json["customer"]["profile_html"]
    owing = admin_client.get("/orders/customers?filter=owing").get_data(as_text=True)
    assert f'data-customer-id="{first["id"]}"' in owing and f'data-customer-id="{second["id"]}"' not in owing
    settled = admin_client.get("/orders/customers?filter=settled").get_data(as_text=True)
    assert f'data-customer-id="{first["id"]}"' not in settled and f'data-customer-id="{second["id"]}"' in settled
    edited = admin_client.post(first["url"], json={"full_name": "Current Name", "contact_number": "09171112222"})
    assert edited.status_code == 200
    db.session.refresh(order)
    assert order.customer_name == "Original Snapshot" and order.customer_contact == "09171234567"
    assert order.amount_paid == Decimal("25") and order.balance_due == Decimal("75")
    assert f'data-customer-id="{first["id"]}"' in admin_client.get("/orders/customers?q=Current&filter=owing").get_data(as_text=True)
