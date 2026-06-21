# AgenticRAG 使用指南

## 概述

AgenticRAG 是一个基于 LangGraph 的智能体驱动的 RAG（检索增强生成）系统。它通过智能体自动分析查询、执行检索、重排序、生成答案并评估质量，实现高质量的问答体验。

## 系统架构

AgenticRAG 由以下核心节点组成：

1. **查询分析节点 (query_analyzer)**: 分析用户查询，确定检索策略
2. **检索节点 (retriever)**: 从 Milvus 向量数据库检索相关文档
3. **重排序节点 (reranker)**: 使用 Reranker 对检索结果进行重排序
4. **上下文构建节点 (context_builder)**: 将检索结果构建成上下文
5. **答案生成节点 (answer_generator)**: 基于上下文生成答案
6. **质量评估节点 (quality_evaluator)**: 评估生成答案的质量
7. **决策节点 (decision_maker)**: 决定是否继续检索或结束

## 当前执行逻辑

当前 AgenticRAG 基于 LangGraph 按以下顺序执行：

1. **查询分析 (`query_analyzer`)**
   - 使用 LLM 分析问题类型、复杂度、关键词、检索范围。
   - 产出 `top_k`、`needs_rerank` 等检索策略。

2. **文档检索 (`retriever`)**
   - 先将 `retrieval_count` 加 1，再调用 Embedding 模型生成查询向量。
   - 从 Milvus 对应租户集合中检索文档。
   - 若未命中文档，会将 `search_results` 和 `reranked_results` 置空，并记录“未找到相关文档”。

3. **结果重排序 (`reranker`)**
   - 如果查询分析认为需要重排序，则调用 Reranker 对检索结果重排。
   - 如果没有检索结果，直接返回空列表；如果 `needs_rerank=false`，则直接使用原始检索结果。

4. **上下文构建 (`context_builder`)**
   - 取重排序结果（若无则取原始检索结果）中的前几条文档，拼接为回答上下文。
   - 如果没有任何结果，上下文会被设置为“没有找到相关的文档信息”。

5. **答案生成 (`answer_generator`)**
   - 使用 LLM 严格基于上下文回答问题。
   - 当上下文为空时，要求模型明确说明未找到足够信息，而不是编造内容。

6. **质量评估 (`quality_evaluator`)**
   - 如果本轮没有检索到任何文档，则**跳过质量模型调用**，直接将 `quality_score` 设为 `0.0`。
   - 如果有检索结果，则调用 LLM 评估答案质量。
   - 质量分数支持两种解析方式：
     - 直接解析纯数字，如 `0.82`
     - 从文本中提取分数，如 `评分: 0.82`
   - 如果仍然无法解析，回退到默认值 `0.5`。

7. **流程决策 (`decision_maker`)**
   - 满足以下任一条件时，流程结束：
     - 本轮没有检索到文档
     - `quality_score >= AGENTIC_RAG_QUALITY_THRESHOLD`
     - `retrieval_count >= max_retrievals`
   - 否则继续回到检索节点，进入下一轮检索。

### 当前退出逻辑说明

为了避免 AgenticRAG 在“无文档命中”场景下反复循环，当前版本增加了以下保护：

- **每次进入检索节点都会累加 `retrieval_count`**，而不是只有命中文档时才计数。
- **未命中文档时立即结束流程**，不会再出现 `0/2` 持续循环的情况。
- **无检索结果时跳过质量评估模型**，避免因为质量分数解析失败导致误判继续检索。

### 简化流程图

```text
用户问题
  -> 查询分析
  -> 文档检索
  -> 重排序
  -> 上下文构建
  -> 答案生成
  -> 质量评估
  -> 决策
       |- 无文档命中 -> 结束
       |- 达到质量阈值 -> 结束
       |- 达到最大检索次数 -> 结束
       \- 否则 -> 回到文档检索
```

## API 接口

### 1. 执行 AgenticRAG 查询

**接口**: `POST /api/v1/ai/agentic-rag/query`

**请求参数**:
```json
{
  "query": "用户查询问题",
  "conversation_history": [
    {
      "role": "user",
      "content": "之前的问题"
    },
    {
      "role": "assistant",
      "content": "之前的回答"
    }
  ],
  "max_retrievals": 2,
  "stream": false
}
```

**响应示例**:
```json
{
  "query": "用户查询问题",
  "answer": "生成的答案",
  "quality_score": 0.85,
  "query_analysis": {
    "query_type": "factual",
    "complexity": "medium",
    "keywords": ["关键词1", "关键词2"],
    "search_scope": "medium",
    "top_k": 10,
    "needs_rerank": true,
    "explanation": "分析说明"
  },
  "search_results": [
    {
      "id": 1,
      "text": "文档内容",
      "distance": 0.123,
      "score": 0.123
    }
  ],
  "reranked_results": [
    {
      "id": 1,
      "text": "文档内容",
      "distance": 0.123,
      "relevance_score": 0.9
    }
  ],
  "retrieval_count": 1,
  "context": "构建的上下文",
  "messages": [
    {
      "role": "user",
      "content": "用户查询问题"
    }
  ],
  "error": null
}
```

### 2. 流式执行 AgenticRAG 查询

**接口**: `POST /api/v1/ai/agentic-rag/stream`

**请求参数**: 同上

**响应**: Server-Sent Events (SSE) 格式，实时返回查询过程中的中间结果

### 3. AgenticRAG 健康检查

**接口**: `GET /api/v1/ai/agentic-rag/health`

**响应示例**:
```json
{
  "status": "healthy",
  "graph_initialized": true,
  "max_retrievals": 2
}
```

### 4. 查询分析

