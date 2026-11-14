"""Central audit logging service.

HOW TO LOG SOMETHING (from any module)::

    from app.audit import services as audit
    audit.record(audit.AuditAction.UPDATE, audit.AuditModule.CUSTOMERS,
                 "Updated customer Ana Cruz", resource_id=customer.id,
                 resource_label=f"Customer {customer.full_name}", old=old, new=new)
    db.session.commit()          # the audit row is saved in the SAME transaction as the change

TRANSACTION STRATEGY
  * `record()` only adds the row to the current SQLAlchemy session. It is committed (or rolled
    back) together with the business change it describes, so the two succeed or fail as one.
  * `record()` never swallows exceptions. If the audit row cannot be saved, the commit fails, the
    business change is rolled back and the request errors out: nothing silently "succeeds" without
    its audit record.
  * Events with no business change of their own (failed sign-in) pass `commit=True`.

NEVER pass passwords, hashes, tokens, API keys or verification data. `sanitize_values()` also drops
any key that looks sensitive and masks phone numbers / e-mail addresses, as a safety net.
"""
import json
import re
from datetime import date, datetime
from decimal import Decimal

from flask import has_request_context, request
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog, User


# ----------------------------------------------------------------------------- vocabulary
class AuditAction:
    LOGIN, LOGIN_FAILED, LOGOUT = "login", "login_failed", "logout"
    CREATE, UPDATE, DELETE = "create", "update", "delete"
    STATUS_CHANGE, PRICE_CHANGE = "status_change", "price_change"
    PAYMENT, REVERSAL = "payment", "reversal"
    APPROVE, REJECT, SUSPEND = "approve", "reject", "suspend"
    REACTIVATE, DEACTIVATE, ENROLL = "reactivate", "deactivate", "enroll"

    LABELS = {
        LOGIN: "Sign in", LOGIN_FAILED: "Failed sign in", LOGOUT: "Sign out",
        CREATE: "Create", UPDATE: "Update", DELETE: "Delete",
        STATUS_CHANGE: "Order status change", PRICE_CHANGE: "Price change",
        PAYMENT: "Payment recorded", REVERSAL: "Payment reversal",
        APPROVE: "Approve account", REJECT: "Reject account", SUSPEND: "Suspend account",
        REACTIVATE: "Reactivate", DEACTIVATE: "Deactivate", ENROLL: "Staff enrollment",
    }
    ALL = tuple(LABELS)
    # Tone for the badge in the UI.
    TONES = {
        LOGIN: "info", LOGIN_FAILED: "danger", LOGOUT: "neutral", CREATE: "success",
        UPDATE: "info", DELETE: "danger", STATUS_CHANGE: "progress", PRICE_CHANGE: "warn",
        PAYMENT: "success", REVERSAL: "danger", APPROVE: "success", REJECT: "danger",
        SUSPEND: "danger", REACTIVATE: "success", DEACTIVATE: "warn", ENROLL: "info",
    }


class AuditModule:
    AUTH, ACCOUNTS, ORDERS, CUSTOMERS = "auth", "accounts", "orders", "customers"
    PAYMENTS, SERVICES, SETTINGS = "payments", "services", "settings"

    LABELS = {
        AUTH: "Authentication", ACCOUNTS: "Accounts & Staff", ORDERS: "Orders",
        CUSTOMERS: "Customers", PAYMENTS: "Payments", SERVICES: "Services & Pricing",
        SETTINGS: "Settings",
    }
    ALL = tuple(LABELS)


# ----------------------------------------------------------------------------- sanitising
# Keys containing any of these are DROPPED (never stored), whatever their value.
_SENSITIVE_PARTS = (
    "password", "passwd", "hash", "token", "secret", "apikey", "api_key", "credential", "session",
    "cookie", "authoriz", "signature", "biometric", "embedding", "selfie", "private_key", "csrf",
)
_SENSITIVE_TOKENS = {"otp", "pin", "pwd"}
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_EMAILISH = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,}$")
MAX_TEXT = 200
MAX_KEYS = 30
MAX_JSON_BYTES = 4000


def _is_sensitive_key(key) -> bool:
    low = str(key).lower()
    if any(part in low for part in _SENSITIVE_PARTS):
        return True
    return bool(_SENSITIVE_TOKENS & set(re.split(r"[^a-z0-9]+", low)))


def mask_phone(text: str) -> str:
    digits = re.sub(r"\D", "", text)
    return ("\u2022" * 4 + digits[-4:]) if len(digits) > 4 else "\u2022" * len(digits)


def mask_email(text: str) -> str:
    local, _, domain = text.partition("@")
    return f"{local[:1]}***@{domain}" if domain else text


