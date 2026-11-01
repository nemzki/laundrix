from decimal import Decimal

from app.core import bp
from app.core.timeutil import to_local
from app.models.order import OrderStatus


@bp.app_template_filter("peso")
def peso(value):
    if value is None:
        return "\u2014"
    return f"\u20b1{Decimal(value):,.2f}"


@bp.app_template_filter("localdt")
def localdt(value, fmt="%b %d, %Y %I:%M %p"):
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
    return OrderStatus.LABELS.get(value, value)


@bp.app_template_filter("status_tone")
def status_tone(value):
    return OrderStatus.TONES.get(value, "neutral")
