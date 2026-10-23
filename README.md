# AgenticRAG

AgenticRAG 是一个基于 FastAPI、LangGraph、OpenAI 兼容模型接口和向量数据库的智能体驱动 RAG + Wiki 知识系统。项目提供后端 API、React 控制台、Gradio 兼容界面、文档解析入库、文本切分、Embedding/混合检索、可选 Rerank、Wiki 页面编译、答案生成与质量评估等能力。

## 核心能力

- **Agentic RAG 问答**：通过 LangGraph 编排查询分析、向量检索、重排序、上下文构建、答案生成、质量评估等节点。
- **文档管理**：支持上传文件或纯文本，保存文档元数据，并可选择生成向量写入向量库。
- **Wiki 知识编译**：支持从源文档编译持久化 Wiki 页面，人工校订、软删除、修订历史、主题索引、页面关系与反链。
- **批量与异步编译**：支持同步批量编译，也支持后台编译任务、任务状态查询和启动恢复。
- **混合证据检索**：AgenticRAG 可融合向量命中、稀疏 chunk 命中和 Wiki 页面命中，并在回答中标记引用来源。
- **React 控制台**：提供文档管理、Wiki 页面管理、问答工作台等生产管理入口。
- **多格式解析**：支持 PDF、Word、PowerPoint、Excel、TXT、Markdown 等文档类型。
- **多种文本切分策略**：支持 recursive、character、token、semantic、paragraph、sentence。
- **向量存储后端可切换**：支持 Milvus 或 PostgreSQL + pgvector。
- **多租户隔离**：API 和向量数据均支持 tenant_id；Milvus 按租户生成独立 collection 名称。
- **OpenAI 兼容模型接入**：LLM、Embedding、Reranker 均通过 OpenAI 兼容接口配置。
- **Gradio 兼容前端**：保留问答、查询分析、文档管理、系统状态四个页面。

## 技术栈

- Web 后端：FastAPI、Uvicorn、Pydantic Settings
- Agent 编排：LangGraph、LangChain message 类型
- 前端：React、Vite、Ant Design；兼容 Gradio
- 数据库：PostgreSQL、SQLAlchemy、asyncpg、Alembic
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
│   ├── services/            # Wiki 等服务层逻辑
│   ├── utils/               # 文档解析、文本切分、租户、日志等工具
│   ├── config.py            # 应用配置
│   └── main.py              # FastAPI 应用入口
├── front/                   # Gradio 前端
├── frontend/                # React 控制台
├── migrations/              # Alembic 数据库迁移
├── docs/                    # 项目文档
├── tests/                   # 自动化测试
├── Dockerfile               # FastAPI / worker 后端镜像
├── docker-compose.yml       # Postgres + Milvus + API + worker + React 控制台
├── main.py                  # 同时启动 FastAPI 与 Gradio
├── start.sh                 # 一键启动脚本
├── pyproject.toml           # Python 依赖与测试配置
├── uv.lock                  # Python 锁文件
├── requirements.txt         # pip 兼容依赖清单
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

Python 依赖以 `pyproject.toml` 和 `uv.lock` 作为锁定来源。建议使用 `uv` 安装：

```bash
uv sync --extra dev
```

`uv sync` 会在项目根目录创建 `.venv`，`start.sh` 会优先使用 `.venv/bin/python`；否则会回退到 `agentic_rag_env/bin/python`、`python3` 或 `python`。

如果部署环境仍使用传统 pip，可以安装兼容清单：

```bash
python3 -m venv agentic_rag_env
source agentic_rag_env/bin/activate
pip install -r requirements.txt
```

`requirements.txt` 与 `pyproject.toml` 的直接依赖保持一致，用作 pip 入口；可复现安装和 CI 仍优先使用 `uv.lock`。

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

### 认证配置

```env
AUTH_ENABLED=false
AUTH_API_KEYS=read_key:tenant_a:read,write_key:tenant_a:write,admin_key:tenant_b:admin
AUTH_ALLOW_ANONYMOUS=false
OIDC_TRUSTED_HEADER_ENABLED=false
TENANT_RATE_LIMIT_PER_MINUTE=1000
TENANT_TOKEN_QUOTA_PER_DAY=1000000
MODEL_COST_PER_1K_TOKENS_USD=0.0
```

