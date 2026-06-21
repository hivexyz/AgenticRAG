"""会话 API。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_auth_context, resolve_tenant_id
from app.context.assembler import (
    compose_history_with_summary,
    generate_session_summary,
    should_refresh_summary,
)
from app.agents import agentic_rag_manager
from app.database.postgres import postgres_manager
from app.db_models import ConversationMessage, ConversationSession
from app.observability import log_audit_event


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


class ConversationCreateRequest(BaseModel):
    tenant_id: Optional[str] = Field(None, description="租户 ID（开发兼容；生产认证开启时忽略）")
    title: str = Field("新会话", description="会话标题")
    user_id: Optional[str] = Field(None, description="用户 ID")


class ConversationSendRequest(BaseModel):
    content: str = Field(..., description="用户消息")
    tenant_id: Optional[str] = Field(None, description="租户 ID（开发兼容；生产认证开启时忽略）")
    stream: bool = Field(False, description="是否流式")


@router.post("/", response_model=Dict[str, Any])
async def create_conversation(
    request: ConversationCreateRequest,
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
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
    auth=Depends(get_auth_context),
):
    normalized_tenant_id = resolve_tenant_id(request.tenant_id, auth)

    result = await session.execute(
        select(ConversationSession).where(
            ConversationSession.id == session_id,
            ConversationSession.tenant_id == normalized_tenant_id,
        )
    )
    convo = result.scalar_one_or_none()
    if not convo:
        raise HTTPException(status_code=404, detail="会话不存在")

    user_message = ConversationMessage(
        session_id=session_id,
        tenant_id=normalized_tenant_id,
        role="user",
        content=request.content,
        message_type="raw",
    )
    session.add(user_message)
    convo.latest_message_at = datetime.utcnow()
    await session.commit()
    await session.refresh(user_message)
    await session.refresh(convo)

    history_result = await session.execute(
        select(ConversationMessage)
        .where(
            ConversationMessage.session_id == session_id,
            ConversationMessage.tenant_id == normalized_tenant_id,
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
                    tenant_id=normalized_tenant_id,
                    role="system",
                    content=refreshed_summary,
                    message_type="summary",
                    message_metadata=_build_summary_message_metadata(
                        convo=convo,
                        summary_result=summary_result,
                        previous_summary=previous_summary,
                    ),
                )
                session.add(summary_message)
                await session.commit()
                await session.refresh(summary_message)
                await session.refresh(convo)
                log_audit_event(
                    "conversation.summary.refresh",
                    tenant_id=normalized_tenant_id,
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

    rag_result = await agentic_rag_manager.query(
        user_query=request.content,
        tenant_id=normalized_tenant_id,
        conversation_history=history_context["history"],
        config={"max_retrievals": 2},
    )

    assistant_content = rag_result.get("answer") or rag_result.get("error") or "抱歉，我暂时无法回答这个问题。"
    assistant_message = ConversationMessage(
        session_id=session_id,
        tenant_id=normalized_tenant_id,
        role="assistant",
        content=assistant_content,
        message_type="raw",
        message_metadata={
            "query_analysis": rag_result.get("query_analysis"),
            "retrieval_count": rag_result.get("retrieval_count"),
            "quality_score": rag_result.get("quality_score"),
            "error": rag_result.get("error"),
            "citations": rag_result.get("citations"),
            "uncertainty": rag_result.get("uncertainty"),
            "refusal": rag_result.get("refusal"),
            "feedback_actions": [
                {"key": "helpful", "label": "👍 有帮助"},
                {"key": "not_helpful", "label": "👎 没帮助"},
                {"key": "incorrect", "label": "答案不准确"},
                {"key": "missing_citations", "label": "没有引用来源"},
                {"key": "missing_information", "label": "遗漏关键信息"},
                {"key": "too_long", "label": "回答太长"},
                {"key": "too_short", "label": "回答太短"},
                {"key": "user_corrected_answer", "label": "补充正确答案"},
            ],
        },
    )
    session.add(assistant_message)
    convo.latest_message_at = datetime.utcnow()
    await session.commit()
    await session.refresh(assistant_message)
    await session.refresh(convo)

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
        "context_status": {
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
        },
    }
