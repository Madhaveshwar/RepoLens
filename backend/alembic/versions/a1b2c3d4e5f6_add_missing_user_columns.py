"""add_missing_user_columns

Revision ID: a1b2c3d4e5f6
Revises: d0e6e4a97dc9
Create Date: 2026-06-19 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'd0e6e4a97dc9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing columns to users table."""
    op.add_column('users', sa.Column('openai_api_key_encrypted', sa.String(), nullable=True))
    op.add_column('users', sa.Column('claude_api_key_encrypted', sa.String(), nullable=True))
    op.add_column('users', sa.Column('gemini_api_key_encrypted', sa.String(), nullable=True))
    op.add_column('users', sa.Column('openrouter_api_key_encrypted', sa.String(), nullable=True))
    op.add_column('users', sa.Column('llm_default_provider', sa.String(), nullable=True, server_default='groq'))
    op.add_column('users', sa.Column('llm_default_model', sa.String(), nullable=True))
    op.add_column('users', sa.Column('llm_temperature', sa.Float(), nullable=True, server_default='0.3'))
    op.add_column('users', sa.Column('llm_max_tokens', sa.Integer(), nullable=True, server_default='4096'))


def downgrade() -> None:
    """Remove the added columns."""
    op.drop_column('users', 'llm_max_tokens')
    op.drop_column('users', 'llm_temperature')
    op.drop_column('users', 'llm_default_model')
    op.drop_column('users', 'llm_default_provider')
    op.drop_column('users', 'openrouter_api_key_encrypted')
    op.drop_column('users', 'gemini_api_key_encrypted')
    op.drop_column('users', 'claude_api_key_encrypted')
    op.drop_column('users', 'openai_api_key_encrypted')
