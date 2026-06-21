# AgenticRAG 生产级整改清单（代码审查版）

**日期**：2026-06-14  
**项目路径**：`/Users/bytedance/Desktop/zkc/python/AgenticRAG`  
**审查角色**：Agentic RAG / 生产化架构审查  
**审查范围**：当前工作区相对 `HEAD` 的已修改文件、未跟踪新增文件，以及关键调用链。  
**目标**：把当前项目从“研发原型 / 内部 PoC”推进到“可灰度、可运维、可控风险的生产级 Agentic RAG 服务”。

---

## 0. 结论摘要

项目已经具备较完整的 RAG 主链路：FastAPI API 层、LangGraph Agentic RAG 图、文档解析/切分、Embedding、Milvus / pgvector 抽象、稀疏检索、RRF、Rerank、会话 API、基础状态字段与测试雏形。

但从生产视角看，当前仍属于：

> **中等完成度的内部原型 / 准产品化系统，不建议直接承接真实多租户生产流量。**

本次代码审查确认了若干会直接影响生产正确性、安全边界和数据一致性的缺陷，其中最高优先级包括：

1. **高成本 AI 模型接口存在认证缺口**：`/ai/llm/*`、`/ai/embedding*`、`/ai/rerank*`、`/ai/agentic-rag/analyze` 未接入统一 auth 依赖。
2. **AgenticRAG 查询在默认无认证模式下忽略前端传入的 `tenant_id`**：容易查到默认租户而非用户选择租户。
3. **异步摄取任务是进程内 `create_task`，且唯一内容源保存在内存闭包 / 临时文件中**：进程重启后文档可能永久 pending 且原文丢失。
4. **Reindex 不是幂等操作，会重复追加向量**：多次重建索引会污染召回结果。
5. **向量删除在 Milvus 断连时返回 0 而非失败，SQL 文档仍会被删除**：会留下孤儿向量。
6. **pgvector 后端忽略 `expr` 过滤条件**：后端切换后检索范围比调用方预期更宽。
7. **混合检索任一路失败会把整次查询标为 error，即使另一路已经召回可用文档**：降级路径会反向造成 500。
8. **同步摄取失败后文档可能卡在 `processing`，同步上传临时文件不清理**。
9. **会话消息查询缺少稳定排序**：多轮上下文顺序可能不确定。
10. **请求上下文中间件异常路径不清理 ContextVar / 不记录失败指标**。

---

## 1. 优先级定义

- **P0 / 阻断上线**：会造成越权、数据污染、数据不可恢复、生产流量失败或成本失控；不修复不建议上线。
- **P1 / 灰度前必须完成**：影响稳定性、可观测性、降级、故障恢复和长期运维；建议首批真实租户前完成。
- **P2 / 工程化完善**：影响成本、性能、可维护性和规模化协作；可分迭代持续推进。

---

# 2. P0：阻断上线项

## P0-1. 收敛认证鉴权边界，禁止高成本 AI 接口裸奔

### 现状与证据

文档、会话、向量部分接口已经开始使用 `get_auth_context()` / `get_tenant_id()`，但 AI 模型直通接口仍未统一加认证：

- `app/routes/api.py:15` 注册 `ai.router` 时没有 router-level auth 依赖。
- `app/routes/ai.py:75` `/llm/chat` 无认证，直接调用 LLM。
- `app/routes/ai.py:97` `/llm/completion` 无认证。
- `app/routes/ai.py:131` `/embedding` 无认证。
- `app/routes/ai.py:152` `/embedding/batch` 无认证。
- `app/routes/ai.py:174` `/rerank` 无认证。
- `app/routes/ai.py:196` `/rerank/embeddings` 无认证。
- `app/routes/agentic_rag.py:152` `/agentic-rag/analyze` 无认证，仍调用 `llm_manager.chat_completion()`。

### 生产风险

- 外部调用者可把服务当成公开模型代理使用，消耗 LLM / Embedding / Rerank 配额。
- 无 tenant / user / API key 维度审计，无法追踪成本和滥用来源。
- 在开启 `AUTH_ENABLED=true` 后，团队容易误以为全站已受保护，但实际存在高成本旁路。

### 整改要求

- 在 `/api/v1` 或至少 `/api/v1/ai` router 层建立默认认证依赖，采用**默认拒绝 + 显式公开 allowlist**。
- 所有高成本接口都必须绑定：`tenant_id`、`principal`、`scope`、`request_id`。
- 增加 scope 权限：例如 `llm:invoke`、`embedding:create`、`rerank:invoke`、`rag:query`、`document:write`。
- 对模型直通接口明确定位：生产是否允许暴露；如果只是调试接口，应只在开发环境或内网启用。

