"""
文档数据库模型
"""
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class Document(Base):
    """文档表模型"""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(255), nullable=False, comment="文档标题")
    content = Column(Text, nullable=False, comment="文档内容")
    author = Column(String(100), nullable=True, comment="作者")
    file_type = Column(String(50), nullable=True, comment="文件类型 (pdf, docx, txt, etc.)")
    file_path = Column(String(500), nullable=True, comment="文件路径")
    file_size = Column(Integer, nullable=True, comment="文件大小（字节）")
    chunk_count = Column(Integer, default=0, nullable=True, comment="切分块数量")
    split_method = Column(String(50), nullable=True, comment="切分方法")
    chunk_size = Column(Integer, nullable=True, comment="块大小")
    chunk_overlap = Column(Integer, nullable=True, comment="块重叠大小")
    doc_metadata = Column(Text, nullable=True, comment="元数据（JSON 格式）")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True, comment="更新时间")

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "author": self.author,
            "file_type": self.file_type,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "chunk_count": self.chunk_count,
            "split_method": self.split_method,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "metadata": self.doc_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
