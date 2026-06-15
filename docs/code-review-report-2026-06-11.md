# 代码审查报告

**日期**: 2026-06-11
**项目**: AgenticRAG
**审查范围**: 当前工作区所有未提交变更（22 个文件，+1293/-614 行）

---

## 审查结果概览

- **已入库问题**: 14 条
- **高优先级**: 8 条
- **中优先级**: 6 条
- **主要风险面**: 多租户参数校验、Milvus 资源副作用、文档删除一致性、错误码契约回归、文档与实现不一致

---

## 🔴 高优先级问题

### 1. 检索路径会隐式为新租户创建空的 Milvus 集合
- **位置**: `app/database/milvus.py:264`
- **问题**: `search_vectors()` 在读路径里直接调用 `ensure_ready()`；当租户集合不存在时，会先创建空 collection、索引并 load，而不是直接返回空结果。
- **影响**: 外部若能传任意 `tenant_id`，普通查询就能不断制造空集合，带来资源膨胀和脏租户资源。

### 2. 删除路径也会隐式创建 Milvus 集合，清理操作产生副作用
- **位置**: `app/database/milvus.py:310`
- **问题**: 删除向量前同样调用 `ensure_ready()`；当该租户原本没有向量集合时，删除动作会先创建空集合再删除。
- **影响**: 一次“清理”请求反而创建额外资源，长期会污染向量库状态。

### 3. 统一向量维度配置造成旧配置兼容性回归
- **位置**: `app/config.py:95`
- **问题**: 当前实现固定读取 `OPENAI_EMBEDDING_DIMENSION`，使已有配置项 `MILVUS_DIMENSION` 失效。
- **影响**: 老部署如果仍使用 `MILVUS_DIMENSION=768`，升级后可能在 `ensure_ready()` 阶段因维度不匹配直接失败。

### 4. 文档删除时吞掉向量删除异常，导致数据库与向量索引不一致
- **位置**: `app/routes/documents.py:352`
- **问题**: `delete_vectors_by_document_id()` 失败后只记 warning，仍继续删除数据库记录。
- **影响**: 文档表里已经删掉，但向量库中的 chunk 仍会被 `/api/v1/ai/search` 和 AgenticRAG 检索到，形成“已删除文档仍可命中”的脏数据。

### 5. `semantic` 切分模式无法兜底超长单句，破坏 `chunk_size` 契约
- **位置**: `app/utils/text_splitter.py:236`
- **问题**: 当输入是超长单句或无标点长段落时，逻辑会直接返回超大 chunk，而不会继续细切。
- **影响**: 后续 embedding 请求可能因上下文过长失败，且行为与其它 split 方法不一致。

### 6. `decision_maker` 把答案生成错误误判为检索错误并触发重复检索
- **位置**: `app/agents/nodes.py:471`
- **问题**: 这里只根据统一的 `state["error"]` 判断是否回到 `retriever`，但 `answer_generator()` 也会写这个字段。
- **影响**: 只要答案生成阶段失败，即使检索已成功，系统也会再次做无意义检索，掩盖真实故障点并浪费资源。

### 7. AgenticRAG 路由缺少 `tenant_id` 边界校验，非法参数被错误包装成 500
- **位置**: `app/routes/agentic_rag.py:17`
- **问题**: 新增的 `tenant_id` 直接进入后续链路，未在接口边界做格式校验。
- **影响**: 非法值会在底层 `validate_tenant_id()` 抛错，但最终对外表现成服务端 500，而不是客户端参数错误。

### 8. AI 搜索接口把依赖未就绪从 503 回退成 500
- **位置**: `app/routes/ai.py:222`
- **问题**: 现在用 `vector_store.ensure_ready()` 替代原有显式检查；后端未连接时抛 `RuntimeError`，最终被统一捕获成 500。
- **影响**: 调用方无法再按“依赖服务不可用”进行重试或降级，破坏原有错误码契约。

---

## 🟡 中优先级问题