### 验收标准

- `AUTH_ENABLED=true` 时，未带有效 API Key 调用所有 `/ai/*` 高成本接口均返回 401。
- 无权限 scope 调用返回 403。
- 每次模型调用审计日志包含 tenant、api_key_name/user_id、endpoint、模型类型、结果、耗时、token/输入条数。
- 增加越权 / 未认证测试覆盖。

---

## P0-2. 修复 AgenticRAG 查询忽略显式 tenant 的开发模式回归

### 现状与证据

前端客户端发送了 `tenant_id`：

- `front/api_client.py:64` `agentic_rag_query(... tenant_id: str = "default")`
- `front/api_client.py:82` 请求体包含 `"tenant_id": tenant_id`

但后端请求模型不接收该字段：

- `app/routes/agentic_rag.py:17` `AgenticRAGRequest` 只有 `query`、`conversation_history`、`max_retrievals`、`stream`。
- `app/routes/agentic_rag.py:45` route 只使用 `tenant_id: str = Depends(get_tenant_id)`。
- `app/auth.py:40` 当 `AUTH_ENABLED=false` 时，`get_tenant_id()` 返回 `settings.DEFAULT_TENANT_ID`。
- `app/auth.py:77` 已有 `resolve_tenant_id(explicit_tenant_id, auth)` 用于“认证关闭时兼容显式 tenant”，但该路由没有使用。

### 生产 / 灰度风险

- 默认开发模式下，用户在前端选择或传入 `acme`，RAG 查询仍查 `default` tenant，表现为“上传成功但问答查不到”。
- 如果演示、灰度、内测环境仍依赖显式 tenant，会产生错误召回或空召回。
- 该问题会掩盖真实多租户链路缺陷，因为文档接口和 RAG 查询接口的 tenant 解析策略不一致。

### 整改要求

短期：

- 为 `AgenticRAGRequest` 增加 `tenant_id: Optional[str]`，route 改为 `auth=Depends(get_auth_context)` 并调用 `resolve_tenant_id(request.tenant_id, auth)`。
- `/agentic-rag/stream` 同步修复。

生产原则：

- 生产认证开启时，永远只信任服务端 auth context 的 tenant。
- 请求体中的 `tenant_id` 只作为本地开发兼容字段，必须在 OpenAPI 文档中标注“生产忽略”。

### 验收标准

- `AUTH_ENABLED=false` 时，上传到 `tenant_id=acme` 后，`/ai/agentic-rag/query` 带 `tenant_id=acme` 能召回该租户文档。
- `AUTH_ENABLED=true` 时，请求体伪造其他 tenant 不生效。
- 增加前后端集成测试覆盖。

---

## P0-3. 用持久化任务系统替换 `InMemoryTaskRunner`，避免异步摄取丢任务 / 丢原文

### 现状与证据

异步上传 / 创建文档时，数据库先提交空内容或空文件路径，然后把唯一内容源放进进程内任务闭包：

- `app/routes/documents.py:351` 上传创建 `Document(content="", file_path=None, ingestion_status=pending)`。
- `app/routes/documents.py:423` 文本创建异步摄取时，`source_payload={"content": document.content}` 仅传入内存闭包。
- `app/routes/documents.py:309` `_schedule_document_ingest()` 用 `lambda` 捕获 `source_payload`。
- `app/tasks.py:12` `InMemoryTaskRunner` 使用进程内 `self._tasks: Dict[str, asyncio.Task]`。
- `app/tasks.py:37` 直接 `loop.create_task(_runner())`。
- `app/tasks.py:40` shutdown 会 cancel 未完成任务，无持久恢复逻辑。

### 生产风险

- 进程重启 / Pod 驱逐 / worker 崩溃后，已返回成功的 pending 文档任务消失。
- 文本文档原文只在内存闭包里，重启后无法恢复。
- 文件上传只把临时路径放在闭包里，且 `file_path=None`，重启后任务和路径都不可恢复。
- 文档会永久停留在 `pending`，无法可靠重试。

### 整改要求

