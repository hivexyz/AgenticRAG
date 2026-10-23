"""Wiki 页面编译与检索服务。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.postgres import async_session_maker
from app.db_models import Document, DocumentChunk, WikiCompileJob, WikiPage, WikiPageLink, WikiPageRevision
from app.models import llm_manager
from app.utils.logger import logger


def _slugify(text: str) -> str:
    normalized = re.sub(r"\s+", "-", (text or "").strip().lower())
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff\\-_]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized or "wiki-page"


def _plain_fallback_summary(content: str, *, max_lines: int = 6, max_chars: int = 800) -> str:
    lines = []
    for raw in (content or "").splitlines():
        item = raw.strip().lstrip("-").lstrip("*").strip()
        if not item:
            continue
        lines.append(item)
        if len(lines) >= max_lines:
            break
    if not lines:
        return (content or "").strip()[:max_chars]
    return "\n".join(f"- {line[:120]}" for line in lines)[:max_chars]


def add_wiki_page_revision(*, session: AsyncSession, page: WikiPage, action: str, metadata: Optional[Dict[str, Any]] = None) -> WikiPageRevision:
    revision = WikiPageRevision(
        tenant_id=page.tenant_id,
        page_id=page.id,
        action=action,
        title=page.title,
        summary=page.summary,
        content=page.content,
        knowledge_base=page.knowledge_base,
        revision_metadata=metadata or {},
    )
    session.add(revision)
    return revision


def build_revision_diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """Build a compact field-level diff for wiki revision metadata."""
    fields = []
    changed: Dict[str, Dict[str, Any]] = {}
    for field in ("title", "summary", "content", "knowledge_base"):
        if before.get(field) == after.get(field):
            continue
        fields.append(field)
        changed[field] = {
            "before": before.get(field),
            "after": after.get(field),
        }
    return {
        "fields": fields,
        "changed": changed,
    }


async def compile_wiki_page_content(*, title: str, content: str, chunk_snippets: List[str]) -> Dict[str, str]:
    """把原始文档编译成 wiki 风格页面。"""
    trimmed_content = (content or "").strip()
    snippet_block = "\n\n".join(
        f"[片段 {index + 1}]\n{snippet[:500]}"
        for index, snippet in enumerate(chunk_snippets[:6])
        if snippet.strip()
    )
    prompt = f"""你是知识编译助手。请把输入文档整理成一页适合长期复用的 wiki 页面。

页面标题：{title}

原文摘要片段：
{snippet_block or trimmed_content[:1200]}

原文全文（可能被截断）：
{trimmed_content[:5000]}

