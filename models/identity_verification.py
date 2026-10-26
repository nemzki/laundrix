import uuid

from app.extensions import db
from app.models.staff_credential import utcnow


def _public_id():
    return uuid.uuid4().hex


class IdentityVerification(db.Model):
    """One verification ATTEMPT for one user.

    Deliberately stores NO ID images, selfies, face templates, ID numbers, names or dates of birth.
    Those stay with the provider's hosted flow. We keep only what is needed to show a status and to
    audit what happened.
    """
    __tablename__ = "identity_verifications"
    __table_args__ = (
        db.UniqueConstraint("public_id", name="uq_identity_verifications_public_id"),
        db.UniqueConstraint("provider_session_id", name="uq_identity_verifications_session"),
        db.Index("ix_identity_verifications_user_id", "user_id"),
        db.Index("ix_identity_verifications_status", "status"),
        db.Index("ix_identity_verifications_user_purpose", "user_id", "purpose"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(32), nullable=False, default=_public_id)  # safe to put in URLs
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # "kyc" = one-time ID + liveness + face match; "biometric_auth" = a returning staff member's
    # sign-in selfie check against the portrait Didit stored from their kyc session.
    purpose = db.Column(db.String(16), nullable=False, default="kyc", server_default="kyc")
    provider = db.Column(db.String(20), nullable=False)
    provider_session_id = db.Column(db.String(64))     # NULL for attempts that never reached the provider
    environment = db.Column(db.String(10), nullable=False)  # "sandbox" | "live"

    status = db.Column(db.String(20), nullable=False)
    reason_codes = db.Column(db.JSON)                  # machine codes only, e.g. ["DOCUMENT_EXPIRED"]
    error_code = db.Column(db.String(40))              # our/provider API failure code (status=error)
    document_type = db.Column(db.String(40))           # e.g. "Passport"; never the document contents

    consent_version = db.Column(db.String(20))
    consent_at = db.Column(db.DateTime)

    provider_updated_at = db.Column(db.DateTime)       # provider's own timestamp of the last change we applied
    last_polled_at = db.Column(db.DateTime)
    decided_at = db.Column(db.DateTime)                # set when the provider reaches a verdict
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    user = db.relationship(
        "User",
        backref=db.backref(
            "identity_verifications", cascade="all, delete-orphan", passive_deletes=True,
            order_by="IdentityVerification.id",
        ),
    )
    events = db.relationship(
        "IdentityVerificationEvent", back_populates="verification",
        cascade="all, delete-orphan", passive_deletes=True,
    )


class IdentityVerificationEvent(db.Model):
    """Append-only audit trail. Also provides webhook de-duplication: `event_id` is unique, so a
    replayed or retried delivery cannot be applied twice."""
    __tablename__ = "identity_verification_events"
    __table_args__ = (
        db.UniqueConstraint("event_id", name="uq_identity_verification_events_event_id"),
        db.Index("ix_identity_verification_events_verification_id", "verification_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    verification_id = db.Column(
        db.Integer, db.ForeignKey("identity_verifications.id", ondelete="CASCADE"), nullable=False
    )
    event_id = db.Column(db.String(64))                # provider event id; NULL for poll/system entries
    source = db.Column(db.String(12), nullable=False)  # webhook | poll | system
    provider_status = db.Column(db.String(30))
    from_status = db.Column(db.String(20))
    to_status = db.Column(db.String(20))
    outcome = db.Column(db.String(24), nullable=False)  # applied | unchanged | stale | invalid_transition | unknown_status
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    verification = db.relationship("IdentityVerification", back_populates="events")
