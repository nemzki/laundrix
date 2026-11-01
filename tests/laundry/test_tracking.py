
from app.extensions import db
from app.models import Order, OrderStatus
from tests.laundry.conftest import NEW_CUSTOMER, svc


def create_order(client):
    response = client.post("/orders/new/confirm", json={
        "items": [
            {
                "kind": "service",
                "id": svc("wash").id,
                "quantity": "2",
            }
        ],
        "extras": [],
        "customer": NEW_CUSTOMER,
    })

    assert response.status_code == 200
    assert response.get_json()["ok"]

    reference = response.get_json()["redirect"].split("/")[2]
    return db.session.execute(
        db.select(Order).filter_by(reference=reference)
    ).scalar_one()


def test_tracking_page_is_public(staff_client, anon_client, catalog):
    order = create_order(staff_client)

    response = anon_client.get(f"/track/{order.tracking_token}")

    assert response.status_code == 200
    assert order.reference in response.get_data(as_text=True)


def test_invalid_tracking_token_returns_404(anon_client):
    response = anon_client.get("/track/invalid-token")

    assert response.status_code == 404


def test_tracking_page_does_not_expose_private_information(
    staff_client, anon_client, catalog
):
    order = create_order(staff_client)

    order.customer_contact = "PRIVATE-CONTACT-987654"
    order.notes = "INTERNAL-STAFF-NOTE-DO-NOT-EXPOSE"
    db.session.commit()

    response = anon_client.get(f"/track/{order.tracking_token}")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "PRIVATE-CONTACT-987654" not in html
    assert "INTERNAL-STAFF-NOTE-DO-NOT-EXPOSE" not in html


def test_tracking_page_displays_latest_order_status(
    staff_client, anon_client, catalog
):
    order = create_order(staff_client)

    order.status = OrderStatus.PROCESSING
    db.session.commit()

    response = anon_client.get(f"/track/{order.tracking_token}")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert OrderStatus.LABELS[OrderStatus.PROCESSING] in html


def test_printable_stub_contains_generated_qr_code(
    staff_client, catalog
):
    order = create_order(staff_client)

    response = staff_client.get(f"/orders/{order.reference}/stub")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Scan to Track Your Order" in html
    assert "data:image/png;base64," in html
    assert order.reference in html
