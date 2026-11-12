"""Manage Orders presentation uses existing guarded routes and derived server data."""
def test_empty_manage_orders_has_real_empty_state_and_seven_columns(staff_client):
    response = staff_client.get("/orders/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "No orders yet." in html
    assert "Contact Number" in html
    assert "Total Amount</th>" not in html
    assert 'id="orders-payment" name="payment"' in html
    assert 'Payment filtering is currently unavailable' not in html
    assert 'data-orders-results data-page="1" data-pages="0" data-total="0"' in html
    assert 'data-order-summary' not in html


def test_manage_orders_still_requires_login(anon_client):
    response = anon_client.get("/orders/")
    assert response.status_code == 302


def test_payment_filter_combines_before_pagination_and_matches_ledger(app, staff_client, admin_client):
    import re
    from decimal import Decimal
    from app.extensions import db
    from app.models import Customer, Order, OrderStatus, Payment, PaymentMethod
    from app.orders.services import order_query

    customer = Customer(full_name="Andrea", contact_number="09171234567", contact_normalized="09171234567")
    method = PaymentMethod(code="cash", label="Cash")
    db.session.add_all([customer, method])
    db.session.flush()
    for index in range(54):
        order = Order(reference=f"FILTER-{index:03}", customer_id=customer.id,
                      customer_name="Andrea", customer_contact="09171234567",
                      subtotal=100, total=100, status=OrderStatus.FLOW[index % 6],
                      payment_arrangement="pay_later" if index < 53 else None)
        db.session.add(order)
        db.session.flush()
        # Each six-status block cycles through unpaid, partial and paid.
        amount = [0, 40, 100][(index // 6) % 3]
        if amount:
            db.session.add(Payment(order_id=order.id, method_id=method.id, method_code="cash",
                                   method_label="Cash", amount=amount))
    db.session.commit()
    for client in (staff_client, admin_client):
        for payment in ("", "unpaid", "partial", "paid"):
            expected = db.session.scalars(order_query(payment=payment)).all()
            assert len(expected) == {"": 54, "unpaid": 18, "partial": 18, "paid": 17}[payment]
            refs = []
            for page in range(1, (len(expected) + 14) // 15 + 1):
                html = client.get(f"/orders/?payment={payment}&page={page}").get_data(as_text=True)
                refs.extend(re.findall(r'<tr data-ref="([^"]+)"', html))
                assert f'data-total="{len(expected)}"' in html
            assert refs == [order.reference for order in expected]
            assert len(refs) == len(set(refs))
            if payment:
                assert all(order.payment_status == payment for order in expected)
            for status in OrderStatus.FLOW:
                for search in ("andrea", "09171234567", "FILTER-"):
                    html = client.get('/orders/', query_string={"payment": payment, "status": status, "q": search}).get_data(as_text=True)
                    actual = re.findall(r'<tr data-ref="([^"]+)"', html)
                    assert actual == [order.reference for order in expected if order.status == status]

    # A reversal and later settlement must move records across filters on refetch.
    order = db.session.scalar(db.select(Order).filter_by(reference="FILTER-012"))
    original = order.payments[0]
    db.session.add(Payment(order_id=order.id, method_id=method.id, method_code="cash", method_label="Cash",
                           amount=100, kind="reversal", reverses_payment_id=original.id))
    db.session.commit()
    assert order in db.session.scalars(order_query(payment="unpaid")).all()
    assert order not in db.session.scalars(order_query(payment="paid")).all()
    db.session.add(Payment(order_id=order.id, method_id=method.id, method_code="cash", method_label="Cash", amount=Decimal('100')))
    db.session.commit()
    assert order in db.session.scalars(order_query(payment="paid")).all()
