"""sms notifications and per-order consent

Revision ID: f2b7d4c9a1e3
Revises: d4e8f1a2b6c7
Create Date: 2026-11-05 09:00:00

Additive only:
  * orders.sms_consent (NOT NULL, default false) and orders.sms_consent_at: every EXISTING order gets
    consent = false, so no historical order can ever trigger a text;
  * sms_notifications: one row per order (unique order_id), created the first time an order reaches
    Ready for Pickup.
batch_alter_table issues plain ALTERs on MySQL and rebuilds the table on SQLite (used in tests).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2b7d4c9a1e3'
down_revision = 'e7b3c9a4d1f6'
branch_labels = None
depends_on = None

STATUSES = ("pending", "queued", "retrying", "sent", "failed", "unknown",
            "skipped_no_consent", "skipped_invalid_recipient")


def upgrade():
    with op.batch_alter_table('orders') as batch:
        batch.add_column(sa.Column('sms_consent', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('sms_consent_at', sa.DateTime(), nullable=True))

    op.create_table(
        'sms_notifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('provider_message_id', sa.String(length=100), nullable=True),
        sa.Column('recipient', sa.String(length=20), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('last_error', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(), nullable=True),
        sa.Column('accepted_at', sa.DateTime(), nullable=True),
        sa.Column('provider_sent_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")",
                           name='ck_sms_notifications_status'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('order_id', name='uq_sms_notifications_order_id'),
    )
    op.create_index('ix_sms_notifications_status', 'sms_notifications', ['status'])
    op.create_index('ix_sms_notifications_provider_message_id', 'sms_notifications', ['provider_message_id'])


def downgrade():
    # Removes every recorded notification and all consent flags. Back up first.
    op.drop_table('sms_notifications')
    with op.batch_alter_table('orders') as batch:
        batch.drop_column('sms_consent_at')
        batch.drop_column('sms_consent')
