"""
CORS 中间件配置
"""
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
from app.config import settings


def add_cors_middleware(app: FastAPI):
    """
    添加 CORS 中间件
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

