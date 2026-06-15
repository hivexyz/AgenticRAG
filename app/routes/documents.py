"""
文档相关 API 路由
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_auth_context, resolve_tenant_id
from app.database.postgres import async_session_maker, postgres_manager
from app.database.vector_store import vector_store
from app.db_models import Document, DocumentChunk
from app.models import embedding_manager
from app.tasks import task_runner
from app.observability import log_audit_event
from app.utils.document_parser import DocumentParser
from app.utils.files import build_temp_upload_path, sanitize_filename
from app.utils.logger import logger
from app.utils.text_splitter import TextSplitter

router = APIRouter()

INGESTION_STATUS_PENDING = "pending"
INGESTION_STATUS_PROCESSING = "processing"
INGESTION_STATUS_READY = "ready"
INGESTION_STATUS_FAILED = "failed"

VECTOR_STATUS_NOT_REQUESTED = "not_requested"
VECTOR_STATUS_PENDING = "pending"
VECTOR_STATUS_READY = "ready"
VECTOR_STATUS_FAILED = "failed"

DELETION_STATUS_ACTIVE = "active"
DELETION_STATUS_PENDING = "pending"
DELETION_STATUS_DELETED = "deleted"
DELETION_STATUS_FAILED = "failed"

SPLIT_PRESET_MAP = {
    "smart": {"split_method": "semantic", "chunk_size": 1000, "chunk_overlap": 150, "label": "智能切分"},
    "general": {"split_method": "semantic", "chunk_size": 1000, "chunk_overlap": 150, "label": "通用文档"},
    "faq": {"split_method": "paragraph", "chunk_size": 600, "chunk_overlap": 80, "label": "FAQ"},
    "policy": {"split_method": "paragraph", "chunk_size": 1200, "chunk_overlap": 120, "label": "法规制度"},
    "manual": {"split_method": "semantic", "chunk_size": 900, "chunk_overlap": 120, "label": "产品手册"},
    "report": {"split_method": "semantic", "chunk_size": 1400, "chunk_overlap": 160, "label": "论文报告"},
    "table": {"split_method": "character", "chunk_size": 500, "chunk_overlap": 60, "label": "表格数据"},
}
INGESTION_STAGE_LABELS = {
    "pending": "上传中",
    "processing": "解析/切分中",
    "ready": "入库成功",
    "failed": "入库失败",
}
VECTOR_STAGE_LABELS = {
    "not_requested": "未生成向量索引",
    "pending": "向量化中",
    "ready": "已生成向量索引",
    "failed": "向量化失败",
}


class DocumentCreate(BaseModel):
    tenant_id: Optional[str] = Field(None, description="租户 ID（开发兼容；生产认证开启时忽略）")
    knowledge_base: Optional[str] = Field(None, description="知识库名称")
    title: str = Field(..., description="文档标题")
    content: str = Field(..., description="文档内容")
    author: Optional[str] = Field(None, description="作者")
    metadata: Optional[Dict[str, Any]] = Field(None, description="文档元数据")
    store_vectors: bool = Field(False, description="是否生成并存储向量索引")
    split_preset: str = Field("smart", description="切分预设")
    split_method: Optional[str] = Field(None, description="切分方法（高级设置）")
    chunk_size: Optional[int] = Field(None, description="块大小（高级设置）")
    chunk_overlap: Optional[int] = Field(None, description="块重叠大小（高级设置）")
    async_ingest: bool = Field(True, description="是否异步摄取")


class DocumentResponse(BaseModel):
    id: int
    tenant_id: str
    title: str
    content: str
    author: Optional[str] = None
    file_type: Optional[str] = None
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    chunk_count: Optional[int] = None
    split_method: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    ingestion_status: Optional[str] = None
    ingestion_error: Optional[str] = None
    vector_status: Optional[str] = None
    vector_error: Optional[str] = None
    deletion_status: Optional[str] = None
    deletion_error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    status_display: Optional[str] = None
    vector_status_display: Optional[str] = None
    failure_reason: Optional[str] = None
    retryable_actions: Optional[List[str]] = None
    workflow: Optional[List[Dict[str, Any]]] = None
    knowledge_base: Optional[str] = None
    uploaded_by: Optional[str] = None
    advanced_split_settings: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None






class DocumentChunkListItemResponse(BaseModel):
    chunk_id: int
    chunk_index: int
    page: Optional[int] = None
    paragraph: Optional[int] = None
    section_title: Optional[str] = None
    snippet: str
    token_count: Optional[int] = None

class DocumentFragmentResponse(BaseModel):
    document_id: int
    chunk_id: int
    title: Optional[str] = None
    uploaded_at: Optional[str] = None
    page: Optional[int] = None
    paragraph: Optional[int] = None
    section_title: Optional[str] = None
    snippet: str
    content: str
    previous_context: Optional[str] = None
    next_context: Optional[str] = None

class DocumentListItemResponse(BaseModel):
    status_display: Optional[str] = None
    vector_status_display: Optional[str] = None
    knowledge_base: Optional[str] = None
    uploaded_by: Optional[str] = None
    id: int
    tenant_id: str
    title: str
    author: Optional[str] = None
    file_type: Optional[str] = None
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    chunk_count: Optional[int] = None
    split_method: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    ingestion_status: Optional[str] = None
    ingestion_error: Optional[str] = None
    vector_status: Optional[str] = None
    vector_error: Optional[str] = None
    deletion_status: Optional[str] = None
    deletion_error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None




def _resolve_split_strategy(split_preset: Optional[str], split_method: Optional[str], chunk_size: Optional[int], chunk_overlap: Optional[int]) -> Dict[str, Any]:
    preset_key = (split_preset or "smart").lower()
    preset = SPLIT_PRESET_MAP.get(preset_key)
    if not preset:
        raise HTTPException(status_code=400, detail="split_preset 无效")
    resolved = dict(preset)
    if split_method:
        resolved["split_method"] = split_method
    if chunk_size is not None:
        resolved["chunk_size"] = chunk_size
    if chunk_overlap is not None:
        resolved["chunk_overlap"] = chunk_overlap
    _validate_split_options(resolved["split_method"], resolved["chunk_size"], resolved["chunk_overlap"])
    resolved["split_preset"] = preset_key
    return resolved


def _build_document_workflow_status(document: Document) -> Dict[str, Any]:
    metadata = document._parse_metadata() or {}
    stages = []
    stages.append({"stage": "upload", "label": "上传中", "status": "completed"})
    if document.ingestion_status == INGESTION_STATUS_PENDING:
        stages.extend([
            {"stage": "parse", "label": "解析中", "status": "pending"},
            {"stage": "split", "label": "切分中", "status": "pending"},
        ])
    elif document.ingestion_status == INGESTION_STATUS_PROCESSING:
        stages.extend([
            {"stage": "parse", "label": "解析中", "status": "in_progress"},
            {"stage": "split", "label": "切分中", "status": "pending"},
        ])
    elif document.ingestion_status == INGESTION_STATUS_READY:
        stages.extend([
            {"stage": "parse", "label": "解析中", "status": "completed"},
            {"stage": "split", "label": "切分中", "status": "completed"},
        ])
    else:
        stages.extend([
            {"stage": "parse", "label": "解析中", "status": "failed"},
            {"stage": "split", "label": "切分中", "status": "failed"},
        ])

    vector_stage_status = "skipped" if document.vector_status == VECTOR_STATUS_NOT_REQUESTED else ("completed" if document.vector_status == VECTOR_STATUS_READY else "failed" if document.vector_status == VECTOR_STATUS_FAILED else "in_progress")
    stages.append({"stage": "vectorize", "label": "向量化中", "status": vector_stage_status})
    stages.append({"stage": "done", "label": "入库成功" if document.ingestion_status == INGESTION_STATUS_READY else "入库失败" if document.ingestion_status == INGESTION_STATUS_FAILED else "入库中", "status": "completed" if document.ingestion_status == INGESTION_STATUS_READY else "failed" if document.ingestion_status == INGESTION_STATUS_FAILED else "in_progress"})

    return {
        "status_display": INGESTION_STAGE_LABELS.get(document.ingestion_status, document.ingestion_status),
        "vector_status_display": VECTOR_STAGE_LABELS.get(document.vector_status, document.vector_status),
        "failure_reason": document.ingestion_error or document.vector_error or document.deletion_error,
        "retryable_actions": [action for action, enabled in {
            "reindex": document.ingestion_status == INGESTION_STATUS_READY and document.vector_status == VECTOR_STATUS_FAILED,
            "retry_delete": document.deletion_status == DELETION_STATUS_FAILED,
        }.items() if enabled],
        "workflow": stages,
        "knowledge_base": metadata.get("knowledge_base"),
        "uploaded_by": document.author,
        "advanced_split_settings": {
            "split_preset": metadata.get("split_preset"),
            "split_method": document.split_method,
            "chunk_size": document.chunk_size,
            "chunk_overlap": document.chunk_overlap,
        },
    }


def _document_to_management_payload(document: Document, *, include_content: bool = True) -> Dict[str, Any]:
    payload = document.to_dict(include_content=include_content)
    payload.update(_build_document_workflow_status(document))
    return payload

def _merge_metadata(*items: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for item in items:
        if item:
            merged.update(item)
    return merged


def _parse_metadata_json(metadata: Optional[str]) -> Optional[Dict[str, Any]]:
    if not metadata:
        return None
    try:
        parsed = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="metadata 必须是合法的 JSON 对象") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="metadata 必须是 JSON 对象")
    return parsed


def _validate_split_options(split_method: str, chunk_size: int, chunk_overlap: int) -> None:
    allowed_methods = {"recursive", "character", "token", "semantic", "paragraph", "sentence"}
    if split_method not in allowed_methods:
        raise HTTPException(status_code=400, detail="split_method 无效，必须是 recursive、character、token、semantic、paragraph、sentence 之一")
    if chunk_size <= 0:
        raise HTTPException(status_code=400, detail="chunk_size 必须大于 0")
    if chunk_overlap < 0:
        raise HTTPException(status_code=400, detail="chunk_overlap 不能小于 0")
    if chunk_overlap >= chunk_size and split_method in {"recursive", "character", "token", "semantic"}:
        raise HTTPException(status_code=400, detail="chunk_overlap 必须小于 chunk_size")


async def _persist_document_chunks(*, tenant_id: str, document: Document, chunks: List[Dict[str, Any]], session: AsyncSession) -> None:
    db_chunks: List[DocumentChunk] = []
    for i, chunk in enumerate(chunks):
        metadata = dict(chunk.get("metadata") or {})
        text = chunk["text"]
        db_chunk = DocumentChunk(
            tenant_id=tenant_id,
            document_id=document.id,
            chunk_index=i,
            content=text,
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            token_count=max(1, len(text) // 4),
            page_number=metadata.get("page_number") or metadata.get("page"),
            section_title=metadata.get("section_title") or metadata.get("section"),
            chunk_metadata=metadata,
        )
        session.add(db_chunk)
        db_chunks.append(db_chunk)

    flush = getattr(session, "flush", None)
    if callable(flush):
        await flush()
    else:
        for i, db_chunk in enumerate(db_chunks, 1):
            if getattr(db_chunk, "id", None) is None:
                db_chunk.id = i

    for chunk, db_chunk in zip(chunks, db_chunks):
        chunk["db_chunk"] = db_chunk


async def _store_document_vectors(*, tenant_id: str, document: Document, chunks: List[Dict[str, Any]]):
    texts = [chunk["text"] for chunk in chunks]
    if not texts:
        return
    if len(texts) == 1:
        vectors = [await embedding_manager.create_embedding(texts[0])]
    else:
        vectors = await embedding_manager.create_embeddings(texts)

    chunk_metadata = []
    for i, chunk in enumerate(chunks):
        source_chunk = chunk.get("db_chunk")
        chunk_metadata.append({
            "tenant_id": tenant_id,
            "document_id": document.id,
            "chunk_id": getattr(source_chunk, "id", None),
            "document_title": document.title,
            "file_type": document.file_type,
            "chunk_index": i,
            "text": chunk["text"],
            **chunk.get("metadata", {}),
        })
    await vector_store.insert_vectors(vectors, chunk_metadata, tenant_id=tenant_id)


async def _ingest_document_with_session(session: AsyncSession, document: Document, *, source_type: str, source_payload: Dict[str, Any]) -> None:
    document.ingestion_status = INGESTION_STATUS_PROCESSING
    document.ingestion_error = None
    await session.commit()
    await session.refresh(document)

    if source_type == "text":
        content = source_payload["content"]
        file_type = "txt"
        parse_metadata = source_payload.get("metadata") or {}
    else:
        parse_result = DocumentParser.parse(source_payload["file_path"])
        content = parse_result["content"]
        file_type = parse_result["file_type"]
        parse_metadata = parse_result.get("metadata") or {}

    chunks = TextSplitter.split(
        text=content,
        method=document.split_method or "recursive",
        chunk_size=document.chunk_size or 1000,
        chunk_overlap=document.chunk_overlap or 200,
    )

    merged_metadata = _merge_metadata(document._parse_metadata(), parse_metadata, {
        "tenant_id": document.tenant_id,
        "chunk_count": len(chunks),
    })

    document.content = content
    document.file_type = document.file_type or file_type
    document.chunk_count = len(chunks)
    document.doc_metadata = json.dumps(merged_metadata, ensure_ascii=False)
    await session.commit()
    await session.refresh(document)

    await _persist_document_chunks(tenant_id=document.tenant_id, document=document, chunks=chunks, session=session)
    await session.commit()
    await session.refresh(document)

    if document.vector_status == VECTOR_STATUS_PENDING:
        try:
            await _store_document_vectors(tenant_id=document.tenant_id, document=document, chunks=chunks)
            document.vector_status = VECTOR_STATUS_READY
            document.vector_error = None
        except Exception as exc:
            document.vector_status = VECTOR_STATUS_FAILED
            document.vector_error = str(exc)

    document.ingestion_status = INGESTION_STATUS_READY
    document.ingestion_error = None
    await session.commit()
    await session.refresh(document)


async def _background_ingest_document(document_id: int, *, source_type: str, source_payload: Dict[str, Any]) -> None:
    async with async_session_maker() as session:
        result = await session.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        if document is None:
            logger.warning(f"后台摄取时文档不存在: {document_id}")
            return

        try:
            await _ingest_document_with_session(session, document, source_type=source_type, source_payload=source_payload)
            logger.info(f"后台摄取完成: document_id={document_id}, tenant={document.tenant_id}")
        except Exception as exc:
            document.ingestion_status = INGESTION_STATUS_FAILED
            document.ingestion_error = str(exc)
            await session.commit()
            logger.error(f"后台摄取失败: document_id={document_id}, error={exc}")
        finally:
            if source_type == "file":
                file_path = source_payload.get("file_path")
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except OSError:
                        logger.warning(f"删除异步摄取临时文件失败: {file_path}")




async def _reindex_document_with_session(session: AsyncSession, document: Document) -> Document:
    result = await session.execute(
        select(DocumentChunk).where(
            DocumentChunk.document_id == document.id,
            DocumentChunk.tenant_id == document.tenant_id,
        )
    )
    chunks = result.scalars().all()
    payload = [{"text": chunk.content, "metadata": chunk.chunk_metadata or {}, "db_chunk": chunk} for chunk in chunks]

    document.vector_status = VECTOR_STATUS_PENDING
    document.vector_error = None
    await session.commit()
    await session.refresh(document)

    try:
        await _store_document_vectors(tenant_id=document.tenant_id, document=document, chunks=payload)
        document.vector_status = VECTOR_STATUS_READY
        document.vector_error = None
    except Exception as exc:
        document.vector_status = VECTOR_STATUS_FAILED
        document.vector_error = str(exc)
        await session.commit()
        await session.refresh(document)
        raise

    await session.commit()
    await session.refresh(document)
    return document

def _schedule_document_ingest(document_id: int, *, source_type: str, source_payload: Dict[str, Any]) -> None:
    task_runner.submit(
        f"document-ingest:{document_id}",
        lambda: _background_ingest_document(document_id, source_type=source_type, source_payload=source_payload),
    )


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    metadata: Optional[str] = Form(None),
    split_preset: str = Form("smart"),
    split_method: Optional[str] = Form(None),
    chunk_size: Optional[int] = Form(None),
    chunk_overlap: Optional[int] = Form(None),
    knowledge_base: Optional[str] = Form(None),
    store_vectors: bool = Form(True),
    async_ingest: bool = Form(True),
    tenant_id: Optional[str] = Form(None),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    try:
        normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
        split_strategy = _resolve_split_strategy(split_preset, split_method if split_method else None, chunk_size if chunk_size else None, chunk_overlap if chunk_overlap else None)
        original_file_name = sanitize_filename(file.filename)
        temp_file_path, _ = build_temp_upload_path(tempfile.gettempdir(), original_file_name)
        user_metadata = _parse_metadata_json(metadata)

        async with aiofiles.open(temp_file_path, "wb") as f:
            content = await file.read()
            await f.write(content)

        file_size = len(content)
        doc_title = title or Path(original_file_name).stem
        merged_metadata = _merge_metadata(user_metadata, {
            "tenant_id": normalized_tenant_id,
            "source_file_name": original_file_name,
            "file_size": file_size,
            "temporary_upload": True,
            "knowledge_base": knowledge_base,
            "split_preset": split_strategy["split_preset"],
        })

        db_document = Document(
            tenant_id=normalized_tenant_id,
            title=doc_title,
            content="",
            author=author,
            file_type=Path(original_file_name).suffix.lstrip('.').lower() or None,
            file_path=None,
            file_size=file_size,
            chunk_count=0,
            split_method=split_strategy["split_method"],
            chunk_size=split_strategy["chunk_size"],
            chunk_overlap=split_strategy["chunk_overlap"],
            ingestion_status=INGESTION_STATUS_PENDING if async_ingest else INGESTION_STATUS_PROCESSING,
            ingestion_error=None,
            vector_status=VECTOR_STATUS_PENDING if store_vectors else VECTOR_STATUS_NOT_REQUESTED,
            vector_error=None,
            deletion_status=DELETION_STATUS_ACTIVE,
            deletion_error=None,
            doc_metadata=json.dumps(merged_metadata, ensure_ascii=False),
        )
        session.add(db_document)
        await session.commit()
        await session.refresh(db_document)

        if async_ingest:
            _schedule_document_ingest(db_document.id, source_type="file", source_payload={"file_path": temp_file_path})
            log_audit_event("document.upload.accepted", tenant_id=normalized_tenant_id, target_id=str(db_document.id), result="accepted")
            return DocumentResponse(**_document_to_management_payload(db_document))

        await _ingest_document_with_session(session, db_document, source_type="file", source_payload={"file_path": temp_file_path})
        log_audit_event("document.upload.completed", tenant_id=normalized_tenant_id, target_id=str(db_document.id))
        return DocumentResponse(**_document_to_management_payload(db_document))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文档上传失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=DocumentResponse)
async def create_document(
    document: DocumentCreate,
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    try:
        normalized_tenant_id = resolve_tenant_id(document.tenant_id, auth)
        split_strategy = _resolve_split_strategy(document.split_preset, document.split_method, document.chunk_size, document.chunk_overlap)
        extra_metadata = {"tenant_id": normalized_tenant_id, "split_preset": split_strategy["split_preset"]}
        if document.knowledge_base is not None:
            extra_metadata["knowledge_base"] = document.knowledge_base
        merged_metadata = _merge_metadata(document.metadata, extra_metadata)

        db_document = Document(
            tenant_id=normalized_tenant_id,
            title=document.title,
            content="" if document.async_ingest else document.content,
            author=document.author,
            file_type="txt",
            chunk_count=0,
            split_method=split_strategy["split_method"],
            chunk_size=split_strategy["chunk_size"],
            chunk_overlap=split_strategy["chunk_overlap"],
            ingestion_status=INGESTION_STATUS_PENDING if document.async_ingest else INGESTION_STATUS_PROCESSING,
            ingestion_error=None,
            vector_status=VECTOR_STATUS_PENDING if document.store_vectors else VECTOR_STATUS_NOT_REQUESTED,
            vector_error=None,
            deletion_status=DELETION_STATUS_ACTIVE,
            deletion_error=None,
            doc_metadata=json.dumps(merged_metadata, ensure_ascii=False) if merged_metadata else None,
        )
        session.add(db_document)
        await session.commit()
        await session.refresh(db_document)

        if document.async_ingest:
            _schedule_document_ingest(db_document.id, source_type="text", source_payload={"content": document.content, "metadata": document.metadata or {}})
            log_audit_event("document.create.accepted", tenant_id=normalized_tenant_id, target_id=str(db_document.id), result="accepted")
            return DocumentResponse(**_document_to_management_payload(db_document))

        await _ingest_document_with_session(session, db_document, source_type="text", source_payload={"content": document.content, "metadata": document.metadata or {}})
        log_audit_event("document.create.completed", tenant_id=normalized_tenant_id, target_id=str(db_document.id))
        return DocumentResponse(**_document_to_management_payload(db_document))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))






@router.get("/{document_id}/chunks", response_model=List[DocumentChunkListItemResponse])
async def list_document_chunks(
    document_id: int,
    tenant_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    try:
        normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
        doc_result = await session.execute(select(Document).where(Document.id == document_id, Document.tenant_id == normalized_tenant_id))
        document = doc_result.scalar_one_or_none()
        if not document:
            raise HTTPException(status_code=404, detail="文档不存在")

        chunk_result = await session.execute(
            select(DocumentChunk).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.tenant_id == normalized_tenant_id,
            )
        )
        chunks = list(chunk_result.scalars().all())
        chunks.sort(key=lambda item: item.chunk_index)
        payload = []
        for chunk in chunks:
            metadata = chunk.chunk_metadata if isinstance(chunk.chunk_metadata, dict) else {}
            payload.append(DocumentChunkListItemResponse(
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                page=chunk.page_number,
                paragraph=metadata.get("paragraph") or metadata.get("paragraph_index") or chunk.chunk_index,
                section_title=chunk.section_title,
                snippet=chunk.content[:200],
                token_count=chunk.token_count,
            ))
        return payload
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"获取文档切片列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{document_id}/chunks/{chunk_id}", response_model=DocumentFragmentResponse)
async def get_document_fragment(
    document_id: int,
    chunk_id: int,
    tenant_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    try:
        normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
        doc_result = await session.execute(
            select(Document).where(Document.id == document_id, Document.tenant_id == normalized_tenant_id)
        )
        document = doc_result.scalar_one_or_none()
        if not document:
            raise HTTPException(status_code=404, detail="文档不存在")

        chunk_result = await session.execute(
            select(DocumentChunk).where(
                DocumentChunk.id == chunk_id,
                DocumentChunk.document_id == document_id,
                DocumentChunk.tenant_id == normalized_tenant_id,
            )
        )
        chunk = chunk_result.scalar_one_or_none()
        if not chunk:
            raise HTTPException(status_code=404, detail="文档片段不存在")

        all_chunks_result = await session.execute(
            select(DocumentChunk).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.tenant_id == normalized_tenant_id,
            )
        )
        all_chunks = list(all_chunks_result.scalars().all())
        all_chunks.sort(key=lambda item: item.chunk_index)
        prev_chunk = None
        next_chunk = None
        for index, item in enumerate(all_chunks):
            if item.id == chunk.id:
                if index > 0:
                    prev_chunk = all_chunks[index - 1]
                if index + 1 < len(all_chunks):
                    next_chunk = all_chunks[index + 1]
                break

        return DocumentFragmentResponse(**chunk.to_fragment_dict(document=document, prev_chunk=prev_chunk, next_chunk=next_chunk))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"获取文档片段失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: int, tenant_id: Optional[str] = Query(None), session: AsyncSession = Depends(postgres_manager.get_session), auth=Depends(get_auth_context)):
    try:
        normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
        result = await session.execute(select(Document).where(Document.id == document_id, Document.tenant_id == normalized_tenant_id))
        document = result.scalar_one_or_none()
        if not document:
            raise HTTPException(status_code=404, detail="文档不存在")
        return DocumentResponse(**_document_to_management_payload(document))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"获取文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=List[DocumentListItemResponse])
async def list_documents(
    tenant_id: Optional[str] = Query(None),
    knowledge_base: Optional[str] = Query(None),
    file_type: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="按文档名搜索"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    try:
        normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
        result = await session.execute(select(Document).where(Document.tenant_id == normalized_tenant_id).offset(skip).limit(limit))
        documents = list(result.scalars().all())
        if knowledge_base:
            documents = [doc for doc in documents if (doc._parse_metadata() or {}).get("knowledge_base") == knowledge_base]
        if file_type:
            documents = [doc for doc in documents if (doc.file_type or "").lower() == file_type.lower()]
        if q:
            lowered = q.lower()
            documents = [doc for doc in documents if lowered in (doc.title or "").lower()]
        return [DocumentListItemResponse(**_document_to_management_payload(doc, include_content=False)) for doc in documents]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"获取文档列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))




class BulkDeleteRequest(BaseModel):
    tenant_id: Optional[str] = None
    document_ids: List[int]


@router.get("/management/presets")
async def list_split_presets():
    return {
        "presets": [
            {"key": key, **value} for key, value in SPLIT_PRESET_MAP.items()
        ],
        "default": "smart",
        "vector_storage_label": "生成并存储向量索引",
    }


@router.post("/bulk-delete")
async def bulk_delete_documents(
    request: BulkDeleteRequest,
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    normalized_tenant_id = resolve_tenant_id(request.tenant_id, auth)
    deleted = []
    for document_id in request.document_ids:
        result = await session.execute(select(Document).where(Document.id == document_id, Document.tenant_id == normalized_tenant_id))
        document = result.scalar_one_or_none()
        if not document:
            continue
        deleted.append(document_id)
    return {
        "tenant_id": normalized_tenant_id,
        "requested": request.document_ids,
        "accepted": deleted,
    }


@router.delete("/{document_id}")
async def delete_document(document_id: int, tenant_id: Optional[str] = Query(None), session: AsyncSession = Depends(postgres_manager.get_session), auth=Depends(get_auth_context)):
    try:
        normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
        result = await session.execute(select(Document).where(Document.id == document_id, Document.tenant_id == normalized_tenant_id))
        document = result.scalar_one_or_none()
        if not document:
            raise HTTPException(status_code=404, detail="文档不存在")
        if document.deletion_status == DELETION_STATUS_PENDING:
            raise HTTPException(status_code=409, detail="文档正在删除中，请稍后重试")

        document.deletion_status = DELETION_STATUS_PENDING
        document.deletion_error = None
        await session.commit()
        await session.refresh(document)

        try:
            deleted_vectors = await vector_store.delete_vectors_by_document_id(document_id, tenant_id=normalized_tenant_id)
        except Exception as e:
            document.deletion_status = DELETION_STATUS_FAILED
            document.deletion_error = str(e)
            await session.commit()
            raise HTTPException(status_code=503, detail="删除文档向量失败，请稍后重试") from e

        try:
            await session.delete(document)
            await session.commit()
        except Exception as e:
            document.deletion_status = DELETION_STATUS_FAILED
            document.deletion_error = str(e)
            await session.commit()
            raise HTTPException(status_code=503, detail="删除数据库记录失败，请稍后重试") from e

        log_audit_event("document.delete.completed", tenant_id=normalized_tenant_id, target_id=str(document_id))
        return {"message": "文档删除成功", "tenant_id": normalized_tenant_id, "deleted_document_id": document_id, "deleted_vectors": deleted_vectors}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"删除文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{document_id}/reindex", response_model=DocumentResponse)
async def reindex_document(
    document_id: int,
    tenant_id: Optional[str] = Query(None),
    async_reindex: bool = Query(True, description="是否异步重建索引"),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    try:
        normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
        result = await session.execute(select(Document).where(Document.id == document_id, Document.tenant_id == normalized_tenant_id))
        document = result.scalar_one_or_none()
        if not document:
            raise HTTPException(status_code=404, detail="文档不存在")
        if document.ingestion_status != INGESTION_STATUS_READY:
            raise HTTPException(status_code=409, detail="文档尚未完成摄取，暂不可重建索引")

        if async_reindex:
            document.vector_status = VECTOR_STATUS_PENDING
            document.vector_error = None
            await session.commit()
            await session.refresh(document)
            task_runner.submit(
                f"document-reindex:{document.id}",
                lambda: _background_reindex_document(document.id),
            )
            log_audit_event("document.reindex.accepted", tenant_id=normalized_tenant_id, target_id=str(document.id), result="accepted")
            return DocumentResponse(**_document_to_management_payload(document))

        await _reindex_document_with_session(session, document)
        log_audit_event("document.reindex.completed", tenant_id=normalized_tenant_id, target_id=str(document.id))
        return DocumentResponse(**_document_to_management_payload(document))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"重建文档索引失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _background_reindex_document(document_id: int) -> None:
    async with async_session_maker() as session:
        result = await session.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        if not document:
            logger.warning(f"后台重建索引时文档不存在: {document_id}")
            return
        try:
            await _reindex_document_with_session(session, document)
            logger.info(f"后台重建索引完成: document_id={document_id}")
        except Exception as exc:
            logger.error(f"后台重建索引失败: document_id={document_id}, error={exc}")


@router.post("/{document_id}/retry-delete")
async def retry_delete_document(
    document_id: int,
    tenant_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(postgres_manager.get_session),
    auth=Depends(get_auth_context),
):
    try:
        normalized_tenant_id = resolve_tenant_id(tenant_id, auth)
        result = await session.execute(select(Document).where(Document.id == document_id, Document.tenant_id == normalized_tenant_id))
        document = result.scalar_one_or_none()
        if not document:
            raise HTTPException(status_code=404, detail="文档不存在")
        if document.deletion_status != DELETION_STATUS_FAILED:
            raise HTTPException(status_code=409, detail="当前文档不处于可重试删除状态")

        document.deletion_status = DELETION_STATUS_PENDING
        document.deletion_error = None
        await session.commit()
        await session.refresh(document)

        try:
            deleted_vectors = await vector_store.delete_vectors_by_document_id(document_id, tenant_id=normalized_tenant_id)
        except Exception as exc:
            document.deletion_status = DELETION_STATUS_FAILED
            document.deletion_error = str(exc)
            await session.commit()
            raise HTTPException(status_code=503, detail="删除文档向量失败，请稍后重试") from exc

        try:
            await session.delete(document)
            await session.commit()
        except Exception as exc:
            document.deletion_status = DELETION_STATUS_FAILED
            document.deletion_error = str(exc)
            await session.commit()
            raise HTTPException(status_code=503, detail="删除数据库记录失败，请稍后重试") from exc

        log_audit_event("document.retry_delete.completed", tenant_id=normalized_tenant_id, target_id=str(document_id))
        return {
            "message": "文档删除重试成功",
            "tenant_id": normalized_tenant_id,
            "deleted_document_id": document_id,
            "deleted_vectors": deleted_vectors,
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"重试删除文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
