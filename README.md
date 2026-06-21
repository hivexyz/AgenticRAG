# AgenticRAG

AgenticRAG 是一个基于 FastAPI、LangGraph、OpenAI 兼容模型接口和向量数据库的智能体驱动 RAG 系统。项目提供后端 API、Gradio 可视化界面、文档解析入库、文本切分、Embedding 检索、可选 Rerank、答案生成与质量评估等能力。

## 核心能力

- **Agentic RAG 问答**：通过 LangGraph 编排查询分析、向量检索、重排序、上下文构建、答案生成、质量评估等节点。
- **文档管理**：支持上传文件或纯文本，保存文档元数据，并可选择生成向量写入向量库。
- **多格式解析**：支持 PDF、Word、PowerPoint、Excel、TXT、Markdown 等文档类型。
- **多种文本切分策略**：支持 recursive、character、token、semantic、paragraph、sentence。
- **向量存储后端可切换**：支持 Milvus 或 PostgreSQL + pgvector。
- **多租户隔离**：API 和向量数据均支持 tenant_id；Milvus 按租户生成独立 collection 名称。
- **OpenAI 兼容模型接入**：LLM、Embedding、Reranker 均通过 OpenAI 兼容接口配置。
- **Gradio 前端**：提供问答、查询分析、文档管理、系统状态四个页面。

## 技术栈

- Web 后端：FastAPI、Uvicorn、Pydantic Settings
- Agent 编排：LangGraph、LangChain message 类型
- 前端：Gradio
- 数据库：PostgreSQL、SQLAlchemy、asyncpg
- 向量库：Milvus 或 PostgreSQL + pgvector
- 模型接口：OpenAI Python SDK、HTTPX，兼容 OpenAI API 格式
- 文档解析：PyMuPDF、python-docx、python-pptx、openpyxl、markdown
- 文本切分：langchain-text-splitters、自定义轻量语义切分

## 目录结构

```text
.
├── app/
│   ├── agents/              # LangGraph AgenticRAG 状态、节点、管理器
│   ├── database/            # PostgreSQL、Milvus、pgvector/向量存储抽象
│   ├── db_models/           # SQLAlchemy 数据模型
│   ├── middleware/          # CORS 等中间件
│   ├── models/              # LLM、Embedding、Reranker 管理器
│   ├── routes/              # FastAPI 路由
│   ├── utils/               # 文档解析、文本切分、租户、日志等工具
│   ├── config.py            # 应用配置
│   └── main.py              # FastAPI 应用入口
├── front/                   # Gradio 前端
├── docs/                    # 项目文档
├── tests/                   # 自动化测试
├── main.py                  # 同时启动 FastAPI 与 Gradio
├── start.sh                 # 一键启动脚本
├── requirements.txt         # 主要 Python 依赖
├── env.example              # 环境变量示例
└── README.md
```

## 环境要求

- Python 3.10+
- PostgreSQL
- 以下向量后端二选一：
  - Milvus
  - PostgreSQL pgvector 扩展
- OpenAI 兼容的模型服务：
  - Chat Completions 接口，用于 LLM 问答、查询分析、质量评估
  - Embeddings 接口，用于文本向量化
  - 可选 Rerank 接口，用于候选结果重排序

## 安装依赖

建议创建虚拟环境后安装 `requirements.txt`：

```bash
python3 -m venv agentic_rag_env
source agentic_rag_env/bin/activate
pip install -r requirements.txt
```

如果你使用项目根目录下的 `.venv`，`start.sh` 会优先使用 `.venv/bin/python`；否则会回退到 `python3` 或 `python`。

## 配置说明

复制示例配置并按实际环境修改：

```bash
cp env.example .env
```

> 注意：不要把真实的 API Key、数据库密码等敏感信息提交到代码仓库。

### 基础配置

```env
ENVIRONMENT=development
APP_NAME=AgenticRAG
APP_VERSION=1.0.0
DEBUG=True
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO
LOG_FILE=logs/app.log
DEFAULT_TENANT_ID=default
```

`ENVIRONMENT=development` 时会启用 FastAPI `/docs` 和 `/redoc`。

