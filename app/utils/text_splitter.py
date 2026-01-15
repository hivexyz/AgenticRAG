"""
文本切分器
支持多种文本切分方法
"""
from typing import List, Dict, Any, Optional
from app.utils.logger import logger


class TextSplitter:
    """文本切分器基类"""
    
    @staticmethod
    def split(
        text: str,
        method: str = "recursive",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        切分文本
        
        Args:
            text: 待切分的文本
            method: 切分方法 (recursive, character, token, semantic)
            chunk_size: 块大小
            chunk_overlap: 块重叠大小
            **kwargs: 其他参数
            
        Returns:
            切分结果列表，每个元素包含 text, metadata 等信息
        """
        logger.info(f"开始切分文本，方法: {method}, 块大小: {chunk_size}, 重叠: {chunk_overlap}")
        
        try:
            if method == "recursive":
                return RecursiveTextSplitter.split(text, chunk_size, chunk_overlap, **kwargs)
            elif method == "character":
                return CharacterTextSplitter.split(text, chunk_size, chunk_overlap, **kwargs)
            elif method == "token":
                return TokenTextSplitter.split(text, chunk_size, chunk_overlap, **kwargs)
            elif method == "semantic":
                return SemanticTextSplitter.split(text, chunk_size, chunk_overlap, **kwargs)
            elif method == "paragraph":
                return ParagraphTextSplitter.split(text, **kwargs)
            elif method == "sentence":
                return SentenceTextSplitter.split(text, **kwargs)
            else:
                raise ValueError(f"不支持的切分方法: {method}")
        except Exception as e:
            logger.error(f"文本切分失败: {e}")
            raise


class RecursiveTextSplitter:
    """递归文本切分器"""
    
    @staticmethod
    def split(
        text: str,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separators: Optional[List[str]] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        递归切分文本
        
        Args:
            text: 待切分的文本
            chunk_size: 块大小
            chunk_overlap: 块重叠大小
            separators: 分隔符列表
            
        Returns:
            切分结果
        """
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
        except ImportError:
            raise ImportError("请安装 langchain-text-splitters: pip install langchain-text-splitters")
        
        if separators is None:
            separators = ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
        
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=separators,
            length_function=len,
        )
        
        chunks = splitter.split_text(text)
        
        return [
            {
                "text": chunk,
                "metadata": {
                    "method": "recursive",
                    "chunk_index": i,
                    "chunk_size": len(chunk),
                }
            }
            for i, chunk in enumerate(chunks)
        ]


class CharacterTextSplitter:
    """字符文本切分器"""
    
    @staticmethod
    def split(
        text: str,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separator: str = "\n\n",
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        按字符切分文本
        
        Args:
            text: 待切分的文本
            chunk_size: 块大小
            chunk_overlap: 块重叠大小
            separator: 分隔符
            
        Returns:
            切分结果
        """
        try:
            from langchain_text_splitters import CharacterTextSplitter
        except ImportError:
            raise ImportError("请安装 langchain-text-splitters: pip install langchain-text-splitters")
        
        splitter = CharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separator=separator,
            length_function=len,
        )
        
        chunks = splitter.split_text(text)
        
        return [
            {
                "text": chunk,
                "metadata": {
                    "method": "character",
                    "chunk_index": i,
                    "chunk_size": len(chunk),
                }
            }
            for i, chunk in enumerate(chunks)
        ]


class TokenTextSplitter:
    """Token 文本切分器"""
    
    @staticmethod
    def split(
        text: str,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        encoding_name: str = "cl100k_base",
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        按 Token 切分文本
        
        Args:
            text: 待切分的文本
            chunk_size: 块大小（token 数）
            chunk_overlap: 块重叠大小（token 数）
            encoding_name: 编码名称
            
        Returns:
            切分结果
        """
        try:
            from langchain_text_splitters import TokenTextSplitter
        except ImportError:
            raise ImportError("请安装 langchain-text-splitters: pip install langchain-text-splitters")
        
        splitter = TokenTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            encoding_name=encoding_name,
        )
        
        chunks = splitter.split_text(text)
        
        return [
            {
                "text": chunk,
                "metadata": {
                    "method": "token",
                    "chunk_index": i,
                    "encoding": encoding_name,
                }
            }
            for i, chunk in enumerate(chunks)
        ]


class SemanticTextSplitter:
    """语义文本切分器"""
    
    @staticmethod
    def split(
        text: str,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        embedding_model: Optional[Any] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        按语义切分文本
        
        Args:
            text: 待切分的文本
            chunk_size: 块大小
            chunk_overlap: 块重叠大小
            embedding_model: 嵌入模型
            
        Returns:
            切分结果
        """
        try:
            from langchain_text_splitters import SemanticChunker
        except ImportError:
            raise ImportError("请安装 langchain-text-splitters: pip install langchain-text-splitters")
        
        if embedding_model is None:
            from app.models import embedding_manager
            embedding_model = embedding_manager.client
        
        splitter = SemanticChunker(
            embeddings=embedding_model,
            breakpoint_threshold_type="percentile",
        )
        
        chunks = splitter.split_text(text)
        
        return [
            {
                "text": chunk,
                "metadata": {
                    "method": "semantic",
                    "chunk_index": i,
                    "chunk_size": len(chunk),
                }
            }
            for i, chunk in enumerate(chunks)
        ]


class ParagraphTextSplitter:
    """段落文本切分器"""
    
    @staticmethod
    def split(
        text: str,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        按段落切分文本
        
        Args:
            text: 待切分的文本
            
        Returns:
            切分结果
        """
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        
        return [
            {
                "text": paragraph,
                "metadata": {
                    "method": "paragraph",
                    "chunk_index": i,
                    "chunk_size": len(paragraph),
                }
            }
            for i, paragraph in enumerate(paragraphs)
        ]


class SentenceTextSplitter:
    """句子文本切分器"""
    
    @staticmethod
    def split(
        text: str,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        按句子切分文本
        
        Args:
            text: 待切分的文本
            
        Returns:
            切分结果
        """
        import re
        
        sentences = re.split(r'([。！？.!?])', text)
        sentences = [s1 + s2 for s1, s2 in zip(sentences[::2], sentences[1::2])]
        sentences = [s.strip() for s in sentences if s.strip()]
        
        return [
            {
                "text": sentence,
                "metadata": {
                    "method": "sentence",
                    "chunk_index": i,
                    "chunk_size": len(sentence),
                }
            }
            for i, sentence in enumerate(sentences)
        ]
