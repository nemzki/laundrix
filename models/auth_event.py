from app.extensions import db
from app.models.staff_credential import utcnow


class AuthEvent(db.Model):
    """Audit trail of sign-in activity (no secrets, no images)."""
    __tablename__ = "auth_events"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    email = db.Column(db.String(255))
    event = db.Column(db.String(40), nullable=False)
    success = db.Column(db.Boolean, nullable=False, default=False)
    ip = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
