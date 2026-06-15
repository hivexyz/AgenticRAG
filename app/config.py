"""
应用配置模块
支持环境变量配置切换（开发/生产环境）
"""
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置类"""
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # 环境配置
    ENVIRONMENT: str = "development"  # development, production
    
    # 应用基本信息
    APP_NAME: str = "协和学院 API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # 多租户配置
    DEFAULT_TENANT_ID: str = "default"


    # 认证配置
    AUTH_ENABLED: bool = False
    AUTH_API_KEYS: str = ""  # 形如 key1:tenant_a,key2:tenant_b

    # 向量存储后端配置
    VECTOR_STORE_BACKEND: str = "milvus"  # milvus, pgvector
    
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
    MILVUS_DIMENSION: int = 1536
    MILVUS_INDEX_TYPE: str = "IVF_FLAT"
    MILVUS_METRIC_TYPE: str = "L2"

    # pgvector 配置
    PGVECTOR_TABLE_NAME: str = "document_vectors"
    PGVECTOR_DISTANCE_METRIC: str = "cosine"  # cosine, l2, ip
    PGVECTOR_IVFFLAT_LISTS: int = 100
    
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
    def vector_dimension(self) -> int:
        """统一的向量维度配置。

        兼容旧配置：
        - 新配置显式设置 `OPENAI_EMBEDDING_DIMENSION` 时，优先使用该值；
        - 旧部署若仅设置 `MILVUS_DIMENSION`，则继续沿用该值，避免升级后维度回归。
        """
        if "OPENAI_EMBEDDING_DIMENSION" in self.model_fields_set:
            return self.OPENAI_EMBEDDING_DIMENSION
        return self.MILVUS_DIMENSION

    @property
    def vector_store_backend(self) -> str:
        """当前启用的向量存储后端。"""
        return self.VECTOR_STORE_BACKEND.strip().lower()

    @property
    def vector_dimensions_aligned(self) -> bool:
        """Milvus 与 Embedding 配置的维度是否一致。"""
        return self.MILVUS_DIMENSION == self.OPENAI_EMBEDDING_DIMENSION
    
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
    
# 创建全局配置实例
settings = Settings()