生产环境要求显式启用 `AUTH_ENABLED=true`。如果确实需要匿名访问，必须显式设置 `AUTH_ALLOW_ANONYMOUS=true`，否则应用启动会 fail-fast，避免生产环境无意识裸奔。

`AUTH_API_KEYS` 兼容旧格式 `key:tenant`，旧格式默认具备读写权限；推荐新格式显式声明 `read`、`write` 或 `admin`。读权限可以查看列表、详情、检索和问答；写权限可以上传、删除、编辑、提交反馈和触发编译等会改变状态的操作。

如果部署在已经完成 OIDC/JWT 校验的可信反向代理后，可以开启 `OIDC_TRUSTED_HEADER_ENABLED=true`，由代理注入 `X-OIDC-Sub`、`X-OIDC-Tenant`、`X-OIDC-Scopes`。该模式默认关闭，且只应在请求头无法被外部客户端伪造的网络边界内使用；API key 仍会优先于 OIDC 头，便于迁移期混用。

`TENANT_RATE_LIMIT_PER_MINUTE` 是进程内 per-tenant 请求限流，`TENANT_TOKEN_QUOTA_PER_DAY` 是 per-tenant LLM token 日配额；小于等于 0 表示关闭对应保护。`MODEL_COST_PER_1K_TOKENS_USD` 用于 Prometheus 导出中的租户成本估算。当前实现是进程内保护层，适合单实例和开发/内测；多实例生产部署建议后续替换为 Redis 或数据库计费表，调用方无需改 API。

### PostgreSQL 配置

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=xiehe_institute
POSTGRES_POOL_SIZE=10
POSTGRES_MAX_OVERFLOW=20
# 开发环境默认自动建表；生产建议显式设为 false，并通过 Alembic 管理 schema
# POSTGRES_AUTO_CREATE_SCHEMA=false
```

PostgreSQL 用于保存文档内容、文档元数据等结构化数据。文档上传和纯文本创建会计算 `content_hash`；同租户内发现相同内容且文档未删除时，接口直接返回已有文档，避免重复切分、重复向量化和重复 Wiki 编译。

### 上传限制

```env
MAX_UPLOAD_SIZE_MB=50
```

文件上传支持 `.pdf`、`.doc`、`.docx`、`.ppt`、`.pptx`、`.xls`、`.xlsx`、`.txt`、`.md`、`.markdown`。上传接口按块写入临时文件并累计大小，超过 `MAX_UPLOAD_SIZE_MB` 会立即中断并清理临时文件。落盘后还会校验真实文件签名：PDF 需匹配 `%PDF-`，旧版 Office 需匹配 OLE 头，`docx/pptx/xlsx` 需匹配 ZIP 且包含对应根目录，文本/Markdown 需为 UTF-8 且不含二进制空字节。

### 数据库迁移

生产环境建议显式执行 Alembic 迁移：

```bash
alembic upgrade head
```

当前迁移链路位于 `migrations/versions/`：`20260807_0000_core_schema.py` 覆盖核心文档/会话/反馈表，`20260807_0001_wiki_schema.py` 覆盖 Wiki 表，`20261020_0002_wiki_job_queue_fields.py` 覆盖 Wiki 编译任务锁定与重试字段，`20261021_0003_document_content_hash.py` 覆盖文档内容 hash 去重索引，`20261021_0004_sparse_tsvector_index.py` 覆盖稀疏检索全文索引。

`postgres_manager.init_db()` 仍保留开发环境自举能力。生产环境默认不会自动建表或改表，应把 `alembic upgrade head` 纳入部署流程；如确需临时自举，可显式设置 `POSTGRES_AUTO_CREATE_SCHEMA=true`。

### Wiki 后台任务配置

```env
WIKI_COMPILE_JOB_MAX_RETRIES=3
WIKI_COMPILE_JOB_RETRY_BACKOFF_SECONDS=60
WIKI_COMPILE_JOB_STALE_SECONDS=1800
WIKI_COMPILE_INLINE_SUBMIT=false
WIKI_WORKER_POLL_SECONDS=5
WIKI_WORKER_BATCH_SIZE=5
```

异步 Wiki 编译任务会写入 `wiki_compile_jobs`，执行时通过 `locked_by` / `locked_at` 认领。任务级异常会按 `retry_count` 和 `next_run_at` 延迟重试，超过 `max_retries` 后标记为 `failed`。服务启动时会恢复到期的 `pending` 任务和超时的 `processing` 任务。

开发环境默认 `WIKI_COMPILE_INLINE_SUBMIT=true`，提交任务后由 Web 进程内的轻量任务执行器立即处理，便于本地调试。生产环境默认 `false`，建议单独启动 worker：

```bash
python -m app.workers.wiki_worker
```

也可以只跑一轮任务扫描，适合排障或定时任务：

```bash
python -m app.workers.wiki_worker --once --batch-size 10
```

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
EMBEDDING_CACHE_ENABLED=true
EMBEDDING_CACHE_TTL_SECONDS=3600
EMBEDDING_CACHE_MAX_SIZE=4096
```

