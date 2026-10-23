"""Wiki 页面管理 API。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_auth_context, require_write_access, resolve_tenant_id
from app.config import settings
from app.database.postgres import postgres_manager
from app.db_models import Document, WikiCompileJob, WikiPage, WikiPageLink, WikiPageRevision
from app.observability import log_audit_event
from app.services.wiki import (
    add_wiki_page_revision,
    build_revision_diff,
    clear_wiki_page_links,
    compile_documents_to_wiki_pages,
    rebuild_wiki_page_links,
    rebuild_wiki_page_links_for_page,
    run_wiki_compile_job,
    upsert_wiki_page_from_document,
)
from app.schemas.wiki import (
    WikiBulkCompileResponse,
    WikiCompileJobResponse,
    WikiDeleteResponse,
    WikiLinksRebuildResponse,
    WikiPageLinksResponse,
    WikiPageResponse,
    WikiPageRevisionResponse,
    WikiTopicIndexResponse,
)
from app.tasks import task_runner

router = APIRouter()


async def _get_ready_wiki_page(
    *,
    session: AsyncSession,
    tenant_id: str,
    page_id: int,
) -> WikiPage:
    result = await session.execute(
        select(WikiPage).where(
            WikiPage.id == page_id,
            WikiPage.tenant_id == tenant_id,
            WikiPage.status.in_(["ready", "stale"]),
        )
    )
    page = result.scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="wiki 页面不存在")
    return page


class WikiCompileRequest(BaseModel):
    tenant_id: Optional[str] = Field(None, description="租户 ID（开发兼容；生产认证开启时忽略）")
    document_id: int = Field(..., description="源文档 ID")


class WikiBulkCompileRequest(BaseModel):
    tenant_id: Optional[str] = Field(None, description="租户 ID（开发兼容；生产认证开启时忽略）")
    document_ids: List[int] = Field(..., min_length=1, max_length=50, description="源文档 ID 列表")
    async_compile: bool = Field(False, description="是否异步编译")


class WikiUpdateRequest(BaseModel):
    tenant_id: Optional[str] = Field(None, description="租户 ID（开发兼容；生产认证开启时忽略）")
    title: Optional[str] = Field(None, min_length=1, max_length=255, description="页面标题")
    summary: Optional[str] = Field(None, description="页面摘要")
    content: Optional[str] = Field(None, min_length=1, description="页面正文")
    knowledge_base: Optional[str] = Field(None, max_length=255, description="知识库名称")
    expected_updated_at: Optional[str] = Field(None, description="编辑时看到的 updated_at，用于冲突检测")


@router.get("/", response_model=List[WikiPageResponse])
async def list_wiki_pages(
    tenant_id: Optional[str] = Query(None),
    knowledge_base: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="页面状态，默认返回 ready 与 stale"),
    q: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
    statement = select(WikiPage).where(
        WikiPage.tenant_id == normalized_tenant_id,
    )
    if status:
        statement = statement.where(WikiPage.status == status)
    else:
        statement = statement.where(WikiPage.status.in_(["ready", "stale"]))
    if knowledge_base:
        statement = statement.where(WikiPage.knowledge_base == knowledge_base)
    if q:
        like = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                WikiPage.title.ilike(like),
                WikiPage.summary.ilike(like),
                WikiPage.content.ilike(like),
            )
        )
    result = await session.execute(
        statement
        .order_by(WikiPage.updated_at.desc(), WikiPage.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return [item.to_dict() for item in result.scalars().all()]


@router.get("/index/summary", response_model=WikiTopicIndexResponse)
async def get_wiki_topic_index(
    tenant_id: Optional[str] = Query(None),
    knowledge_base: Optional[str] = Query(None),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
    statement = select(WikiPage).where(
        WikiPage.tenant_id == normalized_tenant_id,
        WikiPage.status == "ready",
    )
    if knowledge_base:
        statement = statement.where(WikiPage.knowledge_base == knowledge_base)
    result = await session.execute(statement.order_by(WikiPage.knowledge_base.asc(), WikiPage.updated_at.desc(), WikiPage.id.desc()))
    groups: Dict[str, Dict[str, Any]] = {}
    for page in result.scalars().all():
        key = page.knowledge_base or "default"
        group = groups.setdefault(
            key,
            {
                "knowledge_base": key,
                "page_count": 0,
                "pages": [],
            },
        )
        group["page_count"] += 1
        if len(group["pages"]) < 10:
            group["pages"].append({
                "id": page.id,
                "title": page.title,
                "summary": page.summary,
                "updated_at": page.updated_at.isoformat() if page.updated_at else None,
            })
    return {
        "tenant_id": normalized_tenant_id,
        "knowledge_bases": list(groups.values()),
    }


@router.post("/links/rebuild", response_model=WikiLinksRebuildResponse)
async def rebuild_wiki_links(
    tenant_id: Optional[str] = Query(None),
    knowledge_base: Optional[str] = Query(None),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(require_write_access),
):
    normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
    result = await rebuild_wiki_page_links(
        session=session,
        tenant_id=normalized_tenant_id,
        knowledge_base=knowledge_base,
    )
    log_audit_event(
        "wiki.links.rebuild",
        tenant_id=normalized_tenant_id,
        extra={"knowledge_base": knowledge_base, "link_count": result["link_count"]},
    )
    return result


@router.get("/compile/jobs/{job_id}", response_model=WikiCompileJobResponse)
async def get_wiki_compile_job(
    job_id: int,
    tenant_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
    result = await session.execute(
        select(WikiCompileJob).where(
            WikiCompileJob.id == job_id,
            WikiCompileJob.tenant_id == normalized_tenant_id,
        )
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="wiki 编译任务不存在")
    return job.to_dict()


@router.get("/{page_id}", response_model=WikiPageResponse)
async def get_wiki_page(
    page_id: int,
    tenant_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
    page = await _get_ready_wiki_page(
        session=session,
        tenant_id=normalized_tenant_id,
        page_id=page_id,
    )
    return page.to_dict()


@router.get("/{page_id}/links", response_model=WikiPageLinksResponse)
async def get_wiki_page_links(
    page_id: int,
    tenant_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
    await _get_ready_wiki_page(
        session=session,
        tenant_id=normalized_tenant_id,
        page_id=page_id,
    )
    outgoing_result = await session.execute(
        select(WikiPageLink).where(
            WikiPageLink.source_page_id == page_id,
            WikiPageLink.tenant_id == normalized_tenant_id,
        )
    )
    incoming_result = await session.execute(
        select(WikiPageLink).where(
            WikiPageLink.target_page_id == page_id,
            WikiPageLink.tenant_id == normalized_tenant_id,
        )
    )
    return {
        "page_id": page_id,
        "outgoing": [item.to_dict() for item in outgoing_result.scalars().all()],
        "incoming": [item.to_dict() for item in incoming_result.scalars().all()],
    }


@router.get("/{page_id}/revisions", response_model=List[WikiPageRevisionResponse])
async def list_wiki_page_revisions(
    page_id: int,
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
    await _get_ready_wiki_page(
        session=session,
        tenant_id=normalized_tenant_id,
        page_id=page_id,
    )
    result = await session.execute(
        select(WikiPageRevision)
        .where(
            WikiPageRevision.page_id == page_id,
            WikiPageRevision.tenant_id == normalized_tenant_id,
        )
        .order_by(WikiPageRevision.created_at.desc(), WikiPageRevision.id.desc())
        .limit(limit)
    )
    return [item.to_dict() for item in result.scalars().all()]


@router.put("/{page_id}", response_model=WikiPageResponse)
async def update_wiki_page(
    page_id: int,
    request: WikiUpdateRequest,
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(require_write_access),
):
    normalized_tenant_id = resolve_tenant_id(request.tenant_id, auth)
    page = await _get_ready_wiki_page(
        session=session,
        tenant_id=normalized_tenant_id,
        page_id=page_id,
    )
    current_updated_at = page.updated_at.isoformat() if page.updated_at else None
    if request.expected_updated_at and request.expected_updated_at != current_updated_at:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Wiki 页面已被其他人更新，请刷新后再编辑",
                "current_updated_at": current_updated_at,
                "expected_updated_at": request.expected_updated_at,
            },
        )
    old_knowledge_base = page.knowledge_base
    before = {
        "title": page.title,
        "summary": page.summary,
        "content": page.content,
        "knowledge_base": page.knowledge_base,
    }

    if request.title is not None:
        page.title = request.title.strip()
    if request.summary is not None:
        page.summary = request.summary.strip()
    if request.content is not None:
        page.content = request.content.strip()
    if request.knowledge_base is not None:
        page.knowledge_base = request.knowledge_base.strip() or None

    after = {
        "title": page.title,
        "summary": page.summary,
        "content": page.content,
        "knowledge_base": page.knowledge_base,
    }
    diff = build_revision_diff(before, after)

    add_wiki_page_revision(
        session=session,
        page=page,
        action="update",
        metadata={
            "fields": diff["fields"],
            "diff": diff["changed"],
            "expected_updated_at": request.expected_updated_at,
            "previous_updated_at": current_updated_at,
        },
    )
    await session.commit()
    await session.refresh(page)
    await rebuild_wiki_page_links_for_page(session=session, tenant_id=normalized_tenant_id, page_id=page_id)
    if old_knowledge_base and old_knowledge_base != page.knowledge_base:
        await rebuild_wiki_page_links(
            session=session,
            tenant_id=normalized_tenant_id,
            knowledge_base=old_knowledge_base,
        )
    log_audit_event(
        "wiki.page.update",
        tenant_id=normalized_tenant_id,
        target_id=str(page_id),
        extra={"fields": [key for key, value in request.model_dump(exclude={"tenant_id"}).items() if value is not None]},
    )
    return page.to_dict()


@router.delete("/{page_id}", response_model=WikiDeleteResponse)
async def delete_wiki_page(
    page_id: int,
    tenant_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(require_write_access),
):
    normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
    page = await _get_ready_wiki_page(
        session=session,
        tenant_id=normalized_tenant_id,
        page_id=page_id,
    )
    page.status = "deleted"
    add_wiki_page_revision(session=session, page=page, action="delete", metadata={})
    await clear_wiki_page_links(session=session, tenant_id=normalized_tenant_id, page_id=page_id)
    await session.commit()
    log_audit_event("wiki.page.delete", tenant_id=normalized_tenant_id, target_id=str(page_id))
    return {"deleted": True, "page_id": page_id}


@router.post("/compile", response_model=WikiPageResponse)
async def compile_wiki_page(
    request: WikiCompileRequest,
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(require_write_access),
):
    normalized_tenant_id = resolve_tenant_id(request.tenant_id, auth)
    result = await session.execute(
        select(Document).where(
            Document.id == request.document_id,
            Document.tenant_id == normalized_tenant_id,
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="源文档不存在")

    page = await upsert_wiki_page_from_document(
        session=session,
        tenant_id=normalized_tenant_id,
        document=document,
    )
    log_audit_event(
        "wiki.page.compile",
        tenant_id=normalized_tenant_id,
        target_id=str(page.id),
        extra={"source_document_id": request.document_id},
    )
    return page.to_dict()


@router.post("/compile/bulk", response_model=Union[WikiBulkCompileResponse, WikiCompileJobResponse])
async def bulk_compile_wiki_pages(
    request: WikiBulkCompileRequest,
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(require_write_access),
):
    normalized_tenant_id = resolve_tenant_id(request.tenant_id, auth)
    document_ids = list(dict.fromkeys(request.document_ids))

    if request.async_compile:
        job = WikiCompileJob(
            tenant_id=normalized_tenant_id,
            status="pending",
            document_ids=document_ids,
            success_count=0,
            failure_count=0,
            result_metadata={},
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
            "wiki.compile_job.create",
            tenant_id=normalized_tenant_id,
            target_id=str(job.id),
            extra={"document_ids": document_ids, "inline_submit": settings.should_submit_wiki_jobs_inline},
        )
        return job.to_dict()

    output = await compile_documents_to_wiki_pages(
        session=session,
        tenant_id=normalized_tenant_id,
        document_ids=document_ids,
    )
    for page in output["pages"]:
        log_audit_event(
            "wiki.page.compile",
            tenant_id=normalized_tenant_id,
            target_id=str(page["id"]),
            extra={"source_document_id": page.get("source_document_id"), "bulk": True},
        )
    return output
