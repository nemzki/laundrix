"""Small helpers to build orders/payments with exact timestamps for tests."""
from datetime import datetime, timezone
from decimal import Decimal
from itertools import count

from app.core.timeutil import SHOP_TZ
from app.extensions import db
from app.models import (
    Customer, Order, OrderItem, Payment, PaymentKind, PaymentMethod,
)

_n = count(1)


def local(y, m, d, h=0, mi=0, s=0):
    """A Philippine wall-clock time as the naive UTC the database stores."""
    return datetime(y, m, d, h, mi, s, tzinfo=SHOP_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def make_customer(name, created_at):
    n = next(_n)
    c = Customer(full_name=name, contact_number=f"TESTCONTACT-{n:05d}",
                 contact_normalized=f"0917{n:07d}", created_at=created_at)
    db.session.add(c)
    db.session.flush()
    return c


def make_order(customer, total, created_at, status="order_received", tracked=True,
               received=True, items=(), received_at=None):
    """``received_at`` overrides the default (created_at when ``received`` else NULL).
    Items are (type, name, qty, unit, line_total) tuples, or dicts for catalog ids/descriptions."""
    n = next(_n)
    o = Order(
        reference=f"T-{n:06d}", customer_id=customer.id, customer_name=customer.full_name,
        customer_contact=customer.contact_number, status=status,
        subtotal=Decimal(total), total=Decimal(total),
        payment_arrangement="pay_later" if tracked else None,
        received_at=received_at if received_at is not None else (created_at if received else None),
        created_at=created_at, updated_at=created_at,
    )
    db.session.add(o)
    db.session.flush()
    for item in items:
        extra = {}
        if isinstance(item, dict):
            extra = {k: item[k] for k in ("service_id", "package_id", "addon_id", "description") if k in item}
            item_type, name, qty, unit, line_total = (item[k] for k in ("item_type", "name", "quantity", "unit", "line_total"))
        else:
            item_type, name, qty, unit, line_total = item
        db.session.add(OrderItem(
            order_id=o.id, item_type=item_type, name=name, quantity=Decimal(qty), unit=unit,
            unit_price=Decimal(line_total) / Decimal(qty), line_total=Decimal(line_total), **extra))
    db.session.flush()
    return o


def add_payment(order, amount, paid_at, method="cash"):
    m = db.session.execute(db.select(PaymentMethod).filter_by(code=method)).scalar_one()
    p = Payment(order_id=order.id, kind=PaymentKind.PAYMENT, method_id=m.id,
                method_code=m.code, method_label=m.label, amount=Decimal(amount), paid_at=paid_at)
    db.session.add(p)
    db.session.flush()
    return p


def add_reversal(payment, paid_at):
    r = Payment(order_id=payment.order_id, kind=PaymentKind.REVERSAL, method_id=payment.method_id,
                method_code=payment.method_code, method_label=payment.method_label,
                amount=payment.amount, paid_at=paid_at, reverses_payment_id=payment.id)
    db.session.add(r)
    db.session.flush()
    return r
