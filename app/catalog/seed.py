"""Idempotent seed of the confirmed WASH UP! catalog. Existing rows are never modified,
so prices/units an Admin has already changed are preserved."""
from decimal import Decimal

from app.extensions import db
from app.models import PackageMeasure, Service, ServiceAddon, ServicePackage

# pricing_unit is deliberately None: the billing basis of Wash/Dry/Fold/Spin was not specified,
# so an Admin must choose it before they can be ordered.
SERVICES = [
    ("wash", "Wash", "80.00", "wash"),
    ("dry", "Dry", "75.00", "dry"),
    ("fold", "Fold", "20.00", "fold"),
    ("spin", "Spin", "25.00", "spin"),
]
ADDONS = [
    ("fabcon", "Fabcon", "15.00", "softener", "Fabric conditioner"),
    ("liquid_soap", "Liquid Soap", "15.00", "soap", "Liquid detergent"),
]
W, P = PackageMeasure.WEIGHT, PackageMeasure.PIECES
PACKAGES = [  # category, description, size, measure, min, max, price, icon
    ("Clothes", "3KG\u20135KG", None, W, "3", "5", "185.00", "clothes"),
    ("Clothes", "6KG\u20138KG", None, W, "6", "8", "205.00", "clothes"),
    ("Comforter", "2\u20133 pieces (small)", "small", P, "2", "3", "205.00", "comforter"),
    ("Comforter", "1 piece (big)", "big", P, "1", "1", "205.00", "comforter"),
    ("Curtains", "3KG\u20135KG", None, W, "3", "5", "205.00", "curtains"),
    ("Linens", "3KG\u20135KG", None, W, "3", "5", "205.00", "linens"),
]


def seed_catalog():
    """Returns (services_added, addons_added, packages_added)."""
    added = [0, 0, 0]
    for code, name, price, icon in SERVICES:
        if not db.session.execute(db.select(Service).filter_by(code=code)).scalar_one_or_none():
            db.session.add(Service(
                code=code, name=name, price=Decimal(price), pricing_unit=None,
                category="Laundry service", icon_key=icon, is_active=True,
            ))
            added[0] += 1
    for code, name, price, icon, desc in ADDONS:
        if not db.session.execute(db.select(ServiceAddon).filter_by(code=code)).scalar_one_or_none():
            db.session.add(ServiceAddon(
                code=code, name=name, price=Decimal(price), description=desc, icon_key=icon,
                is_chargeable=True, allow_customer_supplied=True, is_active=True,
            ))
            added[1] += 1
    for cat, desc, size, measure, lo, hi, price, icon in PACKAGES:
        exists = db.session.execute(
            db.select(ServicePackage).filter_by(category=cat, description=desc)
        ).scalar_one_or_none()
        if not exists:
            db.session.add(ServicePackage(
                name="Wash, Dry & Fold", category=cat, description=desc, size_label=size,
                measure_type=measure, min_value=Decimal(lo), max_value=Decimal(hi),
                price=Decimal(price), covers_codes="wash,dry,fold", icon_key=icon, is_active=True,
            ))
            added[2] += 1
    db.session.commit()
    return tuple(added)