- 引入 durable job：Celery / RQ / Dramatiq / Arq / 数据库 outbox 任一方案。
- 创建 `ingestion_jobs` 表，至少包含：`job_id`、`tenant_id`、`document_id`、`operation`、`status`、`attempt_count`、`next_retry_at`、`payload_ref`、`idempotency_key`、`error`。
- 原始上传文件进入对象存储或持久 staging 目录，不依赖系统 temp + 内存闭包。
- 文本文档异步摄取必须先持久化原文，或将原文作为 durable payload 引用。
- worker 启动时扫描 `pending/running expired` 任务并恢复。

### 验收标准

- API 进程在任务 accepted 后立刻重启，任务仍可被 worker 恢复并完成。
- 同一 `document_id + operation` 重复提交不会产生重复任务副作用。
- 失败任务有可观测状态、错误原因和可重试路径。
- 增加重启恢复测试 / worker crash 测试。

---

## P0-4. 修复 Reindex 非幂等：重建索引前必须删除旧向量或改为 upsert

### 现状与证据

- `app/routes/documents.py:279` `_reindex_document_with_session()` 读取已有 chunks。
- `app/routes/documents.py:294` 直接调用 `_store_document_vectors(...)`。
- `app/routes/documents.py:172` `_store_document_vectors()` 调用 `vector_store.insert_vectors(...)`。
- Milvus 路径 `app/database/milvus.py:293` 使用 `collection.insert(rows)`。
- pgvector 路径 `app/database/vector_store.py:311` 使用 `session.add_all(payload)`。

中间没有 `delete_vectors_by_document_id()`，也没有以 `(tenant_id, document_id, chunk_id)` 为键的 upsert。

### 生产风险

- 多次 reindex 同一文档会追加重复向量。
- 更换 embedding 模型或 chunk 参数后，旧向量仍参与召回，导致重复 / 陈旧 / 错误上下文。
- Rerank 对重复内容浪费 token 和耗时。
- 删除时需要清理越来越多历史向量，故障面扩大。

### 整改要求

- 定义 `IndexLifecycleService`，提供幂等操作：`index_document()`、`reindex_document()`、`delete_document_index()`。
- Reindex 采用以下二选一：
  - **delete-before-insert**：同一事务状态机中先删除旧向量，再写新向量；失败后标记 `vector_status=failed`。
  - **versioned upsert**：新增 `index_generation`，新一代 ready 后切换 active generation，再异步清理旧 generation。
- pgvector 表增加唯一约束或逻辑唯一键：`tenant_id + document_id + chunk_id + index_generation`。

### 验收标准

- 同一文档连续 reindex 3 次，向量数量仍等于 chunk 数量或仅有一个 active generation。
- reindex 中途失败不会把旧 ready 索引破坏成不可用状态。
- 增加 Milvus 与 pgvector 两个后端的一致性测试。

---

## P0-5. 删除文档时向量删除失败必须阻止 SQL 删除，不能静默跳过

### 现状与证据

Milvus 断连时删除向量返回 0，不抛错：

- `app/database/milvus.py:354` `delete_vectors_by_document_id()`。
- `app/database/milvus.py:356` `if not self.connected: ... return 0`。

路由只在异常时阻止 SQL 删除：

- `app/routes/documents.py:488` 调用 `vector_store.delete_vectors_by_document_id()`。
- `app/routes/documents.py:490` 只有捕获异常才标记 `deletion_status=failed`。
- `app/routes/documents.py:496` 随后删除 SQL 文档记录。
- `app/routes/documents.py:592` retry-delete 同样存在该路径。

### 生产风险

- Milvus 短暂断连时，SQL 文档被删除，但向量仍残留在向量库。
- 后续检索可能返回已删除文档内容，造成数据合规和用户信任问题。
- SQL 主记录已删除后，孤儿向量更难定位和补偿。

### 整改要求

- Milvus 未连接、集合不可达、delete 执行异常时必须抛出明确异常。
- 删除流程改为状态机：`active -> deleting -> deleted`，不要在向量清理不确定时硬删主记录。
- 支持软删除：先标记 `deletion_status=pending/failed`，检索层过滤非 active 文档，再由后台任务最终清理 SQL 与向量。
- 增加 orphan vector reconciliation：按 tenant/document_id 扫描和修复。

### 验收标准

- 模拟 Milvus 断连删除文档，API 返回 503，SQL 文档保留且 `deletion_status=failed`。
- 检索层不返回 `deletion_status != active` 的文档。
- 有后台补偿任务能重试删除失败文档。

---

## P0-6. 修复 pgvector 后端忽略 `expr` 过滤条件的问题

### 现状与证据

