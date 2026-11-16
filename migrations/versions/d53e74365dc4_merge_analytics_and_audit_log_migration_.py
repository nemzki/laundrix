"""merge analytics and audit log migration branches

Revision ID: d53e74365dc4
Revises: a9c4e2d7b1f3, a9c4e2d7b1f5
Create Date: 2026-11-16 08:42:40.905865

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd53e74365dc4'
down_revision = ('a9c4e2d7b1f3', 'a9c4e2d7b1f5')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
