"""normalize_user_emails

Data migration: lowercase and trim all user emails so they match how the
application stores new registrations (see _normalize_email in
app/routers/auth.py).

Why: registration previously stored emails with the domain auto-lowercased
(pydantic EmailStr) but the local part kept its original case, while login
compared emails case-sensitively. Users who signed up with any uppercase
letter (e.g. mobile autocapitalize) could never sign in again. The app now
normalizes everywhere; this migration brings existing rows in line.

Behaviour:
- Emails are normalized to ``email.strip().lower()``.
- When two accounts would collide after normalization (e.g. ``John@x.com``
  and ``JOHN@x.com`` both exist), the OLDEST account keeps the normalized
  address and the newer duplicate is left untouched (skipped). Skipped rows
  still work because the application looks emails up case-insensitively.
  Accounts are never merged or deleted.
- Running the migration twice is a no-op (idempotent).

Works on both SQLite and PostgreSQL: it uses SQLAlchemy Core expressions
with typed columns so UUID values are adapted correctly per dialect.

Downgrade cannot restore the original casing (that information is lost when
lowercasing), so it is a no-op.

Revision ID: b8c9d0e1f2a3
Revises: f2a3b4c5d6e7
Create Date: 2026-09-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Lightweight inline table definition (deliberately NOT imported from
# app.models so this migration stays valid even if the models change later).
users_table = sa.Table(
    'users',
    sa.MetaData(),
    sa.Column('id', sa.UUID(), primary_key=True),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
)


def _normalize(email: str) -> str:
    # Keep in sync with app/routers/auth.py::_normalize_email
    return (email or "").strip().lower()


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(
        sa.select(
            users_table.c.id,
            users_table.c.email,
        ).order_by(users_table.c.created_at.asc(), users_table.c.id.asc())
    ).fetchall()

    # First pass: decide who owns each normalized address (oldest wins).
    owner_by_normalized: dict[str, object] = {}
    for row in rows:
        target = _normalize(row.email)
        if target and target not in owner_by_normalized:
            owner_by_normalized[target] = row.id

    # Second pass: update only rows that (a) differ from their normalized
    # form and (b) own that normalized form. Colliding duplicates and
    # already-normalized rows are left untouched.
    normalized_count = 0
    skipped_count = 0
    for row in rows:
        email = row.email
        target = _normalize(email)
        if not email or target == email:
            continue  # already normalized (or empty)
        if owner_by_normalized.get(target) != row.id:
            skipped_count += 1
            print(f"  email normalization skipped (duplicate of an older account): {email!r}")
            continue
        conn.execute(
            users_table.update()
            .where(users_table.c.id == row.id)
            .values(email=target)
        )
        normalized_count += 1

    print(
        f"  normalize_user_emails: {normalized_count} email(s) normalized, "
        f"{skipped_count} duplicate(s) skipped, {len(rows)} user(s) examined"
    )


def downgrade() -> None:
    # No-op: the original mixed-case/whitespace spelling cannot be recovered
    # after lowercasing. The application handles both normalized and
    # unnormalized emails, so nothing else needs to change.
    pass
