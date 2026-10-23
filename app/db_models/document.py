"""文档数据库模型。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.database.postgres import Base


class Document(Base):
    """文档表模型"""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tenant_id = Column(String(100), nullable=False, default="default", index=True, comment="租户 ID")
    title = Column(String(255), nullable=False, comment="文档标题")
    content = Column(Text, nullable=False, comment="文档内容")
    author = Column(String(100), nullable=True, comment="作者")
    file_type = Column(String(50), nullable=True, comment="文件类型 (pdf, docx, txt, etc.)")
    file_path = Column(String(500), nullable=True, comment="文件路径")
    file_size = Column(Integer, nullable=True, comment="文件大小（字节）")
    content_hash = Column(String(64), nullable=True, index=True, comment="源内容 SHA-256")
    chunk_count = Column(Integer, default=0, nullable=True, comment="切分块数量")
    split_method = Column(String(50), nullable=True, comment="切分方法")
    chunk_size = Column(Integer, nullable=True, comment="块大小")
    chunk_overlap = Column(Integer, nullable=True, comment="块重叠大小")
    ingestion_status = Column(String(50), nullable=False, default="ready", comment="摄取状态")
    ingestion_error = Column(Text, nullable=True, comment="摄取错误信息")
    vector_status = Column(String(50), nullable=False, default="not_requested", comment="向量索引状态")
    vector_error = Column(Text, nullable=True, comment="向量索引错误信息")
    deletion_status = Column(String(50), nullable=False, default="active", comment="删除状态")
    deletion_error = Column(Text, nullable=True, comment="删除错误信息")
    doc_metadata = Column(Text, nullable=True, comment="元数据（JSON 格式）")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True, comment="更新时间")

    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

    def _parse_metadata(self) -> Optional[Dict[str, Any]]:
        """将持久化的 metadata 统一解析为 dict。"""
        if not self.doc_metadata:
            return None

        try:
            parsed = json.loads(self.doc_metadata)
        except json.JSONDecodeError:
            return {"raw": self.doc_metadata}

        if isinstance(parsed, dict):
            return parsed

        return {"value": parsed}

    def to_dict(self, *, include_content: bool = True):
        """转换为字典。"""
        metadata = self._parse_metadata()

        data = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "title": self.title,
            "author": self.author,
            "file_type": self.file_type,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "content_hash": self.content_hash,
            "chunk_count": self.chunk_count,
            "split_method": self.split_method,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "ingestion_status": self.ingestion_status,
            "ingestion_error": self.ingestion_error,
            "vector_status": self.vector_status,
            "vector_error": self.vector_error,
            "deletion_status": self.deletion_status,
            "deletion_error": self.deletion_error,
            "metadata": metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_content:
            data["content"] = self.content
        return data


class DocumentChunk(Base):
    """文档切片表，用于回表、引用和稀疏/混合检索。"""

    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tenant_id = Column(String(100), nullable=False, index=True, comment="租户 ID")
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False, comment="文档内切片序号")
    content = Column(Text, nullable=False, comment="切片正文")
    content_hash = Column(String(64), nullable=True, index=True, comment="切片内容哈希")
    token_count = Column(Integer, nullable=True, comment="估算 token 数")
    page_number = Column(Integer, nullable=True, comment="页码")
    section_title = Column(String(500), nullable=True, comment="章节标题")
    chunk_metadata = Column(JSONB, nullable=True, comment="切片元数据")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True, comment="更新时间")

    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("ix_document_chunks_tenant_document", "tenant_id", "document_id"),
        Index("ix_document_chunks_tenant_document_chunk", "tenant_id", "document_id", "chunk_index"),
    )

    def to_retrieval_dict(self, document: Optional[Document] = None) -> Dict[str, Any]:
        """转换为检索结果格式。"""
        metadata = self.chunk_metadata if isinstance(self.chunk_metadata, dict) else {}
        owner = document or self.document
        document_metadata = {}
        if owner is not None and hasattr(owner, "_parse_metadata"):
            document_metadata = owner._parse_metadata() or {}
        merged_metadata = {**document_metadata, **metadata}
        if document_metadata:
            merged_metadata["document_metadata"] = document_metadata
        return {
            "id": self.id,
            "chunk_id": self.id,
            "tenant_id": self.tenant_id,
            "document_id": self.document_id,
            "document_title": getattr(owner, "title", None),
            "file_type": getattr(owner, "file_type", None),
            "uploaded_at": getattr(owner, "created_at", None).isoformat() if getattr(owner, "created_at", None) else None,
            "chunk_index": self.chunk_index,
            "text": self.content,
            "content": self.content,
            "page_number": self.page_number,
            "section_title": self.section_title,
            "metadata": merged_metadata,
            "knowledge_base": merged_metadata.get("knowledge_base"),
        }

    def to_fragment_dict(self, document: Optional[Document] = None, *, prev_chunk: Optional["DocumentChunk"] = None, next_chunk: Optional["DocumentChunk"] = None) -> Dict[str, Any]:
        owner = document or self.document
        metadata = self.chunk_metadata if isinstance(self.chunk_metadata, dict) else {}
        return {
            "document_id": self.document_id,
            "chunk_id": self.id,
            "title": getattr(owner, "title", None),
            "uploaded_at": getattr(owner, "created_at", None).isoformat() if getattr(owner, "created_at", None) else None,
            "page": self.page_number,
            "paragraph": metadata.get("paragraph") or metadata.get("paragraph_index") or self.chunk_index,
            "section_title": self.section_title,
            "snippet": self.content[:300],
            "content": self.content,
            "previous_context": prev_chunk.content if prev_chunk else None,
            "next_context": next_chunk.content if next_chunk else None,
        }
