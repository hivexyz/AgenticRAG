"""
FastAPI 应用主入口
"""
from fastapi import FastAPI
from app.config import settings
from app.routes import api
from app.middleware.cors import add_cors_middleware
from app.utils.logger import logger
from app.database import postgres_manager, milvus_manager
from app.models import llm_manager, embedding_manager, reranker_manager
from app.agents import agentic_rag_manager

# 创建 FastAPI 应用实例
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="协和学院 FastAPI 项目",
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
)

# 添加 CORS 中间件
add_cors_middleware(app)

# 注册路由
app.include_router(api.api_router, prefix="/api/v1")


@app.on_event("startup")
async def startup_event():
    """
    应用启动时执行
    """
    logger.info(f"{settings.APP_NAME} v{settings.APP_VERSION} 正在启动...")
    logger.info(f"环境: {settings.ENVIRONMENT}")
    logger.info(f"主机: {settings.HOST}:{settings.PORT}")
    
    # 初始化 PostgreSQL 数据库
    try:
        await postgres_manager.init_db()
        logger.info("PostgreSQL 数据库初始化成功")
    except Exception as e:
        logger.error(f"PostgreSQL 数据库初始化失败: {e}")
    
    # 连接 Milvus 向量数据库
    try:
        milvus_manager.connect()
        logger.info("Milvus 向量数据库连接成功")
    except Exception as e:
        logger.error(f"Milvus 向量数据库连接失败: {e}")
    
    # 初始化 AI 模型
    try:
        llm_manager.connect()
        logger.info("LLM 模型初始化成功")
    except Exception as e:
        logger.warning(f"LLM 模型初始化失败: {e}")
    
    try:
        embedding_manager.connect()
        logger.info("Embedding 模型初始化成功")
    except Exception as e:
        logger.warning(f"Embedding 模型初始化失败: {e}")
    
    try:
        reranker_manager.connect()
        logger.info("Reranker 模型初始化成功")
    except Exception as e:
        logger.warning(f"Reranker 模型初始化失败: {e}")
    
    # 初始化 AgenticRAG
    try:
        agentic_rag_manager.build_graph()
        logger.info("AgenticRAG 图构建成功")
    except Exception as e:
        logger.warning(f"AgenticRAG 图构建失败: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """
    应用关闭时执行
    """
    logger.info(f"{settings.APP_NAME} 正在关闭...")
    
    # 关闭 PostgreSQL 数据库连接
    try:
        await postgres_manager.close_db()
        logger.info("PostgreSQL 数据库连接已关闭")
    except Exception as e:
        logger.error(f"关闭 PostgreSQL 数据库连接失败: {e}")
    
    # 断开 Milvus 连接
    try:
        milvus_manager.disconnect()
        logger.info("Milvus 向量数据库连接已断开")
    except Exception as e:
        logger.error(f"断开 Milvus 连接失败: {e}")
    
    # 关闭 AI 模型
    try:
        llm_manager.disconnect()
        logger.info("LLM 模型已关闭")
    except Exception as e:
        logger.warning(f"关闭 LLM 模型失败: {e}")
    
    try:
        embedding_manager.disconnect()
        logger.info("Embedding 模型已关闭")
    except Exception as e:
        logger.warning(f"关闭 Embedding 模型失败: {e}")
    
    try:
        reranker_manager.disconnect()
        logger.info("Reranker 模型已关闭")
    except Exception as e:
        logger.warning(f"关闭 Reranker 模型失败: {e}")


@app.get("/")
async def root():
    """
    根路径
    """
    return {
        "message": f"欢迎使用 {settings.APP_NAME}",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "docs": "/docs" if settings.is_development else None,
        "redoc": "/redoc" if settings.is_development else None,
    }


@app.get("/api/v1")
async def api_root():
    """
    API 根路径
    """
    return {
        "message": "API v1",
        "endpoints": {
            "health": "/api/v1/health",
        }
    }
