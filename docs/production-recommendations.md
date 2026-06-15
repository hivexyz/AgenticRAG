# AgenticRAG 生产级部署建议

> 基于对项目代码的全面走查，从架构设计、可靠性、可观测性、安全性、性能等维度，给出生产环境部署的建议。

---

## 一、架构与流程

### 1.1 当前状态

项目是一个基于 **FastAPI + LangGraph** 的多租户 RAG 系统，采用 6 节点 DAG 流程：

```
query_analyzer → retriever → reranker → context_builder → answer_generator → quality_evaluator
                                                                                    ↑
                                                                    (retry loop)    |
                                                                    ────────────────┘
```

亮点：
- 支持 Milvus / pgvector 双向量后端，通过 `ConfigurableVectorStore` 抽象切换
- 混合检索（向量 + 稀疏 + RRF 融合）
- 多租户（API Key 绑定 tenant，Milvus 按 tenant 分 collection）
- 异步文档摄取（`InMemoryTaskRunner` 进程内后台任务）
- 质量评估 + 重试机制

### 1.2 建议：补齐缺失的 Query Rewrite 节点

**现状：** `AgenticRAGState` 中定义了 `query_rewrites: List[str]`，但没有任何节点填充它。检索始终使用原始 `user_query`，重试时不改写查询，只能改变检索参数，无法纠正检索方向。

**建议方案：**

在 `query_analyzer` 和 `retriever` 之间插入一个 `query_rewriter` 节点，逻辑如下：

1. **首次检索：** 将 `query_analyzer` 产生的 `sub_queries` 写入 `query_rewrites`
2. **重试时：** 如果 `quality_score < threshold` 且 `retrieval_count > 0`，让 LLM 基于 `quality_evaluation` 中的 `missing_information` 和 `retrieval_feedback` 改写查询，生成新的 `query_rewrites`，并将 `current_query` 设置为改写后的最优查询
3. **改写策略：** 支持同义改写、抽象化/具体化、拆分子问题、关键词扩展等

**为什么需要：** 当前重试循环回 `retriever` 时，`current_query` 不变，仅靠调整 `top_k` 或 `route` 无法解决"查询与文档术语不匹配"的核心问题。Query Rewrite 是 Agentic RAG 区别于普通 RAG 的关键能力。

### 1.3 建议：修复质量评估节点

**问题：** `quality_evaluator` 只让 LLM 输出一个 0-1 的分数，但评估维度不够结构化，且 `decision_maker` 没有利用 `quality_evaluation` 字段（State 中定义了该字段但从未被填充）。

**`nodes.py:624-701` 中 `quality_evaluator` 的问题：**
- 评分 prompt 只要求输出一个分数，没有具体维度
- 没有将评估结果存入 `state["quality_evaluation"]`
- 缺少 `groundedness`（基于上下文）、`answer_relevance`（与问题相关性）、`completeness`（完整性）等维度的评估
- 评估结果没有反馈给重试逻辑，无法指导改写方向

**建议：** 让 `quality_evaluator` 输出结构化 JSON：

```json
{
  "groundedness": 0.85,
  "answer_relevance": 0.90,
  "completeness": 0.70,
  "context_sufficiency": 0.65,
  "missing_information": ["缺少关于XX的详细信息"],
  "quality_score": 0.75,
  "should_continue": true,
  "feedback_for_retrieval": "需要补充XX方面的文档"
}
```

将结果存入 `state["quality_evaluation"]`，并在 `decision_maker` 和新的 `query_rewriter` 中消费。

### 1.4 建议：条件路由优化

**问题：** 当前图是严格线性的，所有节点都执行。但 `query_analyzer` 已经识别了 `route`（`direct` / `vector` / `hybrid` / `multi_hop`）和 `query_type`（`greeting` / `chitchat`），问候和闲聊在节点内部通过 `if` 短路跳过——逻辑正确但流程不透明。

**建议：** 在 `query_analyzer` 之后使用条件边：

```python
workflow.add_conditional_edges(
    "query_analyzer",
    route_decision,
    {
        "direct_reply": "answer_generator",
        "retrieve": "retriever",
    }
)
```

这样 `direct` 路由的查询（问候、闲聊）直接跳到答案生成，避免无意义的空检索和空重排序，也更便于监控和调试。

