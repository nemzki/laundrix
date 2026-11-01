from app.extensions import db
from app.models.staff_credential import utcnow
import secrets

class OrderStatus:
    RECEIVED = "order_received"
    PENDING = "pending_processing"
    PROCESSING = "processing"
    READY = "ready_for_pickup"
    RELEASED = "picked_up"
    COMPLETED = "completed"
    # Workflow order. Moves go one step at a time (see app/orders/services.py).
    FLOW = (RECEIVED, PENDING, PROCESSING, READY, RELEASED, COMPLETED)
    LABELS = {
        RECEIVED: "Order Received",
        PENDING: "Pending Processing",
        PROCESSING: "Processing",
        READY: "Ready for Pickup",
        RELEASED: "Picked Up / Released",
        COMPLETED: "Completed",
    }
    # CSS badge modifier per status.
    TONES = {
        RECEIVED: "info", PENDING: "warn", PROCESSING: "progress",
        READY: "ready", RELEASED: "neutral", COMPLETED: "success",
    }


class ItemType:
    SERVICE = "service"
    PACKAGE = "package"
    ADDON = "addon"


class Order(db.Model):
    __tablename__ = "orders"
    __table_args__ = (db.CheckConstraint("total >= 0", name="ck_orders_total_nonneg"),)

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(24), unique=True, nullable=False)
    tracking_token = db.Column(
        db.String(64),
        unique=True,
        nullable=False,
        default=lambda: secrets.token_urlsafe(32),
    )
    customer_id = db.Column(
        db.Integer, db.ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Snapshot of the customer at order time (the Customer row may be edited later).
    customer_name = db.Column(db.String(150), nullable=False)
    customer_contact = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(30), nullable=False, default=OrderStatus.RECEIVED, index=True)
    subtotal = db.Column(db.Numeric(10, 2), nullable=False)
    discount_total = db.Column(db.Numeric(10, 2), nullable=False, default=0)  # discounts not implemented yet
    total = db.Column(db.Numeric(10, 2), nullable=False)
    notes = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    customer = db.relationship("Customer", backref=db.backref("orders", lazy="dynamic"))
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    items = db.relationship(
        "OrderItem", backref="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )
    history = db.relationship(
        "OrderStatusHistory", backref="order", cascade="all, delete-orphan",
        order_by="OrderStatusHistory.id",
    )

    @property
    def status_label(self) -> str:
        return OrderStatus.LABELS.get(self.status, self.status)


class OrderItem(db.Model):
    """One purchased line. All descriptive and price fields are snapshots taken at order time."""
    __tablename__ = "order_items"
    __table_args__ = (
        db.CheckConstraint("unit_price >= 0 AND line_total >= 0 AND quantity > 0", name="ck_items_amounts"),
    )

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    item_type = db.Column(db.Enum("service", "package", "addon", name="order_item_type"), nullable=False)
    # Soft references: catalog rows may later be deactivated/removed without harming the order.
    service_id = db.Column(db.Integer, db.ForeignKey("services.id", ondelete="SET NULL"))
    package_id = db.Column(db.Integer, db.ForeignKey("service_packages.id", ondelete="SET NULL"))
    addon_id = db.Column(db.Integer, db.ForeignKey("service_addons.id", ondelete="SET NULL"))

    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.String(255))
    quantity = db.Column(db.Numeric(10, 2), nullable=False)
    unit = db.Column(db.String(20), nullable=False)
    measurement = db.Column(db.Numeric(8, 2))          # weight / piece count of a package
    measurement_unit = db.Column(db.String(10))
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    line_total = db.Column(db.Numeric(10, 2), nullable=False)
    customer_supplied = db.Column(db.Boolean, nullable=False, default=False)
    instructions = db.Column(db.String(500))


class OrderStatusHistory(db.Model):
    __tablename__ = "order_status_history"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    from_status = db.Column(db.String(30))  # NULL for the initial entry
    to_status = db.Column(db.String(30), nullable=False)
    changed_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    changed_by = db.relationship("User", foreign_keys=[changed_by_id])
