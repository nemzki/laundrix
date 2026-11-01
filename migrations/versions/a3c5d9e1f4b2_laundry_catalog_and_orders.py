"""laundry catalog, customers and orders

Revision ID: a3c5d9e1f4b2
Revises: 11b2bcbca728
Create Date: 2026-10-31 12:00:00

Hand-written (additive only): creates new tables, never touches existing ones.
Review with `flask --app run db upgrade` against MySQL before relying on it.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3c5d9e1f4b2'
down_revision = '11b2bcbca728'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'services',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('category', sa.String(length=80), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('price', sa.Numeric(10, 2), nullable=False),
        sa.Column('pricing_unit', sa.Enum('load', 'kg', 'piece', name='service_pricing_unit'), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('icon_key', sa.String(length=30), nullable=False),
        sa.Column('image_url', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('price >= 0', name='ck_services_price_nonneg'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    op.create_index('ix_services_category', 'services', ['category'])
    op.create_index('ix_services_is_active', 'services', ['is_active'])

    op.create_table(
        'service_packages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('category', sa.String(length=80), nullable=False),
        sa.Column('description', sa.String(length=120), nullable=False),
        sa.Column('size_label', sa.String(length=40), nullable=True),
        sa.Column('measure_type', sa.Enum('weight', 'pieces', name='package_measure'), nullable=False),
        sa.Column('min_value', sa.Numeric(8, 2), nullable=False),
        sa.Column('max_value', sa.Numeric(8, 2), nullable=False),
        sa.Column('price', sa.Numeric(10, 2), nullable=False),
        sa.Column('covers_codes', sa.String(length=120), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('icon_key', sa.String(length=30), nullable=False),
        sa.Column('image_url', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('price >= 0', name='ck_packages_price_nonneg'),
        sa.CheckConstraint('min_value > 0 AND max_value >= min_value', name='ck_packages_range'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('category', 'description', name='uq_package_category_description'),
    )
    op.create_index('ix_service_packages_category', 'service_packages', ['category'])
    op.create_index('ix_service_packages_is_active', 'service_packages', ['is_active'])

    op.create_table(
        'service_addons',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('price', sa.Numeric(10, 2), nullable=False),
        sa.Column('is_chargeable', sa.Boolean(), nullable=False),
        sa.Column('allow_customer_supplied', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('icon_key', sa.String(length=30), nullable=False),
        sa.Column('image_url', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('price >= 0', name='ck_addons_price_nonneg'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    op.create_index('ix_service_addons_is_active', 'service_addons', ['is_active'])

    op.create_table(
        'customers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=150), nullable=False),
        sa.Column('contact_number', sa.String(length=30), nullable=False),
        sa.Column('contact_normalized', sa.String(length=20), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_customers_full_name', 'customers', ['full_name'])
    op.create_index('ix_customers_contact_normalized', 'customers', ['contact_normalized'])

    op.create_table(
        'orders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('reference', sa.String(length=24), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('customer_name', sa.String(length=150), nullable=False),
        sa.Column('customer_contact', sa.String(length=30), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('subtotal', sa.Numeric(10, 2), nullable=False),
        sa.Column('discount_total', sa.Numeric(10, 2), nullable=False),
        sa.Column('total', sa.Numeric(10, 2), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('total >= 0', name='ck_orders_total_nonneg'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('reference'),
    )
    op.create_index('ix_orders_customer_id', 'orders', ['customer_id'])
    op.create_index('ix_orders_status', 'orders', ['status'])
    op.create_index('ix_orders_created_by_id', 'orders', ['created_by_id'])
    op.create_index('ix_orders_created_at', 'orders', ['created_at'])

    op.create_table(
        'order_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('item_type', sa.Enum('service', 'package', 'addon', name='order_item_type'), nullable=False),
        sa.Column('service_id', sa.Integer(), nullable=True),
        sa.Column('package_id', sa.Integer(), nullable=True),
        sa.Column('addon_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('quantity', sa.Numeric(10, 2), nullable=False),
        sa.Column('unit', sa.String(length=20), nullable=False),
        sa.Column('measurement', sa.Numeric(8, 2), nullable=True),
        sa.Column('measurement_unit', sa.String(length=10), nullable=True),
        sa.Column('unit_price', sa.Numeric(10, 2), nullable=False),
        sa.Column('line_total', sa.Numeric(10, 2), nullable=False),
        sa.Column('customer_supplied', sa.Boolean(), nullable=False),
        sa.Column('instructions', sa.String(length=500), nullable=True),
        sa.CheckConstraint('unit_price >= 0 AND line_total >= 0 AND quantity > 0', name='ck_items_amounts'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['service_id'], ['services.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['package_id'], ['service_packages.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['addon_id'], ['service_addons.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_order_items_order_id', 'order_items', ['order_id'])

    op.create_table(
        'order_status_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('from_status', sa.String(length=30), nullable=True),
        sa.Column('to_status', sa.String(length=30), nullable=False),
        sa.Column('changed_by_id', sa.Integer(), nullable=True),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['changed_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_order_status_history_order_id', 'order_status_history', ['order_id'])
    op.create_index('ix_order_status_history_created_at', 'order_status_history', ['created_at'])


def downgrade():
    # Dropping a table drops its indexes; order matters because of foreign keys.
    op.drop_table('order_status_history')
    op.drop_table('order_items')
    op.drop_table('orders')
    op.drop_table('customers')
    op.drop_table('service_addons')
    op.drop_table('service_packages')
    op.drop_table('services')
