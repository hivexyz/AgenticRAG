"""
应用配置模块
支持环境变量配置切换（开发/生产环境）
"""
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """应用配置类"""
    
    # 环境配置
    ENVIRONMENT: str = "development"  # development, production
    
    # 应用基本信息
    APP_NAME: str = "协和学院 API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # CORS 配置
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8080"]
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/app.log"
    
    # PostgreSQL 数据库配置
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "xiehe_institute"
    POSTGRES_POOL_SIZE: int = 10
    POSTGRES_MAX_OVERFLOW: int = 20
    
    # Milvus 向量数据库配置
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_USER: str = ""
    MILVUS_PASSWORD: str = ""
    MILVUS_COLLECTION_NAME: str = "vectors"
    MILVUS_DIMENSION: int = 768
    MILVUS_INDEX_TYPE: str = "IVF_FLAT"
    MILVUS_METRIC_TYPE: str = "L2"
    
    # OpenAI API 配置
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""  # 如果使用兼容 API（如 Azure、本地模型），设置此参数
    
    # LLM 模型配置
    OPENAI_MODEL: str = "gpt-3.5-turbo"
    OPENAI_TEMPERATURE: float = 0.7
    OPENAI_MAX_TOKENS: int = 2048
    OPENAI_TOP_P: float = 1.0
    OPENAI_FREQUENCY_PENALTY: float = 0.0
    OPENAI_PRESENCE_PENALTY: float = 0.0
    
    # Embedding 模型配置
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-ada-002"
    OPENAI_EMBEDDING_DIMENSION: int = 1536
    OPENAI_EMBEDDING_BASE_URL: str = ""  # Embedding 模型的独立 base URL
    
    # Reranker 模型配置
    OPENAI_RERANKER_MODEL: str = "gpt-3.5-turbo"
    OPENAI_RERANKER_TOP_K: int = 10
    OPENAI_RERANKER_BASE_URL: str = ""  # Reranker 模型的独立 base URL
    
    # AgenticRAG 配置
    AGENTIC_RAG_MAX_RETRIEVALS: int = 2  # 最大检索次数
    AGENTIC_RAG_QUALITY_THRESHOLD: float = 0.8  # 质量阈值
    AGENTIC_RAG_DEFAULT_TOP_K: int = 10  # 默认检索数量
    
    @property
    def postgres_url(self) -> str:
        """获取 PostgreSQL 连接 URL"""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    @property
    def postgres_url_sync(self) -> str:
        """获取 PostgreSQL 同步连接 URL（用于 Alembic）"""
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    @property
    def is_development(self) -> bool:
        """判断是否为开发环境"""
        return self.ENVIRONMENT.lower() == "development"
    
    @property
    def is_production(self) -> bool:
        """判断是否为生产环境"""
        return self.ENVIRONMENT.lower() == "production"
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        env_file_encoding = "utf-8"


# 创建全局配置实例
settings = Settings()
