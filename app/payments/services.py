"""Manual payment business rules.

Rules that must hold everywhere:
  * Money is Decimal, quantised to centavos. The browser's amounts are only *requests*;
    the server re-validates them against the server-calculated order total / current balance.
  * The ledger (`payments`) is append-only. Status and balance are derived from it.
  * Recording a payment locks the order row and re-checks the balance, so two staff members
    cannot overpay the same order at the same time.
  * Selecting a method never marks anything as received: a row exists only because staff typed
    an amount they manually confirmed.
"""
import re
from dataclasses import dataclass, field
from decimal import Decimal

from flask import has_request_context, request
from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    Order, Payment, PaymentArrangement, PaymentEvent, PaymentKind, PaymentMethod,
    PaymentSettings, PaymentStatus, Role,
)
from app.models.staff_credential import utcnow
from app.orders.pricing import money, parse_number

MAX_AMOUNT = Decimal("99999.99")
MAX_ENTRIES = 4
MAX_TEXT = 255
REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _./-]{0,63}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def peso(value) -> str:
    return f"\u20b1{Decimal(value):,.2f}"


# ----------------------------------------------------------------------------- settings / methods
def get_settings() -> PaymentSettings:
    """The single settings row. Created with safe defaults if missing (no invented account data)."""
    row = db.session.get(PaymentSettings, 1)
    if row is None:
        row = PaymentSettings(id=1)
        db.session.add(row)
        db.session.flush()
    return row


def active_methods():
    return db.session.scalars(
        db.select(PaymentMethod).where(PaymentMethod.is_active.is_(True))
        .order_by(PaymentMethod.sort_order, PaymentMethod.id)
    ).all()


def _method_by_code(code):
    if not isinstance(code, str):
        return None
    return db.session.execute(
        db.select(PaymentMethod).filter_by(code=code.strip().lower(), is_active=True)
    ).scalar_one_or_none()


# ----------------------------------------------------------------------------- audit
def log_event(action, user=None, order=None, payment=None, detail=None):
    ip = request.remote_addr if has_request_context() else None
    db.session.add(PaymentEvent(
        action=action, actor_id=getattr(user, "id", None), order=order, payment=payment,
        detail=(detail or "")[:500] or None, ip=(ip or None),
    ))


# ----------------------------------------------------------------------------- ledger maths
def net_received(order_id) -> Decimal:
    """Authoritative net amount received, straight from the ledger (not from loaded objects)."""
    signed = case((Payment.kind == PaymentKind.PAYMENT, Payment.amount), else_=-Payment.amount)
    value = db.session.scalar(
        db.select(func.coalesce(func.sum(signed), 0)).where(Payment.order_id == order_id)
    )
    return money(Decimal(str(value or 0)))


def derive_status(total, received, tracked=True) -> str:
    if not tracked:
        return PaymentStatus.NOT_TRACKED
    total, received = Decimal(total), Decimal(received)
    if received >= total:
        return PaymentStatus.PAID
    if received > 0:
        return PaymentStatus.PARTIAL
    return PaymentStatus.UNPAID


