"""audit logs

Revision ID: a9c4e2d7b1f3
Revises: b5d1e8c3a7f2
Create Date: 2026-11-14 12:00:00

Additive only: creates the new `audit_logs` table. No existing table or row is touched.
Old/new values use a JSON column (MySQL 5.7+/8, SQLite 3.9+).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9c4e2d7b1f3'
down_revision = 'b5d1e8c3a7f2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('actor_name', sa.String(length=150), nullable=False),
        sa.Column('actor_role', sa.String(length=20), nullable=True),
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('module', sa.String(length=40), nullable=False),
        sa.Column('resource_id', sa.String(length=64), nullable=True),
        sa.Column('resource_label', sa.String(length=150), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=False),
        sa.Column('old_values', sa.JSON(), nullable=True),
        sa.Column('new_values', sa.JSON(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])
    op.create_index('ix_audit_logs_module_created', 'audit_logs', ['module', 'created_at'])
    op.create_index('ix_audit_logs_action_created', 'audit_logs', ['action', 'created_at'])
    op.create_index('ix_audit_logs_actor_created', 'audit_logs', ['actor_id', 'created_at'])


def downgrade():
    # Deletes the whole audit trail. Back up first.
    op.drop_table('audit_logs')
