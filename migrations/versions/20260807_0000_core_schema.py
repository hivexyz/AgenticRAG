"""core schema baseline

Revision ID: 20260807_0000
Revises:
Create Date: 2026-08-07
"""

from __future__ import annotations

from alembic import op

revision = "20260807_0000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id SERIAL PRIMARY KEY,
            tenant_id VARCHAR(100) NOT NULL DEFAULT 'default',
            title VARCHAR(255) NOT NULL,
            content TEXT NOT NULL,
            author VARCHAR(100) NULL,
            file_type VARCHAR(50) NULL,
            file_path VARCHAR(500) NULL,
            file_size INTEGER NULL,
            chunk_count INTEGER NULL DEFAULT 0,
            split_method VARCHAR(50) NULL,
            chunk_size INTEGER NULL,
            chunk_overlap INTEGER NULL,
            ingestion_status VARCHAR(50) NOT NULL DEFAULT 'ready',
            ingestion_error TEXT NULL,
            vector_status VARCHAR(50) NOT NULL DEFAULT 'not_requested',
            vector_error TEXT NULL,
            deletion_status VARCHAR(50) NOT NULL DEFAULT 'active',
            deletion_error TEXT NULL,
            doc_metadata TEXT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_tenant_id ON documents (tenant_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS document_chunks (
            id SERIAL PRIMARY KEY,
            tenant_id VARCHAR(100) NOT NULL,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            content_hash VARCHAR(64) NULL,
            token_count INTEGER NULL,
            page_number INTEGER NULL,
            section_title VARCHAR(500) NULL,
            chunk_metadata JSONB NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_chunks_tenant_id ON document_chunks (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_chunks_document_id ON document_chunks (document_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_chunks_content_hash ON document_chunks (content_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_chunks_tenant_document ON document_chunks (tenant_id, document_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_chunks_tenant_document_chunk ON document_chunks (tenant_id, document_id, chunk_index)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_chunks_content_trgm ON document_chunks USING gin (content gin_trgm_ops)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_sessions (
            id SERIAL PRIMARY KEY,
            tenant_id VARCHAR(100) NOT NULL,
            user_id VARCHAR(100) NULL,
            title VARCHAR(255) NOT NULL DEFAULT '新会话',
            status VARCHAR(50) NOT NULL DEFAULT 'active',
            latest_summary TEXT NULL,
            summary_updated_at TIMESTAMP NULL,
            summary_message_cutoff_id INTEGER NULL,
            summary_version INTEGER NOT NULL DEFAULT 0,
            latest_message_at TIMESTAMP NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_conversation_sessions_tenant_id ON conversation_sessions (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_conversation_sessions_user_id ON conversation_sessions (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_conversation_sessions_tenant_status ON conversation_sessions (tenant_id, status)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_messages (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES conversation_sessions(id) ON DELETE CASCADE,
            tenant_id VARCHAR(100) NOT NULL,
            role VARCHAR(50) NOT NULL,
            content TEXT NOT NULL,
            message_type VARCHAR(50) NOT NULL DEFAULT 'raw',
            token_count INTEGER NULL,
            metadata JSONB NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_conversation_messages_session_id ON conversation_messages (session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_conversation_messages_tenant_id ON conversation_messages (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_conversation_messages_session_created ON conversation_messages (session_id, created_at)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS answer_feedback (
            id SERIAL PRIMARY KEY,
            tenant_id VARCHAR(100) NOT NULL,
            session_id INTEGER NULL REFERENCES conversation_sessions(id) ON DELETE CASCADE,
            message_id INTEGER NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
            feedback_type VARCHAR(50) NOT NULL,
            rating VARCHAR(20) NOT NULL,
            reason VARCHAR(100) NULL,
            comment TEXT NULL,
            corrected_answer TEXT NULL,
            metadata JSONB NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_answer_feedback_tenant_id ON answer_feedback (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_answer_feedback_session_id ON answer_feedback (session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_answer_feedback_message_id ON answer_feedback (message_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_answer_feedback_feedback_type ON answer_feedback (feedback_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_answer_feedback_rating ON answer_feedback (rating)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_answer_feedback_reason ON answer_feedback (reason)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_answer_feedback_tenant_created ON answer_feedback (tenant_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_answer_feedback_tenant_reason ON answer_feedback (tenant_id, reason)")


def downgrade() -> None:
    op.drop_index("ix_answer_feedback_tenant_reason", table_name="answer_feedback", if_exists=True)
    op.drop_index("ix_answer_feedback_tenant_created", table_name="answer_feedback", if_exists=True)
    op.drop_index("ix_answer_feedback_reason", table_name="answer_feedback", if_exists=True)
    op.drop_index("ix_answer_feedback_rating", table_name="answer_feedback", if_exists=True)
    op.drop_index("ix_answer_feedback_feedback_type", table_name="answer_feedback", if_exists=True)
    op.drop_index("ix_answer_feedback_message_id", table_name="answer_feedback", if_exists=True)
    op.drop_index("ix_answer_feedback_session_id", table_name="answer_feedback", if_exists=True)
    op.drop_index("ix_answer_feedback_tenant_id", table_name="answer_feedback", if_exists=True)
    op.drop_table("answer_feedback", if_exists=True)

    op.drop_index("ix_conversation_messages_session_created", table_name="conversation_messages", if_exists=True)
    op.drop_index("ix_conversation_messages_tenant_id", table_name="conversation_messages", if_exists=True)
    op.drop_index("ix_conversation_messages_session_id", table_name="conversation_messages", if_exists=True)
    op.drop_table("conversation_messages", if_exists=True)

    op.drop_index("ix_conversation_sessions_tenant_status", table_name="conversation_sessions", if_exists=True)
    op.drop_index("ix_conversation_sessions_user_id", table_name="conversation_sessions", if_exists=True)
    op.drop_index("ix_conversation_sessions_tenant_id", table_name="conversation_sessions", if_exists=True)
    op.drop_table("conversation_sessions", if_exists=True)

    op.drop_index("ix_document_chunks_content_trgm", table_name="document_chunks", if_exists=True)
    op.drop_index("ix_document_chunks_tenant_document_chunk", table_name="document_chunks", if_exists=True)
    op.drop_index("ix_document_chunks_tenant_document", table_name="document_chunks", if_exists=True)
    op.drop_index("ix_document_chunks_content_hash", table_name="document_chunks", if_exists=True)
    op.drop_index("ix_document_chunks_document_id", table_name="document_chunks", if_exists=True)
    op.drop_index("ix_document_chunks_tenant_id", table_name="document_chunks", if_exists=True)
    op.drop_table("document_chunks", if_exists=True)

    op.drop_index("ix_documents_tenant_id", table_name="documents", if_exists=True)
    op.drop_table("documents", if_exists=True)
