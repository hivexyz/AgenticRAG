"""AgenticRAG API 路由。"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.agents import agentic_rag_manager
from app.utils.logger import logger
from app.auth import get_tenant_id
from app.utils.messages import langchain_messages_to_dicts
from app.utils.tenancy import require_tenant_id

router = APIRouter()


class AgenticRAGRequest(BaseModel):
    """AgenticRAG 请求模型"""
    query: str = Field(..., description="用户查询")
    conversation_history: Optional[List[Dict[str, str]]] = Field(None, description="对话历史")
    max_retrievals: Optional[int] = Field(2, description="最大检索次数")
    stream: bool = Field(False, description="是否流式输出")


class AgenticRAGResponse(BaseModel):
    """AgenticRAG 响应模型"""
    query: str
    answer: Optional[str]
    quality_score: Optional[float]
    query_analysis: Optional[Dict[str, Any]]
    search_results: Optional[List[Dict[str, Any]]]
    reranked_results: Optional[List[Dict[str, Any]]]
    retrieval_count: int
    context: Optional[str]
    citations: Optional[List[Dict[str, Any]]] = None
    evidence_cards: Optional[List[Dict[str, Any]]] = None
    answer_blocks: Optional[List[Dict[str, Any]]] = None
    uncertainty: Optional[Dict[str, Any]] = None
    refusal: Optional[Dict[str, Any]] = None
    messages: List[Dict[str, str]]
    error: Optional[str]


class AnalyzeQueryRequest(BaseModel):
    """查询分析请求模型"""
    query: str = Field(..., description="待分析的查询")


@router.post("/agentic-rag/query", response_model=AgenticRAGResponse)
async def agentic_rag_query(request: AgenticRAGRequest, tenant_id: str = Depends(get_tenant_id)):
    """
    执行 AgenticRAG 查询
    
    该接口使用 LangGraph 构建的智能体驱动的 RAG 系统，
    具有以下特点：
    - 智能查询分析
    - 自适应检索
    - 自动重排序
    - 质量评估
    - 多轮检索优化
    """
    try:
        config = {
            "max_retrievals": request.max_retrievals,
        }
        
        result = await agentic_rag_manager.query(
            user_query=request.query,
            tenant_id=tenant_id,
            conversation_history=request.conversation_history,
            config=config,
        )
        
        if result.get("error"):
            logger.error(f"AgenticRAG 查询失败: {result['error']}")
            raise HTTPException(status_code=500, detail=result["error"])
        
        logger.info(f"AgenticRAG 查询完成，质量分数: {result.get('quality_score', 'N/A')}")
        return result
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"AgenticRAG 查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agentic-rag/stream")
async def agentic_rag_stream(request: AgenticRAGRequest, tenant_id: str = Depends(get_tenant_id)):
    """
    流式执行 AgenticRAG 查询
    
    返回查询过程中的中间结果，包括：
    - 查询分析结果
    - 检索结果
    - 重排序结果
    - 上下文构建
    - 答案生成
    - 质量评估
    """
    try:
        from fastapi.responses import StreamingResponse
        import json

        config = {
            "max_retrievals": request.max_retrievals,
        }
        
        async def event_generator():
            try:
                async for event in agentic_rag_manager.stream_query(
                    user_query=request.query,
                    tenant_id=tenant_id,
                    conversation_history=request.conversation_history,
                    config=config,
                ):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.error(f"流式查询失败: {e}")
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"AgenticRAG 流式查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agentic-rag/health")
async def agentic_rag_health():
    """
    AgenticRAG 健康检查
    
    检查 AgenticRAG 系统是否正常工作
    """
    try:
        is_initialized = agentic_rag_manager.graph is not None
        
        return {
            "status": "healthy" if is_initialized else "not_initialized",
            "graph_initialized": is_initialized,
            "max_retrievals": agentic_rag_manager.max_retrievals,
        }
    except Exception as e:
        logger.error(f"AgenticRAG 健康检查失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agentic-rag/analyze")
async def analyze_query(request: AnalyzeQueryRequest):
    """
    仅分析查询，不执行检索
    
    返回查询分析结果，包括：
    - 查询类型
    - 复杂度
    - 关键词
    - 搜索范围
    - 建议的检索数量
    - 是否需要重排序
    """
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from app.models import llm_manager
        
        analysis_prompt = f"""分析以下用户查询，提供检索策略建议：

    查询: {request.query}

    请以 JSON 格式返回分析结果，包含以下字段：
    - query_type: 查询类型（factual, conceptual, comparison, how_to, other）
    - complexity: 复杂度（low, medium, high）
    - keywords: 关键词列表
    - search_scope: 搜索范围（narrow, medium, broad）
    - top_k: 建议的检索数量（5-20）
    - needs_rerank: 是否需要重排序（true/false）
    - explanation: 分析说明

    只返回 JSON，不要其他内容。"""

        messages = [
            SystemMessage(content="你是一个专业的查询分析助手，擅长分析用户意图并制定检索策略。"),
            HumanMessage(content=analysis_prompt)
        ]
        
        response = await llm_manager.chat_completion(
            messages=langchain_messages_to_dicts(messages),
            temperature=0.3,
            max_tokens=500,
        )
        
        import json
        analysis_text = response["choices"][0]["message"]["content"]
        
        try:
            analysis = json.loads(analysis_text)
        except json.JSONDecodeError:
            logger.warning(f"无法解析查询分析结果: {analysis_text}")
            analysis = {
                "query_type": "other",
                "complexity": "medium",
                "keywords": [],
                "search_scope": "medium",
                "top_k": 10,
                "needs_rerank": True,
                "explanation": "分析失败，使用默认策略"
            }
        
        return {
            "query": request.query,
            "analysis": analysis,
        }
        
    except Exception as e:
        logger.error(f"查询分析失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
