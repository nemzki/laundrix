from datetime import datetime
from decimal import Decimal

from app.analytics.services import get_analytics_report
from app.extensions import db
from app.models import Customer, Order, OrderItem, OrderStatus, Payment, PaymentMethod
from app.models.payment import PaymentKind


def test_analytics_report_calculates_orders_payments_and_services(app):
    customer_a = Customer(
        full_name="Ana Cruz",
        contact_number="09171234567",
        contact_normalized="09171234567",
    )
    customer_b = Customer(
        full_name="Ben Santos",
        contact_number="09181234567",
        contact_normalized="09181234567",
    )
    db.session.add_all([customer_a, customer_b])
    db.session.flush()

    order_a = Order(
        reference="TEST-ANALYTICS-001",
        customer_id=customer_a.id,
        customer_name=customer_a.full_name,
        customer_contact=customer_a.contact_number,
        status=OrderStatus.READY,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        payment_arrangement="partial",
        created_at=datetime(2026, 11, 3),
    )
    order_b = Order(
        reference="TEST-ANALYTICS-002",
        customer_id=customer_b.id,
        customer_name=customer_b.full_name,
        customer_contact=customer_b.contact_number,
        status=OrderStatus.PROCESSING,
        subtotal=Decimal("50.00"),
        total=Decimal("50.00"),
        payment_arrangement="partial",
        created_at=datetime(2026, 10, 5),
    )
    legacy_order = Order(
        reference="TEST-ANALYTICS-003",
        customer_id=customer_a.id,
        customer_name=customer_a.full_name,
        customer_contact=customer_a.contact_number,
        status=OrderStatus.RECEIVED,
        subtotal=Decimal("25.00"),
        total=Decimal("25.00"),
        payment_arrangement=None,
        created_at=datetime(2025, 10, 20),
    )
    db.session.add_all([order_a, order_b, legacy_order])
    db.session.flush()

    method = PaymentMethod(code="cash", label="Cash")
    db.session.add(method)
    db.session.flush()

    original_payment = Payment(
        order_id=order_a.id,
        method_id=method.id,
        method_code="cash",
        method_label="Cash",
        amount=Decimal("100.00"),
        paid_at=datetime(2026, 9, 15),
    )
    db.session.add(original_payment)
    db.session.flush()

    db.session.add_all([
        Payment(
            order_id=order_a.id,
            method_id=method.id,
            method_code="cash",
            method_label="Cash",
            amount=Decimal("20.00"),
            kind=PaymentKind.REVERSAL,
            reverses_payment_id=original_payment.id,
            paid_at=datetime(2026, 11, 5),
        ),
        Payment(
            order_id=order_b.id,
            method_id=method.id,
            method_code="cash",
            method_label="Cash",
            amount=Decimal("30.00"),
            paid_at=datetime(2026, 11, 8),
        ),
    ])

    db.session.add_all([
        OrderItem(
            order_id=order_a.id,
            item_type="service",
            name="Wash & Fold",
            quantity=Decimal("2.00"),
            unit="load",
            unit_price=Decimal("20.00"),
            line_total=Decimal("40.00"),
        ),
        OrderItem(
            order_id=order_b.id,
            item_type="service",
            name="Wash & Fold",
            quantity=Decimal("1.00"),
            unit="load",
            unit_price=Decimal("30.00"),
            line_total=Decimal("30.00"),
        ),
        OrderItem(
            order_id=order_b.id,
            item_type="service",
            name="Dry",
            quantity=Decimal("1.00"),
            unit="load",
            unit_price=Decimal("10.00"),
            line_total=Decimal("10.00"),
        ),
    ])
    db.session.commit()

    report = get_analytics_report(as_of=datetime(2026, 11, 16))
    summary = report["summary"]

    assert summary["total_orders"] == 3
    assert summary["orders_this_month"] == 1
    assert summary["total_customers"] == 2
    assert summary["order_value"] == Decimal("175.00")

    # Original payment 100 - reversal 20 + second payment 30.
    assert summary["collected_12m"] == Decimal("110.00")
    assert summary["outstanding_balance"] == Decimal("40.00")
    assert summary["orders_with_balance"] == 2

    assert report["payment_methods"] == [
        {"name": "Cash", "amount": Decimal("110.00"), "bar_width": 100}
    ]

    wash = next(item for item in report["services"] if item["name"] == "Wash & Fold")
    assert wash["lines"] == 2
    assert wash["quantity"] == 3.0
    assert wash["sales"] == Decimal("70.00")

    dry = next(item for item in report["services"] if item["name"] == "Dry")
    assert dry["lines"] == 1
    assert dry["sales"] == Decimal("10.00")

    monthly = {item["key"]: item for item in report["monthly"]}
    assert monthly["2026-10"]["orders"] == 1
    assert monthly["2026-11"]["orders"] == 1
    assert monthly["2026-09"]["collected"] == Decimal("100.00")
    assert monthly["2026-11"]["collected"] == Decimal("10.00")

    assert report["report_period"] == "Jun 2026 \u2013 Nov 2026"
