"""identity verification

Adds two NEW tables. Nothing existing is altered, renamed or dropped, and no data is touched.

Revision ID: c7f3a91d5e20
Revises: 4b1d2288b22d
Create Date: 2026-10-22 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7f3a91d5e20'
down_revision = '4b1d2288b22d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'identity_verifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('public_id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('provider_session_id', sa.String(length=64), nullable=True),
        sa.Column('environment', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('reason_codes', sa.JSON(), nullable=True),
        sa.Column('error_code', sa.String(length=40), nullable=True),
        sa.Column('document_type', sa.String(length=40), nullable=True),
        sa.Column('consent_version', sa.String(length=20), nullable=True),
        sa.Column('consent_at', sa.DateTime(), nullable=True),
        sa.Column('provider_updated_at', sa.DateTime(), nullable=True),
        sa.Column('last_polled_at', sa.DateTime(), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('public_id', name='uq_identity_verifications_public_id'),
        sa.UniqueConstraint('provider_session_id', name='uq_identity_verifications_session'),
    )
    op.create_index('ix_identity_verifications_user_id', 'identity_verifications', ['user_id'], unique=False)
    op.create_index('ix_identity_verifications_status', 'identity_verifications', ['status'], unique=False)

    op.create_table(
        'identity_verification_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('verification_id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.String(length=64), nullable=True),
        sa.Column('source', sa.String(length=12), nullable=False),
        sa.Column('provider_status', sa.String(length=30), nullable=True),
        sa.Column('from_status', sa.String(length=20), nullable=True),
        sa.Column('to_status', sa.String(length=20), nullable=True),
        sa.Column('outcome', sa.String(length=24), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['verification_id'], ['identity_verifications.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id', name='uq_identity_verification_events_event_id'),
    )
    op.create_index(
        'ix_identity_verification_events_verification_id',
        'identity_verification_events', ['verification_id'], unique=False,
    )


def downgrade():
    # Child table first (it holds the foreign key). Only the two tables created above are dropped.
    op.drop_index('ix_identity_verification_events_verification_id', table_name='identity_verification_events')
    op.drop_table('identity_verification_events')
    op.drop_index('ix_identity_verifications_status', table_name='identity_verifications')
    op.drop_index('ix_identity_verifications_user_id', table_name='identity_verifications')
    op.drop_table('identity_verifications')
