"""LLM 和 Embedding 相关 API 路由。"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database.vector_store import vector_store
from app.models import embedding_manager, llm_manager, reranker_manager
from app.utils.logger import logger
from app.auth import get_auth_context, get_tenant_id
from app.utils.tenancy import require_tenant_id

router = APIRouter()


class ChatMessage(BaseModel):
    """聊天消息模型"""
    role: str = Field(..., description="角色：user, assistant, system")
    content: str = Field(..., description="消息内容")


class ChatCompletionRequest(BaseModel):
    """聊天补全请求模型"""
    messages: List[ChatMessage] = Field(..., description="消息列表")
    temperature: Optional[float] = Field(None, description="温度参数")
    max_tokens: Optional[int] = Field(None, description="最大 token 数")
    top_p: Optional[float] = Field(None, description="top_p 参数")
    stream: bool = Field(False, description="是否流式输出")


class CompletionRequest(BaseModel):
    """文本补全请求模型"""
    prompt: str = Field(..., description="提示文本")
    temperature: Optional[float] = Field(None, description="温度参数")
    max_tokens: Optional[int] = Field(None, description="最大 token 数")
    top_p: Optional[float] = Field(None, description="top_p 参数")
    stream: bool = Field(False, description="是否流式输出")


class EmbeddingRequest(BaseModel):
    """嵌入向量请求模型"""
    input: str = Field(..., description="输入文本")
    model: Optional[str] = Field(None, description="模型名称")


class EmbeddingBatchRequest(BaseModel):
    """批量嵌入向量请求模型"""
    inputs: List[str] = Field(..., description="输入文本列表")
    model: Optional[str] = Field(None, description="模型名称")


class RerankRequest(BaseModel):
    """重排序请求模型"""
    query: str = Field(..., description="查询文本")
    documents: List[Dict[str, Any]] = Field(..., description="文档列表")
    top_k: Optional[int] = Field(None, description="返回前 K 个结果")


class RerankWithEmbeddingsRequest(BaseModel):
    """基于嵌入向量的重排序请求模型"""
    query_embedding: List[float] = Field(..., description="查询的嵌入向量")
    document_embeddings: List[List[float]] = Field(..., description="文档的嵌入向量列表")
    documents: List[Dict[str, Any]] = Field(..., description="文档列表")
    top_k: Optional[int] = Field(None, description="返回前 K 个结果")


class SearchWithRerankRequest(BaseModel):
    """搜索并重排序请求模型"""
    query: str = Field(..., description="查询文本")
    top_k: int = Field(10, description="返回结果数量")
    rerank_top_k: int = Field(5, description="重排序后返回的结果数量")


@router.post("/llm/chat")
async def chat_completion(request: ChatCompletionRequest, _auth=Depends(get_auth_context)):
    """
    LLM 聊天补全
    """
    try:
        messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]
        response = await llm_manager.chat_completion(
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            top_p=request.top_p,
            stream=request.stream,
        )
        return response
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"聊天补全失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/completion")
async def completion(request: CompletionRequest, _auth=Depends(get_auth_context)):
    """
    LLM 文本补全
    """
    try:
        response = await llm_manager.completion(
            prompt=request.prompt,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            top_p=request.top_p,
            stream=request.stream,
        )
        return response
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"文本补全失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/tokens")
async def count_tokens(text: str, _auth=Depends(get_auth_context)):
    """
    计算 token 数量
    """
    try:
        count = await llm_manager.count_tokens(text)
        return {"text": text, "token_count": count}
    except Exception as e:
        logger.error(f"计算 token 数量失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/embedding")
async def create_embedding(request: EmbeddingRequest, _auth=Depends(get_auth_context)):
    """
    创建文本嵌入向量
    """
    try:
        embedding = await embedding_manager.create_embedding(
            input_text=request.input,
            model=request.model,
        )
        return {
            "embedding": embedding,
            "dimension": len(embedding),
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"创建嵌入向量失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/embedding/batch")
async def create_embeddings(request: EmbeddingBatchRequest, _auth=Depends(get_auth_context)):
    """
    批量创建文本嵌入向量
    """
    try:
        embeddings = await embedding_manager.create_embeddings(
            input_texts=request.inputs,
            model=request.model,
        )
        return {
            "embeddings": embeddings,
            "count": len(embeddings),
            "dimension": len(embeddings[0]) if embeddings else 0,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"批量创建嵌入向量失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rerank")
async def rerank(request: RerankRequest, _auth=Depends(get_auth_context)):
    """
    对文档进行重排序
    """
    try:
        results = await reranker_manager.rerank(
            query=request.query,
            documents=request.documents,
            top_k=request.top_k,
        )
        return {
            "query": request.query,
            "results": results,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"重排序失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rerank/embeddings")
async def rerank_with_embeddings(request: RerankWithEmbeddingsRequest, _auth=Depends(get_auth_context)):
    """
    使用嵌入向量进行重排序
    """
    try:
        results = await reranker_manager.rerank_with_embeddings(
            query_embedding=request.query_embedding,
            document_embeddings=request.document_embeddings,
            documents=request.documents,
            top_k=request.top_k,
        )
        return {
            "results": results,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"基于嵌入向量重排序失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search")
async def search_with_rerank(request: SearchWithRerankRequest, tenant_id: str = Depends(get_tenant_id)):
    """
    搜索并重排序（集成 Embedding + Milvus + Reranker）
    """
    try:
        query_embedding = await embedding_manager.create_embedding(request.query)

        search_results = await vector_store.search_vectors(
            query_vectors=[query_embedding],
            top_k=request.top_k,
            tenant_id=tenant_id,
        )

        if not search_results or not search_results[0]:
            return {
                "query": request.query,
                "results": [],
            }
        
        documents = []
        for hit in search_results[0]:
            doc = hit.get("metadata", {})
            doc["id"] = hit.get("id")
            doc["distance"] = hit.get("distance")
            documents.append(doc)
        
        reranked_results = await reranker_manager.rerank(
            query=request.query,
            documents=documents,
            top_k=request.rerank_top_k,
        )
        
        logger.info(f"搜索并重排序完成，返回 {len(reranked_results)} 个结果")
        return {
            "query": request.query,
            "results": reranked_results,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"搜索并重排序失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
