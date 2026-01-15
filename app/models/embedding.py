"""
Embedding 模型管理
支持 OpenAI 兼容的 API
"""
from openai import AsyncOpenAI
from typing import List, Dict, Any, Optional
from app.config import settings
from app.utils.logger import logger


class EmbeddingManager:
    """Embedding 模型管理器"""
    
    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        self.base_url = settings.OPENAI_EMBEDDING_BASE_URL or settings.OPENAI_BASE_URL
        self.model = settings.OPENAI_EMBEDDING_MODEL
        self.client: Optional[AsyncOpenAI] = None
        self.dimension = settings.OPENAI_EMBEDDING_DIMENSION
    
    def connect(self):
        """初始化 OpenAI 客户端"""
        if not self.api_key:
            logger.warning("未配置 OPENAI_API_KEY，Embedding 功能将不可用")
            return
        
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url if self.base_url else None,
        )
        logger.info(f"Embedding 客户端初始化成功，模型: {self.model}")
    
    async def create_embedding(
        self,
        input_text: str,
        model: Optional[str] = None,
        encoding_format: str = "float",
    ) -> List[float]:
        """
        创建文本嵌入向量
        
        Args:
            input_text: 输入文本
            model: 模型名称
            encoding_format: 编码格式（float 或 base64）
            
        Returns:
            嵌入向量
        """
        if not self.client:
            raise RuntimeError("Embedding 客户端未初始化")
        
        try:
            response = await self.client.embeddings.create(
                model=model if model else self.model,
                input=input_text,
                encoding_format=encoding_format,
            )
            
            embedding = response.data[0].embedding
            logger.debug(f"成功创建嵌入向量，维度: {len(embedding)}")
            return embedding
        except Exception as e:
            logger.error(f"创建嵌入向量失败: {e}")
            raise
    
    async def create_embeddings(
        self,
        input_texts: List[str],
        model: Optional[str] = None,
        encoding_format: str = "float",
    ) -> List[List[float]]:
        """
        批量创建文本嵌入向量
        
        Args:
            input_texts: 输入文本列表
            model: 模型名称
            encoding_format: 编码格式（float 或 base64）
            
        Returns:
            嵌入向量列表
        """
        if not self.client:
            raise RuntimeError("Embedding 客户端未初始化")
        
        try:
            response = await self.client.embeddings.create(
                model=model if model else self.model,
                input=input_texts,
                encoding_format=encoding_format,
            )
            
            embeddings = [item.embedding for item in response.data]
            logger.debug(f"成功创建 {len(embeddings)} 个嵌入向量")
            return embeddings
        except Exception as e:
            logger.error(f"批量创建嵌入向量失败: {e}")
            raise
    
    async def create_embedding_with_metadata(
        self,
        input_text: str,
        metadata: Dict[str, Any],
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        创建嵌入向量并返回带元数据的结果
        
        Args:
            input_text: 输入文本
            metadata: 元数据
            model: 模型名称
            
        Returns:
            包含嵌入向量和元数据的字典
        """
        embedding = await self.create_embedding(input_text, model)
        
        return {
            "embedding": embedding,
            "metadata": metadata,
            "text": input_text,
        }
