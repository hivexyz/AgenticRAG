"""统一的向量存储抽象，支持 Milvus / pgvector。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.orm import declarative_base

from app.config import settings
from app.database.postgres import engine
from app.database.milvus import MilvusManager, milvus_manager
from app.utils.logger import logger
from app.utils.retrieval_filters import build_pgvector_filter_sql
from app.utils.tenancy import validate_tenant_id

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # pragma: no cover - optional dependency in runtime
    Vector = None  # type: ignore[assignment]


PGVectorBase = declarative_base()


class VectorStore(ABC):
    """向量存储统一接口。"""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """当前后端名称。"""

    @abstractmethod
    def connect(self) -> None:
        """建立连接。"""

    @abstractmethod
    def disconnect(self) -> None:
        """关闭连接。"""

    @abstractmethod
    def ensure_ready(
        self,
        collection_name: Optional[str] = None,
        dimension: Optional[int] = None,
        create_index: bool = True,
        load: bool = True,
        tenant_id: Optional[str] = None,
    ) -> Any:
        """确保后端已可用。"""

    @abstractmethod
    def get_collection_name(self, tenant_id: Optional[str] = None) -> str:
        """获取集合/表名。"""

    @abstractmethod
    def insert_vectors(
        self,
        vectors: List[List[float]],
        metadata: Optional[List[Dict[str, Any]]] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        """插入向量。"""

    @abstractmethod
    def search_vectors(
        self,
        query_vectors: List[List[float]],
        top_k: int = 10,
        expr: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> List[List[Dict[str, Any]]]:
        """检索向量。"""

    @abstractmethod
    def delete_vectors_by_document_id(self, document_id: int, tenant_id: Optional[str] = None) -> int:
        """按文档删除向量。"""


class MilvusVectorStore(VectorStore):
    """Milvus 适配层。"""

    def __init__(self, manager: MilvusManager):
        self.manager = manager

    @property
    def backend_name(self) -> str:
        return "milvus"

    def connect(self) -> None:
        self.manager.connect()

    def disconnect(self) -> None:
        self.manager.disconnect()

    def ensure_ready(
        self,
        collection_name: Optional[str] = None,
        dimension: Optional[int] = None,
        create_index: bool = True,
        load: bool = True,
        tenant_id: Optional[str] = None,
    ) -> Any:
        return self.manager.ensure_ready(
            collection_name=collection_name,
            dimension=dimension,
            create_index=create_index,
            load=load,
            tenant_id=tenant_id,
        )

    def get_collection_name(self, tenant_id: Optional[str] = None) -> str:
        return self.manager.get_collection_name(tenant_id)

    def insert_vectors(
        self,
        vectors: List[List[float]],
        metadata: Optional[List[Dict[str, Any]]] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        self.manager.insert_vectors(vectors, metadata, tenant_id=tenant_id)

    def search_vectors(
        self,
        query_vectors: List[List[float]],
        top_k: int = 10,
        expr: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> List[List[Dict[str, Any]]]:
        return self.manager.search_vectors(
            query_vectors,
            top_k=top_k,
            expr=expr,
            params=params,
            tenant_id=tenant_id,
        )

    def delete_vectors_by_document_id(self, document_id: int, tenant_id: Optional[str] = None) -> int:
        return self.manager.delete_vectors_by_document_id(document_id, tenant_id=tenant_id)


if Vector is not None:
    class DocumentVector(PGVectorBase):
        """pgvector 向量表。"""

        __tablename__ = settings.PGVECTOR_TABLE_NAME

        id = Column(Integer, primary_key=True, autoincrement=True)
        tenant_id = Column(String(100), nullable=False, index=True)
        document_id = Column(Integer, nullable=False, index=True)
        embedding = Column(Vector(settings.vector_dimension), nullable=False)
        vector_metadata = Column("metadata", JSONB, nullable=False, default=dict)
        created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

        __table_args__ = (
            Index(
                f"ix_{settings.PGVECTOR_TABLE_NAME}_tenant_document",
                "tenant_id",
                "document_id",
            ),
        )
else:
    DocumentVector = None


class PGVectorStore(VectorStore):
    """PostgreSQL + pgvector 实现。"""

    def __init__(self):
        self.engine = engine
        self.table = DocumentVector
        self.distance_metric = settings.PGVECTOR_DISTANCE_METRIC.strip().lower()
        self.connected = False

    @property
    def backend_name(self) -> str:
        return "pgvector"

    def _require_pgvector(self) -> None:
        if self.table is None or Vector is None:
            raise RuntimeError("当前未安装 pgvector 依赖，请先安装 pgvector Python 包")

    def connect(self) -> None:
        self._require_pgvector()
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    async def _create_pgvector_extension(self, conn: AsyncConnection) -> None:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    async def _create_ivfflat_index(self, conn: AsyncConnection) -> None:
        metric_ops = {
            "cosine": "vector_cosine_ops",
            "l2": "vector_l2_ops",
            "ip": "vector_ip_ops",
        }
        operator_class = metric_ops.get(self.distance_metric)
        if not operator_class:
            raise RuntimeError(
                f"不支持的 PGVECTOR_DISTANCE_METRIC: {self.distance_metric}，支持 cosine/l2/ip"
            )

        index_name = f"ix_{settings.PGVECTOR_TABLE_NAME}_embedding_ivfflat"
        sql = (
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {settings.PGVECTOR_TABLE_NAME} "
            f"USING ivfflat (embedding {operator_class}) "
            f"WITH (lists = {int(settings.PGVECTOR_IVFFLAT_LISTS)})"
        )
        await conn.execute(text(sql))

    def ensure_ready(
        self,
        collection_name: Optional[str] = None,
        dimension: Optional[int] = None,
        create_index: bool = True,
        load: bool = True,
        tenant_id: Optional[str] = None,
    ) -> str:
        self._require_pgvector()
        if not self.connected:
            raise RuntimeError("pgvector 后端尚未连接")

        import asyncio

        async def _ensure() -> None:
            async with self.engine.begin() as conn:
                await self._create_pgvector_extension(conn)
                await conn.run_sync(PGVectorBase.metadata.create_all)
                if create_index:
                    await self._create_ivfflat_index(conn)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_ensure())
        else:
            if loop.is_running():
                raise RuntimeError("请在异步上下文外调用 PGVectorStore.ensure_ready()")

        return self.get_collection_name(tenant_id)

    async def async_ensure_ready(
        self,
        create_index: bool = True,
        tenant_id: Optional[str] = None,
    ) -> str:
        self._require_pgvector()
        if not self.connected:
            raise RuntimeError("pgvector 后端尚未连接")

        async with self.engine.begin() as conn:
            await self._create_pgvector_extension(conn)
            await conn.run_sync(PGVectorBase.metadata.create_all)
            if create_index:
                await self._create_ivfflat_index(conn)
        return self.get_collection_name(tenant_id)

    def get_collection_name(self, tenant_id: Optional[str] = None) -> str:
        return settings.PGVECTOR_TABLE_NAME

    def insert_vectors(
        self,
        vectors: List[List[float]],
        metadata: Optional[List[Dict[str, Any]]] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        raise RuntimeError("PGVectorStore.insert_vectors 需要使用异步版本 async_insert_vectors")

    async def async_insert_vectors(
        self,
        vectors: List[List[float]],
        metadata: Optional[List[Dict[str, Any]]] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        self._require_pgvector()
        await self.async_ensure_ready()

        if not vectors:
            logger.warning("收到空向量列表，跳过插入")
            return

        normalized_tenant_id = validate_tenant_id(tenant_id)
        if metadata is not None and len(metadata) != len(vectors):
            raise ValueError("metadata 数量必须与 vectors 数量一致")

        payload = []
        for index, vector in enumerate(vectors):
            if len(vector) != settings.vector_dimension:
                raise ValueError(
                    f"向量维度不匹配: got={len(vector)}, expected={settings.vector_dimension}"
                )
            item = dict((metadata or [{} for _ in vectors])[index])
            item["tenant_id"] = normalized_tenant_id
            payload.append(
                self.table(
                    tenant_id=normalized_tenant_id,
                    document_id=int(item.get("document_id", 0)),
                    embedding=vector,
                    vector_metadata=item,
                )
            )

        from app.database.postgres import async_session_maker

        async with async_session_maker() as session:
            session.add_all(payload)
            await session.commit()

    def _distance_sql(self) -> str:
        mapping = {
            "cosine": "embedding <=> CAST(:query_vector AS vector)",
            "l2": "embedding <-> CAST(:query_vector AS vector)",
            "ip": "embedding <#> CAST(:query_vector AS vector)",
        }
        if self.distance_metric not in mapping:
            raise RuntimeError(
                f"不支持的 PGVECTOR_DISTANCE_METRIC: {self.distance_metric}，支持 cosine/l2/ip"
            )
        return mapping[self.distance_metric]

    def _vector_literal(self, vector: List[float]) -> str:
        return "[" + ", ".join(str(value) for value in vector) + "]"

    def search_vectors(
        self,
        query_vectors: List[List[float]],
        top_k: int = 10,
        expr: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> List[List[Dict[str, Any]]]:
        raise RuntimeError("PGVectorStore.search_vectors 需要使用异步版本 async_search_vectors")

    async def async_search_vectors(
        self,
        query_vectors: List[List[float]],
        top_k: int = 10,
        expr: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> List[List[Dict[str, Any]]]:
        self._require_pgvector()
        await self.async_ensure_ready()

        if not query_vectors:
            return []

        normalized_tenant_id = validate_tenant_id(tenant_id)
        results: List[List[Dict[str, Any]]] = []
        distance_sql = self._distance_sql()

        from app.database.postgres import async_session_maker

        async with async_session_maker() as session:
            for vector in query_vectors:
                if len(vector) != settings.vector_dimension:
                    raise ValueError(
                        f"查询向量维度不匹配: got={len(vector)}, expected={settings.vector_dimension}"
                    )

                sql = text(
                    f"SELECT id, metadata, {distance_sql} AS distance "
                    f"FROM {settings.PGVECTOR_TABLE_NAME} "
                    f"WHERE tenant_id = :tenant_id "
                    f"{self._metadata_filter_where(params)} "
                    f"ORDER BY distance ASC LIMIT :top_k"
                )
                filter_params = self._metadata_filter_params(params)
                query = await session.execute(
                    sql,
                    {
                        "tenant_id": normalized_tenant_id,
                        "query_vector": self._vector_literal(vector),
                        "top_k": top_k,
                        **filter_params,
                    },
                )
                hits = []
                for row in query.mappings().all():
                    hits.append(
                        {
                            "id": row["id"],
                            "distance": row["distance"],
                            "score": row["distance"],
                            "metadata": row["metadata"],
                        }
                    )
                results.append(hits)

        return results

    def _metadata_filter_where(self, params: Optional[Dict[str, Any]]) -> str:
        filters = (params or {}).get("metadata_filters") if isinstance(params, dict) else None
        clauses, _ = build_pgvector_filter_sql(filters if isinstance(filters, dict) else None)
        if not clauses:
            return ""
        return "AND " + " AND ".join(f"({clause})" for clause in clauses)

    def _metadata_filter_params(self, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        filters = (params or {}).get("metadata_filters") if isinstance(params, dict) else None
        _, filter_params = build_pgvector_filter_sql(filters if isinstance(filters, dict) else None)
        return filter_params

    def delete_vectors_by_document_id(self, document_id: int, tenant_id: Optional[str] = None) -> int:
        raise RuntimeError(
            "PGVectorStore.delete_vectors_by_document_id 需要使用异步版本 async_delete_vectors_by_document_id"
        )

    async def async_delete_vectors_by_document_id(self, document_id: int, tenant_id: Optional[str] = None) -> int:
        self._require_pgvector()
        await self.async_ensure_ready(create_index=False)

        normalized_tenant_id = validate_tenant_id(tenant_id)
        from app.database.postgres import async_session_maker

        async with async_session_maker() as session:
            result = await session.execute(
                text(
                    f"DELETE FROM {settings.PGVECTOR_TABLE_NAME} "
                    "WHERE tenant_id = :tenant_id AND document_id = :document_id"
                ),
                {"tenant_id": normalized_tenant_id, "document_id": int(document_id)},
            )
            await session.commit()
            deleted = result.rowcount or 0
            logger.info(
                f"删除 tenant_id={normalized_tenant_id}, document_id={document_id} 的 pgvector 向量完成，数量: {deleted}"
            )
            return deleted


class AsyncVectorStoreAdapter:
    """为业务层提供统一的 async 向量存储接口。"""

    def __init__(self, store: VectorStore):
        self.store = store

    @property
    def backend_name(self) -> str:
        return self.store.backend_name

    def connect(self) -> None:
        self.store.connect()

    def disconnect(self) -> None:
        self.store.disconnect()

    def get_collection_name(self, tenant_id: Optional[str] = None) -> str:
        return self.store.get_collection_name(tenant_id)

    async def ensure_ready(
        self,
        collection_name: Optional[str] = None,
        dimension: Optional[int] = None,
        create_index: bool = True,
        load: bool = True,
        tenant_id: Optional[str] = None,
    ) -> Any:
        if hasattr(self.store, "async_ensure_ready"):
            return await self.store.async_ensure_ready(create_index=create_index, tenant_id=tenant_id)
        return self.store.ensure_ready(
            collection_name=collection_name,
            dimension=dimension,
            create_index=create_index,
            load=load,
            tenant_id=tenant_id,
        )

    async def insert_vectors(
        self,
        vectors: List[List[float]],
        metadata: Optional[List[Dict[str, Any]]] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        if hasattr(self.store, "async_insert_vectors"):
            await self.store.async_insert_vectors(vectors, metadata, tenant_id=tenant_id)
            return
        self.store.insert_vectors(vectors, metadata, tenant_id=tenant_id)

    async def search_vectors(
        self,
        query_vectors: List[List[float]],
        top_k: int = 10,
        expr: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> List[List[Dict[str, Any]]]:
        if hasattr(self.store, "async_search_vectors"):
            return await self.store.async_search_vectors(
                query_vectors,
                top_k=top_k,
                expr=expr,
                params=params,
                tenant_id=tenant_id,
            )
        return self.store.search_vectors(
            query_vectors,
            top_k=top_k,
            expr=expr,
            params=params,
            tenant_id=tenant_id,
        )

    async def delete_vectors_by_document_id(self, document_id: int, tenant_id: Optional[str] = None) -> int:
        if hasattr(self.store, "async_delete_vectors_by_document_id"):
            return await self.store.async_delete_vectors_by_document_id(document_id, tenant_id=tenant_id)
        return self.store.delete_vectors_by_document_id(document_id, tenant_id=tenant_id)


class ConfigurableVectorStore:
    """按配置动态选择向量后端，避免在 import 时固化。"""

    def _current(self) -> AsyncVectorStoreAdapter:
        return get_vector_store()

    @property
    def backend_name(self) -> str:
        return self._current().backend_name

    def connect(self) -> None:
        self._current().connect()

    def disconnect(self) -> None:
        self._current().disconnect()

    def get_collection_name(self, tenant_id: Optional[str] = None) -> str:
        return self._current().get_collection_name(tenant_id)

    async def ensure_ready(
        self,
        collection_name: Optional[str] = None,
        dimension: Optional[int] = None,
        create_index: bool = True,
        load: bool = True,
        tenant_id: Optional[str] = None,
    ) -> Any:
        return await self._current().ensure_ready(
            collection_name=collection_name,
            dimension=dimension,
            create_index=create_index,
            load=load,
            tenant_id=tenant_id,
        )

    async def insert_vectors(
        self,
        vectors: List[List[float]],
        metadata: Optional[List[Dict[str, Any]]] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        await self._current().insert_vectors(vectors, metadata, tenant_id=tenant_id)

    async def search_vectors(
        self,
        query_vectors: List[List[float]],
        top_k: int = 10,
        expr: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> List[List[Dict[str, Any]]]:
        return await self._current().search_vectors(
            query_vectors,
            top_k=top_k,
            expr=expr,
            params=params,
            tenant_id=tenant_id,
        )

    async def delete_vectors_by_document_id(self, document_id: int, tenant_id: Optional[str] = None) -> int:
        return await self._current().delete_vectors_by_document_id(document_id, tenant_id=tenant_id)


milvus_vector_store = AsyncVectorStoreAdapter(MilvusVectorStore(milvus_manager))
pgvector_store = AsyncVectorStoreAdapter(PGVectorStore())


def get_vector_store() -> AsyncVectorStoreAdapter:
    backend = settings.vector_store_backend
    if backend == "milvus":
        return milvus_vector_store
    if backend == "pgvector":
        return pgvector_store
    raise RuntimeError(f"不支持的 VECTOR_STORE_BACKEND: {backend}，支持 milvus/pgvector")


vector_store = ConfigurableVectorStore()
