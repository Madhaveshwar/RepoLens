"""add repository insights tables

Creates tables for the repository insights features and adds the
`source` column to security_findings / code_smells so AI-generated
findings can be distinguished from deterministic/static findings.

Revision ID: g3h4i5j6k7l8
Revises: b8c9d0e1f2a3
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'g3h4i5j6k7l8'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── finding source provenance columns ──────────────────────────
    op.add_column('security_findings', sa.Column('source', sa.String(), nullable=True))
    op.add_column('code_smells', sa.Column('source', sa.String(), nullable=True))

    # ── 1. repository_health_snapshots ─────────────────────────────
    op.create_table(
        'repository_health_snapshots',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('repository_id', sa.UUID(), nullable=False),
        sa.Column('analysis_id', sa.UUID(), nullable=False),
        sa.Column('branch', sa.String(), nullable=True),
        sa.Column('commit_sha', sa.String(), nullable=True),
        sa.Column('health_score', sa.Integer(), nullable=False),
        sa.Column('security_score', sa.Integer(), nullable=True),
        sa.Column('code_quality_score', sa.Integer(), nullable=True),
        sa.Column('code_smell_count', sa.Integer(), nullable=True),
        sa.Column('performance_issue_count', sa.Integer(), nullable=True),
        sa.Column('critical_count', sa.Integer(), nullable=True),
        sa.Column('high_count', sa.Integer(), nullable=True),
        sa.Column('medium_count', sa.Integer(), nullable=True),
        sa.Column('low_count', sa.Integer(), nullable=True),
        sa.Column('total_issue_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id']),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_repository_health_snapshots_repository_id'), 'repository_health_snapshots', ['repository_id'])
    op.create_index(op.f('ix_repository_health_snapshots_analysis_id'), 'repository_health_snapshots', ['analysis_id'])
    op.create_index(op.f('ix_repository_health_snapshots_created_at'), 'repository_health_snapshots', ['created_at'])

    # ── 2. dependency_findings ─────────────────────────────────────
    op.create_table(
        'dependency_findings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('analysis_id', sa.UUID(), nullable=False),
        sa.Column('ecosystem', sa.String(), nullable=False),
        sa.Column('manifest_file', sa.String(), nullable=False),
        sa.Column('package_name', sa.String(), nullable=False),
        sa.Column('version_spec', sa.String(), nullable=True),
        sa.Column('resolved_version', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('severity', sa.String(), nullable=True),
        sa.Column('advisory_id', sa.String(), nullable=True),
        sa.Column('vulnerable_range', sa.String(), nullable=True),
        sa.Column('recommended_version', sa.String(), nullable=True),
        sa.Column('advisory_url', sa.String(), nullable=True),
        sa.Column('evidence', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_dependency_findings_analysis_id'), 'dependency_findings', ['analysis_id'])

    # ── 3. duplicate_code_findings ─────────────────────────────────
    op.create_table(
        'duplicate_code_findings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('analysis_id', sa.UUID(), nullable=False),
        sa.Column('file_a', sa.String(), nullable=False),
        sa.Column('start_line_a', sa.Integer(), nullable=False),
        sa.Column('end_line_a', sa.Integer(), nullable=False),
        sa.Column('file_b', sa.String(), nullable=False),
        sa.Column('start_line_b', sa.Integer(), nullable=False),
        sa.Column('end_line_b', sa.Integer(), nullable=False),
        sa.Column('similarity', sa.Integer(), nullable=False),
        sa.Column('duplicated_lines', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(), nullable=True),
        sa.Column('snippet', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_duplicate_code_findings_analysis_id'), 'duplicate_code_findings', ['analysis_id'])
    op.create_index(op.f('ix_duplicate_code_findings_token_hash'), 'duplicate_code_findings', ['token_hash'])

    # ── 4. technical_debt_findings ─────────────────────────────────
    op.create_table(
        'technical_debt_findings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('analysis_id', sa.UUID(), nullable=False),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('severity', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('evidence', sa.Text(), nullable=False),
        sa.Column('file', sa.String(), nullable=True),
        sa.Column('line_start', sa.Integer(), nullable=True),
        sa.Column('line_end', sa.Integer(), nullable=True),
        sa.Column('estimated_effort_hours', sa.Float(), nullable=True),
        sa.Column('remediation', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_technical_debt_findings_analysis_id'), 'technical_debt_findings', ['analysis_id'])

    # ── 5. architecture_analyses ───────────────────────────────────
    op.create_table(
        'architecture_analyses',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('analysis_id', sa.UUID(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_architecture_analyses_analysis_id'), 'architecture_analyses', ['analysis_id'])

    # ── 6. complexity_findings ─────────────────────────────────────
    op.create_table(
        'complexity_findings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('analysis_id', sa.UUID(), nullable=False),
        sa.Column('file', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('line_start', sa.Integer(), nullable=False),
        sa.Column('line_end', sa.Integer(), nullable=True),
        sa.Column('cyclomatic_complexity', sa.Integer(), nullable=False),
        sa.Column('nesting_depth', sa.Integer(), nullable=True),
        sa.Column('length_lines', sa.Integer(), nullable=True),
        sa.Column('language', sa.String(), nullable=True),
        sa.Column('severity', sa.String(), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=True),
        sa.Column('suggestion', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_complexity_findings_analysis_id'), 'complexity_findings', ['analysis_id'])

    # ── 7. pull_request_reviews ────────────────────────────────────
    op.create_table(
        'pull_request_reviews',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('repository_id', sa.UUID(), nullable=False),
        sa.Column('pr_number', sa.Integer(), nullable=False),
        sa.Column('head_sha', sa.String(), nullable=True),
        sa.Column('base_branch', sa.String(), nullable=True),
        sa.Column('head_branch', sa.String(), nullable=True),
        sa.Column('author', sa.String(), nullable=True),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('risk_score', sa.Integer(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('findings_json', sa.JSON(), nullable=False),
        sa.Column('files_changed', sa.Integer(), nullable=True),
        sa.Column('additions', sa.Integer(), nullable=True),
        sa.Column('deletions', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_pull_request_reviews_repository_id'), 'pull_request_reviews', ['repository_id'])
    op.create_index(op.f('ix_pull_request_reviews_pr_number'), 'pull_request_reviews', ['pr_number'])

    # ── 8. commit_analyses ─────────────────────────────────────────
    op.create_table(
        'commit_analyses',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('repository_id', sa.UUID(), nullable=False),
        sa.Column('commit_sha', sa.String(), nullable=False),
        sa.Column('parent_sha', sa.String(), nullable=True),
        sa.Column('author', sa.String(), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('committed_at', sa.DateTime(), nullable=True),
        sa.Column('files_changed', sa.Integer(), nullable=True),
        sa.Column('additions', sa.Integer(), nullable=True),
        sa.Column('deletions', sa.Integer(), nullable=True),
        sa.Column('security_impact', sa.Text(), nullable=True),
        sa.Column('quality_impact', sa.Text(), nullable=True),
        sa.Column('code_smells_json', sa.JSON(), nullable=True),
        sa.Column('complexity_json', sa.JSON(), nullable=True),
        sa.Column('ai_summary', sa.Text(), nullable=True),
        sa.Column('findings_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_commit_analyses_repository_id'), 'commit_analyses', ['repository_id'])
    op.create_index(op.f('ix_commit_analyses_commit_sha'), 'commit_analyses', ['commit_sha'])


def downgrade() -> None:
    op.drop_index(op.f('ix_commit_analyses_commit_sha'), table_name='commit_analyses')
    op.drop_index(op.f('ix_commit_analyses_repository_id'), table_name='commit_analyses')
    op.drop_table('commit_analyses')

    op.drop_index(op.f('ix_pull_request_reviews_pr_number'), table_name='pull_request_reviews')
    op.drop_index(op.f('ix_pull_request_reviews_repository_id'), table_name='pull_request_reviews')
    op.drop_table('pull_request_reviews')

    op.drop_index(op.f('ix_complexity_findings_analysis_id'), table_name='complexity_findings')
    op.drop_table('complexity_findings')

    op.drop_index(op.f('ix_architecture_analyses_analysis_id'), table_name='architecture_analyses')
    op.drop_table('architecture_analyses')

    op.drop_index(op.f('ix_technical_debt_findings_analysis_id'), table_name='technical_debt_findings')
    op.drop_table('technical_debt_findings')

    op.drop_index(op.f('ix_duplicate_code_findings_token_hash'), table_name='duplicate_code_findings')
    op.drop_index(op.f('ix_duplicate_code_findings_analysis_id'), table_name='duplicate_code_findings')
    op.drop_table('duplicate_code_findings')

    op.drop_index(op.f('ix_dependency_findings_analysis_id'), table_name='dependency_findings')
    op.drop_table('dependency_findings')

    op.drop_index(op.f('ix_repository_health_snapshots_created_at'), table_name='repository_health_snapshots')
    op.drop_index(op.f('ix_repository_health_snapshots_analysis_id'), table_name='repository_health_snapshots')
    op.drop_index(op.f('ix_repository_health_snapshots_repository_id'), table_name='repository_health_snapshots')
    op.drop_table('repository_health_snapshots')

    op.drop_column('code_smells', 'source')
    op.drop_column('security_findings', 'source')