**接口**: `POST /api/v1/ai/agentic-rag/analyze`

**请求参数**:
```json
{
  "query": "用户查询问题"
}
```

**响应示例**:
```json
{
  "query": "用户查询问题",
  "analysis": {
    "query_type": "factual",
    "complexity": "medium",
    "keywords": ["关键词1", "关键词2"],
    "search_scope": "medium",
    "top_k": 10,
    "needs_rerank": true,
    "explanation": "分析说明"
  }
}
```

## 配置参数

在 `.env` 文件中可以配置以下参数：

```env
# AgenticRAG 配置
AGENTIC_RAG_MAX_RETRIEVALS=2          # 最大检索次数
AGENTIC_RAG_QUALITY_THRESHOLD=0.8     # 质量阈值
AGENTIC_RAG_DEFAULT_TOP_K=10          # 默认检索数量
```

## 使用示例

### Python 示例

```python
import requests
import json

# API 端点
BASE_URL = "http://localhost:8000/api/v1/ai/agentic-rag"

# 执行查询
def query_agentic_rag(question):
    url = f"{BASE_URL}/query"
    payload = {
        "query": question,
        "max_retrievals": 2
    }
    
    response = requests.post(url, json=payload)
    result = response.json()
    
    print(f"问题: {result['query']}")
    print(f"答案: {result['answer']}")
    print(f"质量分数: {result['quality_score']}")
    print(f"检索次数: {result['retrieval_count']}")
    
    return result

# 使用示例
result = query_agentic_rag("什么是人工智能？")
```

### cURL 示例

```bash
# 执行查询
curl -X POST "http://localhost:8000/api/v1/ai/agentic-rag/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "什么是人工智能？",
    "max_retrievals": 2
  }'

# 健康检查
curl -X GET "http://localhost:8000/api/v1/ai/agentic-rag/health"

# 查询分析
curl -X POST "http://localhost:8000/api/v1/ai/agentic-rag/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "什么是人工智能？"
  }'
```

### JavaScript 示例

```javascript
// 执行查询
async function queryAgenticRAG(question) {
  const response = await fetch('http://localhost:8000/api/v1/ai/agentic-rag/query', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      query: question,
      max_retrievals: 2
    })
  });
  
  const result = await response.json();
  
  console.log('问题:', result.query);
  console.log('答案:', result.answer);
  console.log('质量分数:', result.quality_score);
  console.log('检索次数:', result.retrieval_count);
  
  return result;
}

// 使用示例
queryAgenticRAG('什么是人工智能？');
```

## 工作流程

1. **用户提交查询** → 系统接收用户问题
2. **查询分析** → 智能分析查询类型、复杂度和检索策略
3. **文档检索** → 进入检索节点时先增加 `retrieval_count`，再从 Milvus 向量数据库检索相关文档
4. **结果重排序** → 使用 Reranker 对检索结果进行重排序；若无结果则直接返回空列表
5. **上下文构建** → 将重排序后的结果构建成上下文；若无结果则生成“未找到相关文档”的上下文
6. **答案生成** → 基于上下文生成答案
7. **质量评估** → 若有检索结果则评估答案质量；若无结果则跳过评估并将分数设为 `0.0`
8. **决策判断** → 满足以下任一条件时结束：无文档命中、质量达标、达到最大检索次数；否则继续检索

## 特性

- **智能查询分析**: 自动识别查询类型和复杂度
- **自适应检索**: 根据查询特点动态调整检索参数
- **自动重排序**: 使用 Reranker 提升检索质量
- **质量评估**: 自动评估答案质量
- **多轮优化**: 支持多次检索以提升答案质量
- **安全退出**: 在无检索结果时自动结束，避免无意义循环
- **流式输出**: 支持实时返回中间结果
- **对话历史**: 支持多轮对话上下文

## 注意事项

1. 确保 Milvus 向量数据库已正确配置并包含相关文档
2. 确保 OpenAI API 密钥已正确配置
3. 质量阈值和最大检索次数可根据实际需求调整
4. 流式查询需要客户端支持 SSE (Server-Sent Events)
5. 如果查询始终未命中文档，当前版本会直接结束流程，而不是反复检索

## 故障排查

### 问题: AgenticRAG 查询失败

**可能原因**:
- Milvus 服务未连接
- OpenAI API 密钥未配置
- 向量数据库中没有相关文档

**解决方案**:
1. 检查 Milvus 连接状态: `GET /api/v1/ai/agentic-rag/health`
2. 检查 `.env` 文件中的配置
3. 确保向量数据库中有相关文档

### 问题: 查询很快结束，但没有进入多轮检索

**可能原因**:
- 当前查询没有命中任何向量文档
- 命中文档后质量分数已经达到阈值
- 已达到 `max_retrievals`

**说明**:
- 当前版本在“未命中文档”时会直接结束流程，这是为了避免之前出现的无限循环问题。

**解决方案**:
1. 先检查文档是否已经成功入库并写入向量数据库
2. 确认查询内容与已上传文档主题相关
3. 适当调整切分参数、Embedding 模型或文档内容质量
4. 如需更多轮尝试，可提高 `max_retrievals`，但前提是系统至少能检索到文档

### 问题: 质量分数过低

**可能原因**:
- 检索的文档不相关
- 查询分析不准确
- 答案生成参数不合适
- 质量评估模型返回的分数格式不稳定

**解决方案**:
1. 增加 `max_retrievals` 值
2. 降低 `AGENTIC_RAG_QUALITY_THRESHOLD` 值
3. 检查向量数据库中的文档质量
4. 查看日志确认质量分数是直接解析成功，还是走了默认值 `0.5`
