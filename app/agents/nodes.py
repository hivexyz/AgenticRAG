"""
AgenticRAG 节点实现
定义图中的各个处理节点
"""
import re
import json
from typing import Dict, Any, List, Optional
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from app.models import llm_manager, embedding_manager, reranker_manager
from app.database.vector_store import vector_store
from app.database.hybrid_search import hydrate_vector_hits, reciprocal_rank_fusion, sparse_search_chunks
from app.config import settings
from app.utils.logger import logger
from app.utils.messages import langchain_messages_to_dicts
from app.context.assembler import trim_retrieval_results
from .state import AgenticRAGState


DIRECT_REPLY_QUERY_TYPES = {"greeting", "chitchat"}
QUALITY_EVALUATION_MAX_TOKENS = 128




def _split_answer_sentences(answer: str) -> List[str]:
    if not answer:
        return []
    parts = re.split(r'(?<=[。！？!?；;])\s*', answer.strip())
    return [part.strip() for part in parts if part.strip()]


def _bind_answer_citations(answer: str, citations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sentences = _split_answer_sentences(answer)
    if not sentences:
        return []

    citation_ids = list(range(1, len(citations) + 1))
    bound = []
    for idx, sentence in enumerate(sentences):
        if citation_ids:
            matched = [citation_ids[min(idx, len(citation_ids) - 1)]]
        else:
            matched = []
        bound.append({
            "text": sentence,
            "citation_ids": matched,
            "uncertainty_flag": "可能" in sentence or "建议" in sentence or "未" in sentence,
        })
    return bound

def _build_source_reference(doc: Dict[str, Any]) -> Dict[str, Any]:
    metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    return {
        "document_id": doc.get("document_id"),
        "chunk_id": doc.get("chunk_id") or doc.get("id"),
        "title": doc.get("document_title") or doc.get("title") or "未命名文档",
        "page": doc.get("page_number"),
        "paragraph": metadata.get("paragraph") or metadata.get("paragraph_index") or doc.get("chunk_index"),
        "uploaded_at": doc.get("uploaded_at") or doc.get("created_at") or metadata.get("uploaded_at"),
        "section_title": doc.get("section_title"),
        "snippet": (doc.get("text") or doc.get("content") or "")[:300],
        "open_fragment": {
            "document_id": doc.get("document_id"),
            "chunk_id": doc.get("chunk_id") or doc.get("id"),
            "page": doc.get("page_number"),
            "section_title": doc.get("section_title"),
        },
    }


def _build_evidence_card(doc: Dict[str, Any], index: int) -> Dict[str, Any]:
    text = doc.get("text") or doc.get("content") or ""
    snippet = text[:240]
    highlight = snippet[:120] if snippet else ""
    return {
        "rank": index + 1,
        "source": _build_source_reference(doc),
        "snippet": snippet,
        "highlighted_sentences": [highlight] if highlight else [],
        "view_full_context": {
            "document_id": doc.get("document_id"),
            "chunk_id": doc.get("chunk_id") or doc.get("id"),
            "preview": text[:800],
        },
    }


def _build_citations_and_evidence(results: List[Dict[str, Any]], *, max_items: int = 3) -> Dict[str, Any]:
    selected = results[:max_items]
    citations = []
    evidence_cards = []
    for index, doc in enumerate(selected):
        source = _build_source_reference(doc)
        citations.append({
            "claim": f"结论 {index + 1}",
            "sources": [source],
        })
        evidence_cards.append(_build_evidence_card(doc, index))
    return {
        "citations": citations,
        "evidence_cards": evidence_cards,
    }


def _build_uncertainty_signal(quality_score: float, *, has_results: bool, context_doc_count: int) -> Dict[str, Any]:
    score = _safe_float(quality_score)
    if not has_results or context_doc_count <= 0:
        return {
            "level": "high",
            "label": "未找到可靠依据",
            "message": "当前知识库没有足够信息支持回答。",
        }
    if score >= 0.8 and context_doc_count >= 2:
        return {
            "level": "low",
            "label": "资料充分",
            "message": "当前回答有较充分的检索依据支撑。",
        }
    if score >= 0.55:
        return {
            "level": "medium",
            "label": "当前答案可能不完整",
            "message": "已找到部分依据，但建议结合原文进一步确认。",
        }
    return {
        "level": "high",
        "label": "资料较少，建议人工确认",
        "message": "检索证据较弱或覆盖不足，建议人工复核。",
    }


def _build_refusal_response(state: AgenticRAGState, *, reason: str) -> Dict[str, Any]:
    analysis = state.get("query_analysis") or {}
    query_type = analysis.get("query_type")
    suggestion = "请上传相关制度文档或补充更具体的问题。"
    if query_type in {"comparison", "multi_hop"}:
        suggestion = "请尝试拆分问题，或补充涉及的制度/项目文档。"
    return {
        "should_refuse": True,
        "reason": reason,
        "message": "当前知识库没有足够信息支持这个回答。",
        "next_steps": [
            suggestion,
            "你也可以尝试换一种问法，提供更明确的关键词。",
        ],
    }


def _parse_quality_score(score_text: str) -> Optional[float]:
    """从模型返回文本中提取 0-1 之间的质量分数。"""
    normalized = (score_text or "").strip()
    if not normalized:
        return None

    try:
        return min(max(float(normalized), 0.0), 1.0)
    except ValueError:
        pass

    percent_match = re.search(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%", normalized)
    if percent_match:
        return min(max(float(percent_match.group(1)) / 100.0, 0.0), 1.0)

    point_match = re.search(r"(?<!\d)(100|\d{1,2}(?:\.\d+)?)\s*分", normalized)
    if point_match:
        score = float(point_match.group(1))
        if score > 1.0:
            score /= 100.0
        return min(max(score, 0.0), 1.0)

    match = re.search(r"(?<!\d)(?:0(?:\.\d+)?|1(?:\.0+)?)(?!\d)", normalized)
    if not match:
        return None

    return min(max(float(match.group(0)), 0.0), 1.0)


def _extract_chat_response_text(response: Dict[str, Any]) -> str:
    """从 OpenAI 兼容 chat completion 响应中提取助手文本。"""
    try:
        message = response.get("choices", [{}])[0].get("message", {})
    except (AttributeError, IndexError):
        return ""

    content = message.get("content") or ""
    if isinstance(content, str):
        return content.strip()
    return str(content).strip()


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """从模型输出中提取 JSON 对象。"""
    if not text:
        return None
    normalized = text.strip()
    try:
        parsed = json.loads(normalized)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", normalized, flags=re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return default


def _default_quality_evaluation(score: float, *, reason: str, action: str = "end") -> Dict[str, Any]:
    score = _safe_float(score)
    return {
        "groundedness": score,
        "answer_relevance": score,
        "completeness": score,
        "context_sufficiency": score,
        "quality_score": score,
        "should_continue": action != "end",
        "action": action,
        "missing_information": [],
        "reason": reason,
    }


async def _request_quality_score(messages: List[Dict[str, str]], max_tokens: int) -> Dict[str, Any]:
    """请求质量评分。

    qwen3 等模型可能先输出 reasoning，再输出最终 content；max_tokens 太小时容易
    finish_reason=length 且 content 为空，因此质量评估需要给足输出预算。
    """
    return await llm_manager.chat_completion(
        messages=messages,
        temperature=0.0,
        max_tokens=max_tokens,
    )


def _normalize_query_text(text: str) -> str:
    """归一化用户查询，便于识别简短问候和闲聊。"""
    normalized = (text or "").strip().lower()
    return re.sub(r"[\s\.,!?:;，。！？：；、~`'\"()（）\[\]{}<>《》]+", "", normalized)


def _detect_direct_reply_query(user_query: str) -> Optional[Dict[str, Any]]:
    """识别无需走 RAG 的简短问候/闲聊请求。"""
    normalized = _normalize_query_text(user_query)
    if not normalized:
        return None

    greeting_queries = {
        "你好",
        "您好",
        "hi",
        "hello",
        "hey",
        "嗨",
        "哈喽",
        "早上好",
        "中午好",
        "下午好",
        "晚上好",
    }
    chitchat_queries = {
        "你是谁",
        "你是干嘛的",
        "你能做什么",
        "谢谢",
        "多谢",
        "再见",
        "拜拜",
    }

    if normalized in greeting_queries:
        return {
            "query_type": "greeting",
            "complexity": "low",
            "keywords": [],
            "search_scope": "none",
            "top_k": 0,
            "needs_rerank": False,
            "explanation": "识别为简短问候，直接使用模型自然回复。",
        }

    if normalized in chitchat_queries:
        return {
            "query_type": "chitchat",
            "complexity": "low",
            "keywords": [],
            "search_scope": "none",
            "top_k": 0,
            "needs_rerank": False,
            "explanation": "识别为简短闲聊，直接使用模型自然回复。",
        }

    return None


async def query_analyzer(state: AgenticRAGState) -> AgenticRAGState:
    """
    查询分析节点：识别意图并生成可执行检索计划。
    """
    logger.info(f"开始分析查询: {state['user_query']}")

    direct_reply_analysis = _detect_direct_reply_query(state["user_query"])
    if direct_reply_analysis:
        state["query_analysis"] = direct_reply_analysis
        state["query_plan"] = {
            "route": "direct",
            "sub_queries": [],
            "filters": {},
            "top_k_dense": 0,
            "top_k_sparse": 0,
            "rerank_top_n": 0,
            "answer_style": "brief",
        }
        state["current_query"] = state["user_query"]
        state["messages"].append(
            AIMessage(content=f"查询识别为 {direct_reply_analysis['query_type']}，直接回答")
        )
        logger.info(f"查询识别为直接回答类型: {direct_reply_analysis}")
        return state

    try:
        analysis_prompt = f"""分析以下用户查询，制定 Agentic RAG 检索计划。

查询: {state['user_query']}

请只返回 JSON 对象，字段如下：
- query_type: factual, conceptual, comparison, how_to, multi_hop, summary, other
- complexity: low, medium, high
- keywords: 关键词数组
- search_scope: narrow, medium, broad
- top_k: 建议最终召回数量（5-20）
- needs_rerank: 是否需要重排序
- route: direct, vector, hybrid, multi_hop
- sub_queries: 适合检索的子查询数组；简单问题可只包含原问题改写
- filters: 可执行过滤条件对象；没有则为空对象
- top_k_dense: 向量召回数量（5-50）
- top_k_sparse: 稀疏召回数量（0-50）
- rerank_top_n: 重排后保留数量（3-15）
- answer_style: brief, detailed, table, steps
- explanation: 简短说明

要求：
1. hybrid 适用于包含专有名词、编号、政策条款、中文短查询或需要精确匹配的问题。
2. multi_hop/comparison 问题应拆成 2-4 个 sub_queries。
3. top_k_dense/top_k_sparse 不要小于 top_k。
"""

        messages = [
            SystemMessage(content="你是一个专业的 RAG 查询规划器，擅长生成可执行检索计划。"),
            HumanMessage(content=analysis_prompt),
        ]

        response = await llm_manager.chat_completion(
            messages=langchain_messages_to_dicts(messages),
            temperature=0.2,
            max_tokens=800,
        )

        analysis_text = response["choices"][0]["message"]["content"]
        analysis = _extract_json_object(analysis_text)
        if not analysis:
            logger.warning(f"无法解析查询分析结果，使用默认策略: {analysis_text}")
            analysis = {
                "query_type": "other",
                "complexity": "medium",
                "keywords": [],
                "search_scope": "medium",
                "top_k": settings.AGENTIC_RAG_DEFAULT_TOP_K,
                "needs_rerank": True,
                "route": "hybrid",
                "sub_queries": [state["user_query"]],
                "filters": {},
                "top_k_dense": max(settings.AGENTIC_RAG_DEFAULT_TOP_K, 10),
                "top_k_sparse": max(settings.AGENTIC_RAG_DEFAULT_TOP_K, 10),
                "rerank_top_n": 5,
                "answer_style": "detailed",
                "explanation": "分析失败，使用默认混合检索策略",
            }

        sub_queries = analysis.get("sub_queries")
        if not isinstance(sub_queries, list) or not sub_queries:
            sub_queries = [state["user_query"]]
            analysis["sub_queries"] = sub_queries

        analysis["top_k"] = int(analysis.get("top_k") or settings.AGENTIC_RAG_DEFAULT_TOP_K)
        analysis["top_k_dense"] = int(analysis.get("top_k_dense") or analysis["top_k"])
        analysis["top_k_sparse"] = int(analysis.get("top_k_sparse") or analysis["top_k"])
        analysis["rerank_top_n"] = int(analysis.get("rerank_top_n") or min(8, analysis["top_k"]))
        analysis["needs_rerank"] = bool(analysis.get("needs_rerank", True))
        analysis["route"] = analysis.get("route") or "hybrid"
        analysis["filters"] = analysis.get("filters") if isinstance(analysis.get("filters"), dict) else {}

        state["query_analysis"] = analysis
        state["query_plan"] = {
            "route": analysis["route"],
            "sub_queries": sub_queries,
            "filters": analysis["filters"],
            "top_k_dense": analysis["top_k_dense"],
            "top_k_sparse": analysis["top_k_sparse"],
            "rerank_top_n": analysis["rerank_top_n"],
            "answer_style": analysis.get("answer_style", "detailed"),
        }
        state["current_query"] = sub_queries[0]
        state["messages"].append(
            AIMessage(content=f"查询规划完成: {analysis.get('query_type')} / {analysis.get('route')}")
        )

        logger.info(f"查询分析完成: {analysis}")
        return state

    except Exception as e:
        logger.error(f"查询分析失败: {e}")
        fallback = {
            "query_type": "other",
            "complexity": "medium",
            "keywords": [],
            "search_scope": "medium",
            "top_k": settings.AGENTIC_RAG_DEFAULT_TOP_K,
            "needs_rerank": True,
            "route": "hybrid",
            "sub_queries": [state["user_query"]],
            "filters": {},
            "top_k_dense": max(settings.AGENTIC_RAG_DEFAULT_TOP_K, 10),
            "top_k_sparse": max(settings.AGENTIC_RAG_DEFAULT_TOP_K, 10),
            "rerank_top_n": 5,
            "answer_style": "detailed",
            "explanation": "分析失败，使用默认策略",
        }
        state["query_analysis"] = fallback
        state["query_plan"] = {
            "route": "hybrid",
            "sub_queries": [state["user_query"]],
            "filters": {},
            "top_k_dense": fallback["top_k_dense"],
            "top_k_sparse": fallback["top_k_sparse"],
            "rerank_top_n": fallback["rerank_top_n"],
            "answer_style": "detailed",
        }
        state["current_query"] = state["user_query"]
        return state


async def retriever(state: AgenticRAGState) -> AgenticRAGState:
    """
    检索节点
    从 Milvus 向量数据库中检索相关文档
    """
    attempt_number = state["retrieval_count"] + 1
    logger.info(f"开始检索文档，检索次数: {attempt_number}")
    
    try:
        analysis = state.get("query_analysis", {})
        query_type = analysis.get("query_type")
        if query_type in DIRECT_REPLY_QUERY_TYPES:
            state["search_results"] = []
            state["reranked_results"] = []
            state["retrieval_error"] = None
            state["messages"].append(AIMessage(content="当前查询无需知识库检索，直接回答"))
            logger.info(f"查询类型 {query_type}，跳过知识库检索")
            return state

        tenant_id = state.get("tenant_id", "default")
        state["error"] = None
        state["retrieval_error"] = None

        plan = state.get("query_plan") or {}
        route = plan.get("route") or analysis.get("route") or "hybrid"
        top_k = int(analysis.get("top_k") or settings.AGENTIC_RAG_DEFAULT_TOP_K)
        dense_top_k = int(plan.get("top_k_dense") or analysis.get("top_k_dense") or top_k)
        sparse_top_k = int(plan.get("top_k_sparse") or analysis.get("top_k_sparse") or top_k)
        current_query = state.get("current_query") or state["user_query"]

        state["retrieval_count"] = attempt_number
        query_embedding = await embedding_manager.create_embedding(current_query)

        vector_hits: List[Dict[str, Any]] = []
        vector_error: Optional[str] = None
        try:
            vector_pages = await vector_store.search_vectors(
                query_vectors=[query_embedding],
                top_k=dense_top_k,
                tenant_id=tenant_id,
            )
            if vector_pages and vector_pages[0]:
                for hit in vector_pages[0]:
                    doc = hit.get("metadata", {}) or {}
                    doc = dict(doc)
                    doc["id"] = hit.get("id")
                    doc["distance"] = hit.get("distance")
                    doc["score"] = hit.get("distance")
                    doc["vector_score"] = hit.get("score", hit.get("distance"))
                    vector_hits.append(doc)
                try:
                    vector_hits = await hydrate_vector_hits(vector_hits, tenant_id=tenant_id)
                except Exception as exc:
                    logger.warning(f"向量结果回表补齐失败，保留原始命中结果: {exc}")
        except Exception as exc:
            vector_error = str(exc)
            logger.warning(f"向量检索失败，将继续尝试其它可用检索路径: {exc}")

        sparse_hits: List[Dict[str, Any]] = []
        sparse_error: Optional[str] = None
        if route in {"hybrid", "multi_hop"} and sparse_top_k > 0:
            try:
                sparse_hits = await sparse_search_chunks(
                    current_query,
                    tenant_id=tenant_id,
                    top_k=sparse_top_k,
                )
            except Exception as exc:
                sparse_error = str(exc)
                logger.warning(f"稀疏检索失败，将回退为仅使用向量结果: {exc}")

        if route in {"hybrid", "multi_hop"}:
            documents = reciprocal_rank_fusion(
                [vector_hits, sparse_hits],
                ["vector", "sparse"],
                top_k=max(top_k, min(dense_top_k + sparse_top_k, 50)),
            )
        else:
            documents = vector_hits[:top_k]

        attempt = {
            "attempt": attempt_number,
            "query": current_query,
            "route": route,
            "dense_results": len(vector_hits),
            "sparse_results": len(sparse_hits),
            "merged_results": len(documents),
        }
        if vector_error:
            attempt["vector_error"] = vector_error
        if sparse_error:
            attempt["sparse_error"] = sparse_error
        state.setdefault("retrieval_attempts", []).append(attempt)
        state["retrieval_feedback"] = (
            f"第 {attempt_number} 次检索 query={current_query!r}, route={route}, "
            f"dense={len(vector_hits)}, sparse={len(sparse_hits)}, merged={len(documents)}"
        )
        if vector_error or sparse_error:
            errors = [err for err in [vector_error, sparse_error] if err]
            state["retrieval_error"] = " | ".join(errors)
            state["error"] = vector_error or sparse_error
        else:
            state["retrieval_error"] = None
            state["error"] = None

        if not documents:
            state["search_results"] = []
            state["reranked_results"] = []
            message = "未找到相关文档"
            if vector_error and not sparse_hits:
                message = f"未找到相关文档（向量检索失败：{vector_error}）"
            state["messages"].append(AIMessage(content=message))
            logger.warning(f"第 {attempt_number} 次检索未找到相关文档")
            return state
        
        state["search_results"] = documents
        state["messages"].append(AIMessage(content=f"检索到 {len(documents)} 个候选切片"))
        # logger.info(f"检索到的文档: {documents}")
        logger.info(f"检索完成，返回 {len(documents)} 个文档")
        return state
        
    except Exception as e:
        logger.error(f"检索失败: {e}")
        state["retrieval_count"] = attempt_number
        state["retrieval_error"] = str(e)
        state["error"] = str(e)
        state["retrieval_feedback"] = f"第 {attempt_number} 次检索失败: {e}"
        state.setdefault("retrieval_attempts", []).append(
            {
                "attempt": attempt_number,
                "query": state.get("current_query") or state["user_query"],
                "route": (state.get("query_plan") or {}).get("route") or (state.get("query_analysis") or {}).get("route") or "hybrid",
                "dense_results": 0,
                "sparse_results": 0,
                "merged_results": 0,
                "error": str(e),
            }
        )
        state["search_results"] = []
        state["reranked_results"] = []
        state["messages"].append(AIMessage(content=f"检索失败: {e}"))
        return state


async def reranker(state: AgenticRAGState) -> AgenticRAGState:
    """
    重排序节点
    使用 Reranker 对检索结果进行重排序
    """
    logger.info("开始重排序文档")
    
    try:
        analysis = state.get("query_analysis", {})
        needs_rerank = analysis.get("needs_rerank", True)
        
        if not needs_rerank:
            state["reranked_results"] = state["search_results"]
            state["messages"].append(AIMessage(content="跳过重排序"))
            return state
        
        if not state["search_results"]:
            state["reranked_results"] = []
            return state
        
        plan = state.get("query_plan") or {}
        rerank_top_k = min(
            int(plan.get("rerank_top_n") or settings.AGENTIC_RAG_DEFAULT_TOP_K),
            len(state["search_results"]),
        )
        
        reranked_results = await reranker_manager.rerank(
            query=state["user_query"],
            documents=state["search_results"],
            top_k=rerank_top_k,
        )
        
        state["reranked_results"] = reranked_results
        state["messages"].append(AIMessage(content=f"重排序完成，返回 {len(reranked_results)} 个结果"))
        # logger.info(f"重排序后的文档: {reranked_results}")
        logger.info(f"重排序完成，返回 {len(reranked_results)} 个结果")
        return state
        
    except Exception as e:
        logger.error(f"重排序失败: {e}")
        state["reranked_results"] = state["search_results"]
        return state


async def context_builder(state: AgenticRAGState) -> AgenticRAGState:
    """
    上下文构建节点
    将检索结果构建成上下文
    """
    logger.info("开始构建上下文")
    
    try:
        analysis = state.get("query_analysis", {})
        query_type = analysis.get("query_type")
        if query_type in DIRECT_REPLY_QUERY_TYPES:
            state["context"] = ""
            state["messages"].append(AIMessage(content="上下文构建完成（直接回答模式）"))
            logger.info(f"查询类型 {query_type}，跳过知识库上下文构建")
            return state

        results = state.get("reranked_results") or state.get("search_results", [])
        
        if not results:
            state["context"] = "没有找到相关的文档信息。"
            state["messages"].append(AIMessage(content="上下文构建完成（无结果）"))
            return state
        
        trimmed = await trim_retrieval_results(results)
        trimmed_results = trimmed["results"]
        source_bundle = _build_citations_and_evidence(trimmed_results)
        state["citations"] = source_bundle["citations"]
        state["evidence_cards"] = source_bundle["evidence_cards"]

        context_parts = []
        for i, doc in enumerate(trimmed_results, 1):
            text = doc.get("text", doc.get("content", ""))
            if text:
                context_parts.append(f"[文档 {i}] {text}")

        context = "\n\n".join(context_parts)
        state["context"] = context
        state["context_status"] = {
            "retrieval_doc_count": trimmed["doc_count"],
            "retrieval_token_budget": trimmed["token_budget"],
            "retrieval_max_docs": trimmed["max_docs"],
            "retrieval_max_doc_chars": trimmed["max_doc_chars"],
            "citations_count": len(source_bundle["citations"]),
            "evidence_count": len(source_bundle["evidence_cards"]),
        }
        state["messages"].append(AIMessage(content=f"上下文构建完成，包含 {len(context_parts)} 个文档"))

        logger.info(f"上下文构建完成，包含 {len(context_parts)} 个文档")
        return state
        
    except Exception as e:
        logger.error(f"上下文构建失败: {e}")
        state["context"] = ""
        return state


async def answer_generator(state: AgenticRAGState) -> AgenticRAGState:
    """
    答案生成节点
    基于上下文生成答案
    """
    logger.info("开始生成答案")
    
    try:
        analysis = state.get("query_analysis", {})
        query_type = analysis.get("query_type")

        if query_type in DIRECT_REPLY_QUERY_TYPES:
            system_prompt = """你是一个友好、自然的中文 AI 助手。

回答要求：
1. 对问候语、致谢、告别或简短闲聊直接自然回应
2. 不要提及知识库、检索、上下文或文档是否命中
3. 语气简洁、友好、有帮助
4. 如果合适，可以顺带说明你能帮助用户解答问题或检索知识"""

            user_prompt = state["user_query"]
            max_tokens = 200
        else:
            if not (state.get("reranked_results") or state.get("search_results")):
                refusal = _build_refusal_response(state, reason="no_retrieval_results")
                state["answer"] = refusal["message"]
                state["answer_blocks"] = _bind_answer_citations(refusal["message"], [])
                state["refusal"] = refusal
                state["answer_error"] = None
                state["messages"].append(AIMessage(content=refusal["message"]))
                return state

            system_prompt = """你是一个专业的问答助手。请基于提供的上下文信息回答用户的问题。

回答要求：
1. 只使用提供的上下文信息，不要编造内容
2. 如果上下文中没有相关信息，明确说明
3. 回答要准确、清晰、有条理
4. 在关键结论后使用【来源1】【来源2】这种方式标记来源
5. 当证据不足时明确表达不确定性，避免为了回答而回答
6. 使用中文回答"""

            user_prompt = f"""上下文信息：
{state['context']}

用户问题：{state['user_query']}

请基于上下文信息回答用户的问题，并在关键结论后添加来源标记。"""
            max_tokens = 1000

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = await llm_manager.chat_completion(
            messages=langchain_messages_to_dicts(messages),
            temperature=0.7,
            max_tokens=max_tokens,
        )
        
        answer = response["choices"][0]["message"]["content"]
        state["answer"] = answer
        state["answer_blocks"] = _bind_answer_citations(answer, state.get("citations") or [])
        state["refusal"] = None
        state["answer_error"] = None
        state["messages"].append(AIMessage(content=answer))
        
        logger.info(f"答案生成完成，长度: {len(answer)} 字符")
        return state
        
    except Exception as e:
        logger.error(f"答案生成失败: {e}")
        state["answer_error"] = str(e)
        state["error"] = str(e)
        state["answer"] = "抱歉，生成答案时出现错误。"
        return state


async def quality_evaluator(state: AgenticRAGState) -> AgenticRAGState:
    """
    质量评估节点
    评估生成答案的质量
    """
    logger.info("开始评估答案质量")
    
    try:
        query_type = (state.get("query_analysis") or {}).get("query_type")
        if query_type in DIRECT_REPLY_QUERY_TYPES:
            quality_score = 1.0
            state["quality_score"] = quality_score
            state["messages"].append(AIMessage(content="直接回答模式，跳过质量评估"))
            logger.info(f"查询类型 {query_type}，跳过质量模型评估，分数: {quality_score:.2f}")
            return state

        if not state.get("search_results") and not state.get("reranked_results"):
            quality_score = 0.0
            state["quality_score"] = quality_score
            state["uncertainty"] = _build_uncertainty_signal(quality_score, has_results=False, context_doc_count=0)
            state["refusal"] = _build_refusal_response(state, reason="no_retrieval_results")
            state["messages"].append(AIMessage(content="未检索到文档，跳过质量评估"))
            logger.info("未检索到相关文档，跳过质量模型评估，分数: 0.00")
            return state

        evaluation_prompt = f"""请评估以下问答的质量，给出 0 到 1 之间的分数。

用户问题：{state['user_query']}

生成的答案：{state['answer']}

评估标准：
1. 答案是否准确
2. 答案是否完整
3. 答案是否清晰易懂
4. 答案是否直接回答了问题

请只输出分数（0-1 之间的小数），不要输出其他内容。"""

        messages = [
            SystemMessage(content="你是一个专业的问答质量评估助手。"),
            HumanMessage(content=evaluation_prompt)
        ]
        
        request_messages = langchain_messages_to_dicts(messages)
        response = await _request_quality_score(
            messages=request_messages,
            max_tokens=QUALITY_EVALUATION_MAX_TOKENS,
        )
        logger.info(f"质量评估模型响应: {response}")
        score_text = _extract_chat_response_text(response)
        finish_reason = response.get("choices", [{}])[0].get("finish_reason")

        if not score_text and finish_reason == "length":
            logger.warning(
                "质量评估模型返回空内容且 finish_reason=length，使用更大 max_tokens 重试一次"
            )
            response = await _request_quality_score(
                messages=request_messages,
                max_tokens=QUALITY_EVALUATION_MAX_TOKENS * 4,
            )
            # logger.info(f"质量评估重试模型响应: {response}")
            score_text = _extract_chat_response_text(response)


        quality_score = _parse_quality_score(score_text)
        if quality_score is None:
            logger.warning(f"无法解析质量分数: {score_text}，使用默认值 0.5")
            quality_score = 0.5
        
        state["quality_score"] = quality_score
        context_doc_count = len(state.get("citations") or [])
        state["uncertainty"] = _build_uncertainty_signal(
            quality_score,
            has_results=bool(state.get("search_results") or state.get("reranked_results")),
            context_doc_count=context_doc_count,
        )
        if quality_score < 0.35:
            state["refusal"] = _build_refusal_response(state, reason="low_confidence")
        state["messages"].append(AIMessage(content=f"质量评估完成，分数: {quality_score:.2f}"))
        
        logger.info(f"质量评估完成，分数: {quality_score:.2f}")
        return state
        
    except Exception as e:
        logger.error(f"质量评估失败: {e}")
        state["quality_score"] = 0.5
        return state


def decision_maker(state: AgenticRAGState) -> str:
    """
    决策节点
    决定是否继续检索或结束
    """
    quality_threshold = settings.AGENTIC_RAG_QUALITY_THRESHOLD
    query_type = (state.get("query_analysis") or {}).get("query_type")
    quality_score = state.get("quality_score", 0.0)
    retrieval_count = state.get("retrieval_count", 0)
    max_retrievals = state.get("max_retrievals", 2)
    search_results = state.get("search_results") or []
    retrieval_error = state.get("retrieval_error")
    answer_error = state.get("answer_error")
    legacy_error = state.get("error")

    if retrieval_error is None and answer_error is None and legacy_error:
        retrieval_error = legacy_error

    if query_type in DIRECT_REPLY_QUERY_TYPES:
        logger.info(f"查询类型 {query_type}，直接回答完成，结束流程")
        state["should_continue"] = False
        return "end"

    if answer_error:
        logger.warning(f"答案生成失败，结束流程，错误: {answer_error}")
        state["should_continue"] = False
        return "end"

    if state.get("refusal") and retrieval_count >= max_retrievals:
        logger.info("证据不足，输出拒答响应并结束流程")
        state["should_continue"] = False
        return "end"

    if retrieval_error:
        if retrieval_count < max_retrievals:
            logger.warning(
                f"第 {retrieval_count} 次检索失败，准备重试"
                f"（{retrieval_count}/{max_retrievals}），错误: {retrieval_error}"
            )
            state["should_continue"] = True
            return "continue"

        logger.warning(
            f"检索失败且已达到最大重试次数 {max_retrievals}，结束流程，错误: {retrieval_error}"
        )
        state["should_continue"] = False
        return "end"

    if quality_score >= quality_threshold:
        logger.info(f"质量分数 {quality_score:.2f} >= {quality_threshold:.2f}，结束检索")
        state["should_continue"] = False
        return "end"

    if not search_results:
        logger.info(f"第 {retrieval_count} 次检索未命中文档，结束流程")
        state["should_continue"] = False
        return "end"
    
    if retrieval_count >= max_retrievals:
        logger.info(f"已达到最大检索次数 {max_retrievals}，结束检索")
        state["should_continue"] = False
        return "end"
    
    logger.info(
        f"质量分数 {quality_score:.2f} < {quality_threshold:.2f}，继续检索"
        f"（{retrieval_count}/{max_retrievals}）"
    )
    state["should_continue"] = True
    return "continue"
