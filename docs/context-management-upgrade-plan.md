# Context Management Upgrade Plan

**项目**: AgenticRAG  
**日期**: 2026-06-14  
**目标**: 将当前“前端维护短期对话历史 + 请求级 RAG 上下文”的模式，升级为“后端托管的生产级上下文管理体系”。

---

## 一、背景与现状

当前项目已经具备以下上下文能力：

1. **请求级状态上下文**  
   AgenticRAG 通过 LangGraph state 在一次请求内部维护：
   - user_query
   - query_analysis
   - search_results
   - reranked_results
   - context
   - answer
   - quality_score
   - messages

2. **RAG 检索上下文**  
   系统可从 PostgreSQL / Milvus / pgvector / hybrid search 中检索文档片段，并在 `context_builder` 节点中组织成 LLM 可消费的上下文。

3. **前端短期会话上下文**  
   Gradio 前端当前在内存中维护 `conversation_history`，并在每次请求时传给后端。

### 现状问题

当前模式在 PoC 或单用户短会话下可工作，但存在明显的生产缺陷：

- 对话历史由前端托管，不可持久化恢复
- 刷新页面或重开会话会丢失上下文
- 无正式 `session_id` / `conversation_id` 概念
- 无上下文窗口治理（recent turns / token budget / summary）
- 无长期记忆（用户偏好、用户画像）
- 无多会话管理能力

---

## 二、升级目标

本方案的总体目标是将上下文管理升级为以下能力：

1. **后端托管会话上下文**
2. **可恢复、可审计、可分页的消息存储**
3. **上下文窗口治理与 token budget 控制**
4. **摘要记忆（summary memory）**
5. **长期记忆（profile / preference memory）**
6. **与现有 AgenticRAG / RAG 检索流程无缝融合**

---

## 三、升级后的目标架构

```text
                        ┌─────────────────────────┐
                        │   user profile memory   │
                        │  (长期偏好 / 用户画像)    │
                        └────────────┬────────────┘
                                     │
                                     v
┌───────────────┐        ┌─────────────────────────┐
│ session store │ -----> │   session summary       │
│ 会话与消息持久化 │       │   (历史摘要记忆)         │
└──────┬────────┘        └────────────┬────────────┘
       │                               │
       v                               v
┌──────────────────────────────────────────────┐
│             context assembler                │
│  system + profile + summary + recent turns   │
│  + retrieved docs + current query            │
└──────────────────────────────────────────────┘
                       |
                       v
                 [LLM answer]
                       |
                       v
              [messages persisted]
```

---

## 四、阶段化升级路线

---

# Phase 1：后端会话持久化

## 目标

将当前由前端内存维护的 `conversation_history` 升级为后端托管的正式会话模型。

## 核心收益

- 支持刷新页面后继续会话
- 支持多设备/多端访问同一会话
- 支持历史消息审计
- 为后续 summary / long-term memory 打基础

## 新增数据模型

### 1. conversation_sessions

建议字段：

```text
conversation_sessions
- id
- tenant_id
- user_id                # 未来与认证体系结合
- title
- status                 # active / archived
- latest_summary         # Phase 3 使用
- latest_message_at
- created_at
- updated_at
```

### 2. conversation_messages

建议字段：

```text
conversation_messages
- id
- session_id
- tenant_id
- role                   # user / assistant / system
- content
- message_type           # raw / summary / tool / trace
- token_count
- metadata               # JSON，可用于存 prompt 信息 / trace / tool 调用信息
- created_at
```

## 新接口建议

### 创建会话
```text
POST /api/v1/conversations
```

### 获取会话列表
```text
GET /api/v1/conversations
```

### 获取会话详情
```text
GET /api/v1/conversations/{session_id}
```

### 获取消息列表
```text
GET /api/v1/conversations/{session_id}/messages
```

### 发送消息并触发 AgenticRAG
```text
POST /api/v1/conversations/{session_id}/messages
```

## 对现有 AgenticRAG 的改造方式

当前：
```text
query + conversation_history -> answer
```

升级后：
```text
session_id + query -> answer
```

调用路径：
1. 前端传 `session_id + query`
2. 后端查询最近历史消息
3. 构造 conversation context
4. 执行 AgenticRAG
5. 将 user / assistant 消息落库

---

# Phase 2：上下文窗口治理

## 目标

避免上下文无限增长，控制 prompt 长度、性能和成本。

## 核心收益

- 降低 token 成本
- 控制延迟
- 避免历史消息噪音污染当前问答
- 为长对话提供稳定体验

## 建议策略

### 1. 最近 N 轮原始消息
例如保留：
- 最近 6~10 轮 user/assistant 消息

### 2. Prompt token budget
建议配置：

```text
CONTEXT_MAX_TOTAL_TOKENS=8192
CONTEXT_MAX_HISTORY_TOKENS=2048
CONTEXT_MAX_RETRIEVAL_TOKENS=4096
CONTEXT_MAX_SYSTEM_TOKENS=1024
```

### 3. retrieval context budget
控制：
- 最多引用几个 chunk
- 每个 chunk 最大长度
- rerank 后再做裁剪

### 4. 消息优先级策略
优先保留：
1. system prompt
2. session summary（后续阶段）
3. 最近几轮原始消息
4. 当前用户输入
5. 本轮检索出的知识上下文

## 建议的上下文拼装顺序

```text
最终 Prompt Context =
  [system prompt]
+ [session summary]
+ [recent messages]
+ [current user query]
+ [retrieved document context]
```

