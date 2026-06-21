"""用户反馈与知识分析模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.database.postgres import Base


class AnswerFeedback(Base):
    __tablename__ = "answer_feedback"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("conversation_sessions.id", ondelete="CASCADE"), nullable=True, index=True)
    message_id = Column(Integer, ForeignKey("conversation_messages.id", ondelete="CASCADE"), nullable=True, index=True)
    feedback_type = Column(String(50), nullable=False, index=True)
    rating = Column(String(20), nullable=False, index=True)
    reason = Column(String(100), nullable=True, index=True)
    comment = Column(Text, nullable=True)
    corrected_answer = Column(Text, nullable=True)
    feedback_metadata = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_answer_feedback_tenant_created", "tenant_id", "created_at"),
        Index("ix_answer_feedback_tenant_reason", "tenant_id", "reason"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "feedback_type": self.feedback_type,
            "rating": self.rating,
            "reason": self.reason,
            "comment": self.comment,
            "corrected_answer": self.corrected_answer,
            "metadata": self.feedback_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
