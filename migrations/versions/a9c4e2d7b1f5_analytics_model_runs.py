"""analytics model registry

Revision ID: a9c4e2d7b1f5
Revises: f2b7d4c9a1e3
Create Date: 2026-11-12 09:00:00

Additive only: one new table, analytics_model_runs, the audit trail of forecasting-model training runs
(algorithm, plain-number parameters, evaluation metrics, data range).  It contains no customer, staff
or payment-level data and no foreign keys, so existing tables and rows are untouched.  Nothing is
created or trained by this migration; the table stays empty until `flask analytics-train` is run.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9c4e2d7b1f5'
down_revision = 'f2b7d4c9a1e3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'analytics_model_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('target', sa.String(length=40), nullable=False),
        sa.Column('granularity', sa.String(length=10), nullable=False),
        sa.Column('entity', sa.String(length=160), nullable=False, server_default=''),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('algorithm', sa.String(length=40), nullable=True),
        sa.Column('kind', sa.String(length=10), nullable=True),
        sa.Column('params', sa.JSON(), nullable=True),
        sa.Column('feature_config', sa.JSON(), nullable=True),
        sa.Column('metrics', sa.JSON(), nullable=True),
        sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column('checksum', sa.String(length=64), nullable=True),
        sa.Column('data_start', sa.Date(), nullable=True),
        sa.Column('data_end', sa.Date(), nullable=True),
        sa.Column('n_observations', sa.Integer(), nullable=True),
        sa.Column('n_events', sa.Integer(), nullable=True),
        sa.Column('message', sa.String(length=500), nullable=True),
        sa.Column('trained_by', sa.String(length=64), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("granularity IN ('day', 'week')", name='ck_analytics_model_runs_granularity'),
        sa.CheckConstraint("status IN ('training', 'trained', 'evaluation_failed', 'error')",
                           name='ck_analytics_model_runs_status'),
        sa.CheckConstraint('version >= 1', name='ck_analytics_model_runs_version'),
        sa.CheckConstraint("is_active = 0 OR status = 'trained'", name='ck_analytics_model_runs_active_trained'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('target', 'granularity', 'entity', 'version', name='uq_analytics_model_runs_key_version'),
    )
    op.create_index('ix_analytics_model_runs_key_active', 'analytics_model_runs',
                    ['target', 'granularity', 'entity', 'is_active'])


def downgrade():
    # Removes only the training history and the stored models (they can be re-created with
    # `flask analytics-train`).  No order, customer or payment data is touched.
    op.drop_index('ix_analytics_model_runs_key_active', table_name='analytics_model_runs')
    op.drop_table('analytics_model_runs')
