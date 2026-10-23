"""会话 API。"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_auth_context, require_write_access, resolve_tenant_id
from app.context.assembler import (
    compose_history_with_summary,
    generate_session_summary,
    should_refresh_summary,
)
from app.agents import agentic_rag_manager
from app.database.postgres import postgres_manager
from app.db_models import ConversationMessage, ConversationSession
from app.observability import log_audit_event
from app.utils.logger import logger


def _build_summary_message_metadata(*, convo: ConversationSession, summary_result: Dict[str, Any], previous_summary: Optional[str]) -> Dict[str, Any]:
    return {
        "summary_version": convo.summary_version,
        "summary_message_cutoff_id": convo.summary_message_cutoff_id,
        "summary_updated_at": convo.summary_updated_at.isoformat() if convo.summary_updated_at else None,
        "summary_incremental": bool(summary_result.get("incremental")),
        "summary_source_message_count": int(summary_result.get("source_message_count") or 0),
        "previous_summary": previous_summary,
    }

router = APIRouter()

FEEDBACK_ACTIONS = [
    {"key": "helpful", "label": "👍 有帮助"},
    {"key": "not_helpful", "label": "👎 没帮助"},
    {"key": "incorrect", "label": "答案不准确"},
    {"key": "missing_citations", "label": "没有引用来源"},
    {"key": "missing_information", "label": "遗漏关键信息"},
    {"key": "too_long", "label": "回答太长"},
    {"key": "too_short", "label": "回答太短"},
    {"key": "user_corrected_answer", "label": "补充正确答案"},
]


class ConversationCreateRequest(BaseModel):
    tenant_id: Optional[str] = Field(None, description="租户 ID（开发兼容；生产认证开启时忽略）")
    title: str = Field("新会话", description="会话标题")
    user_id: Optional[str] = Field(None, description="用户 ID")


class ConversationSendRequest(BaseModel):
    content: str = Field(..., description="用户消息")
    tenant_id: Optional[str] = Field(None, description="租户 ID（开发兼容；生产认证开启时忽略）")
    stream: bool = Field(False, description="是否流式")


def _build_assistant_content(rag_result: Dict[str, Any]) -> str:
    return rag_result.get("answer") or rag_result.get("error") or "抱歉，我暂时无法回答这个问题。"


def _build_assistant_metadata(rag_result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "query_analysis": rag_result.get("query_analysis"),
        "query_plan": rag_result.get("query_plan"),
        "standalone_query": rag_result.get("standalone_query"),
        "query_rewrites": rag_result.get("query_rewrites"),
        "retrieval_count": rag_result.get("retrieval_count"),
        "retrieval_attempts": rag_result.get("retrieval_attempts"),
        "search_results": rag_result.get("search_results"),
        "context_status": rag_result.get("context_status"),
        "quality_score": rag_result.get("quality_score"),
        "quality_evaluation": rag_result.get("quality_evaluation"),
        "quality_evaluation_status": rag_result.get("quality_evaluation_status"),
        "error": rag_result.get("error"),
        "multi_hop_trace": rag_result.get("multi_hop_trace"),
        "citations": rag_result.get("citations"),
        "answer_blocks": rag_result.get("answer_blocks"),
        "evidence_cards": rag_result.get("evidence_cards"),
        "uncertainty": rag_result.get("uncertainty"),
        "refusal": rag_result.get("refusal"),
        "feedback_actions": FEEDBACK_ACTIONS,
    }


def _sse_event(event: str, payload: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _get_conversation_or_404(
    db: AsyncSession,
    *,
    session_id: int,
    tenant_id: str,
) -> ConversationSession:
    result = await db.execute(
        select(ConversationSession).where(
            ConversationSession.id == session_id,
            ConversationSession.tenant_id == tenant_id,
        )
    )
    convo = result.scalar_one_or_none()
    if not convo:
        raise HTTPException(status_code=404, detail="会话不存在")
    return convo


async def _prepare_message_context(
    db: AsyncSession,
    *,
    convo: ConversationSession,
    session_id: int,
    tenant_id: str,
    content: str,
) -> Dict[str, Any]:
    user_message = ConversationMessage(
        session_id=session_id,
        tenant_id=tenant_id,
        role="user",
        content=content,
        message_type="raw",
    )
    db.add(user_message)
    convo.latest_message_at = datetime.utcnow()
    await db.commit()
    await db.refresh(user_message)
    await db.refresh(convo)

    history_result = await db.execute(
        select(ConversationMessage)
        .where(
            ConversationMessage.session_id == session_id,
            ConversationMessage.tenant_id == tenant_id,
        )
    )
    history_items = history_result.scalars().all()
    conversation_history = [
        {"id": item.id, "role": item.role, "content": item.content}
        for item in history_items
        if getattr(item, "message_type", None) == "raw"
    ]

    summary_generated = False
    summary_error = None
    summary_incremental = False
    summary_source_message_count = 0
    summary_message = None

    if await should_refresh_summary(
        conversation_history,
        latest_summary=convo.latest_summary,
        cutoff_message_id=convo.summary_message_cutoff_id,
    ):
        try:
            previous_summary = convo.latest_summary
            summary_result = await generate_session_summary(
                conversation_history,
                existing_summary=convo.latest_summary,
                cutoff_message_id=convo.summary_message_cutoff_id,
            )
            refreshed_summary = summary_result.get("summary")
            if refreshed_summary:
                convo.latest_summary = refreshed_summary
                convo.summary_message_cutoff_id = summary_result.get("cutoff_message_id")
                convo.summary_updated_at = datetime.utcnow()
                convo.summary_version = int(convo.summary_version or 0) + 1
                summary_generated = True
                summary_incremental = bool(summary_result.get("incremental"))
                summary_source_message_count = int(summary_result.get("source_message_count") or 0)
                summary_message = ConversationMessage(
                    session_id=session_id,
                    tenant_id=tenant_id,
                    role="system",
                    content=refreshed_summary,
                    message_type="summary",
                    message_metadata=_build_summary_message_metadata(
                        convo=convo,
                        summary_result=summary_result,
                        previous_summary=previous_summary,
                    ),
                )
                db.add(summary_message)
                await db.commit()
                await db.refresh(summary_message)
                await db.refresh(convo)
                log_audit_event(
                    "conversation.summary.refresh",
                    tenant_id=tenant_id,
                    target_id=str(session_id),
                    extra={
                        "summary_version": convo.summary_version,
                        "summary_message_id": str(summary_message.id),
                        "summary_message_cutoff_id": convo.summary_message_cutoff_id,
                        "summary_incremental": summary_incremental,
                        "summary_source_message_count": summary_source_message_count,
                    },
                )
        except Exception as exc:  # pragma: no cover
            summary_error = str(exc)

    history_context = await compose_history_with_summary(
        conversation_history,
        latest_summary=convo.latest_summary,
    )

    context_status = {
        "history_message_count": history_context["history_message_count"],
        "history_recent_turns": history_context["recent_turns"],
        "history_token_budget": history_context["history_token_budget"],
        "history_token_count": history_context["history_token_count"],
        "summary_present": history_context["summary_present"],
        "used_summary": history_context["used_summary"],
        "summary_generated": summary_generated,
        "summary_error": summary_error,
        "summary_incremental": summary_incremental,
        "summary_source_message_count": summary_source_message_count,
        "summary_message_cutoff_id": convo.summary_message_cutoff_id,
        "summary_version": convo.summary_version,
        "summary_updated_at": convo.summary_updated_at.isoformat() if convo.summary_updated_at else None,
    }
    return {
        "user_message": user_message,
        "summary_message": summary_message,
        "history_context": history_context,
        "context_status": context_status,
    }


async def _store_assistant_message(
    db: AsyncSession,
    *,
    convo: ConversationSession,
    session_id: int,
    tenant_id: str,
    rag_result: Dict[str, Any],
) -> ConversationMessage:
    assistant_message = ConversationMessage(
        session_id=session_id,
        tenant_id=tenant_id,
        role="assistant",
        content=_build_assistant_content(rag_result),
        message_type="raw",
        message_metadata=_build_assistant_metadata(rag_result),
    )
    db.add(assistant_message)
    convo.latest_message_at = datetime.utcnow()
    await db.commit()
    await db.refresh(assistant_message)
    await db.refresh(convo)
    return assistant_message


@router.post("/", response_model=Dict[str, Any])
async def create_conversation(
    request: ConversationCreateRequest,
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(require_write_access),
):
    tenant_id = resolve_tenant_id(request.tenant_id, auth)
    db_item = ConversationSession(
        tenant_id=tenant_id,
        user_id=request.user_id,
        title=request.title or "新会话",
        status="active",
    )
    session.add(db_item)
    await session.commit()
    await session.refresh(db_item)
    log_audit_event("conversation.create", tenant_id=tenant_id, target_id=str(db_item.id))
    return db_item.to_dict()


@router.get("/", response_model=List[Dict[str, Any]])
async def list_conversations(
    tenant_id: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
    result = await session.execute(
        select(ConversationSession)
        .where(ConversationSession.tenant_id == normalized_tenant_id)
        .offset(skip)
        .limit(limit)
    )
    items = result.scalars().all()
    return [item.to_dict() for item in items]


@router.get("/{session_id}", response_model=Dict[str, Any])
async def get_conversation(
    session_id: int,
    tenant_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
    result = await session.execute(
        select(ConversationSession).where(
            ConversationSession.id == session_id,
            ConversationSession.tenant_id == normalized_tenant_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="会话不存在")
    return item.to_dict()


@router.get("/{session_id}/messages", response_model=List[Dict[str, Any]])
async def list_conversation_messages(
    session_id: int,
    tenant_id: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
    result = await session.execute(
        select(ConversationMessage)
        .where(
            ConversationMessage.session_id == session_id,
            ConversationMessage.tenant_id == normalized_tenant_id,
        )
        .offset(skip)
        .limit(limit)
    )
    items = result.scalars().all()
    return [item.to_dict() for item in items]


@router.post("/{session_id}/messages", response_model=Dict[str, Any])
async def send_message(
    session_id: int,
    request: ConversationSendRequest,
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(require_write_access),
):
    normalized_tenant_id = resolve_tenant_id(request.tenant_id, auth)
    convo = await _get_conversation_or_404(session, session_id=session_id, tenant_id=normalized_tenant_id)
    prepared = await _prepare_message_context(
        session,
        convo=convo,
        session_id=session_id,
        tenant_id=normalized_tenant_id,
        content=request.content,
    )
    user_message = prepared["user_message"]
    summary_message = prepared["summary_message"]
    history_context = prepared["history_context"]

    rag_result = await agentic_rag_manager.query(
        user_query=request.content,
        tenant_id=normalized_tenant_id,
        conversation_history=history_context["history"],
        config=None,
    )

    assistant_message = await _store_assistant_message(
        session,
        convo=convo,
        session_id=session_id,
        tenant_id=normalized_tenant_id,
        rag_result=rag_result,
    )

    log_audit_event("conversation.message.send", tenant_id=normalized_tenant_id, target_id=str(session_id))
    return {
        "session": convo.to_dict(),
        "user_message": user_message.to_dict(),
        "assistant_message": assistant_message.to_dict(),
        "summary_message": summary_message.to_dict() if summary_message else None,
        "feedback": {
            "message_id": assistant_message.id,
            "actions": assistant_message.message_metadata.get("feedback_actions", []),
        },
        "rag_result": rag_result,
        "context_status": prepared["context_status"],
    }


@router.post("/{session_id}/messages/stream")
async def stream_message(
    session_id: int,
    request: ConversationSendRequest,
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(require_write_access),
):
    normalized_tenant_id = resolve_tenant_id(request.tenant_id, auth)
    convo = await _get_conversation_or_404(session, session_id=session_id, tenant_id=normalized_tenant_id)
    prepared = await _prepare_message_context(
        session,
        convo=convo,
        session_id=session_id,
        tenant_id=normalized_tenant_id,
        content=request.content,
    )
    user_message = prepared["user_message"]
    history_context = prepared["history_context"]

    async def event_generator():
        yield _sse_event("user_message", {"user_message": user_message.to_dict()})
        final_result = None
        try:
            async for event in agentic_rag_manager.stream_query_response(
                user_query=request.content,
                tenant_id=normalized_tenant_id,
                conversation_history=history_context["history"],
                config=None,
            ):
                event_name = event.get("event", "message")
                if event_name == "final":
                    final_result = event.get("result")
                    continue
                yield _sse_event(event_name, event)
                if event_name == "error":
                    return

            if final_result is None:
                raise RuntimeError("流式查询未返回最终结果")

            assistant_message = await _store_assistant_message(
                session,
                convo=convo,
                session_id=session_id,
                tenant_id=normalized_tenant_id,
                rag_result=final_result,
            )
            log_audit_event("conversation.message.stream", tenant_id=normalized_tenant_id, target_id=str(session_id))
            payload = {
                "session": convo.to_dict(),
                "user_message": user_message.to_dict(),
                "assistant_message": assistant_message.to_dict(),
                "summary_message": prepared["summary_message"].to_dict() if prepared["summary_message"] else None,
                "feedback": {
                    "message_id": assistant_message.id,
                    "actions": assistant_message.message_metadata.get("feedback_actions", []),
                },
                "rag_result": final_result,
                "context_status": prepared["context_status"],
            }
            yield _sse_event("final", payload)
            yield _sse_event("done", {"ok": True})
        except Exception as exc:  # pragma: no cover - exercised by client disconnects and runtime failures
            logger.error(f"会话流式消息失败: {exc}")
            yield _sse_event("error", {"error": str(exc)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