---

## 二、可靠性

### 2.1 建议：任务队列替换 InMemoryTaskRunner

**现状：** `app/tasks.py` 使用 `InMemoryTaskRunner`，任务存储在进程内存中，进程重启后丢失。

**风险：**
- 进程崩溃/重启后，正在进行的异步文档摄取任务永久丢失
- 无法重试失败任务
- 无法观测任务状态（pending/running/done/failed）
- 无法横向扩展（多 worker 场景下任务无法共享）

**建议：** 使用以下方案之一：

| 方案 | 适用场景 | 复杂度 |
|------|---------|--------|
| **Celery + Redis** | 中大型项目，需要完善的任务调度 | 中 |
| **ARQ + Redis** | 轻量异步任务，Python 原生 async | 低 |
| **BackgroundTasks (FastAPI 内置)** | 极轻量场景，可接受进程重启丢失 | 极低 |

推荐 **ARQ**：与 FastAPI async 生态一致，支持重试、延迟任务、cron 调度，Redis 做 broker。

### 2.2 建议：LLM 调用增加重试和熔断

**问题：** `LLMManager.chat_completion()` 没有重试机制，单次调用失败直接抛出异常，导致整个 RAG 流程中断。

**建议：**

```python
import tenacity

@tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
    retry=tenacity.retry_if_exception_type((httpx.TimeoutException, httpx.RemoteProtocolError)),
)
async def chat_completion(...):
    ...
```

同时对 LLM 调用增加超时配置（当前 `httpx.AsyncClient` 在 Reranker 中有 60s 超时，但 LLM chat 调用没有显式超时）。

### 2.3 建议：Milvus 连接池与健康检查

**问题：** `MilvusManager` 使用全局单例连接，没有连接池。如果连接断开（如网络闪断），后续请求会失败，直到下次重启。

**建议：**
- 在 `search_vectors` / `insert_vectors` 调用前增加健康检查（ping），失败时自动重连
- 或使用 `pymilvus` 的连接池功能
- 启动时做 readiness probe：`connections.list_connections()` 检查连接状态

### 2.4 建议：数据库会话管理规范

**问题：** `app/routes/documents.py` 中使用了 `Depends(postgres_manager.get_session)` 注入会话，但 `postgres_manager.get_session()` 是一个 `async generator`，它内部调用了 `session.commit()` 和 `session.close()`。如果路由处理函数中出现未捕获异常，`finally` 块中的 `close()` 会执行，但 `commit()` 可能不会。实际行为依赖于 FastAPI 的依赖注入生命周期。

**建议：**
- 不要在 `get_session` generator 中自动 commit——让路由函数显式调用 `await session.commit()`
- 或使用 FastAPI 的 `yield` 模式，在 `try/finally` 中只做 rollback 和 close，commit 由调用方控制

### 2.5 建议：向量维度不一致的防护

**`config.py:118-120`** 已有 `vector_dimensions_aligned` 属性检查，但 `MilvusManager.ensure_ready()` 中检测到维度不一致时直接抛出 `RuntimeError`，应用启动即失败。

**建议：** 在 startup 过程中捕获此错误，记录清晰的日志，并在 `/health/ready` 端点中暴露具体原因，方便运维排查。同时考虑在 `ensure_ready` 中提供自动迁移选项（如先删除旧集合再重建）。

---

## 三、可观测性

### 3.1 建议：引入 OpenTelemetry 追踪

**现状：** `app/observability.py` 提供了基础的 request_id、metrics 计数器、审计日志。但缺少分布式追踪能力。

**建议：** 为 LangGraph 节点添加 OpenTelemetry span：

```python
from opentelemetry import trace
tracer = trace.get_tracer(__name__)

async def query_analyzer(state):
    with tracer.start_as_current_span("query_analyzer") as span:
        span.set_attribute("user_query", state["user_query"])
        ...
```

这样可以追踪每个节点耗时、LLM 调用次数、检索延迟等，在 Jaeger/Zipkin 中可视化整个 RAG 流水线。

### 3.2 建议：结构化日志增强

**现状：** 日志使用 loguru + JSON 文件输出，已包含 `request_id`、`tenant_id` 等上下文。但缺少以下关键信息：