- `app/routes/vectors.py:30` 将 `request.expr` 传入 `vector_store.search_vectors(...)`。
- `app/database/vector_store.py:340` `PGVectorStore.async_search_vectors(... expr, params ...)` 接收参数。
- `app/database/vector_store.py:367` SQL 只包含 `WHERE tenant_id = :tenant_id`。
- `expr` 和 `params` 没有参与 SQL 构造。
- 对比 Milvus：`app/database/milvus.py:323` 会构造并传入 `effective_expr`。

### 生产风险

- 从 Milvus 切到 pgvector 后，同一 API 的过滤语义改变。
- 调用方以为限定了 document/category/status，实际只限定 tenant，返回更宽结果集。
- Agentic RAG 上下文可能混入不该参与当前问题的文档。

### 整改要求

- 不要把 Milvus 表达式字符串直接透传为跨后端 filter。
- 引入 typed `SearchFilter`：例如 `document_id`、`file_type`、`metadata_equals`、`created_after`、`status`。
- 分别编译为 Milvus expr 和 SQLAlchemy / SQL 条件。
- 对不支持的 filter 明确返回 400，而不是静默忽略。

### 验收标准

- Milvus / pgvector 对 `tenant_id + document_id`、metadata filter 的结果一致。
- pgvector 收到无法支持的 expr 时返回显式错误。
- 增加 backend conformance tests。

---

## P0-7. 混合检索应支持局部降级：一路失败但另一路有结果时不应返回 500

### 现状与证据

`retriever()` 同时允许 vector / sparse 局部失败并继续合并，但随后仍把任一路错误写入全局 error：

- `app/agents/nodes.py:361` 捕获 vector 错误后继续。
- `app/agents/nodes.py:386` sparse 检索失败后继续。
- `app/agents/nodes.py:399` 对已有结果做 RRF 合并。
- `app/agents/nodes.py:425` 只要 `vector_error or sparse_error`，就设置 `state["error"]`。
- `app/routes/agentic_rag.py:69` 只要最终 `result.get("error")`，就返回 HTTP 500。

### 生产风险

- Milvus 临时故障但 PostgreSQL 稀疏检索可用时，系统本可降级回答，却返回 500。
- pg_trgm / sparse 检索异常但向量检索可用时，也可能被标记为失败。
- 这会把降级设计变成“有结果也失败”，显著降低可用性。

### 整改要求

- 区分 `fatal_error` 与 `degraded_warnings`。
- 当 `documents` 非空时：
  - 不设置全局 `error`；
  - 在 `retrieval_attempts` / `context_status` 中记录 degraded warning；
  - 答案 response 包含 `degraded=true` 和失败分支信息。
- 只有所有检索路径均失败或无结果且失败不可恢复时，才进入 retry / error。

### 验收标准

- 模拟 vector 失败、sparse 成功：接口返回 200、包含答案或可用上下文、标记 degraded。
- 模拟 sparse 失败、vector 成功：同上。
- 模拟两路均失败：才返回明确错误。

---

## P0-8. 同步摄取失败必须进入 failed 状态，并清理临时文件

### 现状与证据

- `app/routes/documents.py:197` `_ingest_document_with_session()` 先把 `ingestion_status` 改为 `processing` 并提交。
- `app/routes/documents.py:207` 之后才 `DocumentParser.parse(...)`。
- `app/routes/documents.py:380` 同步上传直接调用 `_ingest_document_with_session()`。
- `app/routes/documents.py:383` 外层异常只记录日志并返回 500，不把文档状态改为 `failed`。
- `app/routes/documents.py:335` 同步/异步上传都会先写 temp 文件。
- `app/routes/documents.py:267` temp 文件清理只在异步后台 `finally` 中，`async_ingest=false` 路径没有对应清理。

### 生产风险

- 上传损坏文件 / 解析异常后，数据库保留 `processing` 文档，用户和运维以为仍在处理中。
- 临时文件长期残留，导致磁盘空间增长。
- 无法通过当前状态机明确区分“仍在处理”和“已失败”。

### 整改要求

- 给同步路径加 `try/except/finally`：失败时更新 `ingestion_status=failed`、`ingestion_error`、`vector_status=failed/not_requested`。
- 同步和异步上传都必须在 finally 中清理 temp 文件；更推荐使用持久对象存储 + 生命周期管理。
- `_ingest_document_with_session()` 不应自行吞掉状态机边界；由上层 job/service 管理状态转换。

### 验收标准

