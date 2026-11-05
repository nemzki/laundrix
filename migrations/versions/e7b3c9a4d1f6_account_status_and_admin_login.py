"""account status, approval audit columns and administrator password login

Revision ID: e7b3c9a4d1f6
Revises: d4e8f1a2b6c7
Create Date: 2026-11-03 09:00:00

Additive only. Existing users keep working:
  * every existing account becomes `active`, EXCEPT accounts that were already switched off
    (is_active = false), which become `deactivated`;
  * administrator password columns start empty (existing administrators keep signing in with Google);
  * auth_events gains two nullable columns, so existing audit rows are untouched.
batch_alter_table issues plain ALTERs on MySQL and rebuilds the table on SQLite (used in tests).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7b3c9a4d1f6'
down_revision = 'd4e8f1a2b6c7'
branch_labels = None
depends_on = None

STATUSES = ("pending_verification", "pending_approval", "active", "rejected", "suspended", "deactivated")


def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('account_status', sa.String(length=24), nullable=False, server_default='active'))
        batch.add_column(sa.Column('status_reason', sa.String(length=255), nullable=True))
        batch.add_column(sa.Column('status_changed_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('status_changed_by_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('approved_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('approved_by_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('username', sa.String(length=40), nullable=True))
        batch.add_column(sa.Column('password_hash', sa.String(length=255), nullable=True))
        batch.add_column(sa.Column('failed_login_attempts', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('locked_until', sa.DateTime(), nullable=True))

    # Safe defaults for existing rows: already-disabled accounts stay disabled and are labelled as such.
    op.get_bind().execute(
        sa.text("UPDATE users SET account_status = 'deactivated' WHERE is_active = :inactive"),
        {"inactive": False},
    )

    with op.batch_alter_table('users') as batch:
        batch.create_index('ix_users_account_status', ['account_status'])
        batch.create_unique_constraint('uq_users_username', ['username'])
        batch.create_foreign_key('fk_users_status_changed_by_id', 'users', ['status_changed_by_id'], ['id'], ondelete='SET NULL')
        batch.create_foreign_key('fk_users_approved_by_id', 'users', ['approved_by_id'], ['id'], ondelete='SET NULL')
        batch.create_check_constraint(
            'ck_users_account_status',
            "account_status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")",
        )

    with op.batch_alter_table('auth_events') as batch:
        batch.add_column(sa.Column('target_user_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('detail', sa.String(length=500), nullable=True))
    with op.batch_alter_table('auth_events') as batch:
        batch.create_index('ix_auth_events_target_user_id', ['target_user_id'])
        batch.create_foreign_key('fk_auth_events_target_user_id', 'users', ['target_user_id'], ['id'], ondelete='SET NULL')


def downgrade():
    # Drops the new columns (account status, approval trail, administrator passwords). Back up first.
    with op.batch_alter_table('auth_events') as batch:
        batch.drop_constraint('fk_auth_events_target_user_id', type_='foreignkey')
        batch.drop_index('ix_auth_events_target_user_id')
    with op.batch_alter_table('auth_events') as batch:
        batch.drop_column('detail')
        batch.drop_column('target_user_id')

    with op.batch_alter_table('users') as batch:
        batch.drop_constraint('ck_users_account_status', type_='check')
        batch.drop_constraint('fk_users_approved_by_id', type_='foreignkey')
        batch.drop_constraint('fk_users_status_changed_by_id', type_='foreignkey')
        batch.drop_constraint('uq_users_username', type_='unique')
        batch.drop_index('ix_users_account_status')
    with op.batch_alter_table('users') as batch:
        batch.drop_column('locked_until')
        batch.drop_column('failed_login_attempts')
        batch.drop_column('password_hash')
        batch.drop_column('username')
        batch.drop_column('approved_by_id')
        batch.drop_column('approved_at')
        batch.drop_column('status_changed_by_id')
        batch.drop_column('status_changed_at')
        batch.drop_column('status_reason')
        batch.drop_column('account_status')