def _clean_value(value, key="", depth=0):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return sanitize_values(value, depth + 1) if depth < 2 else str(value)[:MAX_TEXT]
    if isinstance(value, (list, tuple, set)):
        return [_clean_value(v, key, depth + 1) for v in list(value)[:20]] if depth < 2 else None
    text = _CONTROL.sub("", str(value)).strip()
    low = str(key).lower()
    if any(p in low for p in ("phone", "contact", "mobile")):
        text = mask_phone(text)
    elif "email" in low and _EMAILISH.match(text):
        text = mask_email(text)
    return text[:MAX_TEXT]


def sanitize_values(values, depth=0):
    """Return a JSON-safe copy of `values` without sensitive keys; None if nothing is left."""
    if not isinstance(values, dict):
        return None
    clean = {}
    for key, value in values.items():
        if len(clean) >= MAX_KEYS:
            break
        if _is_sensitive_key(key):
            continue
        clean[str(key)[:60]] = _clean_value(value, key, depth)
    if depth == 0 and len(json.dumps(clean, default=str)) > MAX_JSON_BYTES:
        return {"_note": "Details were too large to store."}
    return clean or None


def snapshot(obj, fields):
    """{field: value} for the listed attributes of a model object (use before and after a change)."""
    return {name: getattr(obj, name, None) for name in fields}


def changes(old, new):
    """(old, new) reduced to the sanitised fields whose value actually changed."""
    old_c, new_c = sanitize_values(old or {}) or {}, sanitize_values(new or {}) or {}
    keys = [k for k in dict.fromkeys([*old_c, *new_c]) if old_c.get(k) != new_c.get(k)]
    return ({k: old_c.get(k) for k in keys} or None, {k: new_c.get(k) for k in keys} or None)


# ----------------------------------------------------------------------------- recording
_UNSET = object()


def _text(value, limit):
    return _CONTROL.sub("", str(value or "")).strip()[:limit]


def _current_actor():
    if not has_request_context():
        return None
    user = current_user._get_current_object()
    return user if isinstance(user, User) else None


def record(action, module, description, *, actor=_UNSET, actor_name=None, resource_id=None,
           resource_label=None, old=None, new=None, success=True, ip=_UNSET, commit=False):
    """Add one audit row to the current transaction. See the module docstring.

    actor: a User, None (= the system / a command-line action), or omitted (= the signed-in user).
    old/new: dicts of the *changed* fields only; they are sanitised here.
    """
    if action not in AuditAction.ALL:
        raise ValueError(f"Unknown audit action: {action!r}")
    if module not in AuditModule.ALL:
        raise ValueError(f"Unknown audit module: {module!r}")
    description = _text(description, 500)
    if not description:
        raise ValueError("An audit record needs a description.")

    user = _current_actor() if actor is _UNSET else actor
    name = _text(actor_name, 150) or (
        _text(user.full_name or user.email, 150) if user is not None else "System")
    if ip is _UNSET:
        ip = (request.remote_addr or "")[:45] if has_request_context() else None

    row = AuditLog(
        actor_id=getattr(user, "id", None), actor_name=name,
        actor_role=getattr(user, "role", None), action=action, module=module,
        resource_id=_text(resource_id, 64) or None, resource_label=_text(resource_label, 150) or None,
        description=description, old_values=sanitize_values(old), new_values=sanitize_values(new),
        success=bool(success), ip_address=ip or None,
    )
    db.session.add(row)
    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    return row


# ----------------------------------------------------------------------------- bridges
# Auth/account events and payment events were already being logged in their own tables. Those
# writers now also call the functions below, so every such event appears here too without
# touching each call site.
A, M = AuditAction, AuditModule

