# 代码审查报告

**日期**: 2026-06-12  
**项目**: AgenticRAG  
**审查范围**: 当前工作区（FastAPI 后端、AgenticRAG、向量存储、Gradio 前端、测试与文档）  
**审查方式**: 静态代码审查 + 运行现有测试套件

---

## 审查结果概览

- **测试结果**: `pytest -q` 通过，52 passed，8 warnings。
- **本次入库问题**: 10 条。
- **高优先级**: 4 条。
- **中优先级**: 4 条。
- **低优先级**: 2 条。
- **主要风险面**: 启动健康语义、向量存储一致性、生产数据暴露、pgvector 初始化参数丢失、依赖声明漂移。

---

## 🔴 高优先级问题

### 1. 启动时数据库/向量库初始化失败被吞掉，服务仍对外宣称健康

- **位置**: `app/main.py:37-52`, `app/routes/health.py:11-21`
- **问题**: `startup_event()` 对 PostgreSQL 和向量库初始化异常只记录日志，不中断启动，也没有把失败状态写入健康检查。与此同时 `/api/v1/health/` 固定返回 `{"status": "healthy"}`。
- **影响**: 在 PostgreSQL 连接失败、Milvus/pgvector 不可用或 schema 初始化失败时，负载均衡/容器编排仍可能把实例视为可用，随后业务请求才大量返回 500/503。对于 RAG 服务，这会直接影响文档入库、检索、删除等核心链路。
- **建议**: 对必需依赖（至少 PostgreSQL）启动失败应 fail fast；可选依赖应记录到应用级状态，并让 health/readiness 区分 `live` 与 `ready`。例如 `/health` 只表示进程存活，新增 `/ready` 检查 DB、向量库、模型客户端初始化状态。

### 2. 文档创建/上传在向量写入失败后仍返回成功，导致“有文档无向量”的静默不一致

- **位置**: `app/routes/documents.py:218-227`, `app/routes/documents.py:279-287`
- **问题**: 当 `store_vectors=True` 时，embedding 或向量库写入失败只被 `logger.warning` 记录，接口仍返回 200 和文档创建成功。
- **影响**: 调用方会认为文档已经可检索，但 AgenticRAG 和 `/ai/search` 实际找不到该文档；数据库与向量索引长期不一致，且用户没有可见信号触发重试或补偿。
- **建议**: 明确语义：如果 `store_vectors=True` 是强需求，应在向量写入失败时回滚文档事务或返回 503/207 类状态；如果允许异步补偿，应在文档表增加 `vector_status`/`vector_error` 字段，并在响应中暴露 `vector_indexed=false`，同时提供重建索引接口。

### 3. 删除文档时先删向量再删数据库，数据库删除失败会造成“文档仍在但向量已删”

- **位置**: `app/routes/documents.py:371-382`
- **问题**: 删除流程先调用 `vector_store.delete_vectors_by_document_id()`，成功后才 `session.delete(document)` 和 `commit()`。若数据库删除或提交失败，向量已经不可恢复地删除。
- **影响**: 文档列表仍显示该文档，但检索无法命中；后续再次删除可能返回 `deleted_vectors=0`，状态难以解释和修复。
- **建议**: 使用删除状态机或 outbox/后台任务保证最终一致性。较小改法是先在 DB 标记 `deleting/deleted`，提交后删除向量，失败时保留可重试状态；或在向量删除失败时保留 DB 记录但明确返回待重试状态。

### 4. 文档详情/列表响应直接返回完整正文，容易在生产中泄露大文本或敏感内容

- **位置**: `app/db_models/document.py:53-68`, `app/routes/documents.py:326-343`, `app/routes/documents.py:298-318`
- **问题**: `Document.to_dict()` 始终包含完整 `content`，列表接口 `/documents/` 对每个文档也返回全文。
- **影响**: 文档列表可能传输大量内容，造成响应变慢、内存/带宽浪费；更重要的是，一旦该 API 暴露给前端或多用户环境，列表页即可批量读取完整文档内容，缺少最小披露原则。
- **建议**: 列表响应使用摘要模型（不含 `content` 或只含 preview），详情接口再按权限返回全文；同时限制 `limit` 最大值并增加认证/授权后再用于生产。

---

## 🟡 中优先级问题

### 5. pgvector 后端的 `ensure_ready()` 适配器丢弃了 `dimension`、`collection_name`、`load` 等入参

- **位置**: `app/database/vector_store.py:442-452`, `app/database/vector_store.py:248-262`
- **问题**: `AsyncVectorStoreAdapter.ensure_ready()` 一旦发现底层有 `async_ensure_ready`，只转发 `create_index` 和 `tenant_id`，忽略 `dimension`、`collection_name`、`load`。`PGVectorStore.async_ensure_ready()` 本身也不接收/校验 `dimension`。
- **影响**: `/api/v1/vectors/collection?dimension=...` 在 pgvector 模式下看似成功，但实际不会按调用方维度建表，也不会发现与 `settings.vector_dimension` 的不一致；排障时会出现“API 参数已传但无效果”的隐性配置错误。
- **建议**: 对 pgvector 明确拒绝无意义的 `collection_name/load`；对 `dimension` 做显式校验（必须等于 `settings.vector_dimension`），不匹配返回 400/503，而不是静默忽略。

### 6. 文本上传元数据只校验 JSON 格式，不校验必须为对象