- 损坏文件同步上传返回错误后，文档状态为 `failed`，错误原因可见。
- temp 目录无残留文件。
- 增加解析失败、切分失败、embedding 失败的状态机测试。

---

# 3. P1：灰度前高优先级项

## P1-1. 会话消息必须稳定排序，并建立上下文预算

### 证据

- `app/routes/conversations.py:107` list messages 查询无 `.order_by(...)`。
- `app/routes/conversations.py:152` send message 构造 RAG history 的查询无 `.order_by(...)`。
- `app/routes/conversations.py:160` 直接按 DB 返回顺序构造 `conversation_history`。

### 风险

- PostgreSQL 不保证无 `ORDER BY` 查询顺序；长会话可能出现用户/助手轮次错乱。
- 摘要、trim、latest N turns 都依赖输入顺序，顺序错会造成错误回答。

### 整改要求

- 所有消息查询按 `created_at ASC, id ASC` 排序。
- 读取上下文时不要加载全量历史；改为“latest summary + 最近 N 轮 + token budget”。
- 对 `conversation_history` 做最大条数和最大 token 限制。

### 验收标准

- 多轮会话在重复查询、分页、重启后顺序稳定。
- 超长会话不会超过模型上下文预算。

---

## P1-2. 请求上下文中间件异常路径必须清理 ContextVar 并记录失败指标

### 证据

- `app/middleware/request_context.py:15` `response = await call_next(request)`。
- `app/middleware/request_context.py:17` `finally: pass`。
- `app/middleware/request_context.py:19` 之后才记录 metrics。
- `app/middleware/request_context.py:27` 之后才 `clear_request_context()`。

如果 `call_next()` 抛异常，后续 metrics 和 clear 都不会执行。

### 风险

- 异常请求没有指标记录，错误率不准确。
- ContextVar 中的 request_id / tenant_id 可能泄漏到同一 task 的后续日志。
- 排障时容易丢失原始异常关联。

### 整改要求

- 使用真正的 `try/except/finally`：
  - success 路径记录真实 status；
  - exception 路径记录 500 指标后 re-raise 原异常；
  - finally 必须 reset context token。
- 优先使用 ContextVar token reset，而不是只 set 空值。
- 流式响应要确认中间件行为符合 Starlette/FastAPI 预期。

### 验收标准

- 模拟 endpoint 抛异常后，日志 context 被清理。
- metrics 中记录 500。
- 原始异常不被二次异常掩盖。

---

## P1-3. 后台任务需要并发上限、去重、取消与重试语义

### 证据

- `app/tasks.py:37` 每次 submit 都直接 `loop.create_task(...)`。
- `app/tasks.py:15` `_tasks` 只是内存 dict，重复 task_id 会覆盖引用但旧 task 不会被取消。

### 风险

- 大量上传同时触发解析、embedding、DB 写入、向量写入，可能打满 DB pool 或模型服务。
- 重复 reindex / ingest 难以去重，可能引发重复向量和状态竞争。

### 整改要求

- durable queue 中配置 per-tenant / global concurrency。
- 任务 idempotency key 必须唯一。
- 重复提交时返回已有 job，或显式 cancel/restart。
- 对 embedding / rerank / LLM 加 provider 级限速和退避。

---

## P1-4. Embedding / Rerank / LLM 调用必须批量限额、超时、重试、熔断

### 证据

- `app/routes/documents.py:172` `_store_document_vectors()` 会把所有 chunks 一次性送入 `create_embeddings(texts)`。
- `app/models/embedding.py:91` 批量 embedding 直接调用 provider。
- `app/models/reranker.py:223` 每次 rerank 新建 `httpx.AsyncClient(timeout=60.0)`。

### 风险

- 大文档生成上千 chunks 后，一次 provider 请求可能超 payload / token / input count 限制。
- 失败重试会重复整个大批次。
- 每次 rerank 新建 client 不能复用连接池，增加 p95 延迟和 socket churn。

### 整改要求

- Embedding 分批：配置 `EMBEDDING_BATCH_SIZE`、最大 tokens、最大 chunks。
- 幂等批次写入：每批完成后记录进度。
- Provider 调用统一 timeout、retry with exponential backoff、circuit breaker。
- Reranker 复用生命周期内 `httpx.AsyncClient`，shutdown 时关闭。

---

## P1-5. pg_trgm / vector extension / schema DDL 不应阻断应用启动

### 证据