### 9. 文档切分参数缺少入参校验，错误请求被包装成 500
- **位置**: `app/routes/documents.py:237`
- **问题**: `split_method`、`chunk_size`、`chunk_overlap` 直接透传给 `TextSplitter.split()`，对非法值没有预校验。
- **影响**: 客户端传错切分方法会收到“服务器内部错误”，而不是 4xx 参数错误。

### 10. 前端租户 ID 规范化规则与后端不一致，可能误清空会话历史
- **位置**: `front/app.py:45`
- **问题**: 前端仅做 `strip()`，而后端还会 `lower()`、把 `-` 转 `_` 并过滤非法字符。
- **影响**: `Acme-Inc` 与 `acme_inc` 这种等价写法在后端会落到同一租户，但前端会误判为切换租户并清空历史消息。

### 11. AI 搜索接口对非法 `tenant_id` 仍返回 500
- **位置**: `app/routes/ai.py:222`
- **问题**: 当前路由没有像 `/documents` 那样先显式做多租户参数校验。
- **影响**: `validate_tenant_id()` 抛出的 `ValueError` 会落入通用异常分支，客户端参数错误被误报为服务端故障。

### 12. README 中的 AgenticRAG 执行流程说明与代码实现不一致
- **位置**: `README.md:285`
- **问题**: 文档写成所有请求都会进入检索、重排、上下文构建和质量评估。
- **影响**: 但实际 `app/agents/nodes.py` 已存在 `greeting/chitchat` 的 direct-reply 分支；文档会误导排障和使用者认知。

### 13. 指南文档同样遗漏 direct-reply 分支
- **位置**: `AGENTIC_RAG_GUIDE.md:21`
- **问题**: 当前流程图与文字描述仍把所有请求当作普通 RAG 流程。
- **影响**: 与实际实现不一致，尤其会误导对 `quality_score` 与退出条件的理解。

### 14. README 中的默认 Embedding 模型与维度示例互相冲突
- **位置**: `README.md:141`
- **问题**: 文档一处示例写 `text-embedding-bge-m3 + 1024`，但仓库默认配置与其他示例仍是 `text-embedding-ada-002 + 1536`。
- **影响**: 用户按 README 配置后，再参考 `env.example` 或其他章节排障时会得到相互矛盾的模型与维度设定。

---

## 已检查但未发现达到入库阈值问题的文件

- `app/database/postgres.py`
- `app/database/__init__.py`
- `app/db_models/document.py`
- `app/main.py`
- `app/routes/api.py`
- `app/agents/manager.py`
- `app/agents/state.py`
- `app/models/reranker.py`
- `app/models/embedding.py`
- `app/models/llm.py`
- `front/api_client.py`
- `env.example`

---

## 修复优先级建议

建议优先处理以下 5 项：

1. `app/routes/documents.py:352` —— 修复“删库不删向量”的一致性问题。
2. `app/database/milvus.py:264` —— 禁止读路径隐式建集合。
3. `app/database/milvus.py:310` —— 禁止删路径隐式建集合。
4. `app/routes/agentic_rag.py:17` 与 `app/routes/ai.py:222` —— 统一多租户参数校验和错误码映射。
5. `app/agents/nodes.py:471` —— 拆分检索错误与生成错误，避免错误重试路径串扰。

---

## 总结

本次变更的核心风险不在语法层，而在于：

- **多租户能力刚接入，但入口校验与前后端规范化尚未完全对齐**；
- **Milvus 适配层把“ensure ready”复用到了读/删路径，带来了资源副作用**；
- **部分接口的错误码语义发生了回归**；
- **文档已落后于最新的 direct-reply 实现与默认配置**。

如果这些问题在合入前不修复，最容易出现的线上表现是：
1. 错误请求被误报为 500；
2. 删除后的文档仍能被检索到；
3. 空租户集合不断被创建；
4. 使用者按文档配置后得到与实际实现不一致的行为。
