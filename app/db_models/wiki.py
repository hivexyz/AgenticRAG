"""Wiki 页面模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.database.postgres import Base


class WikiPage(Base):
    """编译后的 wiki 页面。"""

    __tablename__ = "wiki_pages"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    knowledge_base = Column(String(255), nullable=True, index=True)
    slug = Column(String(255), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    source_document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    source_chunk_ids = Column(JSONB, nullable=True)
    page_metadata = Column(JSONB, nullable=True)
    status = Column(String(50), nullable=False, default="ready")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)

    source_document = relationship("Document")

    __table_args__ = (
        Index("ix_wiki_pages_tenant_slug", "tenant_id", "slug"),
        Index("ix_wiki_pages_tenant_kb_status", "tenant_id", "knowledge_base", "status"),
    )

    def to_dict(self) -> Dict[str, Any]:
        metadata = self.page_metadata if isinstance(self.page_metadata, dict) else {}
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "knowledge_base": self.knowledge_base,
            "slug": self.slug,
            "title": self.title,
            "summary": self.summary,
            "content": self.content,
            "source_document_id": self.source_document_id,
            "source_chunk_ids": self.source_chunk_ids or [],
            "metadata": metadata,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_retrieval_dict(self) -> Dict[str, Any]:
        metadata = self.page_metadata if isinstance(self.page_metadata, dict) else {}
        return {
            "id": f"wiki:{self.id}",
            "wiki_page_id": self.id,
            "tenant_id": self.tenant_id,
            "document_id": self.source_document_id,
            "chunk_id": None,
            "document_title": self.title,
            "title": self.title,
            "text": self.content,
            "content": self.content,
            "summary": self.summary,
            "section_title": metadata.get("section_title") or "Wiki 页面",
            "page_number": None,
            "source_type": "wiki_page",
            "knowledge_base": self.knowledge_base,
            "metadata": {
                **metadata,
                "wiki_page_id": self.id,
                "wiki_slug": self.slug,
                "source_type": "wiki_page",
                "knowledge_base": self.knowledge_base,
                "source_document_id": self.source_document_id,
                "source_chunk_ids": self.source_chunk_ids or [],
            },
        }


class WikiPageRevision(Base):
    """Wiki 页面修订快照。"""

    __tablename__ = "wiki_page_revisions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    page_id = Column(Integer, ForeignKey("wiki_pages.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    knowledge_base = Column(String(255), nullable=True)
    revision_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    page = relationship("WikiPage")

    __table_args__ = (
        Index("ix_wiki_page_revisions_tenant_page", "tenant_id", "page_id"),
        Index("ix_wiki_page_revisions_page_created", "page_id", "created_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        metadata = self.revision_metadata if isinstance(self.revision_metadata, dict) else {}
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "page_id": self.page_id,
            "action": self.action,
            "title": self.title,
            "summary": self.summary,
            "content": self.content,
            "knowledge_base": self.knowledge_base,
            "metadata": metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class WikiCompileJob(Base):
    """Wiki 编译任务。"""

    __tablename__ = "wiki_compile_jobs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="pending")
    document_ids = Column(JSONB, nullable=False)
    success_count = Column(Integer, nullable=False, default=0)
    failure_count = Column(Integer, nullable=False, default=0)
    result_metadata = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    locked_by = Column(String(100), nullable=True, index=True)
    locked_at = Column(DateTime, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    next_run_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)

    __table_args__ = (
        Index("ix_wiki_compile_jobs_tenant_status", "tenant_id", "status"),
        Index("ix_wiki_compile_jobs_tenant_created", "tenant_id", "created_at"),
        Index("ix_wiki_compile_jobs_tenant_status_next_run", "tenant_id", "status", "next_run_at"),
        Index("ix_wiki_compile_jobs_locked", "status", "locked_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        metadata = self.result_metadata if isinstance(self.result_metadata, dict) else {}
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "status": self.status,
            "document_ids": self.document_ids or [],
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "metadata": metadata,
            "error": self.error,
            "locked_by": self.locked_by,
            "locked_at": self.locked_at.isoformat() if self.locked_at else None,
            "retry_count": self.retry_count or 0,
            "max_retries": self.max_retries or 3,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class WikiPageLink(Base):
    """Wiki 页面之间的确定性链接。"""

    __tablename__ = "wiki_page_links"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    source_page_id = Column(Integer, ForeignKey("wiki_pages.id", ondelete="CASCADE"), nullable=False, index=True)
    target_page_id = Column(Integer, ForeignKey("wiki_pages.id", ondelete="CASCADE"), nullable=False, index=True)
    link_type = Column(String(50), nullable=False, default="title_mention")
    evidence = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    source_page = relationship("WikiPage", foreign_keys=[source_page_id])
    target_page = relationship("WikiPage", foreign_keys=[target_page_id])

    __table_args__ = (
        Index("ix_wiki_page_links_tenant_source", "tenant_id", "source_page_id"),
        Index("ix_wiki_page_links_tenant_target", "tenant_id", "target_page_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        target = self.target_page
        source = self.source_page
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "source_page_id": self.source_page_id,
            "target_page_id": self.target_page_id,
            "source_title": getattr(source, "title", None),
            "target_title": getattr(target, "title", None),
            "link_type": self.link_type,
            "evidence": self.evidence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
