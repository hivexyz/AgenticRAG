"""
API 路由主文件
"""
from fastapi import APIRouter
from app.routes import health, documents, ai, agentic_rag

# 创建主 API 路由器
api_router = APIRouter()

# 注册子路由
api_router.include_router(health.router, prefix="/health", tags=["健康检查"])
api_router.include_router(documents.router, prefix="/documents", tags=["文档管理"])
api_router.include_router(documents.router, prefix="/vectors", tags=["向量搜索"])
api_router.include_router(ai.router, prefix="/ai", tags=["AI 模型"])
api_router.include_router(agentic_rag.router, prefix="/ai", tags=["AgenticRAG"])

