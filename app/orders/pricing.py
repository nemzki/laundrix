"""Server-side pricing and compatibility engine.

The browser sends only *what* was chosen (ids, measurements, quantities). Every price, unit and
total is read from the database here. Nothing in this module trusts a submitted amount."""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.extensions import db
from app.models import ItemType, PackageMeasure, PricingUnit, Service, ServiceAddon, ServicePackage

CENT = Decimal("0.01")
GENERAL = "_general"

# (min, max, decimal places allowed) per billing unit.
SERVICE_LIMITS = {
    PricingUnit.KG: (Decimal("0.1"), Decimal("200"), 2),
    PricingUnit.LOAD: (Decimal("1"), Decimal("50"), 0),
    PricingUnit.PIECE: (Decimal("1"), Decimal("500"), 0),
}
PACKAGE_QTY = (Decimal("1"), Decimal("20"), 0)
ADDON_QTY = (Decimal("1"), Decimal("99"), 0)
MAX_TEXT = 255


def money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def parse_number(raw, label, lo, hi, places):
    """Return (Decimal, None) or (None, message). Rejects NaN/inf, bools, junk and excess precision."""
    if isinstance(raw, bool) or raw is None:
        return None, f"{label} is required."
    text = str(raw).strip()
    if not text or len(text) > 12:
        return None, f"{label} is required." if not text else f"{label} is not a valid number."
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None, f"{label} must be a number."
    if not value.is_finite():
        return None, f"{label} must be a number."
    if value.as_tuple().exponent < -places:
        return None, (f"{label} must be a whole number." if places == 0
                      else f"{label} can have at most {places} decimal places.")
    if value < lo or value > hi:
        return None, f"{label} must be between {lo.normalize():f} and {hi.normalize():f}."
    return value, None


def _id(raw):
    if isinstance(raw, bool):
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


@dataclass
class QuoteLine:
    key: str
    item_type: str
    name: str
    description: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    line_total: Decimal
    service_id: int = None
    package_id: int = None
    addon_id: int = None
    measurement: Decimal = None
    measurement_unit: str = None
    customer_supplied: bool = False
    instructions: str = None


@dataclass
class Quote:
    lines: list = field(default_factory=list)
    errors: dict = field(default_factory=dict)
    subtotal: Decimal = Decimal("0.00")
    discount_total: Decimal = Decimal("0.00")  # discounts are not implemented: always zero
    total: Decimal = Decimal("0.00")

    @property
    def ok(self) -> bool:
        return not self.errors

    def err(self, key, message):
        self.errors.setdefault(key, []).append(message)


def _instructions(raw, quote, key):
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    if len(text) > MAX_TEXT:
        quote.err(key, f"Instructions must be {MAX_TEXT} characters or fewer.")
        return None
    return text or None


def _as_list(value):
    return value if isinstance(value, list) else []


def build_quote(payload) -> Quote:
    quote = Quote()
    if not isinstance(payload, dict):
        quote.err(GENERAL, "Invalid request.")
        return quote

    raw_items = _as_list(payload.get("items"))
    raw_extras = _as_list(payload.get("extras"))

    selected_service_codes, selected_packages = {}, []
    seen = set()

    # ---- 1) packages first, so we know which services they already include
    for raw in raw_items:
        if isinstance(raw, dict) and raw.get("kind") == ItemType.PACKAGE:
            _add_package(quote, raw, seen, selected_packages)
    covered = {}
    for pkg in selected_packages:
        for code in pkg.covered_codes:
            covered.setdefault(code, pkg)

    # ---- 2) individual services
    for raw in raw_items:
        if isinstance(raw, dict) and raw.get("kind") == ItemType.SERVICE:
            _add_service(quote, raw, seen, covered, selected_service_codes)
        elif not isinstance(raw, dict) or raw.get("kind") not in (ItemType.SERVICE, ItemType.PACKAGE):
            quote.err(GENERAL, "One of the selected items is invalid.")

    if not any(l.item_type in (ItemType.SERVICE, ItemType.PACKAGE) for l in quote.lines) and not quote.errors:
        quote.err(GENERAL, "Select at least one service or package.")

    # ---- 3) extras
    for raw in raw_extras:
        _add_extra(quote, raw, seen)

    if quote.errors:
        # Never expose a half-calculated total.
        quote.lines, quote.subtotal, quote.total = [], Decimal("0.00"), Decimal("0.00")
        return quote

    quote.subtotal = money(sum((l.line_total for l in quote.lines), Decimal("0")))
    quote.total = money(quote.subtotal - quote.discount_total)
    return quote


