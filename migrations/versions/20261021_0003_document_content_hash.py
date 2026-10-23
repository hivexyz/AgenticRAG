"""document content hash

Revision ID: 20261021_0003
Revises: 20261020_0002
Create Date: 2026-10-21
"""

from __future__ import annotations

from alembic import op

revision = "20261021_0003"
down_revision = "20261020_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64) NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_content_hash ON documents (content_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_tenant_content_hash ON documents (tenant_id, content_hash)")


def downgrade() -> None:
    op.drop_index("ix_documents_tenant_content_hash", table_name="documents", if_exists=True)
    op.drop_index("ix_documents_content_hash", table_name="documents", if_exists=True)
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS content_hash")
