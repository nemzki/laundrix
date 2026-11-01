"""Parsing + validation of the Admin catalog forms (server side; nothing here trusts the browser)."""
import re
from decimal import Decimal

from app.extensions import db
from app.models import ICON_KEYS, PackageMeasure, PricingUnit, Service, ServiceAddon
from app.orders.pricing import parse_number

CODE_RE = re.compile(r"^[a-z0-9_]{2,40}$")
MAX_PRICE = Decimal("99999.99")


def _text(form, name, *, required=False, max_len=255, label=None):
    value = " ".join((form.get(name) or "").split())
    label = label or name.replace("_", " ").capitalize()
    if required and not value:
        return value, f"{label} is required."
    if len(value) > max_len:
        return value, f"{label} must be {max_len} characters or fewer."
    return value, None


def _price(form):
    return parse_number(form.get("price"), "Price", Decimal("0"), MAX_PRICE, 2)


def _image_url(form, errors):
    value = (form.get("image_url") or "").strip()
    if not value:
        return None
    # Only same-site paths are allowed (the Content-Security-Policy only permits 'self' images).
    if not value.startswith("/") or value.startswith("//") or len(value) > 500 or " " in value:
        errors["image_url"] = "Use a local path starting with a single slash, e.g. /static/img/wash.png."
        return None
    return value


def _icon(form, errors, default):
    value = form.get("icon_key") or default
    if value not in ICON_KEYS:
        errors["icon_key"] = "Choose a valid icon."
    return value


def _checked(form, name):
    return form.get(name) in ("on", "1", "true")


def parse_service(form, existing=None):
    errors, data = {}, {}
    data["name"], e = _text(form, "name", required=True, max_len=120)
    e and errors.__setitem__("name", e)
    data["category"], e = _text(form, "category", required=True, max_len=80)
    e and errors.__setitem__("category", e)
    data["description"], e = _text(form, "description", max_len=255)
    e and errors.__setitem__("description", e)
    data["description"] = data["description"] or None

    price, e = _price(form)
    e and errors.__setitem__("price", e)
    data["price"] = price

    unit = (form.get("pricing_unit") or "").strip()
    if unit and unit not in PricingUnit.ALL:
        errors["pricing_unit"] = "Choose a valid pricing unit."
    data["pricing_unit"] = unit or None

    data["icon_key"] = _icon(form, errors, "generic")
    data["image_url"] = _image_url(form, errors)
    data["is_active"] = _checked(form, "is_active")

    if existing is None:
        code = (form.get("code") or "").strip().lower()
        if not CODE_RE.match(code):
            errors["code"] = "Code must be 2-40 characters: lowercase letters, numbers, underscores."
        elif db.session.execute(db.select(Service).filter_by(code=code)).scalar_one_or_none():
            errors["code"] = "A service with this code already exists."
        data["code"] = code
    return data, errors


def parse_addon(form, existing=None):
    errors, data = {}, {}
    data["name"], e = _text(form, "name", required=True, max_len=120)
    e and errors.__setitem__("name", e)
    data["description"], e = _text(form, "description", max_len=255)
    e and errors.__setitem__("description", e)
    data["description"] = data["description"] or None
    price, e = _price(form)
    e and errors.__setitem__("price", e)
    data["price"] = price
    data["is_chargeable"] = _checked(form, "is_chargeable")
    data["allow_customer_supplied"] = _checked(form, "allow_customer_supplied")
    if not data["is_chargeable"] and not data["allow_customer_supplied"]:
        errors["is_chargeable"] = "An extra must be chargeable, customer-suppliable, or both."
    data["icon_key"] = _icon(form, errors, "generic")
    data["image_url"] = _image_url(form, errors)
    data["is_active"] = _checked(form, "is_active")
    if existing is None:
        code = (form.get("code") or "").strip().lower()
        if not CODE_RE.match(code):
            errors["code"] = "Code must be 2-40 characters: lowercase letters, numbers, underscores."
        elif db.session.execute(db.select(ServiceAddon).filter_by(code=code)).scalar_one_or_none():
            errors["code"] = "An extra with this code already exists."
        data["code"] = code
    return data, errors


def parse_package(form, existing=None):
    errors, data = {}, {}
    data["name"], e = _text(form, "name", required=True, max_len=120)
    e and errors.__setitem__("name", e)
    data["category"], e = _text(form, "category", required=True, max_len=80)
    e and errors.__setitem__("category", e)
    data["description"], e = _text(form, "description", required=True, max_len=120, label="Package description")
    e and errors.__setitem__("description", e)
    size, e = _text(form, "size_label", max_len=40)
    e and errors.__setitem__("size_label", e)
    data["size_label"] = size or None

    measure = form.get("measure_type")
    if measure not in PackageMeasure.ALL:
        errors["measure_type"] = "Choose weight or pieces."
    data["measure_type"] = measure
    places = 2 if measure == PackageMeasure.WEIGHT else 0
    lo, e1 = parse_number(form.get("min_value"), "Minimum", Decimal("0.01"), Decimal("9999"), places)
    hi, e2 = parse_number(form.get("max_value"), "Maximum", Decimal("0.01"), Decimal("9999"), places)
    e1 and errors.__setitem__("min_value", e1)
    e2 and errors.__setitem__("max_value", e2)
    if lo is not None and hi is not None and hi < lo:
        errors["max_value"] = "Maximum must be greater than or equal to the minimum."
    data["min_value"], data["max_value"] = lo, hi

    price, e = _price(form)
    e and errors.__setitem__("price", e)
    data["price"] = price

    valid_codes = set(db.session.scalars(db.select(Service.code)).all())
    chosen = [c for c in form.getlist("covers_codes") if c]
    if any(c not in valid_codes for c in chosen):
        errors["covers_codes"] = "Choose only existing services."
    data["covers_codes"] = ",".join(sorted(set(chosen)))

    data["icon_key"] = _icon(form, errors, "package")
    data["image_url"] = _image_url(form, errors)
    data["is_active"] = _checked(form, "is_active")

    if not errors:
        from app.models import ServicePackage
        dup = db.session.execute(
            db.select(ServicePackage).filter_by(category=data["category"], description=data["description"])
        ).scalar_one_or_none()
        if dup is not None and (existing is None or dup.id != existing.id):
            errors["description"] = "A package with this category and description already exists."
    return data, errors