输出要求：
1. 使用中文
2. 先给出 3-6 条要点摘要
3. 再给出结构化正文，包含“主题概述 / 关键信息 / 使用建议”三个小节
4. 不要编造原文没有的信息
5. 只输出 JSON 对象，字段为 summary 和 content
"""
    try:
        response = await llm_manager.chat_completion(
            messages=[
                {"role": "system", "content": "你是严谨的企业知识编译助手。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1200,
        )
        raw = response["choices"][0]["message"]["content"].strip()
        import json

        parsed = json.loads(raw)
        if isinstance(parsed, dict) and parsed.get("content"):
            summary = str(parsed.get("summary") or "").strip()
            compiled_content = str(parsed.get("content") or "").strip()
            if compiled_content:
                return {
                    "summary": summary or _plain_fallback_summary(compiled_content, max_lines=5, max_chars=500),
                    "content": compiled_content,
                }
    except Exception as exc:
        logger.warning(f"LLM 编译 wiki 页面失败，回退为规则摘要: {exc}")

    fallback_summary = _plain_fallback_summary(trimmed_content)
    fallback_content = "\n\n".join(
        [
            "## 主题概述",
            fallback_summary or "暂无概述。",
            "## 关键信息",
            (trimmed_content[:2500] or "暂无内容。"),
            "## 使用建议",
            "建议结合原始文档片段继续核对细节，并在后续补充更细粒度的主题页。",
        ]
    )
    return {
        "summary": fallback_summary,
        "content": fallback_content,
    }


async def upsert_wiki_page_from_document(
    *,
    session: AsyncSession,
    tenant_id: str,
    document: Document,
    chunk_limit: int = 8,
) -> WikiPage:
    """基于文档生成或更新一页 wiki 页面。"""
    chunk_result = await session.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document.id, DocumentChunk.tenant_id == tenant_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .limit(chunk_limit)
    )
    chunks = chunk_result.scalars().all()
    chunk_ids = [chunk.id for chunk in chunks]
    chunk_snippets = [chunk.content[:800] for chunk in chunks]

    compiled = await compile_wiki_page_content(
        title=document.title,
        content=document.content,
        chunk_snippets=chunk_snippets,
    )

    metadata = document._parse_metadata() or {}
    slug = _slugify(document.title)
    knowledge_base = metadata.get("knowledge_base")

    existing_result = await session.execute(
        select(WikiPage).where(
            WikiPage.tenant_id == tenant_id,
            WikiPage.source_document_id == document.id,
        )
    )
    page = existing_result.scalar_one_or_none()

    page_metadata = {
        "source_document_title": document.title,
        "knowledge_base": knowledge_base,
        "source_file_type": document.file_type,
        "source_chunk_count": document.chunk_count,
    }

    if page is None:
        page = WikiPage(
            tenant_id=tenant_id,
            knowledge_base=knowledge_base,
            slug=slug,
            title=document.title,
            summary=compiled["summary"],
            content=compiled["content"],
            source_document_id=document.id,
            source_chunk_ids=chunk_ids,
            page_metadata=page_metadata,
            status="ready",
        )
        session.add(page)
    else:
        page.knowledge_base = knowledge_base
        page.slug = slug
        page.title = document.title
        page.summary = compiled["summary"]
        page.content = compiled["content"]
        page.source_chunk_ids = chunk_ids
        page.page_metadata = page_metadata
        page.status = "ready"

    await session.commit()
    await session.refresh(page)
    add_wiki_page_revision(
        session=session,
        page=page,
        action="compile",
        metadata={"source_document_id": document.id, "source_chunk_ids": chunk_ids},
    )
    await session.commit()
    return page


async def compile_documents_to_wiki_pages(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_ids: List[int],
) -> Dict[str, Any]:
    successes = []
    failures = []

    for document_id in document_ids:
        try:
            result = await session.execute(
                select(Document).where(
                    Document.id == document_id,
                    Document.tenant_id == tenant_id,
                )
            )
            document = result.scalar_one_or_none()
            if document is None:
                failures.append({"document_id": document_id, "error": "源文档不存在"})
                continue

            page = await upsert_wiki_page_from_document(
                session=session,
                tenant_id=tenant_id,
                document=document,
            )
        except Exception as exc:
            await session.rollback()
            failures.append({"document_id": document_id, "error": str(exc)})
            continue

        successes.append(page.to_dict())

    return {
        "success_count": len(successes),
        "failure_count": len(failures),
        "pages": successes,
        "failures": failures,
    }


async def _pages_for_source_document(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_id: int,
) -> List[WikiPage]:
    result = await session.execute(
        select(WikiPage).where(
            WikiPage.tenant_id == tenant_id,
            WikiPage.source_document_id == document_id,
        )
    )
    return [
        page for page in result.scalars().all()
        if hasattr(page, "source_document_id") and hasattr(page, "status")
    ]


async def mark_wiki_pages_stale_for_document(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_id: int,
) -> List[int]:
    """Mark wiki pages compiled from a changed source document as stale."""
    pages = await _pages_for_source_document(session=session, tenant_id=tenant_id, document_id=document_id)
    stale_page_ids: List[int] = []
    for page in pages:
        if page.status != "ready":
            continue
        metadata = page.page_metadata if isinstance(page.page_metadata, dict) else {}
        page.page_metadata = {
            **metadata,
            "stale_reason": "source_document_updated",
            "stale_at": _utcnow().isoformat(),
        }
        page.status = "stale"
        stale_page_ids.append(page.id)
        add_wiki_page_revision(
            session=session,
            page=page,
            action="stale",
            metadata={"source_document_id": document_id, "reason": "source_document_updated"},
        )
        await clear_wiki_page_links(session=session, tenant_id=tenant_id, page_id=page.id)
    if stale_page_ids:
        await session.commit()
    return stale_page_ids


async def mark_wiki_pages_deleted_for_document(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_id: int,
) -> List[int]:
    """Soft-delete wiki pages whose source document is being deleted."""
    pages = await _pages_for_source_document(session=session, tenant_id=tenant_id, document_id=document_id)
    deleted_page_ids: List[int] = []
    for page in pages:
        if page.status == "deleted":
            continue
        metadata = page.page_metadata if isinstance(page.page_metadata, dict) else {}
        page.page_metadata = {
            **metadata,
            "deleted_reason": "source_document_deleted",
            "deleted_at": _utcnow().isoformat(),
        }
        page.status = "deleted"
        deleted_page_ids.append(page.id)
        add_wiki_page_revision(
            session=session,
            page=page,
            action="delete",
            metadata={"source_document_id": document_id, "reason": "source_document_deleted"},
        )
        await clear_wiki_page_links(session=session, tenant_id=tenant_id, page_id=page.id)
    if deleted_page_ids:
        await session.commit()
    return deleted_page_ids


def _utcnow() -> datetime:
    return datetime.utcnow()


def _next_retry_at(retry_count: int) -> datetime:
    delay_seconds = max(settings.WIKI_COMPILE_JOB_RETRY_BACKOFF_SECONDS, 1) * max(retry_count, 1)
    return _utcnow() + timedelta(seconds=delay_seconds)


async def _mark_wiki_compile_job_failed(session: AsyncSession, job_id: int, error: str) -> None:
    result = await session.execute(select(WikiCompileJob).where(WikiCompileJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        logger.warning(f"Wiki 编译任务不存在，无法记录失败: {job_id}")
        return

    retry_count = int(job.retry_count or 0) + 1
    max_retries = int(job.max_retries or settings.WIKI_COMPILE_JOB_MAX_RETRIES)
    job.retry_count = retry_count
    job.error = error
    job.locked_by = None
    job.locked_at = None
    job.updated_at = _utcnow()
    if retry_count <= max_retries:
        job.status = "pending"
        job.next_run_at = _next_retry_at(retry_count)
    else:
        job.status = "failed"
        job.next_run_at = None


async def run_wiki_compile_job(job_id: int, *, worker_id: Optional[str] = None) -> None:
    worker_id = worker_id or f"wiki-worker-{uuid4().hex[:12]}"
    async with async_session_maker() as session:
        now = _utcnow()
        stale_before = now - timedelta(seconds=max(settings.WIKI_COMPILE_JOB_STALE_SECONDS, 1))
        claim = await session.execute(
            update(WikiCompileJob)
            .where(
                WikiCompileJob.id == job_id,
                or_(
                    and_(
                        WikiCompileJob.status == "pending",
                        or_(WikiCompileJob.next_run_at.is_(None), WikiCompileJob.next_run_at <= now),
                    ),
                    and_(
                        WikiCompileJob.status == "processing",
                        or_(WikiCompileJob.locked_at.is_(None), WikiCompileJob.locked_at <= stale_before),
                    ),
                ),
            )
            .values(
                status="processing",
                error=None,
                locked_by=worker_id,
                locked_at=now,
                updated_at=now,
            )
            .returning(WikiCompileJob.id)
        )
        if claim.scalar_one_or_none() is None:
            logger.info(f"Wiki 编译任务无需执行或已被其它 worker 认领: {job_id}")
            await session.rollback()
            return
        await session.commit()

        result = await session.execute(select(WikiCompileJob).where(WikiCompileJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            logger.warning(f"Wiki 编译任务不存在: {job_id}")
            return

        try:
            output = await compile_documents_to_wiki_pages(
                session=session,
                tenant_id=job.tenant_id,
                document_ids=list(job.document_ids or []),
            )
            job.status = "completed" if output["failure_count"] == 0 else "partial_failed"
            job.success_count = output["success_count"]
            job.failure_count = output["failure_count"]
            job.result_metadata = {
                "pages": output["pages"],
                "failures": output["failures"],
            }
            job.error = None
            job.locked_by = None
            job.locked_at = None
            job.next_run_at = None
            job.updated_at = _utcnow()
        except Exception as exc:
            await session.rollback()
            await _mark_wiki_compile_job_failed(session, job_id, str(exc))
            logger.error(f"Wiki 编译任务失败 job_id={job_id}: {exc}")
        await session.commit()


async def recover_wiki_compile_jobs(submit_job) -> Dict[str, Any]:
    async with async_session_maker() as session:
        now = _utcnow()
        stale_before = now - timedelta(seconds=max(settings.WIKI_COMPILE_JOB_STALE_SECONDS, 1))
        result = await session.execute(
            select(WikiCompileJob)
            .where(
                or_(
                    and_(
                        WikiCompileJob.status == "pending",
                        or_(WikiCompileJob.next_run_at.is_(None), WikiCompileJob.next_run_at <= now),
                    ),
                    and_(
                        WikiCompileJob.status == "processing",
                        or_(WikiCompileJob.locked_at.is_(None), WikiCompileJob.locked_at <= stale_before),
                    ),
                )
            )
            .order_by(WikiCompileJob.created_at.asc(), WikiCompileJob.id.asc())
        )
        jobs = list(result.scalars().all())
        job_ids = [job.id for job in jobs]
        for job in jobs:
            job.status = "pending"
            job.error = None
            job.locked_by = None
            job.locked_at = None
            if getattr(job, "max_retries", None) is None:
                job.max_retries = settings.WIKI_COMPILE_JOB_MAX_RETRIES
        await session.commit()
        for job_id in job_ids:
            submit_job(job_id)
        return {"recovered_count": len(job_ids), "job_ids": job_ids}


def _link_evidence(text: str, title: str) -> str:
    index = text.find(title)
    if index < 0:
        return ""
    start = max(index - 80, 0)
    end = min(index + len(title) + 80, len(text))
    return text[start:end].strip()


async def rebuild_wiki_page_links(*, session: AsyncSession, tenant_id: str, knowledge_base: Optional[str] = None) -> Dict[str, Any]:
    statement = select(WikiPage).where(
        WikiPage.tenant_id == tenant_id,
        WikiPage.status == "ready",
    )
    if knowledge_base:
        statement = statement.where(WikiPage.knowledge_base == knowledge_base)
    result = await session.execute(statement)
    pages = list(result.scalars().all())

    delete_statement = delete(WikiPageLink).where(WikiPageLink.tenant_id == tenant_id)
    if knowledge_base:
        page_ids = [page.id for page in pages]
        if not page_ids:
            return {
                "tenant_id": tenant_id,
                "knowledge_base": knowledge_base,
                "page_count": 0,
                "link_count": 0,
            }
        delete_statement = delete_statement.where(WikiPageLink.source_page_id.in_(page_ids))
    await session.execute(delete_statement)

    created = 0
    for source in pages:
        haystack = f"{source.summary or ''}\n{source.content or ''}"
        for target in pages:
            if source.id == target.id or not target.title:
                continue
            if target.title not in haystack:
                continue
            session.add(WikiPageLink(
                tenant_id=tenant_id,
                source_page_id=source.id,
                target_page_id=target.id,
                link_type="title_mention",
                evidence=_link_evidence(haystack, target.title),
            ))
            created += 1

    await session.commit()
    return {
        "tenant_id": tenant_id,
        "knowledge_base": knowledge_base,
        "page_count": len(pages),
        "link_count": created,
    }


async def rebuild_wiki_page_links_for_page(*, session: AsyncSession, tenant_id: str, page_id: int) -> Dict[str, Any]:
    """Incrementally rebuild links touching one page."""
    result = await session.execute(
        select(WikiPage).where(
            WikiPage.tenant_id == tenant_id,
            WikiPage.status == "ready",
        )
    )
    pages = list(result.scalars().all())
    page_by_id = {page.id: page for page in pages}
    source = page_by_id.get(page_id)
    if source is None:
        await clear_wiki_page_links(session=session, tenant_id=tenant_id, page_id=page_id)
        await session.commit()
        return {
            "tenant_id": tenant_id,
            "page_id": page_id,
            "page_count": len(pages),
            "link_count": 0,
        }

    await clear_wiki_page_links(session=session, tenant_id=tenant_id, page_id=page_id)
    created = 0

    source_haystack = f"{source.summary or ''}\n{source.content or ''}"
    for target in pages:
        if source.id == target.id or not target.title:
            continue
        if target.title in source_haystack:
            session.add(WikiPageLink(
                tenant_id=tenant_id,
                source_page_id=source.id,
                target_page_id=target.id,
                link_type="title_mention",
                evidence=_link_evidence(source_haystack, target.title),
            ))
            created += 1

    if source.title:
        for candidate in pages:
            if candidate.id == source.id:
                continue
            haystack = f"{candidate.summary or ''}\n{candidate.content or ''}"
            if source.title not in haystack:
                continue
            session.add(WikiPageLink(
                tenant_id=tenant_id,
                source_page_id=candidate.id,
                target_page_id=source.id,
                link_type="title_mention",
                evidence=_link_evidence(haystack, source.title),
            ))
            created += 1

    await session.commit()
    return {
        "tenant_id": tenant_id,
        "page_id": page_id,
        "page_count": len(pages),
        "link_count": created,
    }


async def clear_wiki_page_links(*, session: AsyncSession, tenant_id: str, page_id: int) -> None:
    await session.execute(
        delete(WikiPageLink).where(
            WikiPageLink.tenant_id == tenant_id,
            or_(
                WikiPageLink.source_page_id == page_id,
                WikiPageLink.target_page_id == page_id,
            ),
        )
    )


async def search_wiki_pages(
    *,
    session: AsyncSession,
    tenant_id: str,
    query: str,
    knowledge_base: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """基于数据库 ILIKE 的轻量 wiki 页面检索。"""
    terms = [item for item in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", query or "")[:8] if item]
    statement = select(WikiPage).where(
        WikiPage.tenant_id == tenant_id,
        WikiPage.status == "ready",
    )
    if knowledge_base:
        statement = statement.where(WikiPage.knowledge_base == knowledge_base)
    if terms:
        clauses = []
        for term in terms:
            like = f"%{term}%"
            clauses.extend([
                WikiPage.title.ilike(like),
                WikiPage.summary.ilike(like),
                WikiPage.content.ilike(like),
            ])
        statement = statement.where(or_(*clauses))

    result = await session.execute(statement.order_by(WikiPage.updated_at.desc(), WikiPage.id.desc()).limit(max(top_k * 4, top_k)))
    items = result.scalars().all()
    if not terms:
        return [item.to_retrieval_dict() for item in items[:top_k]]

    scored: List[Dict[str, Any]] = []
    for item in items:
        haystack = f"{item.title}\n{item.summary or ''}\n{item.content}"
        score = sum(1 for term in terms if term.lower() in haystack.lower())
        if score <= 0:
            continue
        payload = item.to_retrieval_dict()
        payload["wiki_score"] = float(score)
        payload["score"] = float(score)
        scored.append(payload)

    scored.sort(key=lambda current: current.get("wiki_score", 0.0), reverse=True)
    return scored[:top_k]
