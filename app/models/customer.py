"""Database model for laundry customers."""

from app.extensions import db
from app.models.staff_credential import utcnow


class Customer(db.Model):
    """A customer of the laundry shop.

    Stores the name, the contact number as typed, and a digits-only copy (09XXXXXXXXX) used for matching."""
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False, index=True)
    contact_number = db.Column(db.String(30), nullable=False)          # as entered (display)
    contact_normalized = db.Column(db.String(20), nullable=False, index=True)  # digits only, 09XXXXXXXXX
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    created_by = db.relationship("User", foreign_keys=[created_by_id])
