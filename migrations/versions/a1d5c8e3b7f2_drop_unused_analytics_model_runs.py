"""drop the unused analytics_model_runs table

Revision ID: a1d5c8e3b7f2
Revises: f7b2d9a4c1e8
Create Date: 2026-11-20 09:00:00

analytics_model_runs belonged to an earlier forecasting plan. No model, query or command in the
project uses it any more (the live model registry is unclaimed_model_runs). It has no foreign keys,
so nothing else depends on it.

Safety: the upgrade refuses to run if the table contains any rows, so no data can be lost by accident.
The downgrade recreates the empty table exactly as it was.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1d5c8e3b7f2"
down_revision = "f7b2d9a4c1e8"
branch_labels = None
depends_on = None

TABLE = "analytics_model_runs"
INDEX = "ix_analytics_model_runs_key_active"


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(TABLE):
        return  # nothing to drop (already removed)
    rows = bind.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar()
    if rows:
        raise RuntimeError(
            f"{TABLE} contains {rows} row(s); refusing to drop it. Check the data, "
            "then delete the rows yourself if they are not needed and run the upgrade again."
        )
    op.drop_index(INDEX, table_name=TABLE)
    op.drop_table(TABLE)


def downgrade():
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("target", sa.String(length=40), nullable=False),
        sa.Column("granularity", sa.String(length=10), nullable=False),
        sa.Column("entity", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("algorithm", sa.String(length=40), nullable=True),
        sa.Column("kind", sa.String(length=10), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("feature_config", sa.JSON(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("data_start", sa.Date(), nullable=True),
        sa.Column("data_end", sa.Date(), nullable=True),
        sa.Column("n_observations", sa.Integer(), nullable=True),
        sa.Column("n_events", sa.Integer(), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("trained_by", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("granularity IN ('day', 'week')", name="ck_analytics_model_runs_granularity"),
        sa.CheckConstraint("status IN ('training', 'trained', 'evaluation_failed', 'error')",
                           name="ck_analytics_model_runs_status"),
        sa.CheckConstraint("version >= 1", name="ck_analytics_model_runs_version"),
        sa.CheckConstraint("is_active = 0 OR status = 'trained'", name="ck_analytics_model_runs_active_trained"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target", "granularity", "entity", "version", name="uq_analytics_model_runs_key_version"),
    )
    op.create_index(INDEX, TABLE, ["target", "granularity", "entity", "is_active"])
