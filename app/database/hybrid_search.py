"""混合检索工具：向量召回 + PostgreSQL 稀疏召回 + RRF 合并。"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.database.postgres import async_session_maker
from app.db_models import DocumentChunk
from app.utils.logger import logger
from app.utils.tenancy import validate_tenant_id


def _normalize_hit(hit: Dict[str, Any], source: str, rank: int) -> Dict[str, Any]:
    """把不同检索器的结果统一成 chunk/document 字段。"""
    metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
    normalized = dict(metadata)
    normalized.update({k: v for k, v in hit.items() if k != "metadata"})

    text_value = normalized.get("text") or normalized.get("content") or ""
    chunk_id = normalized.get("chunk_id") or normalized.get("id")
    document_id = normalized.get("document_id")
    key = str(chunk_id or f"doc:{document_id}:chunk:{normalized.get('chunk_index')}:rank:{rank}")

    normalized["id"] = normalized.get("id") or chunk_id
    normalized["chunk_id"] = chunk_id
    normalized["document_id"] = document_id
    normalized["text"] = text_value
    normalized["content"] = text_value
    normalized.setdefault("retrieval_sources", [])
    normalized["retrieval_sources"].append(source)
    normalized[f"{source}_rank"] = rank
    normalized["_merge_key"] = key
    return normalized


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[Dict[str, Any]]],
    source_names: Sequence[str],
    *,
    k: int = 60,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """使用 RRF 合并多路有序检索结果。"""
    merged: Dict[str, Dict[str, Any]] = {}

    for source, hits in zip(source_names, ranked_lists):
        for rank, hit in enumerate(hits, 1):
            normalized = _normalize_hit(hit, source, rank)
            key = normalized["_merge_key"]
            score = 1.0 / (k + rank)
            if key not in merged:
                normalized["rrf_score"] = score
                merged[key] = normalized
                continue

            existing = merged[key]
            existing["rrf_score"] = existing.get("rrf_score", 0.0) + score
            existing.setdefault("retrieval_sources", [])
            for item in normalized.get("retrieval_sources", []):
                if item not in existing["retrieval_sources"]:
                    existing["retrieval_sources"].append(item)
            existing[f"{source}_rank"] = rank

    results = sorted(merged.values(), key=lambda item: item.get("rrf_score", 0.0), reverse=True)
    for item in results:
        item.pop("_merge_key", None)
        item["score"] = item.get("rrf_score", item.get("score"))
    return results[:top_k]


def _query_terms(query: str) -> List[str]:
    """抽取用于 LIKE 稀疏检索的关键词。"""
    tokens = re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", query or "")
    seen = set()
    terms = []
    for token in tokens:
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        terms.append(token)
    return terms[:8]


async def sparse_search_chunks(
    query: str,
    *,
    tenant_id: Optional[str] = None,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """基于 document_chunks 的轻量稀疏检索。优先使用 pg_trgm similarity，失败时退化为 ILIKE。"""
    normalized_tenant_id = validate_tenant_id(tenant_id)
    terms = _query_terms(query)
    if not terms:
        return []

    like_clauses = []
    params: Dict[str, Any] = {"tenant_id": normalized_tenant_id, "query": query, "limit": top_k}
    for index, term in enumerate(terms):
        key = f"term_{index}"
        like_clauses.append(f"dc.content ILIKE :{key}")
        params[key] = f"%{term}%"

    where_like = " OR ".join(like_clauses)
    sql = text(
        "SELECT dc.id, dc.document_id, dc.chunk_index, dc.content, dc.page_number, "
        "dc.section_title, dc.chunk_metadata, d.title AS document_title, d.file_type, "
        "similarity(dc.content, :query) AS sparse_score "
        "FROM document_chunks dc JOIN documents d ON d.id = dc.document_id "
        "WHERE dc.tenant_id = :tenant_id AND (" + where_like + ") "
        "ORDER BY sparse_score DESC, dc.id ASC LIMIT :limit"
    )

    async with async_session_maker() as session:
        try:
            result = await session.execute(sql, params)
        except Exception as exc:
            logger.warning(f"pg_trgm 稀疏检索失败，退化为 ORM ILIKE: {exc}")
            statement = (
                select(DocumentChunk)
                .options(selectinload(DocumentChunk.document))
                .where(DocumentChunk.tenant_id == normalized_tenant_id)
                .where(text(" OR ".join([f"content ILIKE :{k}" for k in params if k.startswith('term_')])))
                .limit(top_k)
            )
            fallback_params = {k: v for k, v in params.items() if k.startswith("term_")}
            fallback = await session.execute(statement, fallback_params)
            chunks = fallback.scalars().all()
            return [chunk.to_retrieval_dict() | {"sparse_score": 0.0} for chunk in chunks]

        rows = result.mappings().all()

    hits = []
    for row in rows:
        metadata = row["chunk_metadata"] if isinstance(row["chunk_metadata"], dict) else {}
        hits.append(
            {
                "id": row["id"],
                "chunk_id": row["id"],
                "document_id": row["document_id"],
                "document_title": row["document_title"],
                "file_type": row["file_type"],
                "chunk_index": row["chunk_index"],
                "text": row["content"],
                "content": row["content"],
                "page_number": row["page_number"],
                "section_title": row["section_title"],
                "metadata": metadata,
                "sparse_score": float(row["sparse_score"] or 0.0),
            }
        )
    return hits


async def hydrate_vector_hits(hits: Iterable[Dict[str, Any]], *, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """向量检索结果如果只包含 chunk_id，则回表补齐正文和来源信息。"""
    normalized_tenant_id = validate_tenant_id(tenant_id)
    items = list(hits)
    chunk_ids = [item.get("chunk_id") or (item.get("metadata") or {}).get("chunk_id") for item in items]
    chunk_ids = [int(item) for item in chunk_ids if item]
    if not chunk_ids:
        return items

    async with async_session_maker() as session:
        result = await session.execute(
            select(DocumentChunk)
            .options(selectinload(DocumentChunk.document))
            .where(DocumentChunk.tenant_id == normalized_tenant_id, DocumentChunk.id.in_(chunk_ids))
        )
        chunks = {chunk.id: chunk for chunk in result.scalars().all()}

    hydrated = []
    for item in items:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        chunk_id = item.get("chunk_id") or metadata.get("chunk_id")
        chunk = chunks.get(int(chunk_id)) if chunk_id else None
        if chunk is None:
            hydrated.append(item)
            continue
        merged = chunk.to_retrieval_dict()
        merged.update({k: v for k, v in item.items() if k not in {"metadata"}})
        merged["metadata"] = {**(merged.get("metadata") or {}), **metadata}
        hydrated.append(merged)
    return hydrated
