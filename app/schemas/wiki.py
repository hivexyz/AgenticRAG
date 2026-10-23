"""Typed API contracts for Wiki routes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WikiPageResponse(BaseModel):
    id: int
    tenant_id: str
    knowledge_base: Optional[str] = None
    slug: str
    title: str
    summary: Optional[str] = None
    content: str
    source_document_id: Optional[int] = None
    source_chunk_ids: List[int] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class WikiTopicIndexPageResponse(BaseModel):
    id: int
    title: str
    summary: Optional[str] = None
    updated_at: Optional[str] = None


class WikiTopicIndexItemResponse(BaseModel):
    knowledge_base: str
    page_count: int
    pages: List[WikiTopicIndexPageResponse]


class WikiTopicIndexResponse(BaseModel):
    tenant_id: str
    knowledge_bases: List[WikiTopicIndexItemResponse]


class WikiPageRevisionResponse(BaseModel):
    id: int
    tenant_id: str
    page_id: int
    action: str
    title: str
    summary: Optional[str] = None
    content: str
    knowledge_base: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class WikiCompileFailureResponse(BaseModel):
    document_id: int
    error: str


class WikiBulkCompileResponse(BaseModel):
    success_count: int
    failure_count: int
    pages: List[WikiPageResponse]
    failures: List[WikiCompileFailureResponse]


class WikiCompileJobResponse(BaseModel):
    id: int
    tenant_id: str
    status: str
    document_ids: List[int]
    success_count: int
    failure_count: int
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    locked_by: Optional[str] = None
    locked_at: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    next_run_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class WikiPageLinkResponse(BaseModel):
    id: int
    tenant_id: str
    source_page_id: int
    target_page_id: int
    source_title: Optional[str] = None
    target_title: Optional[str] = None
    link_type: str
    evidence: Optional[str] = None
    created_at: Optional[str] = None


class WikiPageLinksResponse(BaseModel):
    page_id: int
    outgoing: List[WikiPageLinkResponse]
    incoming: List[WikiPageLinkResponse]


class WikiLinksRebuildResponse(BaseModel):
    tenant_id: str
    knowledge_base: Optional[str] = None
    page_count: int
    link_count: int


class WikiDeleteResponse(BaseModel):
    deleted: bool
    page_id: int