### PostgreSQL 配置

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=xiehe_institute
POSTGRES_POOL_SIZE=10
POSTGRES_MAX_OVERFLOW=20
```

PostgreSQL 用于保存文档内容、文档元数据等结构化数据。

### 向量存储配置

通过 `VECTOR_STORE_BACKEND` 选择向量后端：

```env
VECTOR_STORE_BACKEND=milvus      # 可选：milvus / pgvector
```

Milvus 示例：

```env
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_USER=
MILVUS_PASSWORD=
MILVUS_COLLECTION_NAME=vectors
MILVUS_DIMENSION=1024
MILVUS_INDEX_TYPE=IVF_FLAT
MILVUS_METRIC_TYPE=L2
```

pgvector 示例：

```env
PGVECTOR_TABLE_NAME=document_vectors
PGVECTOR_DISTANCE_METRIC=cosine  # cosine / l2 / ip
PGVECTOR_IVFFLAT_LISTS=100
```

Embedding 维度必须与向量库维度保持一致。当前代码统一通过 `OPENAI_EMBEDDING_DIMENSION` 作为向量维度配置；如果未显式配置该项，则兼容使用旧的 `MILVUS_DIMENSION`。

### OpenAI 兼容模型配置

通用配置：

```env
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=http://your-openai-compatible-server/v1
```

LLM 配置：

```env
OPENAI_MODEL=qwen/qwen3-4b
OPENAI_TEMPERATURE=0.7
OPENAI_MAX_TOKENS=2048
OPENAI_TOP_P=1.0
OPENAI_FREQUENCY_PENALTY=0.0
OPENAI_PRESENCE_PENALTY=0.0
```

Embedding 配置：

```env
OPENAI_EMBEDDING_MODEL=text-embedding-bge-m3
OPENAI_EMBEDDING_DIMENSION=1024
OPENAI_EMBEDDING_BASE_URL=http://your-embedding-server/v1
```

`OPENAI_EMBEDDING_BASE_URL` 可单独指定 Embedding 服务地址；如果为空，则使用 `OPENAI_BASE_URL`。

Reranker 配置：

```env
OPENAI_RERANKER_MODEL=text-embedding-bge-reranker-v2-m3
OPENAI_RERANKER_TOP_K=10
OPENAI_RERANKER_BASE_URL=http://your-reranker-server/v1
```

当前主重排逻辑调用专用 Rerank 接口：

```text
POST {OPENAI_RERANKER_BASE_URL}/rerank
```

例如 `OPENAI_RERANKER_BASE_URL=http://host:1234/v1` 时，请求地址为 `http://host:1234/v1/rerank`。

重要行为说明：

- `app.models.reranker.RerankerManager.rerank()` **不使用 LLM Chat Completion 做重排序**。
- 主 RAG 流程和 `/api/v1/ai/rerank` 会调用专用 `/rerank` 接口。
- 如果模型服务返回类似 `Unexpected endpoint or method. (POST /v1/rerank)`，表示没有开放 `/v1/rerank`，系统会**跳过重排序并保持召回结果原始顺序**，不会再退回到“重新 embedding + cosine similarity”的方式。
- `/api/v1/ai/rerank/embeddings` 仍保留为显式的向量相似度重排序接口，只有直接调用该接口时才会使用传入的 query/document embeddings 计算余弦相似度。

### AgenticRAG 配置

```env
AGENTIC_RAG_MAX_RETRIEVALS=2
AGENTIC_RAG_QUALITY_THRESHOLD=0.8
AGENTIC_RAG_DEFAULT_TOP_K=10
```

### Gradio 配置

```env
API_BASE_URL=http://localhost:8000
GRADIO_SERVER_NAME=0.0.0.0
GRADIO_SERVER_PORT=7860
GRADIO_SHARE=false
```

## 启动方式

### 一键启动 FastAPI + Gradio

```bash
./start.sh
```

`start.sh` 会读取 `.env` 中的常用端口配置，但不会直接 `source .env`，因为 `.env` 中的 `CORS_ORIGINS=["..."]` 等写法适合 python-dotenv/Pydantic，不一定是合法 Shell 语法。

