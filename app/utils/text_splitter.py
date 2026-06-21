"""文本切分器。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.utils.logger import logger


def _split_sentences(text: str) -> List[str]:
    """按中英文句号/问号/感叹号切分句子，并保留尾部残句。"""
    parts = re.split(r"([。！？.!?])", text)
    sentences = [
        f"{left}{right}".strip()
        for left, right in zip(parts[::2], parts[1::2])
        if f"{left}{right}".strip()
    ]
    if len(parts) % 2 == 1 and parts[-1].strip():
        sentences.append(parts[-1].strip())
    return sentences


def _join_sentences(sentences: List[str]) -> str:
    """尽量保持中英文阅读习惯地拼接句子。"""
    if not sentences:
        return ""

    result = sentences[0]
    for sentence in sentences[1:]:
        needs_space = (
            result
            and sentence
            and result[-1].isascii()
            and sentence[0].isascii()
            and result[-1] not in {"\n", " ", "\t"}
        )
        result += (" " if needs_space else "") + sentence
    return result


def _tokenize_for_similarity(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", text)}


def _sentence_similarity(left: str, right: str) -> float:
    left_tokens = _tokenize_for_similarity(left)
    right_tokens = _tokenize_for_similarity(right)

    if not left_tokens or not right_tokens:
        return 0.0

    overlap = left_tokens & right_tokens
    union = left_tokens | right_tokens
    return len(overlap) / len(union)


def _collect_overlap_sentences(sentences: List[str], chunk_overlap: int) -> List[str]:
    if chunk_overlap <= 0:
        return []

    overlap: List[str] = []
    total = 0
    for sentence in reversed(sentences):
        overlap.insert(0, sentence)
        total = len(_join_sentences(overlap))
        if total >= chunk_overlap:
            break
    return overlap


def _enforce_chunk_size(
    chunks: List[Dict[str, Any]],
    chunk_size: int,
    chunk_overlap: int,
    method: str,
) -> List[Dict[str, Any]]:
    """为语义切分等逻辑兜底，确保不会返回超大 chunk。"""
    normalized: List[Dict[str, Any]] = []

    for chunk in chunks:
        chunk_text = (chunk.get("text") or "").strip()
        if not chunk_text:
            continue

        if len(chunk_text) <= chunk_size:
            normalized.append(chunk)
            continue

        fallback_chunks = RecursiveTextSplitter.split(
            chunk_text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        for fallback in fallback_chunks:
            fallback_metadata = {
                **chunk.get("metadata", {}),
                **fallback.get("metadata", {}),
                "method": method,
                "fallback_method": "recursive",
            }
            normalized.append(
                {
                    "text": fallback["text"],
                    "metadata": fallback_metadata,
                }
            )

    for index, item in enumerate(normalized):
        metadata = dict(item.get("metadata", {}))
        metadata["chunk_index"] = index
        metadata["chunk_size"] = len(item["text"])
        item["metadata"] = metadata

    return normalized


class TextSplitter:
    """文本切分器基类"""

    @staticmethod
    def split(
        text: str,
        method: str = "recursive",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """切分文本。"""
        logger.info(f"开始切分文本，方法: {method}, 块大小: {chunk_size}, 重叠: {chunk_overlap}")

        try:
            if method == "recursive":
                return RecursiveTextSplitter.split(text, chunk_size, chunk_overlap, **kwargs)
            if method == "character":
                return CharacterTextSplitter.split(text, chunk_size, chunk_overlap, **kwargs)
            if method == "token":
                return TokenTextSplitter.split(text, chunk_size, chunk_overlap, **kwargs)
            if method == "semantic":
                return SemanticTextSplitter.split(text, chunk_size, chunk_overlap, **kwargs)
            if method == "paragraph":
                return ParagraphTextSplitter.split(text, **kwargs)
            if method == "sentence":
                return SentenceTextSplitter.split(text, **kwargs)
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
        **kwargs,
    ) -> List[Dict[str, Any]]:
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
                },
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
        **kwargs,
    ) -> List[Dict[str, Any]]:
        try:
            from langchain_text_splitters import CharacterTextSplitter as LangChainCharacterTextSplitter
        except ImportError:
            raise ImportError("请安装 langchain-text-splitters: pip install langchain-text-splitters")

        splitter = LangChainCharacterTextSplitter(
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
                },
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
        **kwargs,
    ) -> List[Dict[str, Any]]:
        try:
            from langchain_text_splitters import TokenTextSplitter as LangChainTokenTextSplitter
        except ImportError:
            raise ImportError("请安装 langchain-text-splitters: pip install langchain-text-splitters")

        splitter = LangChainTokenTextSplitter(
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
                },
            }
            for i, chunk in enumerate(chunks)
        ]


class SemanticTextSplitter:
    """轻量语义文本切分器。

    不依赖额外的 LangChain experimental/openai 适配器，
    通过句子边界 + 词项重叠近似识别主题切换，避免 semantic 模式直接崩溃。
    """

    @staticmethod
    def split(
        text: str,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        embedding_model: Optional[Any] = None,
        similarity_threshold: float = 0.15,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        del embedding_model, kwargs

        sentences = _split_sentences(text)
        if not sentences:
            return []

        min_semantic_chunk_size = max(chunk_size // 3, 1)
        built_chunks: List[List[str]] = []
        current: List[str] = []

        for sentence in sentences:
            if not current:
                current = [sentence]
                continue

            current_text = _join_sentences(current)
            projected_text = _join_sentences(current + [sentence])
            similarity = _sentence_similarity(current[-1], sentence)

            should_break_for_size = len(projected_text) > chunk_size and len(current_text) >= min_semantic_chunk_size
            should_break_for_topic = (
                len(current_text) >= min_semantic_chunk_size and similarity < similarity_threshold
            )

            if should_break_for_size or should_break_for_topic:
                built_chunks.append(current)
                current = _collect_overlap_sentences(current, chunk_overlap)

            current.append(sentence)

        if current:
            built_chunks.append(current)

        normalized_chunks = []
        for i, chunk_sentences in enumerate(built_chunks):
            chunk_text = _join_sentences(chunk_sentences).strip()
            if not chunk_text:
                continue
            normalized_chunks.append(
                {
                    "text": chunk_text,
                    "metadata": {
                        "method": "semantic",
                        "chunk_index": i,
                        "chunk_size": len(chunk_text),
                        "sentence_count": len(chunk_sentences),
                        "similarity_threshold": similarity_threshold,
                    },
                }
            )

        if not normalized_chunks:
            return RecursiveTextSplitter.split(text, chunk_size, chunk_overlap)

        return _enforce_chunk_size(normalized_chunks, chunk_size, chunk_overlap, method="semantic")


class ParagraphTextSplitter:
    """段落文本切分器"""

    @staticmethod
    def split(text: str, **kwargs) -> List[Dict[str, Any]]:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return [
            {
                "text": paragraph,
                "metadata": {
                    "method": "paragraph",
                    "chunk_index": i,
                    "chunk_size": len(paragraph),
                },
            }
            for i, paragraph in enumerate(paragraphs)
        ]


class SentenceTextSplitter:
    """句子文本切分器"""

    @staticmethod
    def split(text: str, **kwargs) -> List[Dict[str, Any]]:
        sentences = _split_sentences(text)

        return [
            {
                "text": sentence,
                "metadata": {
                    "method": "sentence",
                    "chunk_index": i,
                    "chunk_size": len(sentence),
                },
            }
            for i, sentence in enumerate(sentences)
        ]