- `app/database/postgres.py:63` `Base.metadata.create_all` 在启动执行。
- `app/database/postgres.py:64` 无条件 `CREATE EXTENSION IF NOT EXISTS pg_trgm`。
- `app/database/postgres.py:67` 多个 `ALTER TABLE` / `CREATE INDEX` 在应用启动执行。
- `app/main.py:51` PostgreSQL init 失败会 raise，应用启动失败。
- `app/database/vector_store.py:349` pgvector search 热路径调用 `async_ensure_ready()`，其中包含 extension/table/index 检查。

### 风险

- 托管数据库中应用角色可能没有 `CREATE EXTENSION` 权限，导致服务无法启动。
- 多实例并发启动执行 DDL 增加锁和不可控迁移风险。
- 热路径检索混入 DDL 检查，增加延迟和元数据锁风险。

### 整改要求

- 引入 Alembic，所有 DDL 进入 migration。
- 应用启动只做只读 readiness check，不做 schema mutation。
- pgvector / pg_trgm extension 由 DBA / migration 管理。
- `ensure_ready()` 拆为 startup check 和 query-time no-op/cached ready flag。

---

## P1-6. 多租户身份必须从“字符串清洗”升级为“权威身份”

### 风险说明

当前 `validate_tenant_id()` / collection naming 对 tenant 做规范化是必要的，但生产环境不应接受任意外部字符串作为租户身份。否则大小写、符号、历史 ID 迁移可能导致 alias / collision。

### 整改要求

- 建立 Tenant registry：`tenant_id`、display name、status、quota、allowed scopes。
- API Key / JWT subject 绑定 registry tenant。
- 请求中出现非 canonical tenant 时拒绝，而不是静默归一化后继续。
- 所有数据表添加 tenant 外键或至少统一 canonical 约束。

---

## P1-7. 检索后端契约一致性测试

### 整改要求

对 Milvus 与 pgvector 建立统一 conformance tests：

- insert/search/delete 基本语义一致。
- tenant 隔离一致。
- document_id / metadata filter 一致。
- 维度不匹配错误一致。
- 空集合 / 空查询返回一致。
- 删除不存在文档语义一致。

---

## P1-8. 错误响应标准化，避免 `detail=str(e)` 暴露内部细节

### 现状

多个 route 捕获异常后直接 `HTTPException(status_code=500, detail=str(e))`。

### 整改要求

统一错误结构：

```json
{
  "code": "VECTOR_BACKEND_UNAVAILABLE",
  "message": "向量检索服务暂不可用，请稍后重试",
  "request_id": "...",
  "details": null
}
```

生产环境不返回内部 exception、SQL、provider 原始错误；内部日志保留完整 traceback 和 request_id。

---

# 4. P2：工程化与长期优化

## P2-1. 抽象 `IndexLifecycleService` 和 `RetrievalService`

当前 document routes 直接编排 parse/split/embed/vector insert/delete/reindex，Agentic RAG 节点也直接调用多个底层组件。建议抽象：

- `DocumentIngestionService`
- `IndexLifecycleService`
- `RetrievalService`
- `ConversationContextService`

Route 只负责鉴权、参数校验、调用 service、返回响应。

---

## P2-2. 统一 query analyzer 实现，避免诊断 endpoint 与真实图分叉

### 证据

- `app/agents/nodes.py:181` `query_analyzer()` 是真实图使用的分析逻辑。
- `app/routes/agentic_rag.py:152` `/agentic-rag/analyze` 重新实现了一套较旧 prompt 和 JSON 解析。

### 风险

诊断 endpoint 给出的 plan 与真实 RAG 执行 plan 不一致，误导前端和调试。

### 整改要求

- 把 analyzer 抽为共享 service。
- `/analyze` 只调用同一 analyzer，并返回同一 normalized schema。

---

## P2-3. 优化混合检索性能

当前 `retriever()` 先做 embedding/vector/hydrate，再做 sparse；两路相对独立，且 dense hits 在 RRF 前已经 hydrate。

建议：

- sparse search 与 dense embedding/vector pipeline 并发执行。
- 先按 ID 做 RRF，最终 top N 再 hydrate。
- 记录各分支耗时：embedding_ms、vector_ms、sparse_ms、hydrate_ms、rerank_ms。

---

## P2-4. 生产可观测性补齐

需要增加：

- Prometheus metrics：请求数、延迟、错误率、provider 调用耗时、embedding batch size、vector search latency、job backlog。
- OpenTelemetry tracing：API -> DB -> vector store -> embedding/rerank/LLM。
- JSON structured logging：request_id、tenant_id、user_id、document_id、job_id、operation、status。
- 审计日志与技术日志分离。

