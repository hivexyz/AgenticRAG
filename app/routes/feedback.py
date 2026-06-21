"""用户反馈与知识优化闭环 API。"""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_auth_context, resolve_tenant_id
from app.database.postgres import postgres_manager
from app.db_models import AnswerFeedback, ConversationMessage, Document
from app.observability import log_audit_event, metrics_registry

router = APIRouter()

FEEDBACK_REASON_OPTIONS = {
    "helpful",
    "not_helpful",
    "incorrect",
    "missing_citations",
    "missing_information",
    "too_long",
    "too_short",
    "user_corrected_answer",
}


class FeedbackCreateRequest(BaseModel):
    tenant_id: Optional[str] = Field(None, description="租户 ID（开发兼容；生产认证开启时忽略）")
    session_id: Optional[int] = None
    message_id: Optional[int] = None
    rating: str = Field(..., description="up/down")
    reason: str = Field(..., description="反馈原因")
    comment: Optional[str] = None
    corrected_answer: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class FeedbackResponse(BaseModel):
    id: int
    tenant_id: str
    session_id: Optional[int] = None
    message_id: Optional[int] = None
    feedback_type: str
    rating: str
    reason: Optional[str] = None
    comment: Optional[str] = None
    corrected_answer: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None


@router.post("/answers", response_model=FeedbackResponse)
async def submit_answer_feedback(
    request: FeedbackCreateRequest,
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    tenant_id = resolve_tenant_id(request.tenant_id, auth)
    if request.reason not in FEEDBACK_REASON_OPTIONS:
        raise HTTPException(status_code=400, detail="reason 无效")
    if request.rating not in {"up", "down"}:
        raise HTTPException(status_code=400, detail="rating 必须为 up 或 down")

    item = AnswerFeedback(
        tenant_id=tenant_id,
        session_id=request.session_id,
        message_id=request.message_id,
        feedback_type="answer",
        rating=request.rating,
        reason=request.reason,
        comment=request.comment,
        corrected_answer=request.corrected_answer,
        feedback_metadata=request.metadata,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    log_audit_event("feedback.answer.create", tenant_id=tenant_id, target_id=str(item.id), extra={"reason": item.reason, "rating": item.rating})
    return FeedbackResponse(**item.to_dict())


@router.get("/answers", response_model=List[FeedbackResponse])
async def list_answer_feedback(
    tenant_id: Optional[str] = Query(None),
    session_id: Optional[int] = Query(None),
    message_id: Optional[int] = Query(None),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
    result = await session.execute(select(AnswerFeedback).where(AnswerFeedback.tenant_id == normalized_tenant_id))
    items = list(result.scalars().all())
    if session_id is not None:
        items = [item for item in items if item.session_id == session_id]
    if message_id is not None:
        items = [item for item in items if item.message_id == message_id]
    return [FeedbackResponse(**item.to_dict()) for item in items]


@router.get("/analytics")
async def feedback_analytics(
    tenant_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
    feedback_result = await session.execute(select(AnswerFeedback).where(AnswerFeedback.tenant_id == normalized_tenant_id))
    feedback_items = list(feedback_result.scalars().all())

    message_result = await session.execute(select(ConversationMessage).where(ConversationMessage.tenant_id == normalized_tenant_id))
    messages = list(message_result.scalars().all())

    document_result = await session.execute(select(Document).where(Document.tenant_id == normalized_tenant_id))
    documents = list(document_result.scalars().all())

    reason_counts = Counter(item.reason for item in feedback_items if item.reason)
    low_quality = [item.to_dict() for item in feedback_items if item.rating == "down"]
    no_answer = [item.to_dict() for item in feedback_items if item.reason in {"not_helpful", "missing_information"}]
    corrected = [item.to_dict() for item in feedback_items if item.corrected_answer]

    question_counter = Counter(msg.content for msg in messages if getattr(msg, "role", None) == "user")
    message_by_id = {msg.id: msg for msg in messages}
    poor_questions = []
    for item in feedback_items:
        msg = message_by_id.get(item.message_id)
        if msg and msg.role == "assistant":
            poor_questions.append(msg.content)

    document_hit_counter = Counter()
    for item in feedback_items:
        metadata = item.feedback_metadata or {}
        for doc_id in metadata.get("document_ids", []):
            document_hit_counter[str(doc_id)] += 1

    unused_documents = [doc.title for doc in documents if doc.vector_status != "ready" or doc.chunk_count in (0, None)]

    metrics = metrics_registry.snapshot()
    response_times = list(metrics.get("average_latency_ms", {}).values())
    estimated_model_cost = round(len(messages) * 0.0002 + len(feedback_items) * 0.00005, 6)

    suggestions = []
    if reason_counts.get("missing_information"):
        suggestions.append("建议补充被频繁反馈为信息缺失的主题文档。")
    if reason_counts.get("missing_citations"):
        suggestions.append("建议强化引用链路和句级证据绑定。")
    if corrected:
        suggestions.append("可将用户补充的正确答案沉淀为 FAQ 或 Golden Set。")

    return {
        "feedback_summary": {
            "total_feedback": len(feedback_items),
            "positive": sum(1 for item in feedback_items if item.rating == "up"),
            "negative": sum(1 for item in feedback_items if item.rating == "down"),
            "reason_counts": dict(reason_counts),
        },
        "high_frequency_questions": question_counter.most_common(10),
        "no_answer_questions": no_answer,
        "low_quality_answers": low_quality,
        "top_hit_documents": document_hit_counter.most_common(10),
        "unused_documents": unused_documents,
        "retrieval_failure_rate": 0.0 if metrics["request_count"] == 0 else metrics["error_count"] / metrics["request_count"],
        "average_response_time_ms": mean(response_times) if response_times else 0.0,
        "estimated_model_cost": estimated_model_cost,
        "optimization_suggestions": suggestions,
        "feedback_driven_actions": {
            "document_gap_analysis": [item[0] for item in reason_counts.most_common(5)],
            "faq_candidates": corrected,
            "golden_set_candidates": corrected,
        },
    }
