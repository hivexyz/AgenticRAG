# 协和学院 FastAPI 项目

基于 FastAPI 构建的轻量级 Python Web API 框架。

## 项目特性

- 🚀 **FastAPI**: 高性能、易用、基于标准 Python 类型提示的现代 Web 框架
- 🗄️ **PostgreSQL**: 使用 SQLAlchemy 和 asyncpg 进行异步数据库操作
- 🔍 **Milvus**: 向量数据库支持，用于相似性搜索和向量检索
- 🤖 **OpenAI 集成**: 支持 LLM、Embedding 和 Reranker 模型
- 🧠 **AgenticRAG**: 基于 LangGraph 的智能体驱动的 RAG 系统
- 🎨 **Gradio 界面**: 直观的 Web 界面，支持问答、文档管理和系统监控
- ⚙️ **环境配置**: 支持开发/生产环境切换
- 📝 **自动文档**: 自动生成 Swagger/OpenAPI 文档（开发环境）
- 🛡️ **CORS 支持**: 跨域资源共享配置
- 📊 **日志管理**: 使用 Loguru 进行结构化日志管理
- 🎯 **类型提示**: 全面的类型提示支持，更好的 IDE 支持

## 项目结构

```
xiehe_institute/
├── app/                    # 应用主目录
│   ├── __init__.py
│   ├── main.py            # FastAPI 应用入口
│   ├── config.py          # 配置管理（支持环境切换）
│   ├── agents/            # AgenticRAG 智能体模块
│   │   ├── __init__.py
│   │   ├── state.py       # 状态定义
│   │   ├── nodes.py       # 节点实现
│   │   └── manager.py     # 管理器
│   ├── database/          # 数据库管理
│   │   ├── __init__.py
│   │   ├── postgres.py    # PostgreSQL 数据库管理
│   │   └── milvus.py      # Milvus 向量数据库管理
│   ├── models/            # 数据模型和 AI 模型
│   │   ├── __init__.py    # 模型初始化
│   │   ├── llm.py         # LLM 模型管理
│   │   ├── embedding.py   # Embedding 模型管理
│   │   └── reranker.py    # Reranker 模型管理
│   ├── routes/            # API 路由
│   │   ├── __init__.py
│   │   ├── api.py         # 路由聚合
│   │   ├── health.py      # 健康检查
│   │   ├── documents.py   # 文档和向量 API
│   │   ├── ai.py          # AI 模型 API
│   │   └── agentic_rag.py # AgenticRAG API
│   ├── middleware/        # 中间件
│   │   └── cors.py        # CORS 配置
│   └── utils/             # 工具函数
│       └── logger.py      # 日志配置
├── front/                 # Gradio 界面
│   ├── __init__.py
│   ├── app.py            # Gradio 主界面
│   ├── config.py         # 界面配置
│   ├── api_client.py     # API 客户端
│   ├── run.py            # 启动脚本
│   └── README.md         # 界面使用指南
├── logs/                  # 日志文件目录
├── requirements.txt       # Python 依赖
├── env.example           # 环境变量示例
├── .gitignore            # Git 忽略文件
├── main.py               # 开发服务器入口
├── start_gradio.bat      # Gradio 启动脚本（Windows）
├── AGENTIC_RAG_GUIDE.md  # AgenticRAG 使用指南
└── README.md             # 项目说明
```

## 快速开始

### 1. 环境要求

- Python 3.8+

### 2. 安装依赖

```bash
# 创建虚拟环境（推荐）
conda crete -n xiehe_institute_env python=3.12

# 激活虚拟环境
conda activate xiehe_institute_env

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置环境变量

复制 `env.example` 为 `.env` 并修改配置：

```bash
# Windows:
copy env.example .env

# Linux/Mac:
cp env.example .env
```

编辑 `.env` 文件，设置环境配置：

```env
# 环境配置 (development, production)
ENVIRONMENT=development

# 应用配置
APP_NAME=xiehe_institute
APP_VERSION=1.0.0
DEBUG=True

# 服务器配置
HOST=0.0.0.0
PORT=8000

# CORS 配置
CORS_ORIGINS=["http://localhost:3000", "http://localhost:8080"]

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=logs/app.log

# PostgreSQL 数据库配置
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=xiehe_institute
POSTGRES_POOL_SIZE=10
POSTGRES_MAX_OVERFLOW=20

