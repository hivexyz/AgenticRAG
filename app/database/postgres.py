"""
PostgreSQL 数据库管理
使用 SQLAlchemy 和 asyncpg 进行异步数据库操作
"""
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config import settings
from app.utils.logger import logger

# 创建异步引擎
engine = create_async_engine(
    settings.postgres_url,
    echo=settings.DEBUG,
    pool_size=settings.POSTGRES_POOL_SIZE,
    max_overflow=settings.POSTGRES_MAX_OVERFLOW,
    pool_pre_ping=True,
)

# 创建异步会话工厂
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# 创建基类
Base = declarative_base()


class PostgreSQLManager:
    """PostgreSQL 数据库管理器"""
    
    def __init__(self):
        self.engine = engine
        self.async_session_maker = async_session_maker
        self.Base = Base
    
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        获取数据库会话
        
        Yields:
            AsyncSession: 数据库会话
        """
        async with self.async_session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"数据库会话错误: {e}")
                raise
            finally:
                await session.close()
    
    async def init_db(self):
        """初始化数据库，创建所有表"""
        if not settings.should_auto_create_postgres_schema:
            logger.info("跳过 PostgreSQL 自动 schema 自举；请使用 alembic upgrade head 管理数据库结构")
            return
        if settings.is_production:
            logger.warning("生产环境启用了 PostgreSQL 自动 schema 自举；建议关闭 POSTGRES_AUTO_CREATE_SCHEMA 并使用 Alembic")

        async with self.engine.begin() as conn:
            await conn.run_sync(self.Base.metadata.create_all)
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            await conn.execute(
                text(
                    "ALTER TABLE documents "
                    "ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) NOT NULL DEFAULT 'default'"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_documents_tenant_id ON documents (tenant_id)"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_document_chunks_tenant_id "
                    "ON document_chunks (tenant_id)"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_document_chunks_tenant_document "
                    "ON document_chunks (tenant_id, document_id)"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_document_chunks_content_trgm "
                    "ON document_chunks USING gin (content gin_trgm_ops)"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_document_chunks_content_tsvector "
                    "ON document_chunks USING gin (to_tsvector('simple', coalesce(content, '')))"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS vector_status VARCHAR(50) NOT NULL DEFAULT 'not_requested'"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS vector_error TEXT"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS deletion_status VARCHAR(50) NOT NULL DEFAULT 'active'"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS deletion_error TEXT"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS ingestion_status VARCHAR(50) NOT NULL DEFAULT 'ready'"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64) NULL"
                )
            )
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_content_hash ON documents (content_hash)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_tenant_content_hash ON documents (tenant_id, content_hash)"))
            await conn.execute(
                text(
                    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS ingestion_error TEXT"
                )
            )
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS conversation_sessions ("
                    "id SERIAL PRIMARY KEY, "
                    "tenant_id VARCHAR(100) NOT NULL, "
                    "user_id VARCHAR(100), "
                    "title VARCHAR(255) NOT NULL DEFAULT '新会话', "
                    "status VARCHAR(50) NOT NULL DEFAULT 'active', "
                    "latest_summary TEXT, "
                    "summary_updated_at TIMESTAMP NULL, "
                    "summary_message_cutoff_id INTEGER NULL, "
                    "summary_version INTEGER NOT NULL DEFAULT 0, "
                    "latest_message_at TIMESTAMP NULL, "
                    "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                    "updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )
            await conn.execute(text("ALTER TABLE conversation_sessions ADD COLUMN IF NOT EXISTS summary_updated_at TIMESTAMP NULL"))
            await conn.execute(text("ALTER TABLE conversation_sessions ADD COLUMN IF NOT EXISTS summary_message_cutoff_id INTEGER NULL"))
            await conn.execute(text("ALTER TABLE conversation_sessions ADD COLUMN IF NOT EXISTS summary_version INTEGER NOT NULL DEFAULT 0"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_conversation_sessions_tenant_id ON conversation_sessions (tenant_id)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_conversation_sessions_tenant_status ON conversation_sessions (tenant_id, status)"))
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS conversation_messages ("
                    "id SERIAL PRIMARY KEY, "
                    "session_id INTEGER NOT NULL REFERENCES conversation_sessions(id) ON DELETE CASCADE, "
                    "tenant_id VARCHAR(100) NOT NULL, "
                    "role VARCHAR(50) NOT NULL, "
                    "content TEXT NOT NULL, "
                    "message_type VARCHAR(50) NOT NULL DEFAULT 'raw', "
                    "token_count INTEGER NULL, "
                    "metadata JSONB NULL, "
                    "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_conversation_messages_session_id ON conversation_messages (session_id)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_conversation_messages_session_created ON conversation_messages (session_id, created_at)"))
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS answer_feedback ("
                    "id SERIAL PRIMARY KEY, "
                    "tenant_id VARCHAR(100) NOT NULL, "
                    "session_id INTEGER NULL REFERENCES conversation_sessions(id) ON DELETE CASCADE, "
                    "message_id INTEGER NULL REFERENCES conversation_messages(id) ON DELETE CASCADE, "
                    "feedback_type VARCHAR(50) NOT NULL, "
                    "rating VARCHAR(20) NOT NULL, "
                    "reason VARCHAR(100) NULL, "
                    "comment TEXT NULL, "
                    "corrected_answer TEXT NULL, "
                    "metadata JSONB NULL, "
                    "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_answer_feedback_tenant_created ON answer_feedback (tenant_id, created_at)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_answer_feedback_tenant_reason ON answer_feedback (tenant_id, reason)"))
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS wiki_pages ("
                    "id SERIAL PRIMARY KEY, "
                    "tenant_id VARCHAR(100) NOT NULL, "
                    "knowledge_base VARCHAR(255) NULL, "
                    "slug VARCHAR(255) NOT NULL, "
                    "title VARCHAR(255) NOT NULL, "
                    "summary TEXT NULL, "
                    "content TEXT NOT NULL, "
                    "source_document_id INTEGER NULL REFERENCES documents(id) ON DELETE SET NULL, "
                    "source_chunk_ids JSONB NULL, "
                    "page_metadata JSONB NULL, "
                    "status VARCHAR(50) NOT NULL DEFAULT 'ready', "
                    "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                    "updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )
            await conn.execute(text("ALTER TABLE wiki_pages ADD COLUMN IF NOT EXISTS knowledge_base VARCHAR(255) NULL"))
            await conn.execute(text("ALTER TABLE wiki_pages ADD COLUMN IF NOT EXISTS slug VARCHAR(255)"))
            await conn.execute(text("ALTER TABLE wiki_pages ADD COLUMN IF NOT EXISTS title VARCHAR(255)"))
            await conn.execute(text("ALTER TABLE wiki_pages ADD COLUMN IF NOT EXISTS summary TEXT"))
            await conn.execute(text("ALTER TABLE wiki_pages ADD COLUMN IF NOT EXISTS content TEXT"))
            await conn.execute(text("ALTER TABLE wiki_pages ADD COLUMN IF NOT EXISTS source_document_id INTEGER NULL"))
            await conn.execute(text("ALTER TABLE wiki_pages ADD COLUMN IF NOT EXISTS source_chunk_ids JSONB NULL"))
            await conn.execute(text("ALTER TABLE wiki_pages ADD COLUMN IF NOT EXISTS page_metadata JSONB NULL"))
            await conn.execute(text("ALTER TABLE wiki_pages ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'ready'"))
            await conn.execute(text("ALTER TABLE wiki_pages ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"))
            await conn.execute(text("ALTER TABLE wiki_pages ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP"))
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_wiki_pages_tenant_id "
                    "ON wiki_pages (tenant_id)"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_wiki_pages_tenant_slug "
                    "ON wiki_pages (tenant_id, slug)"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_wiki_pages_tenant_kb_status "
                    "ON wiki_pages (tenant_id, knowledge_base, status)"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_wiki_pages_content_trgm "
                    "ON wiki_pages USING gin (content gin_trgm_ops)"
                )
            )
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS wiki_page_revisions ("
                    "id SERIAL PRIMARY KEY, "
                    "tenant_id VARCHAR(100) NOT NULL, "
                    "page_id INTEGER NOT NULL REFERENCES wiki_pages(id) ON DELETE CASCADE, "
                    "action VARCHAR(50) NOT NULL, "
                    "title VARCHAR(255) NOT NULL, "
                    "summary TEXT NULL, "
                    "content TEXT NOT NULL, "
                    "knowledge_base VARCHAR(255) NULL, "
                    "revision_metadata JSONB NULL, "
                    "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_wiki_page_revisions_tenant_id ON wiki_page_revisions (tenant_id)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_wiki_page_revisions_tenant_page ON wiki_page_revisions (tenant_id, page_id)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_wiki_page_revisions_page_created ON wiki_page_revisions (page_id, created_at)"))
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS wiki_compile_jobs ("
                    "id SERIAL PRIMARY KEY, "
                    "tenant_id VARCHAR(100) NOT NULL, "
                    "status VARCHAR(50) NOT NULL DEFAULT 'pending', "
                    "document_ids JSONB NOT NULL, "
                    "success_count INTEGER NOT NULL DEFAULT 0, "
                    "failure_count INTEGER NOT NULL DEFAULT 0, "
                    "result_metadata JSONB NULL, "
                    "error TEXT NULL, "
                    "locked_by VARCHAR(100) NULL, "
                    "locked_at TIMESTAMP NULL, "
                    "retry_count INTEGER NOT NULL DEFAULT 0, "
                    "max_retries INTEGER NOT NULL DEFAULT 3, "
                    "next_run_at TIMESTAMP NULL, "
                    "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                    "updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )
            await conn.execute(text("ALTER TABLE wiki_compile_jobs ADD COLUMN IF NOT EXISTS locked_by VARCHAR(100) NULL"))
            await conn.execute(text("ALTER TABLE wiki_compile_jobs ADD COLUMN IF NOT EXISTS locked_at TIMESTAMP NULL"))
            await conn.execute(text("ALTER TABLE wiki_compile_jobs ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0"))
            await conn.execute(text("ALTER TABLE wiki_compile_jobs ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 3"))
            await conn.execute(text("ALTER TABLE wiki_compile_jobs ADD COLUMN IF NOT EXISTS next_run_at TIMESTAMP NULL"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_wiki_compile_jobs_tenant_id ON wiki_compile_jobs (tenant_id)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_wiki_compile_jobs_tenant_status ON wiki_compile_jobs (tenant_id, status)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_wiki_compile_jobs_tenant_created ON wiki_compile_jobs (tenant_id, created_at)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_wiki_compile_jobs_tenant_status_next_run ON wiki_compile_jobs (tenant_id, status, next_run_at)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_wiki_compile_jobs_locked ON wiki_compile_jobs (status, locked_at)"))
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS wiki_page_links ("
                    "id SERIAL PRIMARY KEY, "
                    "tenant_id VARCHAR(100) NOT NULL, "
                    "source_page_id INTEGER NOT NULL REFERENCES wiki_pages(id) ON DELETE CASCADE, "
                    "target_page_id INTEGER NOT NULL REFERENCES wiki_pages(id) ON DELETE CASCADE, "
                    "link_type VARCHAR(50) NOT NULL DEFAULT 'title_mention', "
                    "evidence TEXT NULL, "
                    "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_wiki_page_links_tenant_id ON wiki_page_links (tenant_id)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_wiki_page_links_tenant_source ON wiki_page_links (tenant_id, source_page_id)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_wiki_page_links_tenant_target ON wiki_page_links (tenant_id, target_page_id)"))
        logger.info("PostgreSQL 数据库初始化完成")
    
    async def close_db(self):
        """关闭数据库连接"""
        await self.engine.dispose()
        logger.info("PostgreSQL 数据库连接已关闭")


# 创建全局数据库管理器实例
postgres_manager = PostgreSQLManager()
