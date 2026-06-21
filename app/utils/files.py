"""文件相关工具函数。"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4


def sanitize_filename(filename: str | None, fallback: str = "upload.bin") -> str:
    """返回安全的文件名，去除路径成分和非法占位名。"""
    if not filename:
        return fallback

    normalized = filename.replace("\\", "/").split("/")[-1]
    normalized = re.sub(r"[\x00-\x1f]", "", normalized).strip()

    if normalized in {"", ".", ".."}:
        return fallback

    return normalized


def build_temp_upload_path(temp_dir: str, filename: str | None) -> tuple[str, str]:
    """生成安全的临时上传路径和原始安全文件名。"""
    safe_name = sanitize_filename(filename)
    suffix = Path(safe_name).suffix
    temp_name = f"upload-{uuid4().hex}{suffix}"
    return str(Path(temp_dir) / temp_name), safe_name
