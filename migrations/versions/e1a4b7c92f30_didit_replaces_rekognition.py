"""didit replaces rekognition

* identity_verifications: add `purpose` ("kyc" | "biometric_auth"); existing rows become "kyc".
* staff_credentials: drop the three AWS Rekognition columns (face_id, face_enrolled_at,
  biometric_consent_at). Face data now lives with Didit, not in Laundrix.

DATA NOTE: the dropped columns only held Rekognition face references. After this migration every
existing staff member must re-onboard through Didit (`flask new-enroll-link EMAIL`). Delete the
AWS collection separately (see docs/identity_verification.md, "Retiring AWS Rekognition").

Revision ID: e1a4b7c92f30
Revises: c7f3a91d5e20
Create Date: 2026-10-23 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e1a4b7c92f30'
down_revision = 'c7f3a91d5e20'
branch_labels = None
depends_on = None


def upgrade():
    # server_default fills existing rows with 'kyc' so the NOT NULL column can be added safely.
    op.add_column(
        'identity_verifications',
        sa.Column('purpose', sa.String(length=16), nullable=False, server_default='kyc'),
    )
    op.create_index(
        'ix_identity_verifications_user_purpose', 'identity_verifications', ['user_id', 'purpose'],
        unique=False,
    )

    op.drop_column('staff_credentials', 'biometric_consent_at')
    op.drop_column('staff_credentials', 'face_enrolled_at')
    op.drop_column('staff_credentials', 'face_id')


def downgrade():
    # Restores the columns' SHAPE only. The Rekognition face references are gone for good.
    op.add_column('staff_credentials', sa.Column('face_id', sa.String(length=64), nullable=True))
    op.add_column('staff_credentials', sa.Column('face_enrolled_at', sa.DateTime(), nullable=True))
    op.add_column('staff_credentials', sa.Column('biometric_consent_at', sa.DateTime(), nullable=True))

    op.drop_index('ix_identity_verifications_user_purpose', table_name='identity_verifications')
    op.drop_column('identity_verifications', 'purpose')
