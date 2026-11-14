"""Order business logic: customers, creation (single transaction), status workflow, statistics."""
import re
import secrets
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.audit import services as audit
from app.core.timeutil import local_date_code, local_today_bounds_utc
from app.extensions import db
from app.models import (
    Customer, Order, OrderItem, OrderStatus, OrderStatusHistory, Role,
)
from app.models.staff_credential import utcnow
from app.orders.pricing import GENERAL, build_quote
from app.sms import services as sms_services
from app.payments import services as payment_services

def _customer_audit_view(customer):
    """What an audit record may keep about a customer: the name and a MASKED contact number."""
    return {"name": customer.full_name, "contact_number": customer.contact_number}


_REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I confusion on printed stubs
MAX_NOTES = 500


# ----------------------------------------------------------------------------- customers
def normalize_contact(raw: str):
    """Return (display, normalized, error). Digits only; +63/63 prefixes become 0."""
    text = (raw or "").strip()
    if not re.fullmatch(r"[+\d\s\-()]{7,25}", text):
        return None, None, "Enter a valid contact number."
    digits = re.sub(r"\D", "", text)
    if digits.startswith("63") and len(digits) == 12:
        digits = "0" + digits[2:]
    if not 7 <= len(digits) <= 15:
        return None, None, "Enter a valid contact number."
    return text, digits, None


def search_customers(term: str, limit: int = 8):
    term = (term or "").strip()
    if len(term) < 2:
        return []
    digits = re.sub(r"\D", "", term)
    cond = [Customer.full_name.ilike(f"%{_like_escape(term)}%", escape="\\")]
    if len(digits) >= 3:
        cond.append(Customer.contact_normalized.like(f"%{digits}%"))
    return db.session.execute(
        db.select(Customer).where(or_(*cond)).order_by(Customer.full_name).limit(limit)
    ).scalars().all()


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def validate_customer(raw, exclude_customer_id=None):
    """Return (customer_or_None, new_data_or_None, errors dict, duplicates list)."""
    errors, duplicates = {}, []
    if not isinstance(raw, dict):
        return None, None, {"customer": ["Select or register a customer."]}, duplicates

    if raw.get("id") not in (None, ""):
        try:
            cid = int(str(raw["id"]).strip())
        except ValueError:
            cid = None
        customer = db.session.get(Customer, cid) if cid else None
        if customer is None:
            return None, None, {"customer": ["The selected customer no longer exists."]}, duplicates
        return customer, None, errors, duplicates

    new = raw.get("new")
    if not isinstance(new, dict):
        return None, None, {"customer": ["Select or register a customer."]}, duplicates
    name = " ".join(str(new.get("full_name") or "").split())
    if len(name) < 2:
        errors.setdefault("customer_name", []).append("Enter the customer's full name.")
    elif len(name) > 150:
        errors.setdefault("customer_name", []).append("Name must be 150 characters or fewer.")
    display, normalized, e = normalize_contact(str(new.get("contact_number") or ""))
    if e:
        errors.setdefault("customer_contact", []).append(e)
    if errors:
        return None, None, errors, duplicates

    duplicate_query = db.select(Customer).where(Customer.contact_normalized == normalized)
    # Minimal directory edit integration: an unchanged number is not a self-duplicate.
    # Existing order-entry callers keep the original behavior (no excluded customer).
    if exclude_customer_id is not None:
        duplicate_query = duplicate_query.where(Customer.id != exclude_customer_id)
    dupes = db.session.scalars(duplicate_query.limit(5)).all()
    if dupes and not raw.get("confirm_duplicate"):
        duplicates = [{"id": c.id, "full_name": c.full_name, "contact_number": c.contact_number} for c in dupes]
        return None, None, {"customer_duplicate": [
            "A customer with this contact number already exists. Use the existing record or confirm to create a new one."
        ]}, duplicates
    return None, {"full_name": name, "contact_number": display, "contact_normalized": normalized}, errors, duplicates