---

# Phase 3：摘要记忆（Summary Memory）

## 目标

对长历史会话做压缩，把旧消息摘要化，避免上下文窗口无限增长。

## 核心收益

- 长会话可持续进行
- 老消息不需要一直完整塞进 prompt
- 保留历史关键信息而不是保留全部原文

## 设计建议

### session 级摘要字段
在 `conversation_sessions` 中维护：

```text
latest_summary
summary_updated_at
summary_version
```

### 触发时机
例如：
- 消息数 > 20 条
- 或历史 token 数 > 3000

### 处理机制
1. 选取较旧的一批 raw 消息
2. 调用 LLM 做摘要
3. 将摘要写入 `latest_summary`
4. 旧 raw 消息保留存储，但默认不再进入 prompt

## 上下文结构升级为：

```text
[system]
+ [summary memory]
+ [recent turns]
+ [retrieved docs]
+ [current query]
```

---

# Phase 4：长期记忆（Profile / Preference Memory）

## 目标

支持跨会话的稳定偏好与用户画像管理。

## 核心收益

- 提升多次会话的一致性体验
- 让助手记住用户偏好而不需要每次重新说明
- 更适合企业 / 个人知识助手场景

## 可记录的长期信息

- 偏好语言（中文 / 英文）
- 输出风格（简洁 / 详细 / 表格）
- 领域背景（法务 / 技术 / 医学）
- 常用术语解释偏好
- 风险偏好 / 审慎程度

## 新数据模型建议

```text
user_memories
- id
- tenant_id
- user_id
- key
- value
- source              # inferred / explicit / imported
- updated_at
```

## 使用方式

在会话开始或消息处理前，将长期记忆注入到 context assembler：

```text
system + profile memory + session summary + recent turns + retrieved docs
```

---

## 五、上下文装配器（Context Assembler）设计建议

未来建议把当前零散的上下文拼装逻辑集中到一个显式模块中，例如：

```text
app/context/
├── assembler.py
├── budget.py
├── summarizer.py
└── memory.py
```

### assembler.py 职责
- 接收 session / messages / summary / retrieval results / system prompt
- 根据 token budget 做裁剪
- 生成最终 prompt payload

### budget.py 职责
- 估算 token 数
- 进行 context trim
- 分配 history / retrieval token 预算

### summarizer.py 职责
- 生成摘要记忆
- 更新 session summary

### memory.py 职责
- 查询长期记忆
- 注入 profile / preference context

---

## 六、与现有代码的映射关系

当前项目中可以复用的部分：

### 已存在，可复用
- `app.agents.nodes.context_builder`
- `app.agents.manager`
- `conversation_history` 入参模式
- request-level LangGraph state
- RAG 检索链路
- 文档与 chunk 数据模型

### 需要新增
- 会话数据模型
- 消息存储模型
- 上下文装配器模块
- summary 生成逻辑
- profile memory 模型与读取逻辑

### 需要调整
- Gradio 前端从传 `conversation_history` 改为传 `session_id`
- AgenticRAGRequest 改为支持 `session_id`
- answer 生成前的 context 组装逻辑改为后端统一托管

---

## 七、接口升级建议

### 当前接口
```text
POST /api/v1/ai/agentic-rag/query
{
  "query": "...",
  "conversation_history": [...]
}
```

### 未来建议接口
```text
POST /api/v1/conversations/{session_id}/messages
{
  "content": "...",
  "stream": false
}
```

返回：
```json
{
  "session_id": "...",
  "message_id": "...",
  "assistant_message": {...},
  "query_analysis": {...},
  "retrieval_count": 1,
  "context_status": {
    "used_summary": true,
    "used_recent_messages": 6,
    "used_retrieval_chunks": 4
  }
}
```

---

## 八、迁移策略建议

为了避免对现有系统做一次性重构，建议采用兼容迁移方式：

### Step 1
新增 session/message 表，但保留老接口。

### Step 2
后端支持两种模式：
- `conversation_history` 模式（旧）
- `session_id` 模式（新）

### Step 3
前端逐步切换到 `session_id`

### Step 4
稳定后废弃旧模式

---

## 九、验收标准建议

### Phase 1 验收
- 支持创建会话、查询会话、查询历史消息
- 会话刷新后仍可恢复历史
- assistant 回复与 user 输入均可落库

### Phase 2 验收
- prompt 有统一 token budget
- 超长历史不会无限注入 prompt
- retrieval context 有上限控制

### Phase 3 验收
- 长会话可自动生成 summary
- 老消息可以被 summary 替代进入 prompt

### Phase 4 验收
- 支持用户长期偏好注入
- 跨会话可复用 profile memory

---

## 十、推荐实施顺序

优先级建议如下：

1. **Phase 1：会话持久化**
2. **Phase 2：上下文窗口治理**
3. **Phase 3：摘要记忆**
4. **Phase 4：长期记忆**

不建议跳过前两步直接做长期记忆，因为：
- 没有后端托管 session，长期记忆难以可靠融合
- 没有 token budget，记忆注入很容易导致 prompt 膨胀

---

## 十一、结论

当前 AgenticRAG 项目已经具备：
- 请求级上下文状态
- RAG 检索上下文
- 前端短期会话历史

但它还没有达到生产级上下文管理体系的完整形态。  
未来最值得优先做的是：

> **先把 conversation session 持久化做出来，再做上下文窗口治理。**

这是让项目从“能多轮聊天”走向“真正可靠的会话型 RAG 系统”的关键一步。