`OPENAI_EMBEDDING_BASE_URL` 可单独指定 Embedding 服务地址；如果为空，则使用 `OPENAI_BASE_URL`。Embedding 缓存是进程内 TTL 缓存，key 包含模型名、编码格式和输入文本 hash，适合单实例降本；多实例生产部署可后续替换为 Redis，业务调用方无需改接口。

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
AGENTIC_RAG_MAX_SUB_QUERIES=3
QUERY_ANALYSIS_CACHE_ENABLED=true
QUERY_ANALYSIS_CACHE_TTL_SECONDS=600
QUERY_ANALYSIS_CACHE_MAX_SIZE=1024
RETRIEVAL_PROVIDER_TIMEOUT_SECONDS=3.0
RETRIEVAL_MAX_CONCURRENCY=6
MULTI_HOP_ENABLED=true
MULTI_HOP_MAX_HOPS=2
MULTI_HOP_MAX_QUERIES_PER_HOP=2
MULTI_HOP_TOTAL_TIMEOUT_SECONDS=15.0
MULTI_HOP_SLOT_TIMEOUT_SECONDS=5.0
MULTI_HOP_SLOT_EVIDENCE_DOCS=3
FEEDBACK_GOLDEN_SET_PATH=/data/eval/eval_cases.jsonl
```

`AGENTIC_RAG_MAX_RETRIEVALS` 默认允许一次自适应重检索。第一轮质量分低于阈值且仍有预算时，`decision_maker` 会把缺失信息和关键词合入新 query、切到 hybrid、扩大 dense/sparse top_k 后再检索；基础设施错误仍走错误重试路径。这样保留“智能体继续找”的体验，同时避免对同一 query 原样复读。

查询规划产生的 `sub_queries` 会最多取 `AGENTIC_RAG_MAX_SUB_QUERIES` 条并发检索；每路 provider 受 `RETRIEVAL_PROVIDER_TIMEOUT_SECONDS` 控制，整体并发由 `RETRIEVAL_MAX_CONCURRENCY` 控制。

查询分析缓存同样是进程内 TTL 缓存，key 包含租户、用户原问、对话上下文和模型名，避免不同上下文串用规划结果。Prometheus 指标会导出 `agenticrag_cache_hits_total`、`agenticrag_cache_misses_total` 和 `agenticrag_cache_hit_rate`。

`MULTI_HOP_ENABLED=true` 时，`route=multi_hop` 且查询规划包含 `hops` 的问题会在 retriever 内顺序执行多跳检索：前一跳先定位中间实体，再从证据中抽取槽位并渲染后一跳查询。任一规划或抽取失败会降级回普通并发检索。

反馈闭环中的“一键加入 Golden Set”会向 `FEEDBACK_GOLDEN_SET_PATH` 追加 JSONL case。本地开发可使用仓库内相对路径；Docker Compose 会显式设置为 `/data/eval/eval_cases.jsonl` 并把 `/data/eval` 挂载到 `eval_data` 持久卷，避免生产反馈写到源码目录或随容器销毁。仓库内 `tests/eval/eval_cases.jsonl` 仍作为 CI 的离线种子集；需要把运营沉淀纳入评测时，可将持久卷里的 JSONL 导出并合并到评测输入。

### Gradio 配置

```env
API_BASE_URL=http://localhost:8000
GRADIO_SERVER_NAME=0.0.0.0
GRADIO_SERVER_PORT=7860
GRADIO_SHARE=false
```

### React 控制台配置

React 控制台位于 `frontend/`，默认通过 `/api/v1` 访问后端。开发环境可通过 Vite 代理转发 API：

```env
VITE_API_BASE_URL=/api/v1
VITE_API_PROXY_TARGET=http://127.0.0.1:8000
VITE_API_KEY=
```

React 控制台会把 `VITE_API_KEY` 或顶部输入框保存的值作为 `X-API-Key` 请求头；顶部输入框保存到浏览器 `localStorage`，便于本地和部署后手工切换租户 key。

控制台启动后会调用 `/api/v1/auth/me` 推导当前租户和权限范围，文档、Wiki、工作台和反馈页只展示该租户，不再提供手填 `tenant_id` 输入框。认证开启时，后端始终以 API key 绑定的 tenant 为准；认证关闭时仍兼容默认租户或旧接口传入的 `tenant_id`。

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

### 启动 React 控制台

```bash
cd frontend
npm install
npm run dev
```

默认访问：

- React 控制台：`http://127.0.0.1:5173`
- 页面入口：文档管理、Wiki 页面、问答工作台

