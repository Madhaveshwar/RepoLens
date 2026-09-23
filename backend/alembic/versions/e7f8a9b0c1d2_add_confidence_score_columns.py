"""add_confidence_score_columns

Revision ID: e7f8a9b0c1d2
Revises: a1b2c3d4e5f6
Create Date: 2026-06-22 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add confidence_score columns to findings tables."""
    op.add_column('security_findings', sa.Column('confidence_score', sa.Integer(), nullable=True, server_default='85'))
    op.add_column('code_smells', sa.Column('confidence_score', sa.Integer(), nullable=True, server_default='85'))


def downgrade() -> None:
    """Remove the added columns."""
    op.drop_column('code_smells', 'confidence_score')
    op.drop_column('security_findings', 'confidence_score')