- 每个节点的执行耗时
- LLM 调用的 token 用量（已在 `LLMManager.chat_completion` 返回中，但未记录到日志）
- 检索命中的文档 ID 列表

**建议：** 在每个节点入口和出口记录耗时 + 关键指标：

```python
logger.info(f"节点完成: retriever", duration_ms=..., results_count=..., ...)
```

### 3.3 建议：Metrics 暴露

**现状：** `MetricsRegistry` 仅在内存中维护计数器，没有暴露端点。

**建议：** 增加 `/metrics` 端点（Prometheus 格式），或使用 `prometheus-fastapi-instrumentator` 自动暴露。关键指标：
- RAG 查询 QPS、延迟（P50/P95/P99）
- 各节点耗时分布
- LLM 调用次数、token 消耗、错误率
- 检索命中率、重排序有效率
- 质量评分分布

### 3.4 建议：审计日志完善

**现状：** `log_audit_event` 已在文档 CRUD 操作中使用。但 RAG 查询本身（最主要的业务操作）没有审计日志。

**建议：** 在 `agentic_rag_query` 和 `agentic_rag_stream` 中记录审计日志，包含 `user_query`、`answer`、`quality_score`、`retrieval_count`、`tenant_id`。

---

## 四、安全性

### 4.1 建议：API Key 管理

**现状：** `AUTH_API_KEYS` 通过环境变量 `key1:tenant_a,key2:tenant_b` 格式配置，存储在内存中。

**问题：**
- 明文存储 API Key
- 无法动态增删（需重启服务）
- 无速率限制
- 无使用量统计

**建议：**
- 短期：API Key 做哈希存储（如 `hashlib.sha256(key).hexdigest()`），配置中只存哈希值
- 中期：将 API Key 管理迁移到数据库，提供管理接口
- 增加速率限制（如 `slowapi` 或 Redis 令牌桶）

### 4.2 建议：输入验证

**问题：** 用户查询直接传入 LLM，没有注入防护。虽然 LLM 场景下 SQL 注入风险较低（因为不直接拼接 SQL），但 Prompt Injection 是一个真实风险。

**建议：**
- 对用户输入做长度限制（如 2000 字符）
- 在 `answer_generator` 的 system prompt 中加入防护指令
- 考虑使用 LLM 护栏（guardrails）如 `llama-guard` 或自定义规则

### 4.3 建议：文件上传安全

**`app/utils/files.py`** 已有文件名清理，但缺少以下防护：

- 文件大小限制（FastAPI 层面，如 `maximum_upload_size`）
- 文件类型白名单（当前接受任意类型）
- 病毒扫描（如有需要）
- 上传文件存储路径应在配置中明确，避免路径遍历

**建议：** 在 `upload_document` 中加入文件大小和类型校验。

### 4.4 建议：依赖安全

**问题：** `requirements.txt` 中 `marshmallow==3.0.0rc7` 是 release candidate 版本，不应在生产环境使用。

**建议：** 升级到 `marshmallow>=3.20.0` 稳定版本。运行 `pip-audit` 或 `safety check` 扫描已知漏洞。

---

## 五、性能优化

### 5.1 建议：Embedding 调用批量化

**现状：** `retriever` 节点逐个创建 embedding（`embedding_manager.create_embedding(current_query)`），虽然是单查询场景，但 `_store_document_vectors` 中已使用 `create_embeddings` 批量接口。

**问题：** 如果 `query_rewriter` 节点产生多个改写查询，应使用批量 embedding 接口。

**建议：** 在 `retriever` 中，如果 `sub_queries` 有多个，使用 `create_embeddings` 批量获取向量。

### 5.2 建议：检索结果缓存

**建议：** 对相同/相似查询的检索结果做缓存。方案：
- 对 `(tenant_id, current_query, top_k)` 三元组做哈希，缓存到 Redis
- 对 `content_hash` 相同的文档 chunk 做去重，避免重复的 embedding 计算
- TTL 根据文档更新频率设定（如 5-30 分钟）

### 5.3 建议：连接池参数调优

**`config.py` 中的默认值：**
- `POSTGRES_POOL_SIZE=10`，`POSTGRES_MAX_OVERFLOW=20` — 对于生产环境，应根据实际并发量调整
- LLM 调用没有连接池大小限制（`AsyncOpenAI` 默认无限制）

