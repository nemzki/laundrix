from datetime import datetime, timezone

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class StaffCredential(db.Model):
    """Staff-portal credentials: a hashed Staff ID, lockout state and a one-time enrollment link.

    Face data is NOT stored here or anywhere in Laundrix: the face check is done by Didit, which
    holds the reference portrait. Whether someone is "enrolled" is derived from their identity
    verification record (see app/staff_auth/services.py: is_enrolled)."""
    __tablename__ = "staff_credentials"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    staff_id_hash = db.Column(db.String(255), nullable=False)

    enroll_token_hash = db.Column(db.String(64), unique=True)  # sha256 of the one-time link token
    enroll_token_expires_at = db.Column(db.DateTime)

    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime)
    last_verified_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    user = db.relationship(
        "User",
        backref=db.backref("staff_credential", uselist=False, cascade="all, delete-orphan"),
    )

    @property
    def is_locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > utcnow()
