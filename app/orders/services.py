"""Order business logic: customers, creation (single transaction), status workflow, statistics."""
import re
import secrets
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.core.timeutil import local_date_code, local_today_bounds_utc
from app.extensions import db
from app.models import (
    Customer, Order, OrderItem, OrderStatus, OrderStatusHistory, Role,
)
from app.orders.pricing import GENERAL, build_quote

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


def validate_customer(raw):
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

    dupes = db.session.execute(
        db.select(Customer).where(Customer.contact_normalized == normalized).limit(5)
    ).scalars().all()
    if dupes and not raw.get("confirm_duplicate"):
        duplicates = [{"id": c.id, "full_name": c.full_name, "contact_number": c.contact_number} for c in dupes]
        return None, None, {"customer_duplicate": [
            "A customer with this contact number already exists. Use the existing record or confirm to create a new one."
        ]}, duplicates
    return None, {"full_name": name, "contact_number": display, "contact_normalized": normalized}, errors, duplicates


# ----------------------------------------------------------------------------- creation
def _new_reference() -> str:
    suffix = "".join(secrets.choice(_REF_ALPHABET) for _ in range(5))
    return f"LX-{local_date_code()}-{suffix}"


def create_order(payload, user):
    """Validate everything, recalculate prices, and save the order atomically.

    Returns (order, errors, duplicates). On any failure nothing is written."""
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
    if errors:
        return None, errors, duplicates

    last_exc = None
    for _ in range(5):  # retry only if the random reference collides
        try:
            cust = customer or Customer(created_by_id=user.id, **new_data)
            if customer is None:
                db.session.add(cust)
                db.session.flush()
            order = Order(
                reference=_new_reference(), customer_id=cust.id,
                customer_name=cust.full_name, customer_contact=cust.contact_number,
                status=OrderStatus.RECEIVED, subtotal=quote.subtotal,
                discount_total=quote.discount_total, total=quote.total,
                notes=notes, created_by_id=user.id,
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
            db.session.commit()
            return order, {}, []
        except IntegrityError as exc:
            db.session.rollback()
            last_exc = exc
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
    try:
        db.session.add(OrderStatusHistory(
            order_id=order.id, from_status=order.status, to_status=new_status,
            changed_by_id=user.id, note=note,
        ))
        order.status = new_status
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return order, None


# ----------------------------------------------------------------------------- listing / stats
PAGE_SIZE = 15


def order_query(term=None, status=None):
    q = db.select(Order)
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
    return q.order_by(Order.created_at.desc(), Order.id.desc())


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
    return {
        "total_orders": sum(counts.values()), "today": today or 0, "counts": counts,
        "pending": counts[OrderStatus.RECEIVED] + counts[OrderStatus.PENDING],
        "processing": counts[OrderStatus.PROCESSING], "ready": counts[OrderStatus.READY],
        "recent": recent, "popular": popular,
    }
