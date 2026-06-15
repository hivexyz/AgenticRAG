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
        logger.info("PostgreSQL 数据库初始化完成")
    
    async def close_db(self):
        """关闭数据库连接"""
        await self.engine.dispose()
        logger.info("PostgreSQL 数据库连接已关闭")


# 创建全局数据库管理器实例
postgres_manager = PostgreSQLManager()
