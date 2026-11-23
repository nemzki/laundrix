"""Jinja template filters used in the HTML templates.

Examples: `{{ amount|peso }}` formats money, `{{ date|localdt }}` shows local time, and the
label/tone filters turn status codes into readable text and badge colours."""

from decimal import Decimal

from app.core import bp
from app.core.timeutil import to_local
from app.models.order import OrderStatus
from app.models.payment import PaymentArrangement, PaymentStatus


@bp.app_template_filter("peso")
def peso(value):
    """Format a number as Philippine pesos, e.g. 1500 -> ₱1,500.00 (empty value shows a dash)."""
    if value is None:
        return "\u2014"
    return f"\u20b1{Decimal(value):,.2f}"


@bp.app_template_filter("localdt")
def localdt(value, fmt="%b %d, %Y %I:%M %p"):
    """Convert a stored UTC datetime to shop time and format it as text (empty value shows a dash)."""
    local = to_local(value)
    return local.strftime(fmt) if local else "\u2014"


@bp.app_template_filter("qty")
def qty(value):
    """Trim trailing zeros: 2.50 -> 2.5, 3.00 -> 3."""
    if value is None:
        return ""
    text = f"{Decimal(value):f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


@bp.app_template_filter("status_label")
def status_label(value):
    """Turn an order status code into its readable name (e.g. 'ready_for_pickup' -> 'Ready for Pickup')."""
    return OrderStatus.LABELS.get(value, value)


@bp.app_template_filter("status_tone")
def status_tone(value):
    """Return the badge colour name for an order status."""
    return OrderStatus.TONES.get(value, "neutral")

@bp.app_template_filter("payment_status_label")
def payment_status_label(value):
    """Turn a payment status code into its readable name."""
    return PaymentStatus.LABELS.get(value, value)


@bp.app_template_filter("payment_status_tone")
def payment_status_tone(value):
    """Return the badge colour name for a payment status."""
    return PaymentStatus.TONES.get(value, "neutral")

@bp.app_template_filter("arrangement_label")
def arrangement_label(value):
    """Turn a payment arrangement (full / partial / pay later) into its readable name."""
    return PaymentArrangement.LABELS.get(value, "Not recorded")