启动后通常访问：

- FastAPI：`http://127.0.0.1:8000`
- Swagger 文档：`http://127.0.0.1:8000/docs`
- Gradio：`http://127.0.0.1:7860`

具体端口以 `.env` 或启动脚本输出为准。

### 手动启动

同时启动后端和 Gradio：

```bash
python main.py
```

只启动 FastAPI：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Gradio 界面

Gradio 前端位于 `front/`，包含以下功能页：

- **AgenticRAG 问答**：输入租户 ID 和问题，执行智能问答，可显示查询分析、检索结果、质量分数。
- **查询分析**：仅分析用户问题，返回查询类型、复杂度、关键词、建议检索数量等。
- **文档管理**：上传文件、上传纯文本、查看文档列表、删除文档。
- **系统状态**：检查 API 和 AgenticRAG 图初始化状态。

## API 概览

所有业务接口默认挂载在 `/api/v1` 下。

### 基础与健康检查

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 应用根路径 |
| GET | `/api/v1` | API 根路径 |
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/health/ping` | Ping 检查 |

### 文档管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/documents/upload` | 上传并解析文件，支持生成向量 |
| POST | `/api/v1/documents` | 创建纯文本文档，支持生成向量 |
| GET | `/api/v1/documents/{document_id}` | 获取单个文档 |
| GET | `/api/v1/documents` | 获取文档列表 |
| DELETE | `/api/v1/documents/{document_id}` | 删除文档，并删除对应向量 |

### 向量接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/vectors/search` | 向量检索 |
| POST | `/api/v1/vectors/insert` | 插入向量 |
| POST | `/api/v1/vectors/collection` | 创建或准备向量 collection/table |

### 模型与搜索接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/ai/llm/chat` | LLM Chat Completion |
| POST | `/api/v1/ai/llm/completion` | LLM Completion |
| POST | `/api/v1/ai/llm/tokens` | Token 计数 |
| POST | `/api/v1/ai/embedding` | 单文本 Embedding |
| POST | `/api/v1/ai/embedding/batch` | 批量 Embedding |
| POST | `/api/v1/ai/rerank` | 专用 `/rerank` 接口重排序 |
| POST | `/api/v1/ai/rerank/embeddings` | 显式使用向量余弦相似度重排序 |
| POST | `/api/v1/ai/search` | Embedding 检索 + Reranker 重排 |

### AgenticRAG 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/ai/agentic-rag/query` | 执行 AgenticRAG 问答 |
| POST | `/api/v1/ai/agentic-rag/stream` | 流式返回 AgenticRAG 中间过程 |
| GET | `/api/v1/ai/agentic-rag/health` | AgenticRAG 健康检查 |
| POST | `/api/v1/ai/agentic-rag/analyze` | 仅执行查询分析 |

## 文档解析支持

当前解析入口为 `app/utils/document_parser.py`。

| 后缀 | 解析器 | 依赖 | 说明 |
| --- | --- | --- | --- |
| `.pdf` | `PDFParser` | `pymupdf` | 提取每页文本和 PDF 元数据 |
| `.doc`, `.docx` | `DocxParser` | `python-docx` | 提取段落和 core properties；旧版二进制 `.doc` 可能受库能力限制 |
| `.ppt`, `.pptx` | `PptxParser` | `python-pptx` | 提取幻灯片文本和部分元数据；旧版 `.ppt` 可能受库能力限制 |
| `.xls`, `.xlsx` | `ExcelParser` | `openpyxl` | 提取工作表数据；旧版 `.xls` 可能受库能力限制 |
| `.txt` | `TxtParser` | 标准库 | 按 UTF-8 读取文本 |
| `.md`, `.markdown` | `MarkdownParser` | `markdown` | 保留 Markdown 原文，同时生成 HTML |

## 文本切分支持

当前切分入口为 `app/utils/text_splitter.py`。

