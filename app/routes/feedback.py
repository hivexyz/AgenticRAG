"""用户反馈与知识优化闭环 API。"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_auth_context, require_write_access, resolve_tenant_id
from app.config import settings
from app.database.postgres import postgres_manager
from app.db_models import AnswerFeedback, ConversationMessage, Document, WikiCompileJob
from app.observability import log_audit_event, metrics_registry
from app.services.feedback_loop import append_eval_case, build_badcase_items
from app.services.wiki import run_wiki_compile_job
from app.tasks import task_runner

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


class GoldenSetRequest(BaseModel):
    tenant_id: Optional[str] = Field(None, description="租户 ID（开发兼容；生产认证开启时忽略）")
    append_to_file: bool = Field(True, description="是否写入 FEEDBACK_GOLDEN_SET_PATH")


class WikiRecompileRequest(BaseModel):
    tenant_id: Optional[str] = Field(None, description="租户 ID（开发兼容；生产认证开启时忽略）")
    document_ids: Optional[List[int]] = Field(None, description="为空时从 badcase 命中文档推断")


async def _load_feedback_context(session: AsyncSession, tenant_id: str) -> Dict[str, Any]:
    feedback_result = await session.execute(select(AnswerFeedback).where(AnswerFeedback.tenant_id == tenant_id))
    message_result = await session.execute(select(ConversationMessage).where(ConversationMessage.tenant_id == tenant_id))
    document_result = await session.execute(select(Document).where(Document.tenant_id == tenant_id))
    return {
        "feedback_items": list(feedback_result.scalars().all()),
        "messages": list(message_result.scalars().all()),
        "documents": list(document_result.scalars().all()),
    }


def _find_badcase_or_404(items: List[Dict[str, Any]], feedback_id: int) -> Dict[str, Any]:
    for item in items:
        if item["feedback"]["id"] == feedback_id:
            return item
    raise HTTPException(status_code=404, detail="反馈不存在")


@router.post("/answers", response_model=FeedbackResponse)
async def submit_answer_feedback(
    request: FeedbackCreateRequest,
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(require_write_access),
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


@router.get("/badcases")
async def list_feedback_badcases(
    tenant_id: Optional[str] = Query(None),
    rating: str = Query("down"),
    reason: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
    context = await _load_feedback_context(session, normalized_tenant_id)
    feedback_items = [
        item
        for item in context["feedback_items"]
        if (rating == "all" or item.rating == rating) and (reason is None or item.reason == reason)
    ]
    badcases = build_badcase_items(
        feedback_items,
        context["messages"],
        context["documents"],
    )[:limit]
    reason_counts = Counter(item["feedback"].get("reason") for item in badcases if item["feedback"].get("reason"))
    return {
        "tenant_id": normalized_tenant_id,
        "summary": {
            "total": len(badcases),
            "reason_counts": dict(reason_counts),
        },
        "items": badcases,
    }


@router.post("/answers/{feedback_id}/golden-set")
async def add_feedback_to_golden_set(
    feedback_id: int,
    request: GoldenSetRequest,
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(require_write_access),
):
    normalized_tenant_id = resolve_tenant_id(request.tenant_id, auth)
    context = await _load_feedback_context(session, normalized_tenant_id)
    badcases = build_badcase_items(context["feedback_items"], context["messages"], context["documents"])
    badcase = _find_badcase_or_404(badcases, feedback_id)
    candidate = badcase["golden_candidate"]

    result = {
        "added": False,
        "path": settings.FEEDBACK_GOLDEN_SET_PATH,
        "candidate": candidate,
    }
    if request.append_to_file:
        result = append_eval_case(Path(settings.FEEDBACK_GOLDEN_SET_PATH), candidate)

    feedback = next(item for item in context["feedback_items"] if item.id == feedback_id)
    metadata = feedback.feedback_metadata if isinstance(feedback.feedback_metadata, dict) else {}
    feedback.feedback_metadata = {
        **metadata,
        "golden_set": {
            "added": result["added"],
            "path": result["path"],
            "candidate_id": candidate["id"],
        },
        "golden_set_candidate": candidate,
    }
    await session.commit()
    log_audit_event(
        "feedback.golden_set.add",
        tenant_id=normalized_tenant_id,
        target_id=str(feedback_id),
        extra={"added": result["added"], "path": result["path"]},
    )
    return result


@router.post("/answers/{feedback_id}/wiki-recompile")
async def trigger_feedback_wiki_recompile(
    feedback_id: int,
    request: WikiRecompileRequest,
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(require_write_access),
):
    normalized_tenant_id = resolve_tenant_id(request.tenant_id, auth)
    context = await _load_feedback_context(session, normalized_tenant_id)
    badcases = build_badcase_items(context["feedback_items"], context["messages"], context["documents"])
    badcase = _find_badcase_or_404(badcases, feedback_id)
    known_document_ids = {doc.id for doc in context["documents"]}
    document_ids = list(dict.fromkeys(request.document_ids or badcase["wiki_recompile_document_ids"]))
    document_ids = [document_id for document_id in document_ids if document_id in known_document_ids]
    if not document_ids:
        raise HTTPException(status_code=400, detail="没有可重编 Wiki 的源文档")

    job = WikiCompileJob(
        tenant_id=normalized_tenant_id,
        status="pending",
        document_ids=document_ids,
        success_count=0,
        failure_count=0,
        result_metadata={"source": "feedback", "feedback_id": feedback_id},
        retry_count=0,
        max_retries=settings.WIKI_COMPILE_JOB_MAX_RETRIES,
        next_run_at=None,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    if settings.should_submit_wiki_jobs_inline:
        task_runner.submit(f"wiki-compile:{job.id}", lambda: run_wiki_compile_job(job.id))
    log_audit_event(
        "feedback.wiki_recompile.create",
        tenant_id=normalized_tenant_id,
        target_id=str(feedback_id),
        extra={"job_id": job.id, "document_ids": document_ids},
    )
    return {
        "feedback_id": feedback_id,
        "job": job.to_dict(),
        "document_ids": document_ids,
    }


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

    badcases = build_badcase_items(feedback_items, messages, documents)
    reason_counts = Counter(item.reason for item in feedback_items if item.reason)
    low_quality = [item for item in badcases if item["feedback"].get("rating") == "down"]
    no_answer = [item for item in badcases if item["feedback"].get("reason") in {"not_helpful", "missing_information"}]
    corrected = [item.to_dict() for item in feedback_items if item.corrected_answer]

    question_counter = Counter(msg.content for msg in messages if getattr(msg, "role", None) == "user")

    document_hit_counter = Counter()
    for item in badcases:
        for doc_id in item["document_ids"]:
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
            "golden_set_candidates": [item["golden_candidate"] for item in badcases if item["feedback"].get("rating") == "down"],
        },
    }
