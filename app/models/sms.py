from app.extensions import db
from app.models.staff_credential import utcnow


class SMSStatus:
    """Internal notification states. Provider states map onto these (see app/sms/services.py)."""
    PENDING = "pending"                                  # created, never submitted to the provider
    QUEUED = "queued"                                    # provider accepted it (HTTP 201) and has it queued
    RETRYING = "retrying"                                # provider says it is retrying
    SENT = "sent"                                        # provider reports "sent" (NOT proof of handset delivery)
    FAILED = "failed"                                    # definite failure or rejection
    UNKNOWN = "unknown"                                  # submission outcome ambiguous: never retried blindly
    SKIPPED_NO_CONSENT = "skipped_no_consent"
    SKIPPED_INVALID_RECIPIENT = "skipped_invalid_recipient"
    ALL = (PENDING, QUEUED, RETRYING, SENT, FAILED, UNKNOWN, SKIPPED_NO_CONSENT, SKIPPED_INVALID_RECIPIENT)
    LABELS = {
        PENDING: "Pending", QUEUED: "Queued", RETRYING: "Retrying", SENT: "Sent by provider",
        FAILED: "Failed", UNKNOWN: "Outcome unknown",
        SKIPPED_NO_CONSENT: "Skipped \u2014 no consent", SKIPPED_INVALID_RECIPIENT: "Skipped \u2014 invalid number",
    }
    TONES = {
        PENDING: "warn", QUEUED: "info", RETRYING: "progress", SENT: "success",
        FAILED: "warn", UNKNOWN: "warn", SKIPPED_NO_CONSENT: "neutral", SKIPPED_INVALID_RECIPIENT: "neutral",
    }


class SMSNotification(db.Model):
    """At most ONE per order (unique constraint): the "ready for pickup" text. Re-entering Ready for
    Pickup can never create a second row, and manual retries update this row instead of adding one."""
    __tablename__ = "sms_notifications"
    __table_args__ = (
        db.UniqueConstraint("order_id", name="uq_sms_notifications_order_id"),
        db.CheckConstraint(
            "status IN ('pending', 'queued', 'retrying', 'sent', 'failed', 'unknown', "
            "'skipped_no_consent', 'skipped_invalid_recipient')",
            name="ck_sms_notifications_status",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False)
    provider = db.Column(db.String(20), nullable=False, default="unisms")
    status = db.Column(db.String(30), nullable=False, default=SMSStatus.PENDING, index=True)
    provider_message_id = db.Column(db.String(100), index=True)         # UniSMS reference_id
    recipient = db.Column(db.String(20))                                # normalized E.164; masked in the UI
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.String(255))                              # sanitized, never raw provider text
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    last_attempt_at = db.Column(db.DateTime)
    accepted_at = db.Column(db.DateTime)
    provider_sent_at = db.Column(db.DateTime)

    order = db.relationship("Order", backref=db.backref("sms_notification", uselist=False))