def save_directory_customer(raw, user, customer=None):
    """Approved minimal directory write: existing name/contact validation, no new fields."""
    if not isinstance(raw, dict):
        return None, {"customer": ["Enter the customer's name and contact number."]}, []
    _, values, errors, duplicates = validate_customer(
        {"new": {"full_name": raw.get("full_name"), "contact_number": raw.get("contact_number")},
         "confirm_duplicate": raw.get("confirm_duplicate") is True},
        exclude_customer_id=customer.id if customer else None,
    )
    if errors:
        return None, errors, duplicates
    if customer is None:
        customer = Customer(created_by_id=user.id)
        db.session.add(customer)
    # Update this record only. Historical order name/contact snapshots are immutable here.
    is_new = customer.id is None
    before = {} if is_new else _customer_audit_view(customer)
    customer.full_name = values["full_name"]
    customer.contact_number = values["contact_number"]
    customer.contact_normalized = values["contact_normalized"]
    try:
        if is_new:
            db.session.flush()
            audit.record(audit.AuditAction.CREATE, audit.AuditModule.CUSTOMERS,
                         f"Created customer {customer.full_name}", actor=user, resource_id=customer.id,
                         resource_label=f"Customer {customer.full_name}", new=_customer_audit_view(customer))
        else:
            old_c, new_c = audit.changes(before, _customer_audit_view(customer))
            if new_c:
                audit.record(audit.AuditAction.UPDATE, audit.AuditModule.CUSTOMERS,
                             f"Updated customer {customer.full_name}", actor=user, resource_id=customer.id,
                             resource_label=f"Customer {customer.full_name}", old=old_c, new=new_c)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, {"customer": ["The customer could not be saved. Please try again."]}, []
    return customer, {}, []


def directory_profiles(customers):
    """Read-only directory projection using ORIGINAL order payment properties/reversals."""
    customers = list(customers)
    if not customers:
        return {}
    grouped = {customer.id: [] for customer in customers}
    orders = db.session.scalars(
        db.select(Order).where(Order.customer_id.in_(grouped))
        .options(selectinload(Order.payments)).order_by(Order.created_at.desc(), Order.id.desc())
    ).all()
    for order in orders:
        grouped[order.customer_id].append(order)
    return {customer.id: {
        "customer": customer, "orders": grouped[customer.id],
        "order_count": len(grouped[customer.id]),
        "last_order": grouped[customer.id][0] if grouped[customer.id] else None,
        "paid": sum((order.amount_paid for order in grouped[customer.id]), Decimal("0.00")),
        # Same tracked/positive-balance eligibility as the original finance query.
        "balance": sum((order.balance_due for order in grouped[customer.id]
                        if order.is_payment_tracked and order.balance_due > 0), Decimal("0.00")),
    } for customer in customers}


# ----------------------------------------------------------------------------- creation
def _new_reference() -> str:
    suffix = "".join(secrets.choice(_REF_ALPHABET) for _ in range(5))
    return f"LX-{local_date_code()}-{suffix}"


_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def _clean_submission_token(payload):
    raw = payload.get("submission_token") if isinstance(payload, dict) else None
    if raw in (None, ""):
        return None, None
    if not isinstance(raw, str) or not _TOKEN_RE.match(raw):
        return None, "Invalid submission token. Reload the page and try again."
    return raw, None


def _order_for_token(token):
    return db.session.execute(db.select(Order).filter_by(submission_token=token)).scalar_one_or_none()


def _parse_sms_consent(payload):
    """(consent, error). Absent means "no"; anything that is not a real boolean is rejected."""
    raw = payload.get("sms_consent") if isinstance(payload, dict) else None
    if raw is None:
        return False, None
    if isinstance(raw, bool):
        return raw, None
    return False, "Invalid SMS consent value."