def _lock_order(order_id):
    return db.session.execute(
        db.select(Order).where(Order.id == order_id).with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


# ----------------------------------------------------------------------------- parsing / planning
@dataclass
class PlanEntry:
    method: PaymentMethod
    amount: Decimal
    reference: str = None
    notes: str = None


@dataclass
class PaymentPlan:
    total: Decimal
    arrangement: str = None
    entries: list = field(default_factory=list)
    errors: dict = field(default_factory=dict)

    def err(self, key, message):
        self.errors.setdefault(key, []).append(message)

    @property
    def received(self) -> Decimal:
        return money(sum((e.amount for e in self.entries), Decimal("0")))

    @property
    def balance(self) -> Decimal:
        return money(Decimal(self.total) - self.received)

    @property
    def status(self) -> str:
        return derive_status(self.total, self.received)

    def preview(self) -> dict:
        """Server-computed summary for the order preview (Stage 5 renders it)."""
        return {
            "arrangement": self.arrangement,
            "arrangement_label": PaymentArrangement.LABELS.get(self.arrangement),
            "entries": [{"method": e.method.label, "amount": peso(e.amount), "reference": e.reference}
                        for e in self.entries],
            "received": peso(self.received), "balance": peso(self.balance),
            "status": self.status, "status_label": PaymentStatus.LABELS[self.status],
        }


def _clean_text(value, limit=MAX_TEXT):
    text = _CONTROL.sub("", str(value or "")).strip()
    return text, (len(text) > limit)


def _parse_entries(raw_entries, plan: PaymentPlan):
    """Validate a list of {method, amount, reference?, notes?} dicts into plan.entries."""
    if raw_entries in (None, ""):
        raw_entries = []
    if not isinstance(raw_entries, list) or len(raw_entries) > MAX_ENTRIES:
        plan.err("payment", "The payment details are invalid.")
        return
    seen = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            plan.err("payment", "The payment details are invalid.")
            continue
        method = _method_by_code(raw.get("method"))
        if method is None:
            plan.err("payment", "Choose an available payment method.")
            continue
        key = f"payment:{method.code}"
        if method.code in seen:
            plan.err(key, f"{method.label} was entered more than once.")
            continue
        seen.add(method.code)
        amount, e = parse_number(raw.get("amount"), f"{method.label} amount", Decimal("0.01"), MAX_AMOUNT, 2)
        if e:
            plan.err(key, e)
            continue
        ref, too_long = _clean_text(raw.get("reference"), 64)
        if too_long or (ref and not REFERENCE_RE.match(ref)):
            plan.err(key, f"{method.label} reference may only contain letters, numbers, spaces and - _ . / (max 64).")
            continue
        if method.requires_reference and not ref:
            plan.err(key, f"A reference number is required for {method.label}.")
            continue
        notes, too_long = _clean_text(raw.get("notes"))
        if too_long:
            plan.err(key, f"Notes must be {MAX_TEXT} characters or fewer.")
            continue
        plan.entries.append(PlanEntry(method, money(amount), ref or None, notes or None))


def validate_payment_plan(raw, total) -> PaymentPlan:
    """Validate the payment chosen in the order wizard against the SERVER-calculated total."""
    total = money(total)
    plan = PaymentPlan(total=total)
    if not isinstance(raw, dict):
        plan.err("payment", "Choose how the customer will pay.")
        return plan
    arrangement = raw.get("arrangement")
    settings = get_settings()
    if arrangement not in PaymentArrangement.ALL:
        plan.err("payment", "Choose Full Payment, Partial Payment or Pay Later.")
        return plan
    if arrangement == PaymentArrangement.PARTIAL and not settings.partial_enabled:
        plan.err("payment", "Partial payment is not available.")
    if arrangement == PaymentArrangement.PAY_LATER and not settings.pay_later_enabled:
        plan.err("payment", "Pay Later is not available.")
    plan.arrangement = arrangement
    _parse_entries(raw.get("entries"), plan)
    if plan.errors:
        return plan

    received = plan.received
    if received > total:
        plan.err("payment", f"The amount received ({peso(received)}) cannot exceed the amount due ({peso(total)}).")
    elif arrangement == PaymentArrangement.PAY_LATER:
        if plan.entries:
            plan.err("payment", "Pay Later records no payment. Choose Partial Payment if the customer is paying part now.")
    elif arrangement == PaymentArrangement.FULL:
        if received != total:
            plan.err("payment", f"Full payment must equal the amount due ({peso(total)}).")
    else:  # partial
        if not plan.entries:
            plan.err("payment", "Enter the amount received.")
        elif received >= total:
            plan.err("payment", "A partial payment must be less than the amount due. Choose Full Payment instead.")
    return plan


def legacy_plan(total) -> PaymentPlan:
    """Callers that send no payment block (older API clients) are recorded as Pay Later / unpaid."""
    return PaymentPlan(total=money(total), arrangement=PaymentArrangement.PAY_LATER)


def add_payment_rows(order, entries, user, key_base=None):
    """Add ledger rows for `order` to the session. The caller owns the transaction (no commit here)."""
    now = utcnow()
    rows = []
    for e in entries:
        row = Payment(
            order=order, kind=PaymentKind.PAYMENT, method_id=e.method.id,
            method_code=e.method.code, method_label=e.method.label, amount=money(e.amount),
            reference=e.reference, paid_at=now, recorded_by_id=user.id, notes=e.notes,
            idempotency_key=f"{key_base}:{e.method.code}" if key_base else None,
        )
        db.session.add(row)
        rows.append(row)
        log_event("payment_recorded", user, order=order, payment=row,
                  detail=f"{peso(row.amount)} via {row.method_label}")
    return rows


def _existing_for_key(key):
    escaped = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return db.session.scalars(
        db.select(Payment).where(Payment.idempotency_key.like(f"{escaped}:%", escape="\\"))
        .order_by(Payment.id)
    ).all()


# ----------------------------------------------------------------------------- later payments
def record_payments(order_id, raw_entries, user, idempotency_key=None):
    """Record one or more later payments (e.g. settling a balance).

    Returns (payments, errors, duplicate). `duplicate=True` means the same submission was already
    saved and nothing new was written (a double-click or a replayed request)."""
    key = None
    if idempotency_key not in (None, ""):
        if not isinstance(idempotency_key, str) or not KEY_RE.match(idempotency_key):
            return [], {"payment": ["Invalid submission token. Reload the page and try again."]}, False
        key = idempotency_key
        existing = _existing_for_key(key)
        if existing:
            return existing, {}, True

    order = _lock_order(order_id)
    if order is None:
        db.session.rollback()
        return [], {"payment": ["Order not found."]}, False
    if not order.is_payment_tracked:
        db.session.rollback()
        return [], {"payment": ["Payments are not tracked for this order (it was created before payment recording)."]}, False

    plan = PaymentPlan(total=money(order.total))
    _parse_entries(raw_entries, plan)
    if not plan.entries and not plan.errors:
        plan.err("payment", "Enter the amount received.")
    balance = money(Decimal(order.total) - net_received(order.id))
    if not plan.errors:
        if balance <= 0:
            plan.err("payment", "This order is already fully paid.")
        elif plan.received > balance:
            plan.err("payment", f"The amount ({peso(plan.received)}) exceeds the remaining balance ({peso(balance)}).")
    if plan.errors:
        db.session.rollback()
        return [], plan.errors, False

    try:
        rows = add_payment_rows(order, plan.entries, user, key)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = _existing_for_key(key) if key else []
        if existing:
            return existing, {}, True
        raise
    except Exception:
        db.session.rollback()
        raise
    return rows, {}, False


# ----------------------------------------------------------------------------- admin corrections
def reverse_payment(payment_id, reason, user):
    """Admin-only correction. Adds a reversal row; the original is kept untouched. Returns (row, error)."""
    if getattr(user, "role", None) != Role.ADMIN:
        return None, "Only an administrator can correct payments."
    reason, too_long = _clean_text(reason)
    if len(reason) < 3 or too_long:
        return None, "Enter a reason for the correction (3 to 255 characters)."
    original = db.session.get(Payment, payment_id) if isinstance(payment_id, int) else None
    if original is None:
        return None, "Payment not found."
    order = _lock_order(original.order_id)
    db.session.refresh(original)
    if original.kind != PaymentKind.PAYMENT:
        db.session.rollback()
        return None, "Only a payment can be reversed."
    if db.session.scalar(db.select(func.count(Payment.id)).where(Payment.reverses_payment_id == original.id)):
        db.session.rollback()
        return None, "This payment was already reversed."
    try:
        row = Payment(
            order_id=order.id, kind=PaymentKind.REVERSAL, method_id=original.method_id,
            method_code=original.method_code, method_label=original.method_label,
            amount=original.amount, paid_at=utcnow(), recorded_by_id=user.id, notes=reason,
            reverses_payment_id=original.id,
        )
        db.session.add(row)
        log_event("payment_reversed", user, order=order, payment=row,
                  detail=f"Reversed {peso(original.amount)} {original.method_label} (payment #{original.id}): {reason}")
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, "This payment was already reversed."
    except Exception:
        db.session.rollback()
        raise
    return row, None


# ----------------------------------------------------------------------------- settings (admin)
def _flag(value):
    return value in (True, "on", "1", "true", "True", 1)


def parse_settings(data):
    """Returns (values, errors). `data` is a dict or form mapping."""
    errors, values = {}, {}
    for name in ("partial_enabled", "pay_later_enabled", "show_qr_on_stub"):
        values[name] = _flag(data.get(name))
    limits = {"gcash_account_name": 120, "payment_notice": 255, "stub_footer": 255, "payment_instructions": 1000}
    for name, limit in limits.items():
        text, too_long = _clean_text(data.get(name), limit)
        if too_long:
            errors[name] = f"Must be {limit} characters or fewer."
        values[name] = text or None
    number, too_long = _clean_text(data.get("gcash_account_number"), 40)
    if too_long or (number and not re.fullmatch(r"[0-9+()\- ]{1,40}", number)):
        errors["gcash_account_number"] = "Use digits, spaces, + ( ) - only (max 40)."
    values["gcash_account_number"] = number or None
    return values, errors


def update_settings(data, user):
    values, errors = parse_settings(data)
    if errors:
        return None, errors
    settings = get_settings()
    changed = [k for k, v in values.items() if getattr(settings, k) != v]
    for k, v in values.items():
        setattr(settings, k, v)
    settings.updated_by_id = user.id
    if changed:
        log_event("settings_updated", user, detail="Changed: " + ", ".join(sorted(changed)))
    db.session.commit()
    return settings, {}


def create_method(label, requires_reference, user):
    label, too_long = _clean_text(label, 60)
    if len(label) < 2 or too_long:
        return None, "Enter a method name (2 to 60 characters)."
    code = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:30]
    if not code:
        return None, "Enter a valid method name."
    if db.session.execute(db.select(PaymentMethod).filter_by(code=code)).scalar_one_or_none():
        return None, "A payment method with this name already exists."
    method = PaymentMethod(code=code, label=label, requires_reference=_flag(requires_reference), sort_order=100)
    db.session.add(method)
    log_event("method_created", user, detail=f"Added payment method {label}")
    db.session.commit()
    return method, None