---

## P2-5. 文件上传安全与资源治理

- 限制单文件大小、总存储、单租户文档数。
- MIME + 扩展名双校验。
- PDF / Office 解析加超时、内存限制、页数限制。
- 拒绝加密文件、畸形文件。
- 解析任务放到隔离 worker / sandbox。

---

## P2-6. 配额、限流与成本控制

- 每 IP、每 tenant、每 API key 限流。
- 高成本接口独立限流：RAG query、embedding batch、rerank、upload/reindex。
- tenant 级 token quota、embedding quota、存储 quota。
- top_k、rerank_top_k、max_retrievals、history 长度硬上限。

---

## P2-7. 发布、迁移、测试体系

- Alembic baseline migration。
- Dockerfile / docker-compose / Helm。
- CI：lint、type check、unit、integration、migration check。
- 真 PostgreSQL + pgvector 集成测试。
- Milvus 集成测试或 Testcontainers。
- 故障注入：模型超时、向量库断连、DB rollback、worker crash。
- 压测：大文件、多租户并发、长会话、多轮检索。

---

# 5. 建议实施顺序

## 第一阶段：立即修复的 P0 patch（1-3 天）

1. 给 `/ai/*` 高成本接口和 `/agentic-rag/analyze` 补认证依赖或开发环境开关。
2. 修复 AgenticRAG request tenant 解析：`tenant_id + resolve_tenant_id()`。
3. 修复混合检索局部失败逻辑：有结果时返回 degraded 而不是 error。
4. 修复同步摄取失败状态和 temp 文件清理。
5. Milvus 未连接删除向量时改为抛错，阻止 SQL 删除。
6. Reindex 前先删除旧向量，至少先实现 delete-before-insert。
7. pgvector 对 `expr` 不支持时显式 400/501，避免静默忽略；随后实现 typed filter。
8. 会话消息查询加 `order_by(created_at, id)`。
9. RequestContextMiddleware 异常路径 finally 清理。

## 第二阶段：生产化重构（1-2 个迭代）

1. 引入 durable job / outbox，替换 `InMemoryTaskRunner`。
2. 建立 ingestion/index/delete 状态机和补偿任务。
3. 引入 Alembic，移除启动 DDL。
4. 建立 typed SearchFilter 和后端契约测试。
5. Provider 调用治理：batch、timeout、retry、breaker、quota。
6. 统一错误码、审计日志、metrics、tracing。

## 第三阶段：规模化优化（持续）

1. 正式 Tenant registry / AuthZ scope。
2. Conversation context budget + summary lifecycle。
3. 检索并发优化、缓存、embedding cache。
4. 存储分层：原始文件对象存储、正文/chunk 分层、冷热数据分离。
5. 压测容量模型与 SLO / error budget。

---

# 6. 验收用例清单

## 安全 / 租户

- [ ] `AUTH_ENABLED=true` 时，所有 `/api/v1/ai/*` 未认证请求返回 401。
- [ ] API Key A 无法访问 API Key B 的文档、会话、向量。
- [ ] 请求体伪造 `tenant_id` 不影响认证上下文 tenant。
- [ ] `AUTH_ENABLED=false` 开发模式下，显式 `tenant_id` 在 documents、vectors、agentic-rag 查询路径语义一致。

## 文档摄取 / 任务

- [ ] accepted 后重启 API/worker，任务可恢复。
- [ ] 文本文档 async create 后重启，不丢原文。
- [ ] 文件 async upload 后重启，不丢文件引用。
- [ ] 解析失败进入 `ingestion_status=failed`，不会卡 `processing/pending`。
- [ ] 同步上传成功/失败都不残留 temp 文件。

## 向量生命周期

- [ ] 同一文档重复 reindex 不增加 active vector 数。
- [ ] reindex 失败不会污染旧 ready 索引。
- [ ] Milvus 断连删除文档返回失败，SQL 文档不被硬删。
- [ ] orphan vector reconciliation 能发现并修复孤儿向量。

## 检索

- [ ] pgvector 与 Milvus 对 document_id filter 结果一致。
- [ ] vector 失败 sparse 成功时 RAG 返回 200 degraded。
- [ ] sparse 失败 vector 成功时 RAG 返回 200 degraded。
- [ ] 两路均失败才返回明确错误。
- [ ] 多轮会话上下文顺序稳定。

