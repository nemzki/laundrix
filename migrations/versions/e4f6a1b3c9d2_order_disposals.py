"""order disposals (admin 'mark as disposed' on the Analytics page)

Revision ID: e4f6a1b3c9d2
Revises: c3a8e5f21d47
Create Date: 2026-11-19 12:00:00

Additive only: one new table. The orders table and every other table are untouched.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e4f6a1b3c9d2"
down_revision = "c3a8e5f21d47"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "order_disposals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("disposed_by_id", sa.Integer(), nullable=True),
        sa.Column("disposed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["disposed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", name="uq_order_disposals_order"),
    )


def downgrade():
    op.drop_table("order_disposals")
