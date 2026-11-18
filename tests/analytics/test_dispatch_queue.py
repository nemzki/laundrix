
from datetime import datetime, timedelta
from decimal import Decimal

from app.analytics.ml.dispatch_queue import get_ready_dispatch_queue
from app.extensions import db
from app.models import (
    Customer,
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
)


def create_order(reference, status, customer, ready_at=None):
    order = Order(
        reference=reference,
        customer_id=customer.id,
        customer_name=customer.full_name,
        customer_contact=customer.contact_number,
        status=status,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        payment_arrangement="partial",
        created_at=datetime(2026, 11, 1),
    )
    db.session.add(order)
    db.session.flush()

    db.session.add(
        OrderItem(
            order_id=order.id,
            item_type="service",
            name="Wash & Fold",
            quantity=Decimal("2.00"),
            unit="load",
            unit_price=Decimal("50.00"),
            line_total=Decimal("100.00"),
        )
    )

    if ready_at is not None:
        db.session.add(
            OrderStatusHistory(
                order_id=order.id,
                from_status=OrderStatus.PROCESSING,
                to_status=OrderStatus.READY,
                created_at=ready_at,
            )
        )

    return order


def create_customer():
    customer = Customer(
        full_name="Test Customer",
        contact_number="09171234567",
        contact_normalized="09171234567",
    )
    db.session.add(customer)
    db.session.flush()
    return customer


def test_queue_prioritizes_oldest_ready_order_first(app):
    now = datetime(2026, 11, 18, 12, 0)
    customer = create_customer()

    older = create_order(
        "TEST-OLDER",
        OrderStatus.READY,
        customer,
        now - timedelta(days=3),
    )
    newer = create_order(
        "TEST-NEWER",
        OrderStatus.READY,
        customer,
        now - timedelta(days=1),
    )
    db.session.commit()

    queue = get_ready_dispatch_queue(as_of=now)

    assert [item["order_id"] for item in queue] == [
        older.id,
        newer.id,
    ]
    assert [item["priority"] for item in queue] == [1, 2]


def test_queue_calculates_waiting_time_from_ready_event(app):
    now = datetime(2026, 11, 18, 12, 0)
    ready_at = now - timedelta(days=2, hours=3, minutes=15)
    customer = create_customer()

    order = create_order(
        "TEST-WAITING",
        OrderStatus.READY,
        customer,
        ready_at,
    )
    db.session.commit()

    queue = get_ready_dispatch_queue(as_of=now)

    assert len(queue) == 1
    assert queue[0]["order_id"] == order.id
    assert queue[0]["waiting_minutes"] == 3075
    assert queue[0]["waiting_label"] == "2d 3h 15m"


def test_queue_excludes_orders_that_are_not_currently_ready(app):
    now = datetime(2026, 11, 18, 12, 0)
    customer = create_customer()

    create_order(
        "TEST-PICKED-UP",
        OrderStatus.RELEASED,
        customer,
        now - timedelta(days=3),
    )
    create_order(
        "TEST-PROCESSING",
        OrderStatus.PROCESSING,
        customer,
        now - timedelta(days=2),
    )
    db.session.commit()

    assert get_ready_dispatch_queue(as_of=now) == []


def test_queue_uses_latest_ready_event(app):
    now = datetime(2026, 11, 18, 12, 0)
    first_ready = now - timedelta(days=10)
    latest_ready = now - timedelta(hours=5)
    customer = create_customer()

    order = create_order(
        "TEST-READY-AGAIN",
        OrderStatus.READY,
        customer,
        first_ready,
    )
    db.session.add(
        OrderStatusHistory(
            order_id=order.id,
            from_status=OrderStatus.RELEASED,
            to_status=OrderStatus.READY,
            created_at=latest_ready,
        )
    )
    db.session.commit()

    queue = get_ready_dispatch_queue(as_of=now)

    assert len(queue) == 1
    assert queue[0]["ready_at"] == latest_ready
    assert queue[0]["waiting_minutes"] == 300


def test_queue_excludes_ready_orders_without_ready_history(app):
    now = datetime(2026, 11, 18, 12, 0)
    customer = create_customer()

    create_order(
        "TEST-MISSING-HISTORY",
        OrderStatus.READY,
        customer,
    )
    db.session.commit()

    assert get_ready_dispatch_queue(as_of=now) == []
