"""Add snapshot identity columns to analyses and analysis_result_cache table.

Revision ID: h5j6k7l8m9n0
Revises: g3h4i5j6k7l8
Create Date: 2026-09-25

Snapshot consistency + persistent result reuse:
- analyses.commit_sha / branch / analysis_version: the EXACT repository
  snapshot a scan analyzed, stored on the scan row itself.
- analysis_result_cache: production source of truth for deterministic result
  reuse (repository + commit + analysis version ⇒ stored result). Replaces
  reliance on the local JSON reviewer cache, which Render instances lose on
  restart/redeploy.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "h5j6k7l8m9n0"
down_revision = "g3h4i5j6k7l8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Snapshot identity columns on analyses ──────────────────────────
    op.add_column("analyses", sa.Column("commit_sha", sa.String(), nullable=True))
    op.add_column("analyses", sa.Column("branch", sa.String(), nullable=True))
    op.add_column("analyses", sa.Column("analysis_version", sa.String(), nullable=True))
    op.create_index(op.f("ix_analyses_commit_sha"), "analyses", ["commit_sha"], unique=False)
    op.create_index(op.f("ix_analyses_analysis_version"), "analyses", ["analysis_version"], unique=False)

    # ── Persistent scan result cache ───────────────────────────────────
    op.create_table(
        "analysis_result_cache",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=False),
        sa.Column("commit_sha", sa.String(), nullable=False),
        sa.Column("analysis_version", sa.String(), nullable=False),
        sa.Column("cache_key", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_hit_at", sa.DateTime(), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analysis_result_cache_repository_id"), "analysis_result_cache", ["repository_id"], unique=False)
    op.create_index(op.f("ix_analysis_result_cache_commit_sha"), "analysis_result_cache", ["commit_sha"], unique=False)
    op.create_index(op.f("ix_analysis_result_cache_analysis_version"), "analysis_result_cache", ["analysis_version"], unique=False)
    # Unique constraint on the natural key — enables atomic INSERT ... ON CONFLICT DO NOTHING.
    op.create_index(op.f("ix_analysis_result_cache_cache_key"), "analysis_result_cache", ["cache_key"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_analysis_result_cache_cache_key"), table_name="analysis_result_cache")
    op.drop_index(op.f("ix_analysis_result_cache_analysis_version"), table_name="analysis_result_cache")
    op.drop_index(op.f("ix_analysis_result_cache_commit_sha"), table_name="analysis_result_cache")
    op.drop_index(op.f("ix_analysis_result_cache_repository_id"), table_name="analysis_result_cache")
    op.drop_table("analysis_result_cache")
    op.drop_index(op.f("ix_analyses_analysis_version"), table_name="analyses")
    op.drop_index(op.f("ix_analyses_commit_sha"), table_name="analyses")
    op.drop_column("analyses", "analysis_version")
    op.drop_column("analyses", "branch")
    op.drop_column("analyses", "commit_sha")
