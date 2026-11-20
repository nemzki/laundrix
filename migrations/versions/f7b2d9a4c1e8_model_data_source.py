"""mark which data a trained model came from

Revision ID: f7b2d9a4c1e8
Revises: e4f6a1b3c9d2
Create Date: 2026-11-19 18:00:00

Additive only: one new column on unclaimed_model_runs. Existing rows (trained on imported
history) become data_source = 'imported' and are never used for predictions any more.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f7b2d9a4c1e8"
down_revision = "e4f6a1b3c9d2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "unclaimed_model_runs",
        sa.Column("data_source", sa.String(length=20), nullable=False, server_default="imported"),
    )


def downgrade():
    op.drop_column("unclaimed_model_runs", "data_source")
