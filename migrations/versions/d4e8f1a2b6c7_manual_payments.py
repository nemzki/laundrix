"""manual payment recording

Revision ID: d4e8f1a2b6c7
Revises: fbc865bc8499
Create Date: 2026-11-02 09:00:00

Additive only. Existing orders keep working:
  * received_at is back-filled from created_at (they were all received when created);
  * payment_arrangement stays NULL, which the app shows as "Payment not tracked", so old orders
    never appear as false outstanding balances.
Run `flask --app run seed-payments` afterwards to create the Cash and GCash methods.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e8f1a2b6c7'
down_revision = 'fbc865bc8499'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'payment_methods',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=30), nullable=False),
        sa.Column('label', sa.String(length=60), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('requires_reference', sa.Boolean(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )

    op.create_table(
        'payment_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('partial_enabled', sa.Boolean(), nullable=False),
        sa.Column('pay_later_enabled', sa.Boolean(), nullable=False),
        sa.Column('gcash_account_name', sa.String(length=120), nullable=True),
        sa.Column('gcash_account_number', sa.String(length=40), nullable=True),
        sa.Column('payment_instructions', sa.Text(), nullable=True),
        sa.Column('payment_notice', sa.String(length=255), nullable=True),
        sa.Column('stub_footer', sa.String(length=255), nullable=True),
        sa.Column('show_qr_on_stub', sa.Boolean(), nullable=False),
        sa.Column('qr_filename', sa.String(length=80), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- orders: four nullable columns (no existing row is rejected; only received_at is back-filled).
    # batch_alter_table issues plain ALTERs on MySQL and rebuilds the table on SQLite (used in tests).
    with op.batch_alter_table('orders') as batch:
        batch.add_column(sa.Column('payment_arrangement', sa.String(length=20), nullable=True))
        batch.add_column(sa.Column('received_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('received_by_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('submission_token', sa.String(length=64), nullable=True))
    op.execute("UPDATE orders SET received_at = created_at WHERE received_at IS NULL")
    with op.batch_alter_table('orders') as batch:
        batch.create_index('ix_orders_received_at', ['received_at'])
        batch.create_foreign_key('fk_orders_received_by_id_users', 'users',
                                 ['received_by_id'], ['id'], ondelete='SET NULL')
        batch.create_unique_constraint('uq_orders_submission_token', ['submission_token'])

    op.create_table(
        'payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.Enum('payment', 'reversal', name='payment_kind'), nullable=False),
        sa.Column('method_id', sa.Integer(), nullable=False),
        sa.Column('method_code', sa.String(length=30), nullable=False),
        sa.Column('method_label', sa.String(length=60), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('reference', sa.String(length=64), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=False),
        sa.Column('recorded_by_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.String(length=255), nullable=True),
        sa.Column('reverses_payment_id', sa.Integer(), nullable=True),
        sa.Column('idempotency_key', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('amount > 0', name='ck_payments_amount_positive'),
        sa.CheckConstraint(
            "(kind = 'payment' AND reverses_payment_id IS NULL) OR "
            "(kind = 'reversal' AND reverses_payment_id IS NOT NULL)",
            name='ck_payments_kind_link'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['method_id'], ['payment_methods.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['recorded_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reverses_payment_id'], ['payments.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('reverses_payment_id'),
        sa.UniqueConstraint('idempotency_key'),
    )
    op.create_index('ix_payments_order_id', 'payments', ['order_id'])
    op.create_index('ix_payments_method_id', 'payments', ['method_id'])
    op.create_index('ix_payments_paid_at', 'payments', ['paid_at'])
    op.create_index('ix_payments_recorded_by_id', 'payments', ['recorded_by_id'])

    op.create_table(
        'payment_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=True),
        sa.Column('payment_id', sa.Integer(), nullable=True),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('detail', sa.String(length=500), nullable=True),
        sa.Column('ip', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_payment_events_order_id', 'payment_events', ['order_id'])
    op.create_index('ix_payment_events_payment_id', 'payment_events', ['payment_id'])
    op.create_index('ix_payment_events_actor_id', 'payment_events', ['actor_id'])
    op.create_index('ix_payment_events_action', 'payment_events', ['action'])
    op.create_index('ix_payment_events_created_at', 'payment_events', ['created_at'])


def downgrade():
    # Destroys recorded payments by design (it is the inverse of the upgrade). Back up first.
    op.drop_table('payment_events')
    op.drop_table('payments')
    with op.batch_alter_table('orders') as batch:
        batch.drop_constraint('uq_orders_submission_token', type_='unique')
        batch.drop_constraint('fk_orders_received_by_id_users', type_='foreignkey')
        batch.drop_index('ix_orders_received_at')
    with op.batch_alter_table('orders') as batch:
        batch.drop_column('submission_token')
        batch.drop_column('received_by_id')
        batch.drop_column('received_at')
        batch.drop_column('payment_arrangement')
    op.drop_table('payment_settings')
    op.drop_table('payment_methods')