### Docker Compose

复制并修改环境变量后，可以启动完整本地栈：

```bash
cp env.example .env
docker compose up --build
```

Compose 会启动 PostgreSQL + pgvector、Milvus standalone、FastAPI、Wiki worker 和 React 静态控制台。首次生产化部署建议在 API 启动前显式执行迁移：

```bash
docker compose run --rm api uv run alembic upgrade head
```

默认访问：

- API：`http://127.0.0.1:8000`
- React 控制台：`http://127.0.0.1:5173`
- Prometheus 指标：`http://127.0.0.1:8000/api/v1/health/metrics/prometheus`

## Gradio 界面

Gradio 前端位于 `front/`，包含以下功能页：

- **AgenticRAG 问答**：输入租户 ID 和问题，执行智能问答，可显示查询分析、检索结果、质量分数。
- **查询分析**：仅分析用户问题，返回查询类型、复杂度、关键词、建议检索数量等。
- **文档管理**：上传文件、上传纯文本、查看文档列表、删除文档。
- **系统状态**：检查 API 和 AgenticRAG 图初始化状态。

## React 控制台

React 控制台位于 `frontend/`，是当前主要的生产管理入口：

- **文档管理**：上传/创建文档、查看入库状态、内容 hash、chunk、重新向量化、从文档生成 Wiki。
- **Wiki 页面**：搜索页面、单文档编译、同步/异步批量编译、任务状态轮询、查看/编辑页面、软删除、查看修订历史、查看主题索引、重建页面关系、查看出链和反链；源文档更新后页面会标记为 `stale`。
- **问答工作台**：管理会话，执行 RAG 问答，展示引用、证据卡、不确定性和反馈入口。
- **反馈闭环**：按原因聚合点踩 badcase，查看 query_plan、multi_hop_trace、命中 chunk、质量分和证据卡，并可一键加入 Golden Set 或触发源文档 Wiki 重编。

## API 概览

所有业务接口默认挂载在 `/api/v1` 下。

