"""sparse tsvector index

Revision ID: 20261021_0004
Revises: 20261021_0003
Create Date: 2026-10-21
"""

from __future__ import annotations

from alembic import op

revision = "20261021_0004"
down_revision = "20261021_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_content_tsvector "
        "ON document_chunks USING gin (to_tsvector('simple', coalesce(content, '')))"
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_content_tsvector", table_name="document_chunks", if_exists=True)