def create_order(payload, user):
    """Validate everything, recalculate prices, and save the order atomically.

    Payment (optional block `payload["payment"]`) is validated against the SERVER total and saved in
    the same transaction. Without that block (older clients) the order is recorded as Pay Later /
    unpaid and counted as received, exactly like before payments existed.

    Returns (order, errors, duplicates). On any failure nothing is written."""
    token, token_error = _clean_submission_token(payload)
    if token_error:
        return None, {"submission_token": [token_error]}, []
    if token:  # a replayed/double-clicked submission returns the order it already created
        existing = _order_for_token(token)
        if existing is not None:
            if existing.created_by_id == user.id:
                return existing, {}, []
            return None, {GENERAL: ["This submission was already used."]}, []

    quote = build_quote(payload)
    errors = {k: list(v) for k, v in quote.errors.items()}

    customer_raw = payload.get("customer") if isinstance(payload, dict) else None
    customer, new_data, cust_errors, duplicates = validate_customer(customer_raw)
    errors.update(cust_errors)

    notes = None
    if isinstance(payload, dict) and payload.get("notes"):
        notes = str(payload["notes"]).strip()
        if len(notes) > MAX_NOTES:
            errors.setdefault("notes", []).append(f"Notes must be {MAX_NOTES} characters or fewer.")
    legacy = not (isinstance(payload, dict) and "payment" in payload)
    plan = None
    if not quote.errors:
        if legacy:
            plan = payment_services.legacy_plan(quote.total)
        else:
            plan = payment_services.validate_payment_plan(payload.get("payment"), quote.total)
            errors.update(plan.errors)
    sms_consent, consent_error = _parse_sms_consent(payload)
    if consent_error:
        errors.setdefault("sms_consent", []).append(consent_error)
    if errors:
        return None, errors, duplicates

    last_exc = None
    for _ in range(5):  # retry only if the random reference collides
        try:
            cust = customer or Customer(created_by_id=user.id, **new_data)
            if customer is None:
                db.session.add(cust)
                db.session.flush()
                audit.record(audit.AuditAction.CREATE, audit.AuditModule.CUSTOMERS,
                             f"Added customer {cust.full_name} while creating an order",
                             actor=user, resource_id=cust.id, resource_label=f"Customer {cust.full_name}",
                             new=_customer_audit_view(cust))
            order = Order(
                reference=_new_reference(), customer_id=cust.id,
                customer_name=cust.full_name, customer_contact=cust.contact_number,
                status=OrderStatus.RECEIVED, subtotal=quote.subtotal,
                discount_total=quote.discount_total, total=quote.total,
                notes=notes, created_by_id=user.id,
                sms_consent=sms_consent, sms_consent_at=utcnow() if sms_consent else None,
                payment_arrangement=plan.arrangement, submission_token=token,
                received_at=utcnow() if legacy else None,
                received_by_id=user.id if legacy else None,
            )
            for line in quote.lines:
                order.items.append(OrderItem(
                    item_type=line.item_type, service_id=line.service_id,
                    package_id=line.package_id, addon_id=line.addon_id,
                    name=line.name, description=line.description, quantity=line.quantity,
                    unit=line.unit, measurement=line.measurement,
                    measurement_unit=line.measurement_unit, unit_price=line.unit_price,
                    line_total=line.line_total, customer_supplied=line.customer_supplied,
                    instructions=line.instructions,
                ))
            order.history.append(OrderStatusHistory(
                from_status=None, to_status=OrderStatus.RECEIVED, changed_by_id=user.id,
                note="Order created",
            ))
            db.session.add(order)
            payment_services.add_payment_rows(order, plan.entries, user, token)
            audit.record(audit.AuditAction.CREATE, audit.AuditModule.ORDERS,
                         f"Created order {order.reference}",
                         actor=user, resource_id=order.reference, resource_label=f"Order {order.reference}",
                         new={"items": len(quote.lines), "total": quote.total,
                              "payment_arrangement": plan.arrangement, "amount_received": plan.received,
                              "balance": plan.balance})
            db.session.commit()
            return order, {}, []
        except IntegrityError as exc:
            db.session.rollback()
            last_exc = exc
            if token:
                existing = _order_for_token(token)
                if existing is not None and existing.created_by_id == user.id:
                    return existing, {}, []
            if customer is not None:
                customer = db.session.get(Customer, customer.id)
        except Exception:
            db.session.rollback()
            raise
    raise last_exc


# ----------------------------------------------------------------------------- status workflow
def allowed_transitions(order, user):
    """List of (status, requires_note). Staff/Admin move forward one step; only Admin may step back."""
    flow = OrderStatus.FLOW
    if order.status not in flow:
        return []
    i = flow.index(order.status)
    moves = []
    if i + 1 < len(flow):
        moves.append((flow[i + 1], False))
    if i > 0 and user.role == Role.ADMIN:
        moves.append((flow[i - 1], True))
    return moves


