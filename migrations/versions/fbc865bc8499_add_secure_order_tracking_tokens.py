
"""add secure order tracking tokens

Revision ID: fbc865bc8499
Revises: a3c5d9e1f4b2
Create Date: 2026-11-01 10:27:06.086295
"""

import secrets

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "fbc865bc8499"
down_revision = "a3c5d9e1f4b2"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add the column as nullable so existing orders remain valid.
    op.add_column(
        "orders",
        sa.Column("tracking_token", sa.String(length=64), nullable=True),
    )

    # 2. Generate a secure, unique token for every existing order.
    orders = sa.table(
        "orders",
        sa.column("id", sa.Integer()),
        sa.column("tracking_token", sa.String(length=64)),
    )

    connection = op.get_bind()

    order_ids = connection.execute(
        sa.select(orders.c.id).where(
            orders.c.tracking_token.is_(None)
        )
    ).scalars()

    for order_id in order_ids:
        connection.execute(
            orders.update()
            .where(orders.c.id == order_id)
            .values(tracking_token=secrets.token_urlsafe(32))
        )

    # 3. Require a token for every order.
    op.alter_column(
        "orders",
        "tracking_token",
        existing_type=sa.String(length=64),
        nullable=False,
    )

    # 4. Enforce token uniqueness.
    op.create_unique_constraint(
        "uq_orders_tracking_token",
        "orders",
        ["tracking_token"],
    )


def downgrade():
    op.drop_constraint(
        "uq_orders_tracking_token",
        "orders",
        type_="unique",
    )

    op.drop_column("orders", "tracking_token")