def toggle_method(method_id, user):
    method = db.session.get(PaymentMethod, method_id) if isinstance(method_id, int) else None
    if method is None:
        return None, "Payment method not found."
    if method.is_active and len(active_methods()) <= 1:
        return None, "At least one payment method must stay active."
    method.is_active = not method.is_active
    log_event("method_toggled", user, detail=f"{method.label} {'enabled' if method.is_active else 'disabled'}")
    db.session.commit()
    return method, None

# ----------------------------------------------------------------------------- reporting queries
def _signed():
    return case((Payment.kind == PaymentKind.PAYMENT, Payment.amount), else_=-Payment.amount)


def _net_subquery():
    return (
        db.select(Payment.order_id.label("order_id"), func.sum(_signed()).label("net"))
        .group_by(Payment.order_id).subquery()
    )


OUTSTANDING_FILTERS = ("outstanding", "unpaid", "partial", "paid")


def orders_by_payment_status(status="outstanding"):
    """SELECT of tracked orders filtered by DERIVED payment status (same rules as Order.payment_status)."""
    net = _net_subquery()
    received = func.coalesce(net.c.net, 0)
    q = (
        db.select(Order).outerjoin(net, net.c.order_id == Order.id)
        .where(Order.payment_arrangement.is_not(None))
    )
    if status == "unpaid":
        q = q.where(received <= 0, Order.total > 0)
    elif status == "partial":
        q = q.where(received > 0, received < Order.total)
    elif status == "paid":
        q = q.where(received >= Order.total)
    else:  # outstanding = anything with a balance left
        q = q.where(received < Order.total)
    return q.order_by(Order.created_at.desc(), Order.id.desc())


