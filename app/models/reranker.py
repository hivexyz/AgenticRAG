"""
Reranker 模型管理
支持 OpenAI 兼容的 API（使用 LLM 进行重排序）
"""
from openai import AsyncOpenAI
from typing import List, Dict, Any, Optional
from app.config import settings
from app.utils.logger import logger


class RerankerManager:
    """Reranker 模型管理器"""
    
    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        self.base_url = settings.OPENAI_RERANKER_BASE_URL or settings.OPENAI_BASE_URL
        self.model = settings.OPENAI_RERANKER_MODEL
        self.client: Optional[AsyncOpenAI] = None
        self.top_k = settings.OPENAI_RERANKER_TOP_K
    
    def connect(self):
        """初始化 OpenAI 客户端"""
        if not self.api_key:
            logger.warning("未配置 OPENAI_API_KEY，Reranker 功能将不可用")
            return
        
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url if self.base_url else None,
        )
        logger.info(f"Reranker 客户端初始化成功，模型: {self.model}")
    
    async def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        对文档进行重排序
        
        Args:
            query: 查询文本
            documents: 文档列表，每个文档应包含 text 和其他元数据
            top_k: 返回前 K 个结果
            
        Returns:
            重排序后的文档列表，包含相关性分数
        """
        if not self.client:
            raise RuntimeError("Reranker 客户端未初始化")
        
        if not documents:
            return []
        
        top_k = top_k if top_k else self.top_k
        
        try:
            scores = []
            for doc in documents:
                text = doc.get("text", doc.get("content", ""))
                score = await self._compute_relevance_score(query, text)
                scores.append({
                    "document": doc,
                    "score": score,
                })
            
            sorted_scores = sorted(scores, key=lambda x: x["score"], reverse=True)
            top_results = sorted_scores[:top_k]
            
            results = []
            for item in top_results:
                result = item["document"].copy()
                result["relevance_score"] = item["score"]
                results.append(result)
            
            logger.info(f"重排序完成，返回前 {len(results)} 个结果")
            return results
        except Exception as e:
            logger.error(f"重排序失败: {e}")
            raise
    
    async def _compute_relevance_score(
        self,
        query: str,
        document: str,
    ) -> float:
        """
        计算查询和文档的相关性分数
        
        Args:
            query: 查询文本
            document: 文档文本
            
        Returns:
            相关性分数（0-1）
        """
        try:
            prompt = f"""请评估以下查询和文档的相关性，并给出一个 0 到 1 之间的分数。

查询: {query}

文档: {document}

请只输出分数，不要输出其他内容。"""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个专业的文档相关性评估助手。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=10,
            )
            
            score_text = response.choices[0].message.content.strip()
            score = float(score_text)
            
            return min(max(score, 0.0), 1.0)
        except Exception as e:
            logger.warning(f"计算相关性分数失败: {e}")
            return 0.5
    
    async def rerank_with_embeddings(
        self,
        query_embedding: List[float],
        document_embeddings: List[List[float]],
        documents: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        使用嵌入向量进行重排序（基于余弦相似度）
        
        Args:
            query_embedding: 查询的嵌入向量
            document_embeddings: 文档的嵌入向量列表
            documents: 文档列表
            top_k: 返回前 K 个结果
            
        Returns:
            重排序后的文档列表
        """
        if len(document_embeddings) != len(documents):
            raise ValueError("文档嵌入向量数量与文档数量不匹配")
        
        top_k = top_k if top_k else self.top_k
        
        try:
            scores = []
            for i, doc_embedding in enumerate(document_embeddings):
                similarity = self._cosine_similarity(query_embedding, doc_embedding)
                scores.append({
                    "document": documents[i],
                    "score": similarity,
                })
            
            sorted_scores = sorted(scores, key=lambda x: x["score"], reverse=True)
            top_results = sorted_scores[:top_k]
            
            results = []
            for item in top_results:
                result = item["document"].copy()
                result["relevance_score"] = item["score"]
                results.append(result)
            
            logger.info(f"基于嵌入向量重排序完成，返回前 {len(results)} 个结果")
            return results
        except Exception as e:
            logger.error(f"基于嵌入向量重排序失败: {e}")
            raise
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        计算余弦相似度
        
        Args:
            vec1: 向量 1
            vec2: 向量 2
            
        Returns:
            余弦相似度
        """
        import math
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(b * b for b in vec2))
        
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        
        return dot_product / (magnitude1 * magnitude2)
