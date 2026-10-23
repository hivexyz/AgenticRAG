"""
应用配置模块
支持环境变量配置切换（开发/生产环境）
"""
from typing import List, Optional

from pydantic import field_validator
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
    AUTH_ALLOW_ANONYMOUS: bool = False
    OIDC_TRUSTED_HEADER_ENABLED: bool = False
    TENANT_RATE_LIMIT_PER_MINUTE: int = 1000
    TENANT_TOKEN_QUOTA_PER_DAY: int = 1_000_000
    MODEL_COST_PER_1K_TOKENS_USD: float = 0.0

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
    POSTGRES_AUTO_CREATE_SCHEMA: Optional[bool] = None
    MAX_UPLOAD_SIZE_MB: int = 50

    # Wiki 后台编译任务配置
    WIKI_COMPILE_JOB_MAX_RETRIES: int = 3
    WIKI_COMPILE_JOB_RETRY_BACKOFF_SECONDS: int = 60
    WIKI_COMPILE_JOB_STALE_SECONDS: int = 1800
    WIKI_COMPILE_INLINE_SUBMIT: Optional[bool] = None
    WIKI_WORKER_POLL_SECONDS: int = 5
    WIKI_WORKER_BATCH_SIZE: int = 5

    @field_validator("POSTGRES_AUTO_CREATE_SCHEMA", "WIKI_COMPILE_INLINE_SUBMIT", mode="before")
    @classmethod
    def _normalize_optional_bool(cls, value):
        if value == "":
            return None
        return value
    
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
    EMBEDDING_CACHE_ENABLED: bool = True
    EMBEDDING_CACHE_TTL_SECONDS: int = 3600
    EMBEDDING_CACHE_MAX_SIZE: int = 4096
    
    # Reranker 模型配置
    OPENAI_RERANKER_MODEL: str = "gpt-3.5-turbo"
    OPENAI_RERANKER_TOP_K: int = 10
    OPENAI_RERANKER_BASE_URL: str = ""  # Reranker 模型的独立 base URL
    
    # AgenticRAG 配置
    AGENTIC_RAG_MAX_RETRIEVALS: int = 2  # 最大检索次数
    AGENTIC_RAG_QUALITY_THRESHOLD: float = 0.8  # 质量阈值
    AGENTIC_RAG_DEFAULT_TOP_K: int = 10  # 默认检索数量
    AGENTIC_RAG_MAX_SUB_QUERIES: int = 3
    QUERY_ANALYSIS_CACHE_ENABLED: bool = True
    QUERY_ANALYSIS_CACHE_TTL_SECONDS: int = 600
    QUERY_ANALYSIS_CACHE_MAX_SIZE: int = 1024
    RETRIEVAL_PROVIDER_TIMEOUT_SECONDS: float = 3.0
    RETRIEVAL_MAX_CONCURRENCY: int = 6
    MULTI_HOP_ENABLED: bool = True
    MULTI_HOP_MAX_HOPS: int = 2
    MULTI_HOP_MAX_QUERIES_PER_HOP: int = 2
    MULTI_HOP_TOTAL_TIMEOUT_SECONDS: float = 15.0
    MULTI_HOP_SLOT_TIMEOUT_SECONDS: float = 5.0
    MULTI_HOP_SLOT_EVIDENCE_DOCS: int = 3
    FEEDBACK_GOLDEN_SET_PATH: str = "data/eval/eval_cases.jsonl"

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
    def max_upload_size_bytes(self) -> int:
        return max(int(self.MAX_UPLOAD_SIZE_MB), 1) * 1024 * 1024

    @property
    def should_auto_create_postgres_schema(self) -> bool:
        """开发环境默认允许自举 schema，生产默认要求显式执行 Alembic。"""
        if self.POSTGRES_AUTO_CREATE_SCHEMA is not None:
            return self.POSTGRES_AUTO_CREATE_SCHEMA
        return self.is_development

    @property
    def should_submit_wiki_jobs_inline(self) -> bool:
        """开发环境默认在 Web 进程内立即执行任务；生产建议交给独立 worker。"""
        if self.WIKI_COMPILE_INLINE_SUBMIT is not None:
            return self.WIKI_COMPILE_INLINE_SUBMIT
        return self.is_development
    
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