### 基础与健康检查

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 应用根路径 |
| GET | `/api/v1` | API 根路径 |
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/health/ping` | Ping 检查 |
| GET | `/api/v1/health/metrics` | JSON 格式进程内指标 |
| GET | `/api/v1/health/metrics/prometheus` | Prometheus 文本指标，含 HTTP、租户 token、成本估算与缓存命中率 |
| GET | `/api/v1/auth/me` | 返回当前认证上下文、租户、scope 和写权限 |

### 文档管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/documents/upload` | 上传并解析文件，支持生成向量 |
| POST | `/api/v1/documents` | 创建纯文本文档，支持生成向量 |
| GET | `/api/v1/documents/{document_id}` | 获取单个文档 |
| GET | `/api/v1/documents` | 获取文档列表 |
| POST | `/api/v1/documents/bulk-delete` | 批量删除文档，逐条清理向量与关联 Wiki，返回成功/失败明细 |
| DELETE | `/api/v1/documents/{document_id}` | 删除文档，并删除对应向量与软删除关联 Wiki |
| POST | `/api/v1/documents/{document_id}/retry-delete` | 重试处于删除失败状态的文档 |

### Wiki 页面

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/wiki` | 获取 Wiki 页面列表，支持 `tenant_id`、`knowledge_base`、`status`、`q`、`skip`、`limit`；默认返回 `ready` 与 `stale` |
| GET | `/api/v1/wiki/{page_id}` | 获取 Wiki 页面详情 |
| PUT | `/api/v1/wiki/{page_id}` | 人工校订页面标题、摘要、正文和知识库；支持 `expected_updated_at` 乐观锁冲突检测 |
| DELETE | `/api/v1/wiki/{page_id}` | 软删除 Wiki 页面 |
| GET | `/api/v1/wiki/{page_id}/revisions` | 获取页面修订历史 |
| POST | `/api/v1/wiki/compile` | 从单个源文档编译或刷新 Wiki 页面 |
| POST | `/api/v1/wiki/compile/bulk` | 批量编译 Wiki 页面；`async_compile=true` 时创建后台任务 |
| GET | `/api/v1/wiki/compile/jobs/{job_id}` | 查询后台编译任务状态 |
| GET | `/api/v1/wiki/index/summary` | 获取按知识库聚合的主题索引 |
| POST | `/api/v1/wiki/links/rebuild` | 基于标题提及重建页面关系 |
| GET | `/api/v1/wiki/{page_id}/links` | 获取页面出链和反链 |

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

### 会话接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/conversations` | 获取会话列表 |
| POST | `/api/v1/conversations` | 创建会话 |
| GET | `/api/v1/conversations/{session_id}/messages` | 获取会话消息 |
| POST | `/api/v1/conversations/{session_id}/messages` | 发送会话消息，返回完整结果 |
| POST | `/api/v1/conversations/{session_id}/messages/stream` | 发送会话消息，SSE 返回 answer_delta、quality_warning/quality_done、answer_done 和 final 事件 |

### 反馈闭环接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/feedback/answers` | 提交答案反馈 |
| GET | `/api/v1/feedback/badcases` | 获取点踩 badcase，附带 query_plan、multi_hop_trace、命中 chunk 和 Golden Set 候选 |
| POST | `/api/v1/feedback/answers/{feedback_id}/golden-set` | 将 badcase 候选追加到 `FEEDBACK_GOLDEN_SET_PATH` |
| POST | `/api/v1/feedback/answers/{feedback_id}/wiki-recompile` | 基于命中文档创建 Wiki 重编任务 |
| GET | `/api/v1/feedback/analytics` | 获取反馈聚合与优化建议 |

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

### Wiki 编译

1. 选择已入库文档，调用单文档或批量编译接口。
2. 系统读取源文档和前若干 chunk，优先使用 LLM 编译为长期复用的 Wiki 页面。
3. 如果 LLM 不可用，回退为规则摘要和结构化正文。
4. 保存 `wiki_pages`，记录源文档、源 chunk、知识库、摘要和正文。
5. 每次编译、编辑、删除都会写入 `wiki_page_revisions` 修订快照；人工编辑会在 revision metadata 中记录字段级 diff。
6. 大批量编译可通过 `async_compile=true` 创建 `wiki_compile_jobs`，后台执行并支持锁定、重试和启动恢复。
7. 可调用关系重建接口生成 `wiki_page_links`，用于出链和反链浏览；页面编辑后默认只增量重建触达该页面的链接。
8. 源文档重新摄取后，关联 Wiki 页面会从 `ready` 标记为 `stale` 并清理页面关系；源文档删除前，关联 Wiki 页面会软删除并保留修订记录。

