"""Manual payment recording. Nothing here talks to any payment provider: every row exists because
a staff member confirmed, by hand, that the money was received."""
from app.extensions import db
from app.models.staff_credential import utcnow


class PaymentKind:
    PAYMENT = "payment"
    REVERSAL = "reversal"      # an Admin correction that cancels one earlier payment row
    ALL = (PAYMENT, REVERSAL)


class PaymentArrangement:
    """HOW MUCH is paid at the time of ordering (not the method)."""
    FULL = "full"
    PARTIAL = "partial"
    PAY_LATER = "pay_later"
    ALL = (FULL, PARTIAL, PAY_LATER)
    LABELS = {FULL: "Full Payment", PARTIAL: "Partial Payment", PAY_LATER: "Pay Later"}


class PaymentStatus:
    """Derived from the ledger. Never stored, never accepted from the browser."""
    UNPAID = "unpaid"
    PARTIAL = "partial"
    PAID = "paid"
    NOT_TRACKED = "not_tracked"   # orders created before payment recording existed
    LABELS = {
        UNPAID: "Unpaid", PARTIAL: "Partially Paid", PAID: "Paid", NOT_TRACKED: "Payment not tracked",
    }
    TONES = {UNPAID: "warn", PARTIAL: "progress", PAID: "success", NOT_TRACKED: "neutral"}


class PaymentMethod(db.Model):
    """HOW the customer pays (Cash, GCash, ...). Admin-configurable; nothing is hardcoded in views."""
    __tablename__ = "payment_methods"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    label = db.Column(db.String(60), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    requires_reference = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=100)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class PaymentSettings(db.Model):
    """Single-row table (id = 1) holding editable payment policy and display text."""
    __tablename__ = "payment_settings"

    id = db.Column(db.Integer, primary_key=True)
    partial_enabled = db.Column(db.Boolean, nullable=False, default=True)
    pay_later_enabled = db.Column(db.Boolean, nullable=False, default=True)
    gcash_account_name = db.Column(db.String(120))
    gcash_account_number = db.Column(db.String(40))
    payment_instructions = db.Column(db.Text)
    payment_notice = db.Column(db.String(255))
    stub_footer = db.Column(db.String(255))
    show_qr_on_stub = db.Column(db.Boolean, nullable=False, default=False)
    qr_filename = db.Column(db.String(80))          # generated name only; never a path
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    updated_by = db.relationship("User", foreign_keys=[updated_by_id])


class Payment(db.Model):
    """Append-only ledger entry. Rows are never edited or deleted; a mistake is fixed by adding a
    `reversal` row that points at the original, so the full history is always preserved."""
    __tablename__ = "payments"
    __table_args__ = (
        db.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        db.CheckConstraint(
            "(kind = 'payment' AND reverses_payment_id IS NULL) OR "
            "(kind = 'reversal' AND reverses_payment_id IS NOT NULL)",
            name="ck_payments_kind_link",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    kind = db.Column(db.Enum(*PaymentKind.ALL, name="payment_kind"), nullable=False, default=PaymentKind.PAYMENT)
    method_id = db.Column(db.Integer, db.ForeignKey("payment_methods.id", ondelete="RESTRICT"), nullable=False, index=True)
    # Snapshots, so renaming or disabling a method never rewrites history.
    method_code = db.Column(db.String(30), nullable=False)
    method_label = db.Column(db.String(60), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    reference = db.Column(db.String(64))
    paid_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    notes = db.Column(db.String(255))
    reverses_payment_id = db.Column(db.Integer, db.ForeignKey("payments.id", ondelete="RESTRICT"), unique=True)
    idempotency_key = db.Column(db.String(100), unique=True)   # blocks double-submits
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    order = db.relationship("Order", backref=db.backref("payments", order_by="Payment.id"))
    method = db.relationship("PaymentMethod")
    recorded_by = db.relationship("User", foreign_keys=[recorded_by_id])
    reversed_payment = db.relationship(
        "Payment", remote_side="Payment.id", foreign_keys=[reverses_payment_id],
        backref=db.backref("reversal", uselist=False),
    )

    @property
    def is_reversal(self) -> bool:
        return self.kind == PaymentKind.REVERSAL


class PaymentEvent(db.Model):
    """Audit trail of payment activity and payment-settings changes."""
    __tablename__ = "payment_events"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id", ondelete="SET NULL"), index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id", ondelete="SET NULL"), index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action = db.Column(db.String(40), nullable=False, index=True)
    detail = db.Column(db.String(500))
    ip = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    order = db.relationship("Order", foreign_keys=[order_id])
    payment = db.relationship("Payment", foreign_keys=[payment_id])
    actor = db.relationship("User", foreign_keys=[actor_id])
