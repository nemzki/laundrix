"""Database model for recording that an unclaimed order was disposed of."""

from app.extensions import db
from app.models.staff_credential import utcnow


class OrderDisposal(db.Model):
    """An admin recorded that an unclaimed Ready-for-Pickup order was disposed of.

    Kept in its own table on purpose: it does not change the order's status, so the Orders
    pages behave exactly as before. It is the real outcome data a future model can learn from.
    """

    __tablename__ = "order_disposals"
    __table_args__ = (db.UniqueConstraint("order_id", name="uq_order_disposals_order"),)

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(
        db.Integer, db.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False,
    )
    disposed_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    disposed_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    order = db.relationship("Order", backref=db.backref("disposal", uselist=False, cascade="all, delete-orphan"))
    disposed_by = db.relationship("User", foreign_keys=[disposed_by_id])
