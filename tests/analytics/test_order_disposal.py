"""Tests for the 'mark as disposed' action. Run: pytest tests/analytics/test_order_disposal.py -q"""
from datetime import datetime
from decimal import Decimal

from app.extensions import db
from app.models import Customer, Order, OrderDisposal, OrderStatus, OrderStatusHistory, Role, User
from app.analytics.ml.predictions import get_waiting_orders


def _order(status=OrderStatus.READY):
    customer = Customer(full_name="Ana Cruz", contact_number="09171234567", contact_normalized="09171234567")
    db.session.add(customer)
    db.session.flush()
    order = Order(
        reference="T-DISP-1", customer_id=customer.id, customer_name="Ana Cruz",
        customer_contact="09171234567", status=status, subtotal=Decimal("100"), total=Decimal("100"),
        created_at=datetime(2026, 11, 10),
    )
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderStatusHistory(order_id=order.id, to_status=OrderStatus.READY, created_at=datetime(2026, 11, 11)))
    db.session.commit()
    return order


def test_disposed_live_order_leaves_the_waiting_list(app):
    order = _order()
    assert [i["reference"] for i in get_waiting_orders(None, datetime(2026, 11, 19).date())] == ["T-DISP-1"]

    db.session.add(OrderDisposal(order_id=order.id))
    db.session.commit()

    assert get_waiting_orders(None, datetime(2026, 11, 19).date()) == []
    db.session.delete(db.session.scalar(db.select(OrderDisposal)))
    db.session.commit()
    assert len(get_waiting_orders(None, datetime(2026, 11, 19).date())) == 1


def test_order_status_is_not_changed_by_a_disposal_record(app):
    order = _order()
    db.session.add(OrderDisposal(order_id=order.id))
    db.session.commit()
    assert db.session.get(Order, order.id).status == OrderStatus.READY
