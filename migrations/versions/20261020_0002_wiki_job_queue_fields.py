"""add durable wiki job queue fields

Revision ID: 20261020_0002
Revises: 20260807_0001
Create Date: 2026-10-20
"""

from __future__ import annotations

from alembic import op

revision = "20261020_0002"
down_revision = "20260807_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE wiki_compile_jobs ADD COLUMN IF NOT EXISTS locked_by VARCHAR(100) NULL")
    op.execute("ALTER TABLE wiki_compile_jobs ADD COLUMN IF NOT EXISTS locked_at TIMESTAMP NULL")
    op.execute("ALTER TABLE wiki_compile_jobs ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE wiki_compile_jobs ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 3")
    op.execute("ALTER TABLE wiki_compile_jobs ADD COLUMN IF NOT EXISTS next_run_at TIMESTAMP NULL")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wiki_compile_jobs_tenant_status_next_run "
        "ON wiki_compile_jobs (tenant_id, status, next_run_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wiki_compile_jobs_locked "
        "ON wiki_compile_jobs (status, locked_at)"
    )


def downgrade() -> None:
    op.drop_index("ix_wiki_compile_jobs_locked", table_name="wiki_compile_jobs", if_exists=True)
    op.drop_index("ix_wiki_compile_jobs_tenant_status_next_run", table_name="wiki_compile_jobs", if_exists=True)
    op.execute("ALTER TABLE wiki_compile_jobs DROP COLUMN IF EXISTS next_run_at")
    op.execute("ALTER TABLE wiki_compile_jobs DROP COLUMN IF EXISTS max_retries")
    op.execute("ALTER TABLE wiki_compile_jobs DROP COLUMN IF EXISTS retry_count")
    op.execute("ALTER TABLE wiki_compile_jobs DROP COLUMN IF EXISTS locked_at")
    op.execute("ALTER TABLE wiki_compile_jobs DROP COLUMN IF EXISTS locked_by")
