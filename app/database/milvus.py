"""
Milvus 向量数据库管理
使用 pymilvus 进行向量数据库操作
"""
from pymilvus import connections, Collection, utility, FieldSchema, CollectionSchema, DataType
from typing import List, Optional, Dict, Any
from app.config import settings
from app.utils.logger import logger


class MilvusManager:
    """Milvus 向量数据库管理器"""
    
    def __init__(self):
        self.host = settings.MILVUS_HOST
        self.port = settings.MILVUS_PORT
        self.user = settings.MILVUS_USER
        self.password = settings.MILVUS_PASSWORD
        self.collection_name = settings.MILVUS_COLLECTION_NAME
        self.dimension = settings.MILVUS_DIMENSION
        self.index_type = settings.MILVUS_INDEX_TYPE
        self.metric_type = settings.MILVUS_METRIC_TYPE
        self.collection: Optional[Collection] = None
        self.connected = False
    
    def connect(self, db_name: str = "default"):
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
        """断开 Milvus 连接"""
        if self.connected:
            connections.disconnect("default")
            self.connected = False
            logger.info("Milvus 连接已断开")
    
    def create_collection(self, collection_name: Optional[str] = None, dimension: Optional[int] = None):
        """
        创建向量集合
        
        Args:
            collection_name: 集合名称，默认使用配置中的名称
            dimension: 向量维度，默认使用配置中的维度
        """
        collection_name = collection_name or self.collection_name
        dimension = dimension or self.dimension
        
        if utility.has_collection(collection_name):
            logger.warning(f"集合 {collection_name} 已存在")
            self.collection = Collection(collection_name)
            return
        
        # 定义字段
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dimension),
            FieldSchema(name="metadata", dtype=DataType.JSON),
        ]
        
        # 创建 Schema
        schema = CollectionSchema(fields=fields, description=f"向量集合: {collection_name}")
        
        # 创建集合
        self.collection = Collection(name=collection_name, schema=schema)
        logger.info(f"成功创建集合 {collection_name}，维度: {dimension}")
    
    def create_index(self, collection_name: Optional[str] = None, index_type: Optional[str] = None, metric_type: Optional[str] = None):
        """
       创建索引
        
        Args:
            collection_name: 集合名称
            index_type: 索引类型
            metric_type: 度量类型
        """
        collection_name = collection_name or self.collection_name
        index_type = index_type or self.index_type
        metric_type = metric_type or self.metric_type
        
        if not self.collection:
            self.collection = Collection(collection_name)
        
        # 定义索引参数
        index_params = {
            "index_type": index_type,
            "metric_type": metric_type,
            "params": {"nlist": 128},
        }
        
        # 创建索引
        self.collection.create_index(field_name="embedding", index_params=index_params)
        logger.info(f"成功为集合 {collection_name} 创建索引: {index_type}")
    
    def load_collection(self, collection_name: Optional[str] = None):
        """
        加载集合到内存
        
        Args:
            collection_name: 集合名称
        """
        collection_name = collection_name or self.collection_name
        
        if not self.collection:
            self.collection = Collection(collection_name)
        
        self.collection.load()
        logger.info(f"集合 {collection_name} 已加载到内存")
    
    def insert_vectors(self, vectors: List[List[float]], metadata: Optional[List[Dict[str, Any]]] = None):
        """
        插入向量数据
        
        Args:
            vectors: 向量列表
            metadata: 元数据列表
        """
        if not self.collection:
            raise RuntimeError("集合未初始化，请先调用 create_collection")
        
        entities = {
            "embedding": vectors,
        }
        if metadata:
            entities["metadata"] = metadata

        self.collection.insert(entities)
        logger.info(f"成功插入 {len(vectors)} 个向量")
    
    def search_vectors(
        self,
        query_vectors: List[List[float]],
        top_k: int = 10,
        expr: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[List[Dict[str, Any]]]:
        """
        搜索相似向量
        
        Args:
            query_vectors: 查询向量列表
            top_k: 返回最相似的 K 个结果
            expr: 过滤表达式
            params: 搜索参数
            
        Returns:
            搜索结果列表
        """
        if not self.collection:
            raise RuntimeError("集合未初始化，请先调用 create_collection")
        
        search_params = params or {"metric_type": self.metric_type, "params": {"nprobe": 10}}
        
        results = self.collection.search(
            data=query_vectors,
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=["metadata"],
        )
        
        formatted_results = []
        for hits in results:
            formatted_hits = []
            for hit in hits:
                formatted_hits.append({
                    "id": hit.id,
                    "distance": hit.distance,
                    "score": hit.distance,
                    "metadata": hit.entity.get("metadata"),
                })
            formatted_results.append(formatted_hits)
        
        return formatted_results
    
    def delete_collection(self, collection_name: Optional[str] = None):
        """
        删除集合
        
        Args:
            collection_name: 集合名称
        """
        collection_name = collection_name or self.collection_name
        
        if utility.has_collection(collection_name):
            utility.drop_collection(collection_name)
            logger.info(f"成功删除集合 {collection_name}")
        else:
            logger.warning(f"集合 {collection_name} 不存在")


# 创建全局 Milvus 管理器实例
milvus_manager = MilvusManager()
