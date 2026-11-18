
"""add historical transactions

Revision ID: 94f6f8ac3700
Revises: d53e74365dc4
Create Date: 2026-11-18

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "94f6f8ac3700"
down_revision = "d53e74365dc4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "historical_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("source_transaction_no", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(length=150), nullable=True),
        sa.Column("raw_weight", sa.String(length=30), nullable=True),
        sa.Column("fold_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("liquid_soap_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("surf_downy_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("load_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "payment_status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column("import_source", sa.String(length=255), nullable=False),
        sa.Column("source_row_key", sa.String(length=191), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),

        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "import_source",
            "transaction_date",
            "source_transaction_no",
            name="uq_historical_source_date_no",
        ),
        sa.UniqueConstraint(
            "source_row_key",
            name="uq_historical_transactions_source_row_key",
        ),
    )

    op.create_index(
        "ix_historical_transactions_date",
        "historical_transactions",
        ["transaction_date"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_historical_transactions_date",
        table_name="historical_transactions",
    )
    op.drop_table("historical_transactions")