### 问答检索

1. 分析用户查询，生成可执行检索计划和最多 3 个子查询。
2. 对每个子查询并发执行向量、稀疏和 Wiki provider 检索；稀疏检索优先使用 PostgreSQL `to_tsvector('simple', content)` + `plainto_tsquery` 排名，并叠加 trigram/ILIKE 信号兜底；单路 provider 超时后只标记该路错误，不阻塞其它结果。
3. 使用 RRF 融合多子查询、多 provider 的结果。
4. 如果需要重排，调用专用 `/rerank` 接口；如果服务不支持该接口，则保持原召回顺序。
5. 构建上下文和引用来源。
6. 调用 LLM 生成答案。检索上下文会被放入隔离边界并标记为不可信资料；其中出现的角色扮演、忽略规则、泄露密钥或跳过引用等指令只按文档正文处理，不作为系统指令执行。
7. 对答案进行质量评估并返回不确定性提示；默认不进行无改写动作的重复检索。

## 测试

运行测试：

```bash
uv run pytest -q
```

最近一次本地测试结果：

```text
188 passed
```

前端生产构建：

```bash
cd frontend
npm ci
npm run build
```

数据库迁移检查：

```bash
uv run alembic heads
# 20261021_0004 (head)
```

离线质量评测（使用录制结果，适合 CI 或本地回归）：

```bash
uv run python tests/eval/eval_runner.py \
  --cases tests/eval/eval_cases.jsonl \
  --results tests/eval/recorded_results.jsonl
```

该脚本会输出 `recall_at_k`、`mrr`、`citation_accuracy`、`answer_must_mention_accuracy`、`refusal_accuracy` 和 `p95_latency_ms`。`tests/eval/eval_cases.jsonl` 目前提供 51 条可复现种子样本，后续每次改 prompt、切分、检索或 rerank 前后都应保留一份录制结果并对比这些指标。CI 会带阈值参数运行该脚本，任一核心指标低于门槛会直接失败，而不是只打印数字。

语义质量评测需要真实模型作为裁判，因此不放进普通 CI。可在模型服务可用的环境手工或定时执行：

```bash
uv run python scripts/eval_llm_judge.py \
  --cases tests/eval/eval_cases.jsonl \
  --results tests/eval/recorded_results.jsonl \
  --limit 20
```

该脚本会让 LLM-judge 基于问题、参考答案、检索证据和系统答案输出 `groundedness`、`relevance`、`completeness` 与 `hallucination_risk`，并按阈值返回非零退出码。

多跳 golden set 可用录制结果做离线验收：

```bash
uv run python scripts/eval_multi_hop.py \
  --cases tests/fixtures/multi_hop_golden.jsonl \
  --recorded-results tests/fixtures/multi_hop_golden_recorded.jsonl \
  --enforce-thresholds
```

需要真实模型和知识库时，去掉 `--recorded-results` 即可手工跑 live multi-hop golden set；保留 `--enforce-thresholds` 会在低于验收阈值时返回非零退出码。Live 模式会先检查 LLM、Embedding、PostgreSQL 和向量库是否可用，并要求目标租户已导入与 `tests/fixtures/multi_hop_golden.jsonl` 对应的知识库数据；否则会在正式跑题前快速失败并提示依赖缺口。

也可以先只做 live 依赖预检：

```bash
uv run python scripts/eval_multi_hop.py --preflight-only
```

该命令会输出 `{"preflight": ...}` JSON，便于部署脚本或发布检查读取。

CI 位于 `.github/workflows/ci.yml`，会执行 ruff 语法门禁、`uv run pytest -q`、`uv run alembic heads`、离线评测和前端 `npm run build`。

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

- 主要依赖以 `pyproject.toml` / `uv.lock` 为准，不再维护 `requirements.txt`。
- 修改模型、向量库、Reranker 配置后建议重启服务。
- 上传文档前确认 PostgreSQL 和所选向量后端已启动。
