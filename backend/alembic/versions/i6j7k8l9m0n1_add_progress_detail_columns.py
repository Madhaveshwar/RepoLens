"""Add truthful live-progress columns to analyses.

Revision ID: i6j7k8l9m0n1
Revises: h5j6k7l8m9n0
Create Date: 2026-09-28

The scan worker already publishes progress details (status message, current
file, total files) to Redis for WebSocket subscribers, but polling clients
read the database — which never stored them. That is why the UI showed
"Files Scanned: 0" and generic stage names during long scans. These columns
persist the real progress state.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "i6j7k8l9m0n1"
down_revision = "h5j6k7l8m9n0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("status_message", sa.String(500), nullable=True))
    op.add_column("analyses", sa.Column("current_file", sa.String(300), nullable=True))
    op.add_column("analyses", sa.Column("total_files_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("analyses", "total_files_count")
    op.drop_column("analyses", "current_file")
    op.drop_column("analyses", "status_message")