| 方法 | 说明 |
| --- | --- |
| `recursive` | 使用 LangChain RecursiveCharacterTextSplitter，默认按段落、换行、中文/英文标点、空格递归切分 |
| `character` | 使用 LangChain CharacterTextSplitter 按指定分隔符切分 |
| `token` | 使用 LangChain TokenTextSplitter，默认 `cl100k_base` 编码 |
| `semantic` | 项目内置轻量语义切分：句子边界 + 词项重叠识别主题切换；不是基于 embedding 的语义切分 |
| `paragraph` | 按空行切分段落 |
| `sentence` | 按中英文句号、问号、感叹号切分句子 |

对 `recursive`、`character`、`token`、`semantic`，要求 `chunk_overlap < chunk_size`。

## 多租户规则

多数接口支持 `tenant_id`，默认值为 `default`。租户 ID 会被规范化：

- 转为小写
- `-` 替换为 `_`
- 非字母、数字、下划线字符替换为 `_`
- 多个连续 `_` 合并

Milvus 后端会使用 `MILVUS_COLLECTION_NAME_{tenant_id}` 作为租户 collection 名称；pgvector 后端通过 `tenant_id` 字段过滤。

## 数据流程

### 文档入库

1. 上传文件或提交纯文本。
2. 解析文档内容和元数据。
3. 按指定策略切分 chunks。
4. 保存文档到 PostgreSQL。
5. 如果 `store_vectors=true`，调用 Embedding 接口生成向量。
6. 将向量和 chunk metadata 写入 Milvus 或 pgvector。

### 问答检索

1. 分析用户查询。
2. 对查询生成 Embedding。
3. 在当前租户的向量库中召回候选 chunks。
4. 如果需要重排，调用专用 `/rerank` 接口；如果服务不支持该接口，则保持原召回顺序。
5. 构建上下文。
6. 调用 LLM 生成答案。
7. 对答案进行质量评估，必要时按图逻辑继续检索或返回结果。

## 测试

运行测试：

```bash
PYTHONPATH=. agentic_rag_env/bin/pytest -q
```

最近一次本地测试结果：

```text
59 passed, 8 warnings
```

如果使用其他虚拟环境，请替换为对应的 `python -m pytest` 或 `pytest` 命令。

## 常见问题

### 1. Reranker 报 `Unexpected endpoint or method. (POST /v1/rerank)`

说明当前模型服务没有开放 `/v1/rerank`。当前代码会跳过重排序，保持向量召回结果原始顺序，不会退回到 embedding cosine similarity。

解决方式：

- 确认服务端是否支持 Rerank API。
- 确认 `OPENAI_RERANKER_BASE_URL` 是否配置到 `/v1`，例如 `http://host:1234/v1`。
- 如果服务本身只支持 embeddings/chat completions，则主流程不会执行 rerank。

### 2. Embedding 维度不匹配

请确保：

```env
OPENAI_EMBEDDING_DIMENSION=实际模型维度
MILVUS_DIMENSION=实际模型维度
```

对于 pgvector，表的 vector 维度来自 `settings.vector_dimension`，变更维度后可能需要重建表或迁移数据。

### 3. 文档上传成功但没有向量

可能原因：

- `store_vectors=false`
- Embedding 客户端未初始化或接口不可用
- 向量库未启动或连接失败
- 向量维度和 collection/table 定义不一致

可以查看 `logs/app.log` 获取具体错误。

### 4. 质量评估返回空字符串或无法解析分数

质量评估节点要求模型只返回 `0-1` 的数字。代码已针对部分模型的空响应或 `finish_reason=length` 做了重试和解析兜底；如果仍经常失败，可以调大模型服务的输出 token 限制，或检查 LLM 是否能稳定响应短数字。

### 5. `start.sh` 没有加载完整 `.env`

这是预期行为。`start.sh` 只读取启动所需的少量变量，完整配置由 Python 进程通过 Pydantic Settings 从 `.env` 加载。

## 开发提示

- 主要依赖以 `requirements.txt` 为准。
- `pyproject.toml` 当前较简化，不代表完整运行依赖。
- 修改模型、向量库、Reranker 配置后建议重启服务。
- 上传文档前确认 PostgreSQL 和所选向量后端已启动。