def outstanding_summary():
    """(count, total_balance) over tracked orders that still owe money."""
    net = _net_subquery()
    received = func.coalesce(net.c.net, 0)
    row = db.session.execute(
        db.select(func.count(Order.id), func.coalesce(func.sum(Order.total - received), 0))
        .outerjoin(net, net.c.order_id == Order.id)
        .where(Order.payment_arrangement.is_not(None), received < Order.total)
    ).one()
    return int(row[0] or 0), money(Decimal(str(row[1] or 0)))


def collections_total(start, end):
    value = db.session.scalar(
        db.select(func.coalesce(func.sum(_signed()), 0)).where(Payment.paid_at >= start, Payment.paid_at < end)
    )
    return money(Decimal(str(value or 0)))


def collections_by_method(start, end):
    rows = db.session.execute(
        db.select(Payment.method_label, func.sum(_signed()))
        .where(Payment.paid_at >= start, Payment.paid_at < end)
        .group_by(Payment.method_label).order_by(Payment.method_label)
    ).all()
    return [(label, money(Decimal(str(total or 0)))) for label, total in rows]



def collections_by_staff(start, end):
    from app.models import User
    from sqlalchemy.orm import aliased

    original_payment = aliased(Payment)

    rows = db.session.execute(
        db.select(
            User.full_name,
            User.email,
            func.count(Payment.id),
            func.sum(_signed()),
        )
        .select_from(Payment)
        .outerjoin(
            original_payment,
            Payment.reverses_payment_id == original_payment.id,
        )
        .join(
            User,
            User.id == func.coalesce(
                original_payment.recorded_by_id,
                Payment.recorded_by_id,
            ),
        )
        .where(Payment.paid_at >= start, Payment.paid_at < end)
        .group_by(User.id, User.full_name, User.email)
        .order_by(User.email)
    ).all()

    return [
        (name or email, int(n), money(Decimal(str(total or 0))))
        for name, email, n, total in rows
    ]
