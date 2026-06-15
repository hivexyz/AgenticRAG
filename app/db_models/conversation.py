"""会话与消息模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.database.postgres import Base


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    user_id = Column(String(100), nullable=True, index=True)
    title = Column(String(255), nullable=False, default="新会话")
    status = Column(String(50), nullable=False, default="active")
    latest_summary = Column(Text, nullable=True)
    summary_updated_at = Column(DateTime, nullable=True)
    summary_message_cutoff_id = Column(Integer, nullable=True)
    summary_version = Column(Integer, nullable=False, default=0)
    latest_message_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)

    messages = relationship("ConversationMessage", back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_conversation_sessions_tenant_status", "tenant_id", "status"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "title": self.title,
            "status": self.status,
            "latest_summary": self.latest_summary,
            "summary_updated_at": self.summary_updated_at.isoformat() if self.summary_updated_at else None,
            "summary_message_cutoff_id": self.summary_message_cutoff_id,
            "summary_version": self.summary_version,
            "latest_message_at": self.latest_message_at.isoformat() if self.latest_message_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("conversation_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    role = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    message_type = Column(String(50), nullable=False, default="raw")
    token_count = Column(Integer, nullable=True)
    message_metadata = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("ConversationSession", back_populates="messages")

    __table_args__ = (
        Index("ix_conversation_messages_session_created", "session_id", "created_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "role": self.role,
            "content": self.content,
            "message_type": self.message_type,
            "token_count": self.token_count,
            "metadata": self.message_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
