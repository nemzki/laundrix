"""Official service catalog: individual services, Wash-Dry-Fold packages and add-ons/extras.

Only Admin users may change these rows (enforced in app/catalog). Orders never depend on them for
display: order items store their own price snapshot (see app/models/order.py)."""
from decimal import Decimal

from app.extensions import db
from app.models.staff_credential import utcnow


class PricingUnit:
    """How an individual service is billed. NULL on a service means "not configured yet"."""
    LOAD = "load"
    KG = "kg"
    PIECE = "piece"
    ALL = (LOAD, KG, PIECE)
    LABELS = {LOAD: "per load", KG: "per kg", PIECE: "per piece"}


class PackageMeasure:
    WEIGHT = "weight"   # range in kilograms
    PIECES = "pieces"   # range in number of pieces
    ALL = (WEIGHT, PIECES)
    UNIT_LABEL = {WEIGHT: "kg", PIECES: "pcs"}


ICON_KEYS = (
    "wash", "dry", "fold", "spin", "softener", "soap",
    "clothes", "comforter", "curtains", "linens", "package", "generic",
)


class _Timestamps:
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class Service(_Timestamps, db.Model):
    __tablename__ = "services"
    __table_args__ = (db.CheckConstraint("price >= 0", name="ck_services_price_nonneg"),)

    id = db.Column(db.Integer, primary_key=True)
    # Stable machine code (e.g. "wash"). Packages refer to it through `covers_codes`.
    code = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80), nullable=False, default="Laundry service", index=True)
    description = db.Column(db.String(255))
    price = db.Column(db.Numeric(10, 2), nullable=False)
    pricing_unit = db.Column(db.Enum(*PricingUnit.ALL, name="service_pricing_unit"), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    icon_key = db.Column(db.String(30), nullable=False, default="generic")
    image_url = db.Column(db.String(500))  # optional; placeholder until you wire real images

    @property
    def is_orderable(self) -> bool:
        return bool(self.is_active and self.pricing_unit)

    @property
    def unit_label(self) -> str:
        return PricingUnit.LABELS.get(self.pricing_unit, "unit not set")


class ServicePackage(_Timestamps, db.Model):
    __tablename__ = "service_packages"
    __table_args__ = (
        db.UniqueConstraint("category", "description", name="uq_package_category_description"),
        db.CheckConstraint("price >= 0", name="ck_packages_price_nonneg"),
        db.CheckConstraint("min_value > 0 AND max_value >= min_value", name="ck_packages_range"),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, default="Wash, Dry & Fold")
    category = db.Column(db.String(80), nullable=False, index=True)       # Clothes, Comforter...
    description = db.Column(db.String(120), nullable=False)                # "3KG-5KG"
    size_label = db.Column(db.String(40))                                  # "small" / "big"
    measure_type = db.Column(db.Enum(*PackageMeasure.ALL, name="package_measure"), nullable=False)
    min_value = db.Column(db.Numeric(8, 2), nullable=False)
    max_value = db.Column(db.Numeric(8, 2), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    # Comma separated Service.code values this package already includes (no double charging).
    covers_codes = db.Column(db.String(120), nullable=False, default="wash,dry,fold")
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    icon_key = db.Column(db.String(30), nullable=False, default="package")
    image_url = db.Column(db.String(500))

    @property
    def covered_codes(self) -> set:
        return {c.strip() for c in (self.covers_codes or "").split(",") if c.strip()}

    @property
    def unit_label(self) -> str:
        return PackageMeasure.UNIT_LABEL[self.measure_type]

    @property
    def range_label(self) -> str:
        lo, hi = Decimal(self.min_value).normalize(), Decimal(self.max_value).normalize()
        lo, hi = f"{lo:f}", f"{hi:f}"
        rng = lo if lo == hi else f"{lo}\u2013{hi}"
        return f"{rng} {self.unit_label}"

    @property
    def display_name(self) -> str:
        return f"{self.category} \u00b7 {self.description}"


class ServiceAddon(_Timestamps, db.Model):
    """Optional products/extras such as Fabcon or Liquid Soap."""
    __tablename__ = "service_addons"
    __table_args__ = (db.CheckConstraint("price >= 0", name="ck_addons_price_nonneg"),)

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255))
    price = db.Column(db.Numeric(10, 2), nullable=False)
    is_chargeable = db.Column(db.Boolean, nullable=False, default=True)
    allow_customer_supplied = db.Column(db.Boolean, nullable=False, default=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    icon_key = db.Column(db.String(30), nullable=False, default="generic")
    image_url = db.Column(db.String(500))