## 运维

- [ ] 启动不执行 DDL；migration 独立可审计可回滚。
- [ ] 所有请求有 request_id，异常路径也有 metrics。
- [ ] Provider 超时/失败有重试、熔断和告警。
- [ ] 限流与 quota 生效，并能按 tenant 观测成本。

---

# 7. 本次审查确认的高风险缺陷 JSON 摘要

```json
[
  {
    "file": "app/routes/ai.py",
    "line": 75,
    "summary": "高成本 LLM/Embedding/Rerank 直通接口缺少认证依赖，可被未认证调用消耗模型资源。",
    "failure_scenario": "AUTH_ENABLED=true 后，攻击者仍可直接调用 /api/v1/ai/llm/chat 或 /embedding/batch 消耗 token 和 embedding 配额。"
  },
  {
    "file": "app/routes/agentic_rag.py",
    "line": 17,
    "summary": "AgenticRAGRequest 不接收 tenant_id，默认无认证模式下会忽略前端传入租户。",
    "failure_scenario": "用户上传到 tenant=acme 后前端查询也发送 acme，但后端使用 DEFAULT_TENANT_ID 检索，返回空结果或错误租户结果。"
  },
  {
    "file": "app/routes/documents.py",
    "line": 423,
    "summary": "异步文档摄取把唯一原文保存在进程内任务闭包，任务丢失后文档永久 pending 且原文不可恢复。",
    "failure_scenario": "POST /documents/ 默认 async_ingest=true 返回成功后进程重启，数据库只有 content=''，后台任务和原文都丢失。"
  },
  {
    "file": "app/routes/documents.py",
    "line": 295,
    "summary": "reindex 直接 insert 新向量，未删除或 upsert 旧向量。",
    "failure_scenario": "同一文档连续重建索引多次，向量库中出现多份相同 document_id/chunk_id，召回重复和陈旧内容。"
  },
  {
    "file": "app/database/milvus.py",
    "line": 356,
    "summary": "Milvus 未连接时 delete_vectors_by_document_id 返回 0，路由会继续删除 SQL 文档。",
    "failure_scenario": "Milvus 短暂断连时删除文档，SQL 行被删除但向量残留，后续检索可能返回已删除内容。"
  },
  {
    "file": "app/database/vector_store.py",
    "line": 367,
    "summary": "pgvector 检索忽略 expr 过滤条件。",
    "failure_scenario": "调用 /vectors/search 传入 document/category filter，pgvector 只按 tenant 过滤，返回同租户其他文档内容。"
  },
  {
    "file": "app/agents/nodes.py",
    "line": 425,
    "summary": "混合检索任一路失败会设置全局 error，即使另一路已有可用文档。",
    "failure_scenario": "Milvus 故障但 sparse 检索召回结果，最终仍因 result.error 被 /agentic-rag/query 转成 HTTP 500。"
  },
  {
    "file": "app/routes/documents.py",
    "line": 380,
    "summary": "同步上传摄取失败不标记 failed，且同步路径不清理临时文件。",
    "failure_scenario": "损坏文件 async_ingest=false 上传后解析异常，文档卡 processing，temp 文件残留在系统临时目录。"
  },
  {
    "file": "app/routes/conversations.py",
    "line": 152,
    "summary": "构造 RAG 会话历史时没有 order_by，消息顺序不确定。",
    "failure_scenario": "数据库返回非时间顺序消息，LLM 看到错乱对话上下文并基于错误轮次回答。"
  },
  {
    "file": "app/middleware/request_context.py",
    "line": 17,
    "summary": "请求处理中抛异常时中间件不会清理 request context，也不会记录失败指标。",
    "failure_scenario": "endpoint 抛出未处理异常后，ContextVar 中的 request_id/tenant 可能污染后续日志，metrics 漏记 500。"
  }
]
```

---

# 8. 最终建议

未来 1-2 个迭代不要继续优先堆 Agentic RAG 功能，而应切换到“生产化收敛”：

1. **先封安全边界**：认证、授权、tenant、quota。
2. **再固化数据生命周期**：ingest / index / reindex / delete 全部幂等、可恢复、可补偿。
3. **然后补可运维性**：metrics、trace、审计、错误码、SLO。
4. **最后做规模优化**：缓存、并发检索、批处理、上下文预算、存储分层。

修完 P0 后，项目可以进入受控灰度；修完 P1 后，才建议接入真实多租户生产流量。
