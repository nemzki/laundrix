from app.extensions import db
from app.models.staff_credential import utcnow


class HistoricalOutcome:
    """What happened to a laundry order after it was ready for pickup."""
    CLAIMED = "claimed"      # the customer picked it up
    UNCLAIMED = "unclaimed"  # still waiting at the shop
    DISPOSED = "disposed"    # left too long and disposed of by the shop
    UNKNOWN = "unknown"      # outcome not recorded (e.g. rows from the old 9-column CSV)
    ALL = (CLAIMED, UNCLAIMED, DISPOSED, UNKNOWN)


class HistoricalTransaction(db.Model):
    """Imported historical laundry transactions, separate from live orders and payments."""

    __tablename__ = "historical_transactions"

    __table_args__ = (
        db.UniqueConstraint(
            "import_source",
            "transaction_date",
            "source_transaction_no",
            name="uq_historical_source_date_no",
        ),
        db.Index("ix_historical_transactions_date", "transaction_date"),
        db.UniqueConstraint(
            "source_row_key",
            name="uq_historical_transactions_source_row_key",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    transaction_date = db.Column(db.Date, nullable=False)
    source_transaction_no = db.Column(db.Integer, nullable=False)

    customer_name = db.Column(db.String(150), nullable=True)
    raw_weight = db.Column(db.String(30), nullable=True)

    fold_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    liquid_soap_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    surf_downy_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    load_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)

    # "paid" / "unpaid" / "unknown"
    payment_status = db.Column(
        db.String(20),
        nullable=False,
        default="unknown",
    )

    # --- outcome columns used by the unclaimed-order prediction model ---------------------
    ready_date = db.Column(db.Date, nullable=True)       # day the laundry was ready for pickup
    outcome_status = db.Column(
        db.String(20), nullable=False, default=HistoricalOutcome.UNKNOWN,
        server_default=HistoricalOutcome.UNKNOWN,
    )
    claimed_date = db.Column(db.Date, nullable=True)
    disposed_date = db.Column(db.Date, nullable=True)
    # "recorded" = taken from the shop's real records, "simulated" = placeholder, "unknown"
    status_source = db.Column(
        db.String(20), nullable=False, default="unknown", server_default="unknown",
    )

    import_source = db.Column(db.String(255), nullable=False)
    source_row_key = db.Column(db.String(191), nullable=False)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