def _add_package(quote, raw, seen, selected_packages):
    pid = _id(raw.get("id"))
    key = f"package:{pid}"
    pkg = db.session.get(ServicePackage, pid) if pid else None
    if pkg is None or not pkg.is_active:
        quote.err(GENERAL, "A selected package is no longer available.")
        return
    if key in seen:
        quote.err(key, "This package was selected twice. Increase the quantity instead.")
        return
    seen.add(key)

    label = "Weight" if pkg.measure_type == PackageMeasure.WEIGHT else "Number of pieces"
    places = 2 if pkg.measure_type == PackageMeasure.WEIGHT else 0
    measurement, e = parse_number(raw.get("measurement"), label,
                                  Decimal(pkg.min_value), Decimal(pkg.max_value), places)
    if e:
        quote.err(key, f"{pkg.display_name}: {e}")
    count, e2 = parse_number(raw.get("quantity", 1), "Package quantity", *PACKAGE_QTY)
    if e2:
        quote.err(key, f"{pkg.display_name}: {e2}")
    instructions = _instructions(raw.get("instructions"), quote, key)
    if e or e2:
        return

    selected_packages.append(pkg)
    desc = pkg.display_name + (f" ({pkg.size_label})" if pkg.size_label else "")
    quote.lines.append(QuoteLine(
        key=key, item_type=ItemType.PACKAGE, package_id=pkg.id,
        name=pkg.name, description=desc, quantity=count, unit="package",
        measurement=measurement, measurement_unit=pkg.unit_label,
        unit_price=money(pkg.price), line_total=money(Decimal(pkg.price) * count),
        instructions=instructions,
    ))


def _add_service(quote, raw, seen, covered, selected_codes):
    sid = _id(raw.get("id"))
    key = f"service:{sid}"
    svc = db.session.get(Service, sid) if sid else None
    if svc is None or not svc.is_active:
        quote.err(GENERAL, "A selected service is no longer available.")
        return
    if not svc.pricing_unit:
        quote.err(key, f"{svc.name} cannot be ordered yet: its pricing unit has not been configured by an Admin.")
        return
    if key in seen:
        quote.err(key, f"{svc.name} was selected twice.")
        return
    seen.add(key)
    if svc.code in covered:
        quote.err(key, f"{svc.name} is already included in the selected package "
                       f"({covered[svc.code].display_name}) and would be charged twice.")
        return

    lo, hi, places = SERVICE_LIMITS[svc.pricing_unit]
    unit_word = {"kg": "Weight (kg)", "load": "Number of loads", "piece": "Number of pieces"}[svc.pricing_unit]
    qty, e = parse_number(raw.get("quantity"), unit_word, lo, hi, places)
    instructions = _instructions(raw.get("instructions"), quote, key)
    if e:
        quote.err(key, f"{svc.name}: {e}")
        return
    selected_codes[svc.code] = svc
    quote.lines.append(QuoteLine(
        key=key, item_type=ItemType.SERVICE, service_id=svc.id,
        name=svc.name, description=svc.description, quantity=qty, unit=svc.pricing_unit,
        unit_price=money(svc.price), line_total=money(Decimal(svc.price) * qty),
        instructions=instructions,
    ))


def _add_extra(quote, raw, seen):
    if not isinstance(raw, dict):
        quote.err(GENERAL, "One of the selected extras is invalid.")
        return
    aid = _id(raw.get("id"))
    key = f"addon:{aid}"
    addon = db.session.get(ServiceAddon, aid) if aid else None
    if addon is None or not addon.is_active:
        quote.err(GENERAL, "A selected extra is no longer available.")
        return
    if key in seen:
        quote.err(key, f"{addon.name} was selected twice.")
        return
    seen.add(key)

    mode = raw.get("mode")
    qty, e = parse_number(raw.get("quantity", 1), f"{addon.name} quantity", *ADDON_QTY)
    if e:
        quote.err(key, e)
        return
    if mode == "customer_supplied":
        if not addon.allow_customer_supplied:
            quote.err(key, f"{addon.name} cannot be customer-supplied.")
            return
        unit_price, supplied = Decimal("0.00"), True
    elif mode == "paid":
        if not addon.is_chargeable:
            quote.err(key, f"{addon.name} is not available as a paid extra.")
            return
        unit_price, supplied = money(addon.price), False
    else:
        quote.err(key, f"Choose paid or customer-supplied for {addon.name}.")
        return
    quote.lines.append(QuoteLine(
        key=key, item_type=ItemType.ADDON, addon_id=addon.id,
        name=addon.name, description="Customer-supplied" if supplied else addon.description,
        quantity=qty, unit="unit", unit_price=unit_price,
        line_total=money(unit_price * qty), customer_supplied=supplied,
    ))