# Milvus 向量数据库配置
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_USER=
MILVUS_PASSWORD=
MILVUS_COLLECTION_NAME=vectors
MILVUS_DIMENSION=768
MILVUS_INDEX_TYPE=IVF_FLAT
MILVUS_METRIC_TYPE=L2

# OpenAI API 配置
OPENAI_API_KEY=
OPENAI_BASE_URL=

# LLM 模型配置
OPENAI_MODEL=gpt-3.5-turbo
OPENAI_TEMPERATURE=0.7
OPENAI_MAX_TOKENS=2048
OPENAI_TOP_P=1.0
OPENAI_FREQUENCY_PENALTY=0.0
OPENAI_PRESENCE_PENALTY=0.0

# Embedding 模型配置
OPENAI_EMBEDDING_MODEL=text-embedding-ada-002
OPENAI_EMBEDDING_DIMENSION=1536

# Reranker 模型配置
OPENAI_RERANKER_MODEL=gpt-3.5-turbo
OPENAI_RERANKER_TOP_K=10
```

### 4. 启动数据库服务

在启动应用之前，确保已启动 PostgreSQL 和 Milvus 服务：

```bash
# 启动 PostgreSQL（使用 Docker）
docker run -d \
  --name postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=xiehe_institute \
  -p 5432:5432 \
  postgres:15

# 启动 Milvus（使用 Docker Compose）
# 创建 docker-compose.yml 文件并运行
docker-compose up -d
```

### 4. 启动开发服务器

现在可以通过一个命令同时启动 FastAPI 后端和 Gradio 界面：

```bash
python main.py
```

这将同时启动：
- FastAPI 后端服务: http://localhost:8000
- Gradio 界面: http://localhost:7860

**注意**: 如果需要分别启动，可以使用以下方式：

**仅启动 FastAPI 后端**:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**仅启动 Gradio 界面**:
```bash
python front/run.py
```

### 5. 访问应用

- **API 文档 (Swagger)**: http://localhost:8000/docs （仅开发环境）
- **API 文档 (ReDoc)**: http://localhost:8000/redoc （仅开发环境）
- **根路径**: http://localhost:8000/
- **健康检查**: http://localhost:8000/api/v1/health

## API 端点

### 健康检查
- `GET /api/v1/health/` - 健康检查
- `GET /api/v1/health/ping` - 简单 ping 测试

### 文档管理
- `POST /api/v1/documents` - 创建新文档
- `GET /api/v1/documents/{document_id}` - 获取指定 ID 的文档
- `GET /api/v1/documents` - 获取文档列表

### 向量搜索
- `POST /api/v1/vectors/search` - 向量相似性搜索
- `POST /api/v1/vectors/insert` - 插入向量数据
- `POST /api/v1/vectors/collection` - 创建向量集合

### AI 模型
#### LLM
- `POST /api/v1/ai/llm/chat` - LLM 聊天补全
- `POST /api/v1/ai/llm/completion` - LLM 文本补全
- `POST /api/v1/ai/llm/tokens` - 计算 token 数量

#### Embedding
- `POST /api/v1/ai/embedding` - 创建文本嵌入向量
- `POST /api/v1/ai/embedding/batch` - 批量创建文本嵌入向量

#### Reranker
- `POST /api/v1/ai/rerank` - 对文档进行重排序
- `POST /api/v1/ai/rerank/embeddings` - 使用嵌入向量进行重排序

#### 搜索
- `POST /api/v1/ai/search` - 搜索并重排序（集成 Embedding + Milvus + Reranker）

#### AgenticRAG
- `POST /api/v1/ai/agentic-rag/query` - 执行 AgenticRAG 查询
- `POST /api/v1/ai/agentic-rag/stream` - 流式执行 AgenticRAG 查询
- `GET /api/v1/ai/agentic-rag/health` - AgenticRAG 健康检查
- `POST /api/v1/ai/agentic-rag/analyze` - 查询分析

## Gradio 界面

项目提供了一个基于 Gradio 的 Web 界面，支持问答、文档管理和系统监控。

### 启动 Gradio 界面

**Windows:**
```bash
start_gradio.bat
```

**Linux/Mac:**
```bash
python front/run.py
```

界面将在 `http://localhost:7860` 启动。

### 界面功能

- **AgenticRAG 问答**: 智能问答对话，支持多轮对话
- **查询分析**: 分析查询类型和复杂度
- **文档管理**: 上传、查看和删除文档
- **系统状态**: 检查系统健康状态

详细使用说明请参考 [front/README.md](front/README.md)。

## OpenAI 集成说明