- **位置**: `front/app.py:200-207`, `app/routes/documents.py:31-45`, `app/routes/documents.py:246-295`
- **问题**: 文件上传路径已有 `_parse_metadata_json()`，会拒绝非对象 metadata；但 Gradio 的纯文本上传仅 `json.loads()`，若用户输入 `[1,2]` 会传给后端 `DocumentCreate.metadata: Optional[Dict]`，由 Pydantic 返回默认 422，前端显示为泛化请求失败。
- **影响**: 同一个“文档元数据”字段在文件上传和纯文本上传表现不一致，用户体验和 API 契约不统一。
- **建议**: 前端纯文本上传也增加 `isinstance(metadata_dict, dict)` 校验；后端可为 `DocumentCreate` 增加更明确的校验错误消息，与 `/upload` 保持一致。

### 7. AI/AgenticRAG 查询入参缺少边界约束，可能触发昂贵或异常调用

- **位置**: `app/routes/ai.py:56-61`, `app/routes/ai.py:198-203`, `app/routes/agentic_rag.py:17-23`
- **问题**: `top_k`、`rerank_top_k`、`max_retrievals` 没有 Pydantic 范围约束；`query` 也没有最小长度/最大长度限制。虽然前端 slider 限制了部分值，但 API 可被直接调用。
- **影响**: `top_k` 或 `max_retrievals` 过大时会放大向量检索和 LLM rerank 成本；负数/零值可能导致底层库异常或返回难以理解的结果。
- **建议**: 使用 `Field(ge=1, le=...)`、`constr(strip_whitespace=True, min_length=1, max_length=...)` 等约束；对 `rerank_top_k <= top_k` 做模型级校验。

### 8. Reranker 串行逐文档调用 LLM，成本和延迟随 top_k 线性放大

- **位置**: `app/models/reranker.py:62-79`, `app/models/reranker.py:87-127`
- **问题**: `rerank()` 对每个候选文档单独调用一次 LLM 评分。
- **影响**: 当 `top_k=10` 时一次搜索至少额外 10 次模型请求；在 AgenticRAG 多轮检索下成本和延迟进一步放大，也更容易触发 API 限流。当前入参又缺少强上限，会加剧该问题。
- **建议**: 改为批量 rerank prompt（一次请求给出多个文档评分）或使用专用 rerank/embedding 相似度模型；至少并发控制 + 超时 + top_k 上限，并在失败时保留原始向量排序。

---

## 🟢 低优先级问题

### 9. `pyproject.toml` 与 `requirements.txt` 依赖声明严重不一致

- **位置**: `pyproject.toml:1-10`, `requirements.txt:1-52`
- **问题**: `pyproject.toml` 只声明了 `marshmallow` 和 `setuptools`，而项目运行所需的 FastAPI、SQLAlchemy、OpenAI、LangGraph、Gradio、pgvector 等都只在 `requirements.txt` 中。
- **影响**: 使用 `uv sync`、`pip install .` 或基于 PEP 621 元数据的部署方式时，环境会缺少绝大多数运行依赖；本地 README 又推荐 uv，容易造成安装路径混乱。
- **建议**: 将运行依赖统一迁移到 `pyproject.toml`，或明确 `requirements.txt` 是唯一安装入口；避免两套依赖源长期漂移。

### 10. 测试函数返回布尔值而不是断言，未来 pytest 会升级为错误

- **位置**: `test_langgraph.py:10-42`, `test_langgraph.py:45-77`, `test_langgraph.py:80-97`
- **问题**: 三个 pytest 测试函数返回 `True/False`，当前运行已出现 `PytestReturnNotNoneWarning`。
- **影响**: 未来 pytest 版本可能将该 warning 变成错误；同时测试失败时依赖返回值而不是断言，失败定位不如标准 pytest 清晰。
- **建议**: 改为直接 `assert`，异常让 pytest 捕获；如果需要脚本式运行，可把打印逻辑放到 `main()`，测试函数保持无返回值。

---

## 已验证的积极改进

- 当前测试套件覆盖了多租户校验、文件名清洗、Milvus collection 维度检查、向量删除、AgenticRAG direct-reply、无检索结果质量评估等关键路径。
- Milvus 读/删路径已避免为不存在的新租户隐式创建 collection，这降低了资源污染风险。
- 文件上传会清洗路径型文件名，并且响应不暴露临时上传路径。
- `semantic` 切分已经对超长单句做 recursive fallback，避免超大 chunk 直接进入 embedding。

---

## 测试与告警记录

执行命令：

```bash
pytest -q
```

结果：

```text
52 passed, 8 warnings in 1.60s
```

主要 warnings：

- FastAPI `@app.on_event` 已弃用，建议迁移到 lifespan。
- `test_langgraph.py` 中 3 个测试返回非 `None`，未来 pytest 可能报错。
- Starlette TestClient 关于 httpx 的弃用提示。

---

## 修复优先级建议

建议按以下顺序处理：

1. **启动健康语义**：PostgreSQL 初始化失败时 fail fast；新增 readiness，避免坏实例接流量。
2. **文档/向量一致性**：为入库和删除建立明确的事务/补偿策略，不再静默成功。
3. **响应最小化**：列表接口移除全文 `content`，详情接口加权限后再返回全文。
4. **API 入参约束**：限制 `top_k`、`rerank_top_k`、`max_retrievals`、query 长度。
5. **依赖与测试卫生**：统一依赖声明，修复 pytest warning，逐步迁移 FastAPI lifespan。

---

## 总结

项目当前代码能通过现有测试，且前几轮关于多租户、Milvus 副作用、文件安全和 semantic 切分的风险已有明显改善。剩余最值得优先关注的是**运行时一致性和生产可运维性**：启动失败不能伪装健康，文档与向量索引不能静默分叉，列表接口不应批量暴露全文。解决这些问题后，项目会更适合进入真实多租户和长文档场景。
