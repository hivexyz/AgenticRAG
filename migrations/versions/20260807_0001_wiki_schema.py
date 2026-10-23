"""wiki schema

Revision ID: 20260807_0001
Revises: 20260807_0000
Create Date: 2026-08-07
"""

from __future__ import annotations

from alembic import op

revision = "20260807_0001"
down_revision = "20260807_0000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wiki_pages (
            id SERIAL PRIMARY KEY,
            tenant_id VARCHAR(100) NOT NULL,
            knowledge_base VARCHAR(255) NULL,
            slug VARCHAR(255) NOT NULL,
            title VARCHAR(255) NOT NULL,
            summary TEXT NULL,
            content TEXT NOT NULL,
            source_document_id INTEGER NULL REFERENCES documents(id) ON DELETE SET NULL,
            source_chunk_ids JSONB NULL,
            page_metadata JSONB NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'ready',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_wiki_pages_tenant_id ON wiki_pages (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wiki_pages_tenant_slug ON wiki_pages (tenant_id, slug)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wiki_pages_tenant_kb_status ON wiki_pages (tenant_id, knowledge_base, status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wiki_pages_content_trgm ON wiki_pages USING gin (content gin_trgm_ops)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wiki_page_revisions (
            id SERIAL PRIMARY KEY,
            tenant_id VARCHAR(100) NOT NULL,
            page_id INTEGER NOT NULL REFERENCES wiki_pages(id) ON DELETE CASCADE,
            action VARCHAR(50) NOT NULL,
            title VARCHAR(255) NOT NULL,
            summary TEXT NULL,
            content TEXT NOT NULL,
            knowledge_base VARCHAR(255) NULL,
            revision_metadata JSONB NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_wiki_page_revisions_tenant_id ON wiki_page_revisions (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wiki_page_revisions_tenant_page ON wiki_page_revisions (tenant_id, page_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wiki_page_revisions_page_created ON wiki_page_revisions (page_id, created_at)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wiki_compile_jobs (
            id SERIAL PRIMARY KEY,
            tenant_id VARCHAR(100) NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'pending',
            document_ids JSONB NOT NULL,
            success_count INTEGER NOT NULL DEFAULT 0,
            failure_count INTEGER NOT NULL DEFAULT 0,
            result_metadata JSONB NULL,
            error TEXT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_wiki_compile_jobs_tenant_id ON wiki_compile_jobs (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wiki_compile_jobs_tenant_status ON wiki_compile_jobs (tenant_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wiki_compile_jobs_tenant_created ON wiki_compile_jobs (tenant_id, created_at)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wiki_page_links (
            id SERIAL PRIMARY KEY,
            tenant_id VARCHAR(100) NOT NULL,
            source_page_id INTEGER NOT NULL REFERENCES wiki_pages(id) ON DELETE CASCADE,
            target_page_id INTEGER NOT NULL REFERENCES wiki_pages(id) ON DELETE CASCADE,
            link_type VARCHAR(50) NOT NULL DEFAULT 'title_mention',
            evidence TEXT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_wiki_page_links_tenant_id ON wiki_page_links (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wiki_page_links_tenant_source ON wiki_page_links (tenant_id, source_page_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_wiki_page_links_tenant_target ON wiki_page_links (tenant_id, target_page_id)")


def downgrade() -> None:
    op.drop_index("ix_wiki_page_links_tenant_target", table_name="wiki_page_links", if_exists=True)
    op.drop_index("ix_wiki_page_links_tenant_source", table_name="wiki_page_links", if_exists=True)
    op.drop_index("ix_wiki_page_links_tenant_id", table_name="wiki_page_links", if_exists=True)
    op.drop_table("wiki_page_links", if_exists=True)

    op.drop_index("ix_wiki_compile_jobs_tenant_created", table_name="wiki_compile_jobs", if_exists=True)
    op.drop_index("ix_wiki_compile_jobs_tenant_status", table_name="wiki_compile_jobs", if_exists=True)
    op.drop_index("ix_wiki_compile_jobs_tenant_id", table_name="wiki_compile_jobs", if_exists=True)
    op.drop_table("wiki_compile_jobs", if_exists=True)

    op.drop_index("ix_wiki_page_revisions_page_created", table_name="wiki_page_revisions", if_exists=True)
    op.drop_index("ix_wiki_page_revisions_tenant_page", table_name="wiki_page_revisions", if_exists=True)
    op.drop_index("ix_wiki_page_revisions_tenant_id", table_name="wiki_page_revisions", if_exists=True)
    op.drop_table("wiki_page_revisions", if_exists=True)

    op.drop_index("ix_wiki_pages_content_trgm", table_name="wiki_pages", if_exists=True)
    op.drop_index("ix_wiki_pages_tenant_kb_status", table_name="wiki_pages", if_exists=True)
    op.drop_index("ix_wiki_pages_tenant_slug", table_name="wiki_pages", if_exists=True)
    op.drop_index("ix_wiki_pages_tenant_id", table_name="wiki_pages", if_exists=True)
    op.drop_table("wiki_pages", if_exists=True)
