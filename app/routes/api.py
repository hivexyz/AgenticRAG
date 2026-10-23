"""
API 路由主文件
"""
from fastapi import APIRouter
from app.routes import health, documents, vectors, ai, agentic_rag, conversations, feedback, wiki, auth

# 创建主 API 路由器
api_router = APIRouter()

# 注册子路由
api_router.include_router(health.router, prefix="/health", tags=["健康检查"])
api_router.include_router(auth.router, prefix="/auth", tags=["认证上下文"])
api_router.include_router(documents.router, prefix="/documents", tags=["文档管理"])
api_router.include_router(wiki.router, prefix="/wiki", tags=["Wiki 页面"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["会话管理"])
api_router.include_router(feedback.router, prefix="/feedback", tags=["用户反馈"])
api_router.include_router(vectors.router, prefix="/vectors", tags=["向量搜索"])
api_router.include_router(ai.router, prefix="/ai", tags=["AI 模型"])
api_router.include_router(agentic_rag.router, prefix="/ai", tags=["AgenticRAG"])
