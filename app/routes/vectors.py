"""向量相关 API 路由。"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_tenant_id
from app.database.vector_store import vector_store
from app.utils.logger import logger

router = APIRouter()


class VectorSearchRequest(BaseModel):
    """向量搜索请求模型"""
    query_vector: List[float] = Field(..., description="查询向量")
    top_k: int = Field(10, description="返回结果数量")
    expr: Optional[str] = Field(None, description="过滤表达式")


class VectorSearchResponse(BaseModel):
    """向量搜索响应模型"""
    results: List[dict]


@router.post("/search", response_model=VectorSearchResponse)
async def search_vectors(request: VectorSearchRequest, tenant_id: str = Depends(get_tenant_id)):
    """向量搜索"""
    try:
        results = await vector_store.search_vectors(
            query_vectors=[request.query_vector],
            top_k=request.top_k,
            expr=request.expr,
            tenant_id=tenant_id,
        )
        first_page = results[0] if results else []
        logger.info(f"向量搜索完成，tenant={tenant_id}，返回 {len(first_page)} 个结果")
        return VectorSearchResponse(results=first_page)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"向量搜索失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/insert")
async def insert_vectors(
    vectors: List[List[float]],
    metadata: Optional[List[dict]] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """插入向量数据"""
    try:
        await vector_store.ensure_ready(tenant_id=tenant_id)
        await vector_store.insert_vectors(vectors, metadata, tenant_id=tenant_id)
        logger.info(f"成功插入 {len(vectors)} 个向量，tenant={tenant_id}")
        return {"message": f"成功插入 {len(vectors)} 个向量"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"插入向量失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collection")
async def create_vector_collection(
    collection_name: Optional[str] = None,
    dimension: Optional[int] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """创建向量集合"""
    try:
        await vector_store.ensure_ready(
            collection_name=collection_name,
            dimension=dimension,
            tenant_id=tenant_id,
        )
        actual_collection_name = collection_name or vector_store.get_collection_name(tenant_id)
        logger.info(f"成功创建向量集合: {actual_collection_name}, tenant={tenant_id}")
        return {"message": f"成功创建向量集合: {actual_collection_name}"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建向量集合失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