**建议：**
- 根据压测结果调整 PostgreSQL 连接池（通常 `pool_size = 2 * CPU cores`）
- 为 LLM 调用添加并发限制（使用 `asyncio.Semaphore`），防止 API 限流

### 5.4 建议：Context Builder 的硬编码 top-5

**问题：** `nodes.py:539` 中 `context_builder` 硬编码取前 5 个文档构建上下文：

```python
for i, doc in enumerate(results[:5], 1):
```

**建议：** 使用 `query_plan` 中的 `rerank_top_n` 或 `answer_style` 动态决定取多少文档。对于 `detailed` 或 `steps` 风格，可能需要更多上下文。

---

## 六、测试与 CI/CD

### 6.1 建议：测试覆盖

**现状：** `tests/` 目录存在但为空。`pyproject.toml` 中定义了 pytest 依赖，但没有测试文件。

**建议优先级：**

| 优先级 | 测试类型 | 覆盖范围 |
|--------|---------|---------|
| P0 | 单元测试 | `nodes.py` 中各节点的错误路径、`decision_maker` 逻辑 |
| P0 | 集成测试 | 完整的 RAG 流程 end-to-end（使用 mock LLM） |
| P1 | API 测试 | 所有路由的 HTTP 状态码和响应格式 |
| P1 | 数据库测试 | 文档 CRUD、向量存储、租户隔离 |
| P2 | 性能测试 | 并发查询、大批量文档摄取 |

### 6.2 建议：pre-commit 钩子

**建议：** 配置 `.pre-commit-config.yaml`：
- `black` 格式化
- `flake8` / `ruff` 检查
- `mypy` 类型检查
- `bandit` 安全扫描

### 6.3 建议：Docker 化

**建议：** 提供 `Dockerfile` 和 `docker-compose.yml`，包含：
- FastAPI 应用容器
- PostgreSQL 容器
- Milvus 容器（或 pgvector 替代）
- 可选 Redis 容器（用于缓存和任务队列）

---

## 七、文档与运维

### 7.1 建议：补充文档

- **API 文档：** 当前 FastAPI 的 `/docs` 已自动生成，但缺少请求/响应示例
- **运维手册：** Milvus 索引参数调优、向量维度变更流程、租户管理
- **故障排查：** 常见错误码及解决方案

### 7.2 建议：健康检查增强

**`app/main.py`** 中的健康检查已经比较完善，区分了 `required` 和 `optional` 组件。建议：

- 在 `/health/ready` 中返回各组件的详细状态（当前只有 `APP_STATE` 的 `_is_ready()` 检查）
- 添加 `/health/live`（liveness，仅检查进程存活）和 `/health/ready`（readiness，检查所有依赖）的 Kubernetes 标准端点

---

## 八、总结优先级

按紧急程度和影响范围排序：

| 优先级 | 建议 | 影响 |
|--------|------|------|
| **P0** | 质量评估结构化 + 填充 `state["quality_evaluation"]` | 当前质量评估信息无法被下游消费 |
| **P0** | LLM 调用增加重试机制 | 单次网络抖动导致整个查询失败 |
| **P0** | 修复 `marshmallow==3.0.0rc7` 依赖 | 使用 RC 版本存在未知风险 |
| **P1** | 添加 Query Rewrite 节点 | 重试循环的核心能力缺失 |
| **P1** | 任务队列替换 InMemoryTaskRunner | 进程重启丢失异步任务 |
| **P1** | 条件路由（direct vs retrieve） | 减少无效节点执行 |
| **P1** | Milvus 连接健康检查与自动重连 | 网络闪断后服务不可用 |
| **P2** | OpenTelemetry 追踪 | 性能瓶颈分析和故障排查 |
| **P2** | 检索结果缓存 | 降低延迟和 LLM 成本 |
| **P2** | API Key 增强（哈希存储、速率限制） | 提升安全性 |
| **P2** | 容器化与 CI/CD | 标准化部署流程 |
| **P3** | Metrics 暴露端点 | 运维监控 |
| **P3** | 审计日志覆盖 RAG 查询 | 合规与问题回溯 |
| **P3** | 测试体系建设 | 代码质量保障 |