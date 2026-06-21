"""
Milvus 向量数据库管理
使用 pymilvus 进行向量数据库操作
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility
from pymilvus.exceptions import ConnectionNotExistException

from app.config import settings
from app.utils.logger import logger
from app.utils.tenancy import (
    build_tenant_collection_name,
    build_tenant_expr,
    validate_tenant_id,
)


class MilvusManager:
    """Milvus 向量数据库管理器"""

    def __init__(self):
        self.host = settings.MILVUS_HOST
        self.port = settings.MILVUS_PORT
        self.user = settings.MILVUS_USER
        self.password = settings.MILVUS_PASSWORD
        self.collection_name = settings.MILVUS_COLLECTION_NAME
        self.dimension = settings.vector_dimension
        self.index_type = settings.MILVUS_INDEX_TYPE
        self.metric_type = settings.MILVUS_METRIC_TYPE
        self.collection: Optional[Collection] = None
        self.connected = False
        self.loaded = False

    def get_collection_name(self, tenant_id: Optional[str] = None) -> str:
        """获取租户对应的 collection 名称。"""
        return build_tenant_collection_name(validate_tenant_id(tenant_id))

    def _resolve_collection_name(
        self,
        tenant_id: Optional[str] = None,
        collection_name: Optional[str] = None,
    ) -> str:
        """解析实际使用的 collection 名称，并兼容旧版默认集合。"""
        if collection_name:
            return collection_name

        normalized_tenant_id = validate_tenant_id(tenant_id)
        target_name = build_tenant_collection_name(normalized_tenant_id)

        if self.collection is not None:
            if self.collection.name == target_name:
                return target_name
            if self._uses_legacy_default_collection(normalized_tenant_id, self.collection.name):
                return self.collection.name

        if (
            self.connected
            and normalized_tenant_id == settings.DEFAULT_TENANT_ID
            and not self._has_collection(target_name)
            and self._has_collection(self.collection_name)
        ):
            logger.info(
                f"检测到旧版默认集合 {self.collection_name}，将继续复用该集合而不是创建 {target_name}"
            )
            return self.collection_name

        return target_name

    def _uses_legacy_default_collection(self, tenant_id: str, collection_name: str) -> bool:
        """判断当前是否命中了旧版默认集合兼容路径。"""
        return (
            tenant_id == settings.DEFAULT_TENANT_ID
            and collection_name == self.collection_name
            and collection_name != build_tenant_collection_name(settings.DEFAULT_TENANT_ID)
        )

    def _has_collection(self, collection_name: str) -> bool:
        """检测 collection 是否存在，并将底层未连接错误转换为统一语义。"""
        try:
            return utility.has_collection(collection_name)
        except ConnectionNotExistException as exc:
            raise RuntimeError("Milvus 服务未连接") from exc

    def get_existing_collection(
        self,
        tenant_id: Optional[str] = None,
        collection_name: Optional[str] = None,
        load: bool = True,
    ) -> Optional[Collection]:
        """仅获取已存在的集合，不执行隐式创建。"""
        if not self.connected:
            raise RuntimeError("Milvus 服务未连接")

        normalized_tenant_id = validate_tenant_id(tenant_id)
        target_name = build_tenant_collection_name(normalized_tenant_id)
        if self.collection is not None:
            if self.collection.name == target_name:
                return self.collection
            if self._uses_legacy_default_collection(normalized_tenant_id, self.collection.name):
                return self.collection

        resolved_name = self._resolve_collection_name(
            tenant_id=normalized_tenant_id,
            collection_name=collection_name,
        )

        if not self._has_collection(resolved_name):
            return None

        collection = Collection(resolved_name)
        self.collection = collection

        if load:
            self.load_collection(collection_name=resolved_name)

        return collection

    def connect(self, db_name: str = "default"):
        """连接到 Milvus。"""
        try:
            connections.connect(
                alias="default",
                host=self.host,
                port=self.port,
                user=self.user or None,
                password=self.password or None,
                db_name=db_name,
            )
            self.connected = True
            logger.info(f"成功连接到 Milvus 数据库 '{db_name}': {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"连接 Milvus 失败: {e}")
            raise

    def disconnect(self):
        """断开 Milvus 连接。"""
        if self.connected:
            connections.disconnect("default")
            self.connected = False
            self.collection = None
            self.loaded = False
            logger.info("Milvus 连接已断开")

    def ensure_ready(
        self,
        collection_name: Optional[str] = None,
        dimension: Optional[int] = None,
        create_index: bool = True,
        load: bool = True,
        tenant_id: Optional[str] = None,
    ) -> Collection:
        """确保集合已存在、维度正确，并在需要时创建索引/加载。"""
        if not self.connected:
            raise RuntimeError("Milvus 服务未连接")

        normalized_tenant_id = validate_tenant_id(tenant_id)
        collection_name = self._resolve_collection_name(
            tenant_id=normalized_tenant_id,
            collection_name=collection_name,
        )
        dimension = dimension or self.dimension

        if self._has_collection(collection_name):
            collection = Collection(collection_name)
            embedding_field = next(
                (field for field in collection.schema.fields if field.name == "embedding"),
                None,
            )
            actual_dimension = None
            if embedding_field is not None:
                actual_dimension = getattr(embedding_field, "params", {}).get("dim")
            if actual_dimension != dimension:
                raise RuntimeError(
                    "Milvus 集合维度与当前 Embedding 配置不一致："
                    f"collection={actual_dimension}, expected={dimension}"
                )
            self.collection = collection
        else:
            self.create_collection(
                collection_name=collection_name,
                dimension=dimension,
                tenant_id=normalized_tenant_id,
            )

        if create_index:
            self.create_index(collection_name=collection_name)
        if load:
            self.load_collection(collection_name=collection_name)

        assert self.collection is not None
        return self.collection

    def create_collection(
        self,
        collection_name: Optional[str] = None,
        dimension: Optional[int] = None,
        tenant_id: Optional[str] = None,
    ):
        """创建向量集合。"""
        collection_name = collection_name or self._resolve_collection_name(tenant_id=tenant_id)
        dimension = dimension or self.dimension

        if self._has_collection(collection_name):
            logger.warning(f"集合 {collection_name} 已存在")
            self.collection = Collection(collection_name)
            return self.collection

        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dimension),
            FieldSchema(name="metadata", dtype=DataType.JSON),
        ]

        schema = CollectionSchema(fields=fields, description=f"向量集合: {collection_name}")
        self.collection = Collection(name=collection_name, schema=schema)
        self.loaded = False
        logger.info(f"成功创建集合 {collection_name}，维度: {dimension}")
        return self.collection

    def create_index(
        self,
        collection_name: Optional[str] = None,
        index_type: Optional[str] = None,
        metric_type: Optional[str] = None,
    ):
        """创建索引；若已存在则跳过。"""
        collection_name = collection_name or self.get_collection_name()
        index_type = index_type or self.index_type
        metric_type = metric_type or self.metric_type

        if not self.collection or self.collection.name != collection_name:
            self.collection = Collection(collection_name)

        existing_indexes = getattr(self.collection, "indexes", []) or []
        if existing_indexes:
            logger.info(f"集合 {collection_name} 已存在索引，跳过创建")
            return

        index_params = {
            "index_type": index_type,
            "metric_type": metric_type,
            "params": {"nlist": 128},
        }

        self.collection.create_index(field_name="embedding", index_params=index_params)
        logger.info(f"成功为集合 {collection_name} 创建索引: {index_type}")

    def load_collection(self, collection_name: Optional[str] = None, tenant_id: Optional[str] = None):
        """加载集合到内存。"""
        collection_name = collection_name or self._resolve_collection_name(tenant_id=tenant_id)

        if not self.collection or self.collection.name != collection_name:
            self.collection = Collection(collection_name)

        self.collection.load()
        self.loaded = True
        logger.info(f"集合 {collection_name} 已加载到内存")

    def insert_vectors(
        self,
        vectors: List[List[float]],
        metadata: Optional[List[Dict[str, Any]]] = None,
        tenant_id: Optional[str] = None,
    ):
        """插入向量数据。"""
        if not vectors:
            logger.warning("收到空向量列表，跳过插入")
            return

        normalized_tenant_id = validate_tenant_id(tenant_id)
        collection = self.ensure_ready(tenant_id=normalized_tenant_id)

        if metadata is not None and len(metadata) != len(vectors):
            raise ValueError("metadata 数量必须与 vectors 数量一致")

        vector_dimension = len(vectors[0])
        if vector_dimension != self.dimension:
            raise ValueError(
                f"向量维度不匹配: got={vector_dimension}, expected={self.dimension}"
            )

        normalized_metadata = []
        for item in (metadata if metadata is not None else [{} for _ in vectors]):
            current = dict(item)
            current["tenant_id"] = normalized_tenant_id
            normalized_metadata.append(current)

        rows = [vectors, normalized_metadata]

        collection.insert(rows)
        collection.flush()
        logger.info(
            f"成功向租户 {normalized_tenant_id} 的集合 {collection.name} 插入 {len(vectors)} 个向量"
        )

    def search_vectors(
        self,
        query_vectors: List[List[float]],
        top_k: int = 10,
        expr: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> List[List[Dict[str, Any]]]:
        """搜索相似向量。"""
        if not query_vectors:
            return []

        normalized_tenant_id = validate_tenant_id(tenant_id)
        collection = self.get_existing_collection(tenant_id=normalized_tenant_id)
        if collection is None:
            logger.info(f"租户 {normalized_tenant_id} 的集合不存在，直接返回空检索结果")
            return [[] for _ in query_vectors]

        query_dimension = len(query_vectors[0])
        if query_dimension != self.dimension:
            raise ValueError(
                f"查询向量维度不匹配: got={query_dimension}, expected={self.dimension}"
            )

        search_params = params or {"metric_type": self.metric_type, "params": {"nprobe": 10}}
        if self._uses_legacy_default_collection(normalized_tenant_id, collection.name):
            effective_expr = expr
        else:
            effective_expr = build_tenant_expr(normalized_tenant_id, expr)

        results = collection.search(
            data=query_vectors,
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=effective_expr,
            output_fields=["metadata"],
        )

        formatted_results = []
        for hits in results:
            formatted_hits = []
            for hit in hits:
                formatted_hits.append(
                    {
                        "id": hit.id,
                        "distance": hit.distance,
                        "score": hit.distance,
                        "metadata": hit.entity.get("metadata"),
                    }
                )
            formatted_results.append(formatted_hits)

        return formatted_results

    def delete_vectors_by_document_id(self, document_id: int, tenant_id: Optional[str] = None) -> int:
        """按 tenant_id + document_id 删除对应向量。"""
        if not self.connected:
            logger.warning("Milvus 未连接，跳过向量删除")
            return 0

        normalized_tenant_id = validate_tenant_id(tenant_id)
        collection = self.get_existing_collection(tenant_id=normalized_tenant_id)
        if collection is None:
            logger.info(f"租户 {normalized_tenant_id} 的集合不存在，删除向量时无需处理")
            return 0

        document_expr = f'metadata["document_id"] == {int(document_id)}'
        if self._uses_legacy_default_collection(normalized_tenant_id, collection.name):
            expr = document_expr
        else:
            expr = build_tenant_expr(normalized_tenant_id, document_expr)

        result = collection.delete(expr)
        collection.flush()

        deleted_count = getattr(result, "delete_count", 0) or 0
        logger.info(
            f"删除 tenant_id={normalized_tenant_id}, document_id={document_id} 的向量完成，数量: {deleted_count}"
        )
        return deleted_count

    def delete_collection(self, collection_name: Optional[str] = None, tenant_id: Optional[str] = None):
        """删除集合。"""
        collection_name = collection_name or self._resolve_collection_name(tenant_id=tenant_id)

        if self._has_collection(collection_name):
            utility.drop_collection(collection_name)
            if self.collection and self.collection.name == collection_name:
                self.collection = None
                self.loaded = False
            logger.info(f"成功删除集合 {collection_name}")
        else:
            logger.warning(f"集合 {collection_name} 不存在")


# 创建全局 Milvus 管理器实例
milvus_manager = MilvusManager()
