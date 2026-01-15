"""
PostgreSQL 数据库管理
使用 SQLAlchemy 和 asyncpg 进行异步数据库操作
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from typing import AsyncGenerator
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
        logger.info("PostgreSQL 数据库初始化完成")
    
    async def close_db(self):
        """关闭数据库连接"""
        await self.engine.dispose()
        logger.info("PostgreSQL 数据库连接已关闭")


# 创建全局数据库管理器实例
postgres_manager = PostgreSQLManager()
