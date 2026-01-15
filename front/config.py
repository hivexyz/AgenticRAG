"""
Gradio 界面配置
"""
import os
from pathlib import Path

# 基础路径
BASE_DIR = Path(__file__).parent.parent

# API 配置
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
API_V1_URL = f"{API_BASE_URL}/api/v1"

# Gradio 配置
GRADIO_SERVER_NAME = os.getenv("GRADIO_SERVER_NAME", "0.0.0.0")
GRADIO_SERVER_PORT = int(os.getenv("GRADIO_SERVER_PORT", 7860))
GRADIO_SHARE = os.getenv("GRADIO_SHARE", "false").lower() == "true"
GRADIO_AUTH = None

# 界面配置
APP_TITLE = "AgenticRAG 智能问答系统"
APP_DESCRIPTION = "基于 LangGraph 的智能体驱动的 RAG 系统"
APP_VERSION = "1.0.0"

# 聊天配置
DEFAULT_MAX_RETRIEVALS = 2
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TOP_K = 10

# 文档配置
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
SUPPORTED_FILE_TYPES = [".txt", ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".md", ".markdown"]

# 文档切分配置
DEFAULT_SPLIT_METHOD = "recursive"
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200
