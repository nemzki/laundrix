"""retire the Staff ID: make staff_credentials.staff_id_hash nullable

Revision ID: b5d1e8c3a7f2
Revises: a9c4e2d7b1f5
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa

revision = 'b5d1e8c3a7f2'
down_revision = 'a9c4e2d7b1f5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('staff_credentials') as batch:
        batch.alter_column('staff_id_hash', existing_type=sa.String(length=255), nullable=True)
    # Existing hashes are no longer needed; clear them so no credential-like data lingers.
    op.execute("UPDATE staff_credentials SET staff_id_hash = NULL")


def downgrade():
    op.execute("UPDATE staff_credentials SET staff_id_hash = 'retired' WHERE staff_id_hash IS NULL")
    with op.batch_alter_table('staff_credentials') as batch:
        batch.alter_column('staff_id_hash', existing_type=sa.String(length=255), nullable=False)
