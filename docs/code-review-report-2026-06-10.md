# 代码审查报告

**日期**: 2026-06-10
**项目**: AgenticRAG
**审查范围**: 当前工作区所有未提交变更（22 个文件，+1109/-558 行）

---

## 审查结果

以下是我发现的主要问题（按严重程度排序）：

---

### 🔴 严重问题

**1. Milvus 中文本被截断至 500 字符，导致检索结果信息丢失**
- **文件**: `app/routes/documents.py:122`, `app/agents/nodes.py:218,303`
- **描述**: 在 `_store_document_vectors` 中，chunk 文本被截断为 `chunk["text"][:500]` 存入 Milvus 的 metadata 字段。而默认 `chunk_size=1000`。检索时光会从 Milvus metadata 中取回这个截断文本 → reranker 用截断文本打分 → context_builder 用截断文本构建上下文。chunk 在 PostgreSQL 中的完整文本从未在检索链路中被使用。
- **场景**: 上传 1000 字符的 chunk，关键信息在 501–1000 字符区间。reranker 仅看到前 500 字符，打出低分，文档被排除出 top-5；最终生成的答案缺失关键信息。

---

**2. 检索异常时 `decision_maker` 不检查 `error` 字段就终止流程**
- **文件**: `app/agents/nodes.py:230-235,468-471`
- **描述**: `retriever` 发生异常时，同时设置了 `search_results=[]` 和 `error=str(e)`。`decision_maker` 在看到空 `search_results` 时立刻返回 `"end"`，从不检查 `error`。配置 `max_retrievals=3` 的情况：第一次检索因临时故障失败 → 空结果 → 直接结束，浪费剩余 2 次重试机会。
- **场景**: Milvus 连接瞬时断开 → retriever 抛异常 → search_results=[] → decision_maker 立即结束 → 用户收到"未找到相关文档"的答案，实际数据存在且有 2 次未用重试。

---

### 🟡 中等问题

**3. `retrieval_count` 在检索成功前就被递增，异常时计数偏向**
- **文件**: `app/agents/nodes.py:194`
- **描述**: `state["retrieval_count"] += 1` 在 Milvus 实际搜索之前执行。虽然 `decision_maker` 的空结果检查（问题 2）让此场景几乎不可达，但如果将来决策逻辑改变（例如某些异常不置空 `search_results`），计数器会在没有有效结果的情况下增加。
- **场景**: 未来修改异常处理策略使某些错误不立即终止流程 → 计数器因失败尝试被递增 → 有效重试次数减少。

---

**4. 启动时使用的集合名 `vectors_default` 无法发现已有的 `vectors` 集合**
- **文件**: `app/main.py:48`
- **描述**: 启动时调用 `milvus_manager.ensure_ready()` 无参数，内部解析为 `collection_name = "vectors_default"`（因为 `tenant_id=None` → `normalize_tenant_id(None)` → `"default"`）。如果旧部署（多租户改造前）中存在集合 `"vectors"`，启动时完全不会检测到；系统会创建一个空的 `"vectors_default"` 集合，旧数据永远不可见。
- **场景**: 从非多租户版本升级到当前版本 → 用户查询返回零结果 → 尽管旧集合 `"vectors"` 中有数万条向量，全部被忽略。

---

**5. `normalize_tenant_id` 对全特殊字符输入静默回退到默认租户**
- **文件**: `app/utils/tenancy.py:20`
- **描述**: 输入 `tenant_id="___"` 或 `"!@#$%"` → 归一化后得到空字符串 → 返回 `settings.DEFAULT_TENANT_ID` → `require_tenant_id` 永远不会抛出 `HTTPException(400)`。数据被静默写入 "default" 租户集合中。
- **场景**: 客户端因编程错误发送 `tenant_id="___"` → 无错误提示 → 数据被存入 "default" 租户 → 数据"丢失"（从客户角度看）。

---

### 🟢 低严重度 / 改进建议

**6. `document_routes.py:186` 中 `file_path=None`，打破了依赖路径的消费者**
- **文件**: `app/routes/documents.py:186`
- **描述**: 上传文档时将 `file_path` 设为 `None`（旧代码会记录临时文件路径）。临时文件在 finally 块中被删除，所以 None 是比过期路径更合理的值。但如果下游 admin 面板或监控工具依赖该字段来显示源文件路径，它们会看到 null。
- **场景**: 管理后台查询 `GET /documents/{id}` 获取文档信息 → `file_path: null` → 无法溯源上传文件。

---

**7. `decision_maker` 逻辑顺序问题：空结果检查应在质量分数检查之后**
- **文件**: `app/agents/nodes.py:468-471`
- **观察**: 当前逻辑在检查 `retrieval_count >= max_retrievals`（第 478 行）之前就因空结果终止。在极端场景下（`max_retrievals` 配置极高，Milvus 间歇故障），这会阻止自动恢复。建议让决策节点在退出前至少检查 `error` 字段是否存在。

---

## 总结

| 类型 | 数量 |
|------|------|
| 数据完整性 Bug | 3 (#1, #2, #5) |
| 逻辑/流程 Bug | 2 (#3, #7) |
| 部署/迁移问题 | 1 (#4) |
| 兼容性变更 | 1 (#6) |

最值得优先修复的是 **#1（文本截断）** 和 **#2（异常时跳过重试）**。

---

## 已排除的误报

以下候选问题经核实已排除：

| 候选 | 结论 |
|------|------|
| MilvusManager 方法缺少 `await` | 排除了 — 都是普通 `def`（同步方法），在 async 上下文中直接调用正确 |
| `create_index`/`load_collection` 使用了错误的 collection 名 | 排除了 — `ensure_ready` 显式传了 `collection_name` 参数 |
| `decision_maker` 中 `quality_score=None` 引发 TypeError | 排除了 — `quality_evaluator` 总是在 `decision_maker` 之前运行，会设置 float 值 |
| 空 `reranked_results` 导致空上下文 | 排除了 — metadata 中始终有 `text` 字段，引用了从 Milvus 中获取的正常路径 |