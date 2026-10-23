"""
FastAPI 应用主入口
"""
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI
from app.auth import validate_auth_startup_policy
from app.config import settings
from app.routes import api
from app.middleware.cors import add_cors_middleware
from app.middleware.request_context import RequestContextMiddleware
from app.utils.logger import logger
from app.database import postgres_manager
from app.database.vector_store import vector_store
from app.models import llm_manager, embedding_manager, reranker_manager
from app.agents import agentic_rag_manager
from app.tasks import task_runner
from app.services.wiki import recover_wiki_compile_jobs, run_wiki_compile_job


APP_STATE: Dict[str, Any] = {
    "postgres": {"ready": False, "error": None, "required": True},
    "vector_store": {"ready": False, "error": None, "required": True, "backend": None},
    "llm": {"ready": False, "error": None, "required": False},
    "embedding": {"ready": False, "error": None, "required": False},
    "reranker": {"ready": False, "error": None, "required": False},
    "agent_graph": {"ready": False, "error": None, "required": False},
}


def _set_component_state(name: str, *, ready: bool, error: str | None = None, **extra: Any) -> None:
    state = APP_STATE.setdefault(name, {})
    state["ready"] = ready
    state["error"] = error
    for key, value in extra.items():
        state[key] = value


def _is_ready() -> bool:
    for component in APP_STATE.values():
        if component.get("required") and not component.get("ready"):
            return False
    return True


async def startup_event() -> None:
    """应用启动时执行。"""
    logger.info(f"{settings.APP_NAME} v{settings.APP_VERSION} 正在启动...")
    logger.info(f"环境: {settings.ENVIRONMENT}")
    logger.info(f"主机: {settings.HOST}:{settings.PORT}")
    validate_auth_startup_policy()

    try:
        await postgres_manager.init_db()
        _set_component_state("postgres", ready=True, error=None)
        logger.info("PostgreSQL 数据库初始化成功")
        if settings.should_submit_wiki_jobs_inline:
            recovered = await recover_wiki_compile_jobs(
                lambda job_id: task_runner.submit(f"wiki-compile:{job_id}", lambda: run_wiki_compile_job(job_id))
            )
            if recovered["recovered_count"]:
                logger.info(f"已恢复 Wiki 编译任务: {recovered}")
        else:
            logger.info("Wiki 编译任务由独立 worker 负责恢复与执行")
    except Exception as e:
        _set_component_state("postgres", ready=False, error=str(e))
        logger.error(f"PostgreSQL 数据库初始化失败: {e}")
        raise

    try:
        vector_store.connect()
        await vector_store.ensure_ready()
        _set_component_state(
            "vector_store",
            ready=True,
            error=None,
            backend=vector_store.backend_name,
        )
        logger.info(f"向量数据库后端初始化成功: {vector_store.backend_name}")
    except Exception as e:
        _set_component_state(
            "vector_store",
            ready=False,
            error=str(e),
            backend=getattr(vector_store, "backend_name", None),
        )
        logger.error(f"向量数据库后端初始化失败: {e}")
        raise

    try:
        llm_manager.connect()
        _set_component_state("llm", ready=True, error=None)
        logger.info("LLM 模型初始化成功")
    except Exception as e:
        _set_component_state("llm", ready=False, error=str(e))
        logger.warning(f"LLM 模型初始化失败: {e}")

    try:
        embedding_manager.connect()
        _set_component_state("embedding", ready=True, error=None)
        logger.info("Embedding 模型初始化成功")
    except Exception as e:
        _set_component_state("embedding", ready=False, error=str(e))
        logger.warning(f"Embedding 模型初始化失败: {e}")

    try:
        reranker_manager.connect()
        _set_component_state("reranker", ready=True, error=None)
        logger.info("Reranker 模型初始化成功")
    except Exception as e:
        _set_component_state("reranker", ready=False, error=str(e))
        logger.warning(f"Reranker 模型初始化失败: {e}")

    try:
        agentic_rag_manager.build_graph()
        _set_component_state("agent_graph", ready=True, error=None)
        logger.info("AgenticRAG 图构建成功")
    except Exception as e:
        _set_component_state("agent_graph", ready=False, error=str(e))
        logger.warning(f"AgenticRAG 图构建失败: {e}")


async def shutdown_event() -> None:
    """应用关闭时执行。"""
    logger.info(f"{settings.APP_NAME} 正在关闭...")

    try:
        await postgres_manager.close_db()
        logger.info("PostgreSQL 数据库连接已关闭")
    except Exception as e:
        logger.error(f"关闭 PostgreSQL 数据库连接失败: {e}")

    try:
        vector_store.disconnect()
        logger.info(f"向量数据库后端已断开: {vector_store.backend_name}")
    except Exception as e:
        logger.error(f"断开向量数据库连接失败: {e}")

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

    try:
        await task_runner.shutdown()
        logger.info("后台任务执行器已关闭")
    except Exception as e:
        logger.warning(f"关闭后台任务执行器失败: {e}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await startup_event()
    try:
        yield
    finally:
        await shutdown_event()


# 创建 FastAPI 应用实例
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AgenticRAG项目",
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    lifespan=lifespan,
)
app.state.app_status = APP_STATE
app.state.is_ready = _is_ready

# 添加请求上下文中间件
app.add_middleware(RequestContextMiddleware)

# 添加 CORS 中间件
add_cors_middleware(app)

# 注册路由
app.include_router(api.api_router, prefix="/api/v1")


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": f"欢迎使用 {settings.APP_NAME}",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "docs": "/docs" if settings.is_development else None,
        "redoc": "/redoc" if settings.is_development else None,
        "ready": _is_ready(),
    }


@app.get("/api/v1")
async def api_root():
    """API 根路径"""
    return {
        "message": "API v1",
        "endpoints": {
            "health": "/api/v1/health",
            "ready": "/api/v1/health/ready",
        }
    }