def change_status(order_id: int, new_status: str, user, note: str = None):
    """Returns (order, error). Locks the row so two users cannot both apply a stale transition."""
    order = db.session.execute(
        db.select(Order).where(Order.id == order_id).with_for_update()
    ).scalar_one_or_none()
    if order is None:
        return None, "Order not found."
    if order.received_at is None:
        db.session.rollback()
        return order, "Confirm that the laundry was received before changing the order status."
    allowed = dict(allowed_transitions(order, user))
    if new_status not in allowed:
        db.session.rollback()
        return order, "That status change is not allowed for this order."
    note = (note or "").strip() or None
    if allowed[new_status] and not note:
        db.session.rollback()
        return order, "A note is required when moving an order back."
    if note and len(note) > 255:
        db.session.rollback()
        return order, "Note must be 255 characters or fewer."
    previous = order.status
    try:
        db.session.add(OrderStatusHistory(
            order_id=order.id, from_status=previous, to_status=new_status,
            changed_by_id=user.id, note=note,
        ))
        order.status = new_status
        audit.record(audit.AuditAction.STATUS_CHANGE, audit.AuditModule.ORDERS,
                     f"Order {order.reference}: {OrderStatus.LABELS.get(previous, previous)} to "
                     f"{OrderStatus.LABELS.get(new_status, new_status)}",
                     actor=user, resource_id=order.reference, resource_label=f"Order {order.reference}",
                     old={"status": OrderStatus.LABELS.get(previous, previous)},
                     new={"status": OrderStatus.LABELS.get(new_status, new_status), "note": note})
        if new_status == OrderStatus.READY and previous != OrderStatus.READY:
            # One row per order (unique constraint): a later return to Ready finds it and adds nothing.
            sms_services.create_ready_notification(order)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    if new_status == OrderStatus.READY:
        # Only now, with the status change safely committed and no lock held, may the provider be contacted.
        sms_services.submit_after_commit(order.id)
    return order, None


def confirm_received(order_id: int, user):
    """Staff confirm the physical laundry is in the shop. This is NOT a payment event and never
    touches payment status. Returns (order, error, already_confirmed)."""
    order = db.session.execute(
        db.select(Order).where(Order.id == order_id).with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if order is None:
        return None, "Order not found.", False
    if order.received_at is not None:
        db.session.rollback()
        return order, None, True
    try:
        order.received_at = utcnow()
        order.received_by_id = user.id
        order.history.append(OrderStatusHistory(
            from_status=order.status, to_status=order.status, changed_by_id=user.id,
            note="Laundry received by the shop",
        ))
        audit.record(audit.AuditAction.UPDATE, audit.AuditModule.ORDERS,
                     f"Order {order.reference}: laundry confirmed as received",
                     actor=user, resource_id=order.reference, resource_label=f"Order {order.reference}",
                     old={"laundry_received": False}, new={"laundry_received": True})
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return order, None, False


# ----------------------------------------------------------------------------- listing / stats
PAGE_SIZE = 15


def order_query(term=None, status=None, payment=None):
    # Reuse the original ledger-derived predicate before pagination. No client-side
    # filtering and no change to recording/reversal or payment-status rules.
    q = (payment_services.orders_by_payment_status(payment)
         if payment in ("unpaid", "partial", "paid") else db.select(Order))
    term = (term or "").strip()
    if term:
        like = f"%{_like_escape(term)}%"
        cond = [Order.reference.ilike(like, escape="\\"), Order.customer_name.ilike(like, escape="\\")]
        digits = re.sub(r"\D", "", term)
        if len(digits) >= 3:
            cond.append(Order.customer_contact.like(f"%{digits}%"))
        q = q.where(or_(*cond))
    if status in OrderStatus.FLOW:
        q = q.where(Order.status == status)
    return q.order_by(None).order_by(Order.created_at.desc(), Order.id.desc())


def status_counts():
    rows = db.session.execute(
        db.select(Order.status, func.count(Order.id)).group_by(Order.status)
    ).all()
    counts = {s: 0 for s in OrderStatus.FLOW}
    counts.update({s: n for s, n in rows})
    return counts


def dashboard_stats():
    start, end = local_today_bounds_utc()
    counts = status_counts()
    today = db.session.scalar(
        db.select(func.count(Order.id)).where(Order.created_at >= start, Order.created_at < end)
    )
    recent = db.session.execute(
        db.select(Order).order_by(Order.created_at.desc(), Order.id.desc()).limit(6)
    ).scalars().all()
    popular = db.session.execute(
        db.select(OrderItem.name, func.count(OrderItem.id).label("n"))
        .where(OrderItem.item_type != "addon")
        .group_by(OrderItem.name).order_by(func.count(OrderItem.id).desc()).limit(5)
    ).all()
    owing_count, owing_total = payment_services.outstanding_summary()
    awaiting = db.session.scalar(db.select(func.count(Order.id)).where(Order.received_at.is_(None)))
    return {
        "owing_count": owing_count, "owing_total": owing_total, "awaiting_receipt": awaiting or 0,
        "collected_today": payment_services.collections_total(start, end),
        "total_orders": sum(counts.values()), "today": today or 0, "counts": counts,
        "pending": counts[OrderStatus.RECEIVED] + counts[OrderStatus.PENDING],
        "processing": counts[OrderStatus.PROCESSING], "ready": counts[OrderStatus.READY],
        "recent": recent, "popular": popular,
    }
