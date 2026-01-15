"""
文档相关 API 路由
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from pydantic import BaseModel, Field
from pathlib import Path
import json
import aiofiles
from app.database.postgres import postgres_manager
from app.database.milvus import milvus_manager
from app.db_models import Document
from sqlalchemy import select
from app.utils.logger import logger
from app.utils.document_parser import DocumentParser
from app.utils.text_splitter import TextSplitter
from app.models import embedding_manager

router = APIRouter()


class DocumentCreate(BaseModel):
    """创建文档的请求模型"""
    title: str = Field(..., description="文档标题")
    content: str = Field(..., description="文档内容")
    author: str = Field(None, description="作者")


class DocumentUploadConfig(BaseModel):
    """文档上传配置"""
    split_method: str = Field("recursive", description="切分方法 (recursive, character, token, semantic, paragraph, sentence)")
    chunk_size: int = Field(1000, description="块大小")
    chunk_overlap: int = Field(200, description="块重叠大小")
    store_vectors: bool = Field(True, description="是否存储向量")


class DocumentResponse(BaseModel):
    """文档响应模型"""
    id: int
    title: str
    content: str
    author: str = None
    file_type: str = None
    file_path: str = None
    file_size: int = None
    chunk_count: int = None
    split_method: str = None
    chunk_size: int = None
    chunk_overlap: int = None
    metadata: str = None
    created_at: str
    updated_at: str = None


class VectorSearchRequest(BaseModel):
    """向量搜索请求模型"""
    query_vector: List[float] = Field(..., description="查询向量")
    top_k: int = Field(10, description="返回结果数量")
    expr: str = Field(None, description="过滤表达式")


class VectorSearchResponse(BaseModel):
    """向量搜索响应模型"""
    results: List[dict]


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(..., description="上传的文件"),
    title: str = Form(None, description="文档标题（可选，默认使用文件名）"),
    author: str = Form(None, description="作者"),
    split_method: str = Form("recursive", description="切分方法"),
    chunk_size: int = Form(1000, description="块大小"),
    chunk_overlap: int = Form(200, description="块重叠大小"),
    store_vectors: bool = Form(True, description="是否存储向量"),
    session: AsyncSession = Depends(postgres_manager.get_session),
):
    """
    上传并解析文档
    
    支持的文件类型:
    - PDF (.pdf)
    - Word (.doc, .docx)
    - PowerPoint (.ppt, .pptx)
    - Excel (.xls, .xlsx)
    - 纯文本 (.txt)
    - Markdown (.md, .markdown)
    
    切分方法:
    - recursive: 递归切分（推荐）
    - character: 按字符切分
    - token: 按 Token 切分
    - semantic: 按语义切分
    - paragraph: 按段落切分
    - sentence: 按句子切分
    """
    try:
        import tempfile
        import os
        
        # 保存上传的文件到临时目录
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, file.filename)
        
        async with aiofiles.open(file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)
        
        file_size = len(content)
        
        # 解析文档
        parse_result = DocumentParser.parse(file_path)
        
        # 使用文件名作为标题（如果未提供）
        doc_title = title or Path(file.filename).stem
        
        # 切分文本
        chunks = TextSplitter.split(
            text=parse_result["content"],
            method=split_method,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        
        # 准备元数据
        metadata = {
            **parse_result.get("metadata", {}),
            "file_name": file.filename,
            "file_size": file_size,
            "chunk_count": len(chunks),
        }
        
        # 创建数据库记录
        db_document = Document(
            title=doc_title,
            content=parse_result["content"],
            author=author,
            file_type=parse_result["file_type"],
            file_path=file_path,
            file_size=file_size,
            chunk_count=len(chunks),
            split_method=split_method,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            doc_metadata=json.dumps(metadata, ensure_ascii=False),
        )
        session.add(db_document)
        await session.commit()
        await session.refresh(db_document)
        
        # 如果需要，存储向量
        if store_vectors and milvus_manager.connected:
            try:
                # 为每个块生成向量并存储
                vectors = []
                chunk_metadata = []
                
                for i, chunk in enumerate(chunks):
                    # 生成嵌入向量
                    embedding = embedding_manager.embed_query(chunk["text"])
                    vectors.append(embedding)
                    
                    # 准备元数据
                    chunk_meta = {
                        "document_id": db_document.id,
                        "chunk_index": i,
                        "text": chunk["text"][:500],  # 只存储前500个字符
                        **chunk.get("metadata", {}),
                    }
                    chunk_metadata.append(chunk_meta)
                
                # 插入向量到 Milvus
                milvus_manager.insert_vectors(vectors, chunk_metadata)
                
                logger.info(f"成功存储 {len(vectors)} 个向量到 Milvus")
            except Exception as e:
                logger.warning(f"向量存储失败: {e}")
        
        # 删除临时文件
        try:
            os.remove(file_path)
        except:
            pass
        
        logger.info(f"文档上传成功: ID={db_document.id}, 类型={parse_result['file_type']}, 块数={len(chunks)}")
        return DocumentResponse(**db_document.to_dict())
        
    except Exception as e:
        logger.error(f"文档上传失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=DocumentResponse)
async def create_document(
    document: DocumentCreate,
    session: AsyncSession = Depends(postgres_manager.get_session),
):
    """
    创建新文档（纯文本）
    """
    try:
        db_document = Document(
            title=document.title,
            content=document.content,
            author=document.author,
            file_type="txt",
        )
        session.add(db_document)
        await session.commit()
        await session.refresh(db_document)
        
        logger.info(f"创建文档成功: ID={db_document.id}")
        return DocumentResponse(**db_document.to_dict())
    except Exception as e:
        logger.error(f"创建文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: int,
    session: AsyncSession = Depends(postgres_manager.get_session),
):
    """
    获取指定 ID 的文档
    """
    try:
        result = await session.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        
        if not document:
            raise HTTPException(status_code=404, detail="文档不存在")
        
        return DocumentResponse(**document.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=List[DocumentResponse])
async def list_documents(
    skip: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(postgres_manager.get_session),
):
    """
    获取文档列表
    """
    try:
        result = await session.execute(
            select(Document).offset(skip).limit(limit)
        )
        documents = result.scalars().all()
        
        return [DocumentResponse(**doc.to_dict()) for doc in documents]
    except Exception as e:
        logger.error(f"获取文档列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    session: AsyncSession = Depends(postgres_manager.get_session),
):
    """
    删除文档
    """
    try:
        result = await session.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        
        if not document:
            raise HTTPException(status_code=404, detail="文档不存在")
        
        await session.delete(document)
        await session.commit()
        
        logger.info(f"删除文档成功: ID={document_id}")
        return {"message": "文档删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vectors/search", response_model=VectorSearchResponse)
async def search_vectors(request: VectorSearchRequest):
    """
    向量搜索
    """
    try:
        if not milvus_manager.connected:
            raise HTTPException(status_code=503, detail="Milvus 服务未连接")
        
        results = milvus_manager.search_vectors(
            query_vectors=[request.query_vector],
            top_k=request.top_k,
            expr=request.expr,
        )
        
        logger.info(f"向量搜索完成，返回 {len(results[0])} 个结果")
        return VectorSearchResponse(results=results[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"向量搜索失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vectors/insert")
async def insert_vectors(
    vectors: List[List[float]],
    metadata: List[dict] = None,
):
    """
    插入向量数据
    """
    try:
        if not milvus_manager.connected:
            raise HTTPException(status_code=503, detail="Milvus 服务未连接")
        
        milvus_manager.insert_vectors(vectors, metadata)
        
        logger.info(f"成功插入 {len(vectors)} 个向量")
        return {"message": f"成功插入 {len(vectors)} 个向量"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"插入向量失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vectors/collection")
async def create_vector_collection(
    collection_name: str = None,
    dimension: int = None,
):
    """
    创建向量集合
    """
    try:
        if not milvus_manager.connected:
            raise HTTPException(status_code=503, detail="Milvus 服务未连接")
        
        milvus_manager.create_collection(collection_name, dimension)
        milvus_manager.create_index(collection_name)
        milvus_manager.load_collection(collection_name)
        
        collection_name = collection_name or milvus_manager.collection_name
        logger.info(f"成功创建向量集合: {collection_name}")
        return {"message": f"成功创建向量集合: {collection_name}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建向量集合失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