### 配置 OpenAI API

在 `.env` 文件中配置 OpenAI 相关参数：

```env
# OpenAI API 配置
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=  # 可选：如果使用兼容 API（如 Azure、本地模型），设置此参数

# LLM 模型配置
OPENAI_MODEL=gpt-3.5-turbo
OPENAI_TEMPERATURE=0.7
OPENAI_MAX_TOKENS=2048
OPENAI_TOP_P=1.0
OPENAI_FREQUENCY_PENALTY=0.0
OPENAI_PRESENCE_PENALTY=0.0

# Embedding 模型配置
OPENAI_EMBEDDING_MODEL=text-embedding-ada-002
OPENAI_EMBEDDING_DIMENSION=1536

# Reranker 模型配置
OPENAI_RERANKER_MODEL=gpt-3.5-turbo
OPENAI_RERANKER_TOP_K=10
```

### 使用兼容 API

如果需要使用兼容 OpenAI API 的服务（如 Azure OpenAI、本地 LLM 服务等），只需设置 `OPENAI_BASE_URL` 参数：

```env
# Azure OpenAI 示例
OPENAI_BASE_URL=https://your-resource.openai.azure.com/

# 本地兼容服务示例
OPENAI_BASE_URL=http://localhost:8000/v1
```

### API 使用示例

#### LLM 聊天补全

```bash
curl -X POST "http://localhost:8000/api/v1/ai/llm/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "你是一个有帮助的助手。"},
      {"role": "user", "content": "你好，请介绍一下自己。"}
    ],
    "temperature": 0.7
  }'
```

#### 创建嵌入向量

```bash
curl -X POST "http://localhost:8000/api/v1/ai/embedding" \
  -H "Content-Type: application/json" \
  -d '{
    "input": "这是一段需要生成嵌入向量的文本"
  }'
```

#### 文档重排序

```bash
curl -X POST "http://localhost:8000/api/v1/ai/rerank" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "什么是 FastAPI",
    "documents": [
      {"id": 1, "content": "FastAPI 是一个现代、快速的 Web 框架"},
      {"id": 2, "content": "Python 是一种编程语言"}
    ],
    "top_k": 5
  }'
```

#### 搜索并重排序

```bash
curl -X POST "http://localhost:8000/api/v1/ai/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "什么是 FastAPI",
    "top_k": 10,
    "rerank_top_k": 5
  }'
```

## 开发指南

### 环境配置切换

项目支持通过 `ENVIRONMENT` 环境变量切换开发/生产环境：

- **开发环境** (`ENVIRONMENT=development`): 
  - 启用 API 文档 (`/docs`, `/redoc`)
  - 启用调试模式
  - 详细的日志输出

- **生产环境** (`ENVIRONMENT=production`):
  - 禁用 API 文档
  - 禁用调试模式
  - 优化的日志输出

### 添加新的路由

1. 在 `app/routes/` 目录下创建新的路由文件（例如 `example.py`）：

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def get_example():
    return {"message": "示例路由"}
```

2. 在 `app/routes/api.py` 中注册路由：

```python
from app.routes import example

api_router.include_router(example.router, prefix="/example", tags=["示例"])
```

### 日志管理

日志配置位于 `app/utils/logger.py`，使用 Loguru 进行日志管理：

- 控制台输出（带颜色）
- 文件输出（按天轮转，自动压缩）
- 可通过 `.env` 文件配置日志级别和文件路径

使用日志：

```python
from app.utils.logger import logger

logger.info("这是一条信息日志")
logger.error("这是一条错误日志")
logger.debug("这是一条调试日志")
```

### 配置管理

配置文件位于 `app/config.py`，使用 `pydantic-settings` 管理：

- 支持从 `.env` 文件读取配置
- 支持环境变量覆盖
- 提供 `is_development` 和 `is_production` 属性判断环境

访问配置：

```python
from app.config import settings

print(settings.APP_NAME)
print(settings.ENVIRONMENT)
if settings.is_development:
    print("当前为开发环境")
```

## 部署

### 生产环境配置

1. 设置 `.env` 文件：
   ```env
   ENVIRONMENT=production
   DEBUG=False
   LOG_LEVEL=WARNING
   ```

2. 使用进程管理器（如 systemd、supervisor）或容器（Docker）

3. 使用 uvicorn 启动（生产环境建议使用多进程）：
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
   ```

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

[在此添加许可证信息]

## 支持

如有问题，请提交 Issue 或联系项目维护者。
