"""unclaimed order prediction: outcome columns and model registry

Revision ID: c3a8e5f21d47
Revises: 94f6f8ac3700
Create Date: 2026-11-19 09:00:00

Additive only.
  * historical_transactions gets 5 new columns (ready_date, outcome_status, claimed_date,
    disposed_date, status_source).  Existing rows keep every current value; their
    outcome_status / status_source become 'unknown' until the updated CSV is re-imported.
  * unclaimed_model_runs is a new table holding the trained model as plain JSON numbers.
No orders, customers, payments or staff tables are touched.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3a8e5f21d47"
down_revision = "94f6f8ac3700"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("historical_transactions", sa.Column("ready_date", sa.Date(), nullable=True))
    op.add_column(
        "historical_transactions",
        sa.Column("outcome_status", sa.String(length=20), nullable=False, server_default="unknown"),
    )
    op.add_column("historical_transactions", sa.Column("claimed_date", sa.Date(), nullable=True))
    op.add_column("historical_transactions", sa.Column("disposed_date", sa.Date(), nullable=True))
    op.add_column(
        "historical_transactions",
        sa.Column("status_source", sa.String(length=20), nullable=False, server_default="unknown"),
    )

    op.create_table(
        "unclaimed_model_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("algorithm", sa.String(length=40), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("n_orders", sa.Integer(), nullable=False),
        sa.Column("n_disposed", sa.Integer(), nullable=False),
        sa.Column("data_start", sa.Date(), nullable=True),
        sa.Column("data_end", sa.Date(), nullable=True),
        sa.Column("disposal_days", sa.Integer(), nullable=False),
        sa.Column("labels_simulated", sa.Boolean(), nullable=False),
        sa.Column("trained_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version", name="uq_unclaimed_model_runs_version"),
    )


def downgrade():
    # Removes only the trained models and the new outcome columns (the CSV can be re-imported).
    op.drop_table("unclaimed_model_runs")
    op.drop_column("historical_transactions", "status_source")
    op.drop_column("historical_transactions", "disposed_date")
    op.drop_column("historical_transactions", "claimed_date")
    op.drop_column("historical_transactions", "outcome_status")
    op.drop_column("historical_transactions", "ready_date")
