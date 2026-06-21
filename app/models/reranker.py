"""
Reranker 模型管理
支持 OpenAI 兼容的 Rerank API（不使用 LLM Chat Completion）
"""
from typing import List, Dict, Any, Optional, Union

import httpx

from app.config import settings
from app.utils.logger import logger


class RerankerManager:
    """Reranker 模型管理器"""
    
    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        self.base_url = settings.OPENAI_RERANKER_BASE_URL or settings.OPENAI_BASE_URL
        self.model = settings.OPENAI_RERANKER_MODEL
        self.connected = False
        self.top_k = settings.OPENAI_RERANKER_TOP_K
    
    def connect(self):
        """初始化 Reranker 配置。"""
        if not self.base_url:
            logger.warning("未配置 OPENAI_RERANKER_BASE_URL/OPENAI_BASE_URL，Reranker 功能将不可用")
            return

        self.connected = True
        if not self.api_key:
            logger.info("未配置 OPENAI_API_KEY，Reranker 请求将不发送 Authorization 头")
        logger.info(f"Reranker 配置初始化成功，模型: {self.model}，接口: {self._rerank_url()}")

    def disconnect(self):
        """关闭客户端引用。"""
        self.connected = False

    @staticmethod
    def _document_text(document: Dict[str, Any]) -> str:
        """获取待重排文档文本，兼容 text/content 两种字段。"""
        return str(document.get("text", document.get("content", "")) or "")

    def _rerank_url(self) -> str:
        """构造 Rerank API 地址。

        例如 `http://host:1234/v1` 会被转换为 `http://host:1234/v1/rerank`。
        如配置已包含 `/rerank`，则直接使用。
        """
        return self._endpoint_url("rerank")

    def _endpoint_url(self, endpoint: str) -> str:
        base_url = (self.base_url or "").rstrip("/")
        if base_url.endswith("/rerank"):
            base_url = base_url[: -len("/rerank")]
        return f"{base_url}/{endpoint}"

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _extract_score(item: Dict[str, Any]) -> Optional[float]:
        """从不同 OpenAI 兼容实现的返回项中提取分数。"""
        for key in ("relevance_score", "score", "document_score", "similarity"):
            if key in item:
                try:
                    return float(item[key])
                except (TypeError, ValueError):
                    return None

        document = item.get("document")
        if isinstance(document, dict):
            for key in ("relevance_score", "score", "document_score", "similarity"):
                if key in document:
                    try:
                        return float(document[key])
                    except (TypeError, ValueError):
                        return None

        return None

    @staticmethod
    def _extract_index(item: Dict[str, Any]) -> Optional[int]:
        """从不同 OpenAI 兼容实现的返回项中提取原始文档下标。"""
        if "index" in item:
            try:
                return int(item["index"])
            except (TypeError, ValueError):
                return None

        document = item.get("document")
        if isinstance(document, dict) and "index" in document:
            try:
                return int(document["index"])
            except (TypeError, ValueError):
                return None

        return None

    @classmethod
    def _parse_score_list(cls, raw_scores: List[Any]) -> List[Dict[str, float]]:
        """解析按输入文档顺序返回的分数列表。"""
        results = []
        for index, raw_score in enumerate(raw_scores):
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                continue
            results.append({"index": index, "score": score})
        return results

    @classmethod
    def _parse_rerank_response(cls, payload: Union[Dict[str, Any], List[Any]]) -> List[Dict[str, float]]:
        """解析常见 rerank 接口响应格式。

        兼容以下返回：
        - {"results": [{"index": 0, "relevance_score": 0.9}]}
        - {"data": [{"index": 0, "score": 0.9}]}
        - [{"index": 0, "score": 0.9}]
        - {"scores": [0.9, 0.2]}
        - {"results": {"scores": [0.9, 0.2]}}
        """
        if isinstance(payload, dict) and payload.get("error"):
            error = payload["error"]
            if isinstance(error, dict):
                message = error.get("message") or str(error)
            else:
                message = str(error)
            raise RuntimeError(f"Reranker 接口返回错误: {message}")

        if isinstance(payload, list):
            raw_results = payload
        elif isinstance(payload, dict):
            raw_results = (
                payload.get("results")
                or payload.get("data")
                or payload.get("rerank_results")
                or payload.get("rankings")
            )

            for score_key in ("scores", "rerank_scores", "relevance_scores"):
                raw_scores = payload.get(score_key)
                if isinstance(raw_scores, list):
                    return cls._parse_score_list(raw_scores)

            if isinstance(raw_results, dict):
                for score_key in ("scores", "rerank_scores", "relevance_scores"):
                    raw_scores = raw_results.get(score_key)
                    if isinstance(raw_scores, list):
                        return cls._parse_score_list(raw_scores)
                raw_results = (
                    raw_results.get("results")
                    or raw_results.get("data")
                    or raw_results.get("items")
                )
        else:
            raise RuntimeError(f"Reranker 响应格式不支持: {type(payload).__name__}")

        if not isinstance(raw_results, list):
            if isinstance(payload, dict):
                keys = ", ".join(payload.keys()) or "空响应"
                raise RuntimeError(f"Reranker 响应缺少可解析的结果列表，响应字段: {keys}")
            raise RuntimeError("Reranker 响应缺少可解析的结果列表")

        if raw_results and all(not isinstance(item, dict) for item in raw_results):
            return cls._parse_score_list(raw_results)

        results = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue

            index = cls._extract_index(item)
            score = cls._extract_score(item)
            if index is None or score is None:
                continue
            results.append({"index": index, "score": score})

        if not results and raw_results:
            raise RuntimeError("Reranker 响应中未找到有效 index/score")
        return results

    @staticmethod
    def _keep_original_order(documents: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
        """保持召回结果原始顺序返回，不做重排序。"""
        return [doc.copy() for doc in documents[:top_k]]
    
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
        if not self.connected or not self.base_url:
            raise RuntimeError("Reranker 客户端未初始化")
        
        if not documents:
            return []
        
        top_k = min(top_k if top_k else self.top_k, len(documents))
        
        try:
            payload = {
                "model": self.model,
                "query": query,
                "documents": [self._document_text(doc) for doc in documents],
                "top_n": top_k,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self._rerank_url(),
                    json=payload,
                    headers=self._headers(),
                )
                response.raise_for_status()

            response_payload = response.json()
            if self._is_rerank_endpoint_unsupported(response_payload):
                logger.warning("当前服务不支持 /rerank，跳过重排序并保持召回结果原始顺序")
                return self._keep_original_order(documents, top_k)

            ranked_items = self._parse_rerank_response(response_payload)
            ranked_items = sorted(ranked_items, key=lambda x: x["score"], reverse=True)[:top_k]

            results = []
            for item in ranked_items:
                index = int(item["index"])
                if index < 0 or index >= len(documents):
                    logger.warning(f"Reranker 返回了无效文档下标: {index}")
                    continue

                result = documents[index].copy()
                result["relevance_score"] = item["score"]
                results.append(result)
            
            logger.info(f"重排序完成，返回前 {len(results)} 个结果")
            return results
        except httpx.HTTPStatusError as e:
            logger.error(f"Reranker 接口返回错误: {e.response.status_code} {e.response.text}")
            raise RuntimeError(f"Reranker 接口返回错误: {e.response.status_code}") from e
        except httpx.RequestError as e:
            logger.error(f"Reranker 接口请求失败: {e}")
            raise RuntimeError(f"Reranker 接口请求失败: {e}") from e
        except Exception as e:
            logger.error(f"重排序失败: {e}")
            raise

    @staticmethod
    def _is_rerank_endpoint_unsupported(payload: Any) -> bool:
        """判断是否为服务不支持 /rerank 的错误。"""
        if not isinstance(payload, dict) or "error" not in payload:
            return False

        error = payload["error"]
        if isinstance(error, dict):
            message = str(error.get("message", ""))
        else:
            message = str(error)

        return "Unexpected endpoint or method" in message and "/rerank" in message
    
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