# event -> (action, module, description template, append the reason from `detail`?)
AUTH_EVENTS = {
    "admin_login": (A.LOGIN, M.AUTH, "Administrator signed in with password", False),
    "password_login_success": (A.LOGIN, M.AUTH, "Signed in with email and password", False),
    "face_login_success": (A.LOGIN, M.AUTH, "Signed in with Face Login", False),
    "google_login_success": (A.LOGIN, M.AUTH, "Signed in with Google", False),
    "admin_login_failed": (A.LOGIN_FAILED, M.AUTH, "Failed administrator sign-in for {who}", False),
    "password_login_failed": (A.LOGIN_FAILED, M.AUTH, "Failed sign-in for {who}", False),
    "login_failed": (A.LOGIN_FAILED, M.AUTH, "Failed sign-in for {who}", False),
    "face_login_failed": (A.LOGIN_FAILED, M.AUTH, "Face Login did not recognise the person", False),
    "google_login_failed": (A.LOGIN_FAILED, M.AUTH, "Google sign-in refused for {who}", False),
    "admin_login_locked": (A.LOGIN_FAILED, M.AUTH, "Sign-in blocked: administrator account {who} is locked", False),
    "password_login_locked": (A.LOGIN_FAILED, M.AUTH, "Sign-in blocked: account {who} is locked", False),
    "login_pending_approval": (A.LOGIN_FAILED, M.AUTH, "Sign-in refused: {who} is awaiting approval", False),
    "password_login_not_enrolled": (A.LOGIN_FAILED, M.AUTH, "Sign-in refused: {who} has not finished enrollment", False),
    "logout": (A.LOGOUT, M.AUTH, "Signed out", False),
    "admin_bootstrap": (A.CREATE, M.ACCOUNTS, "Initial administrator account created", False),
    "admin_password_rotated": (A.UPDATE, M.ACCOUNTS, "Password changed for {target}", False),
    "staff_created": (A.CREATE, M.ACCOUNTS, "Created staff account for {target}", False),
    "staff_enroll_link_issued": (A.UPDATE, M.ACCOUNTS, "Issued a new enrollment link for {target}", False),
    "staff_verification_completed": (A.UPDATE, M.ACCOUNTS, "Identity verification completed for {target}; awaiting approval", False),
    "staff_approved": (A.APPROVE, M.ACCOUNTS, "Approved staff account {target}", False),
    "staff_rejected": (A.REJECT, M.ACCOUNTS, "Rejected staff account {target}", True),
    "staff_suspended": (A.SUSPEND, M.ACCOUNTS, "Suspended staff account {target}", True),
    "staff_reactivated": (A.REACTIVATE, M.ACCOUNTS, "Reactivated staff account {target}", False),
    "staff_deactivated": (A.DEACTIVATE, M.ACCOUNTS, "Deactivated staff account {target}", True),
    "enroll_started": (A.ENROLL, M.ACCOUNTS, "{target} started enrollment", False),
    "enroll_didit_started": (A.ENROLL, M.ACCOUNTS, "{target} began identity verification", False),
    "enrolled": (A.ENROLL, M.ACCOUNTS, "{target} completed enrollment", False),
    "enroll_rejected": (A.ENROLL, M.ACCOUNTS, "Identity verification failed for {target}", False),
}


def _label(user, fallback="an unknown account"):
    return _text(user.full_name or user.email, 150) if user is not None else fallback


def audit_auth_event(event, *, success=True, actor=None, target=None, email=None, detail=None):
    """Mirror one AuthEvent into the audit log (same transaction, no commit)."""
    action, module, template, with_reason = AUTH_EVENTS.get(
        event, (A.UPDATE, M.ACCOUNTS, _text(event, 40).replace("_", " ").capitalize(), False))
    about = target or actor
    typed = _text(email, 150) if email and _EMAILISH.match(str(email).strip()) else ""
    who = _label(about, "") or typed or "an unknown account"      # only an e-mail-like identifier is kept
    description = template.format(who=who, target=_label(about, "an account"))
    if with_reason and detail and ": " in detail:
        description += f". Reason: {detail.split(': ', 1)[1]}"
    sign_in_failure = action == A.LOGIN_FAILED
    return record(
        action, module, description,
        # Nobody is authenticated on a failed sign-in: show who it was *attempted* as.
        actor=None if sign_in_failure else actor,
        actor_name=(_label(about, "") or typed or "Unknown") if sign_in_failure else None,
        resource_id=getattr(about, "id", None),
        resource_label=f"Account: {_label(about)}" if about is not None else None,
        success=success,
    )


# payment event -> (action, module, description prefix)
PAYMENT_EVENTS = {
    "payment_recorded": (A.PAYMENT, M.PAYMENTS, "Recorded payment"),
    "payment_reversed": (A.REVERSAL, M.PAYMENTS, "Reversed payment"),
    "settings_updated": (A.UPDATE, M.SETTINGS, "Payment settings updated"),
    "method_created": (A.CREATE, M.SETTINGS, "Payment method"),
    "method_toggled": (A.UPDATE, M.SETTINGS, "Payment method"),
    "qr_uploaded": (A.UPDATE, M.SETTINGS, "Payment QR"),
    "qr_removed": (A.DELETE, M.SETTINGS, "Payment QR"),
}


def audit_payment_event(event, user=None, order=None, payment=None, detail=None, old=None, new=None):
    """Mirror one PaymentEvent into the audit log (same transaction, no commit)."""
    action, module, prefix = PAYMENT_EVENTS.get(event, (A.UPDATE, M.PAYMENTS, _text(event, 40)))
    reference = getattr(order, "reference", None)
    if reference:
        description = f"{prefix} on order {reference}" + (f": {detail}" if detail else "")
        resource_id, resource_label = reference, f"Order {reference}"
    else:
        description = f"{prefix}: {detail}" if detail else prefix
        resource_id, resource_label = None, "Payment settings"
    if new is None and payment is not None:
        new = {"amount": payment.amount, "method": payment.method_label}
    return record(action, module, description, actor=user, resource_id=resource_id,
                  resource_label=resource_label, old=old, new=new)
