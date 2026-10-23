# AgenticRAG 产品改进执行计划（多跳优先）

> 创建日期：2026-10-21
> 分支：v2
> 用法：按 Sprint 顺序领取任务。每张任务卡包含【入口文件】【改动点】【验收标准】，验收标准全部满足才能算完成。先做 Sprint 1（真·多跳），再做其余。

---

## 当前落地证据（2026-10-21）

本文件的工程实施已覆盖 Sprint 1-8 的主要代码与产品切片，当前可复现证据如下：

- Sprint 1 多跳：`app/services/multi_hop.py`、`app/services/retrieval.py`、`app/agents/nodes.py` 已实现顺序多跳、槽位抽取、跨跳 RRF、失败降级和 trace；`tests/test_multi_hop.py` 覆盖 hop 规整、slot 成功/null/超时、总超时、异常降级、`MULTI_HOP_ENABLED=false`。
- Sprint 1 golden：`tests/fixtures/multi_hop_golden.jsonl` 含 15 条样本，`tests/fixtures/multi_hop_golden_recorded.jsonl` 含录制结果；`scripts/eval_multi_hop.py --recorded-results ... --enforce-thresholds` 可离线校验，当前 summary 为 `acceptance_pass=15`、`false_multi_hop=0`。真实模型和真实知识库上线前仍应去掉 `--recorded-results` 手工跑 live 验收。
- Sprint 2 多轮：`query_analyzer` 注入会话摘要/近轮上下文并生成 `standalone_query`，`answer_generator` 注入同样上下文；`tests/test_agentic_rag_nodes.py` 覆盖代词追问、省略主语追问、跨轮引用编号追问。
- Sprint 3 评测：`tests/eval/eval_cases.jsonl` 和 `recorded_results.jsonl` 已扩展到 51 条，`tests/eval/eval_runner.py` 输出 recall@k、MRR、引用准确率、必提词准确率、拒答准确率、P95 延迟。
- Sprint 4 工作台体验：`/conversations/{session_id}/messages/stream` 与 React 工作台实现 token/SSE 渲染、停止、重新生成、复制、推荐追问、质量分后置事件和多跳 trace 展示。
- Sprint 5 反馈飞轮：`/feedback/badcases`、`/feedback/answers/{id}/golden-set`、`/feedback/answers/{id}/wiki-recompile` 和 `/feedback` 控制台实现 badcase 聚合、Golden Set 沉淀和 Wiki 重编。
- Sprint 6 知识新鲜度：文档 `content_hash` 去重、文档状态/向量状态展示、源文档更新后 Wiki `stale`、源文档删除前软删关联 Wiki、批量删除真实清理向量/Wiki/DB。
- Sprint 7 企业底座：生产 auth fail-fast、API key read/write/admin role、可信 OIDC 反向代理头、React 控制台 `X-API-Key` 与 `/auth/me` 租户推导、per-tenant 请求限流、token 日配额、上传 magic bytes 校验、RAG 上下文提示词注入隔离。
- Sprint 8 运维成本：Dockerfile、docker-compose、GitHub Actions CI、`pyproject.toml`/`uv.lock` 单源依赖、Prometheus metrics、租户 token/成本和 cache 命中率指标、embedding/query-analysis TTL cache、PostgreSQL tsvector 稀疏检索、Wiki 编辑冲突提示、revision diff、页面级链接增量重建。

最近一次完整验证：

```bash
uvx ruff check app tests migrations scripts --select E9,F --ignore F401
uv run pytest -q                         # 188 passed
npm run build                            # frontend build passed
uv run python tests/eval/eval_runner.py --cases tests/eval/eval_cases.jsonl --results tests/eval/recorded_results.jsonl
uv run python scripts/eval_multi_hop.py --cases tests/fixtures/multi_hop_golden.jsonl --recorded-results tests/fixtures/multi_hop_golden_recorded.jsonl --enforce-thresholds
uv run alembic heads                     # 20261021_0004 (head)
docker compose config
git diff --check
```

---

## 0. 背景：为什么先做多跳

当前系统标称 `multi_hop`，但实际行为是**伪多跳**：

- `query_analyzer` 产出 `sub_queries` 后，`RetrievalOrchestrator.retrieve_many()`（`app/services/retrieval.py:152`）把所有子查询**一次性并发**丢给三个 provider，再用 RRF 融合。
- 第二跳的检索词无法利用第一跳的证据。例如"差旅办法里引用的那份文件，报销标准是什么"——第一跳必须先检索出被引用文件的**名称**，第二跳才能拿名称去检索；并发模型直接拿原句检索，第二跳必然漏。
- LangGraph 图是一条固定直线（`app/agents/manager.py:54-58`），没有顺序读取-再检索的环节。

本 Sprint 的目标：**不改图拓扑**（风险最小、1-3 天可上线），在 `retriever` 节点内部实现"跳间依赖"的顺序检索。

设计原则：

1. 只对 `route in {"multi_hop"}` 的查询启用顺序多跳；`comparison` 保持并发但按实体拆查询（见 1.8）。
2. 任何一跳规划/抽取失败，**降级回今天的并发 RRF 行为**，用户无感知。
3. 硬上限：最多 2 跳、每跳最多 2 条 query、总检索预算 15s，防止延迟和成本失控。
4. 每一跳的证据和耗时写入 `retrieval_attempts`，可观测、可回放。

---

## Sprint 1：真·多跳检索（Day 1-3）

### 1.1 整体流程

```text
query_analyzer
  └─ 输出 hops 计划（仅 multi_hop）
retriever
  ├─ 无 hops 计划 → 现有 retrieve_many（并发 RRF），逻辑不变
  └─ 有 hops 计划 → MultiHopExecutor
        hop1: retrieve_many(queries=hop1.queries)
              → 取 top3 证据，LLM 抽取 slots（JSON，温度 0）
        hop2: 用 slots 渲染 hop2.queries 模板 → retrieve_many
        ...（最多 MULTI_HOP_MAX_HOPS 跳）
        → 所有跳的 ranked groups 统一做一次 RRF
  → reranker → context_builder → answer_generator（按 answer_style 出答案）
```

关键点：每跳内部仍然复用现有 provider 并发 + 单跳 RRF 的能力；**跳与跳之间顺序执行**，后跳 query 由前跳证据渲染。

### 1.2 配置项（`app/config.py`）

在 AgenticRAG 配置段追加：

```python
# 多跳检索配置
MULTI_HOP_ENABLED: bool = True
MULTI_HOP_MAX_HOPS: int = 2            # 顺序跳硬上限
MULTI_HOP_MAX_QUERIES_PER_HOP: int = 2 # 每跳并发子查询上限
MULTI_HOP_TOTAL_TIMEOUT_SECONDS: float = 15.0   # 多跳总预算
MULTI_HOP_SLOT_TIMEOUT_SECONDS: float = 5.0     # 单次 slot 抽取 LLM 超时
MULTI_HOP_SLOT_EVIDENCE_DOCS: int = 3           # 抽 slot 时喂给 LLM 的证据条数
```

同步更新 `env.example` 与 README 的「AgenticRAG 配置」段。

### 1.3 查询规划协议扩展（`app/agents/nodes.py` 的 `query_analyzer`）

在分析 prompt 的 JSON 字段说明中追加 `hops`：

```text
- hops: 当 route=multi_hop 时给出顺序检索计划，最多 2 跳；其他 route 留空数组。
  每跳结构：
  {
    "hop": 1,
    "purpose": "本跳要找到什么（中文短语）",
    "queries": ["用于检索的查询1", "查询2"],
    "slots": []
  }
  第二跳起：
  {
    "hop": 2,
    "purpose": "...",
    "depends_on": 1,
    "queries": ["{slots.文件名} 报销标准"],
    "slots": [
      {"name": "文件名", "instruction": "从上一跳证据中提取被引用制度文件的完整名称，去掉书名号；找不到返回 null"}
    ]
  }
规则：
1. 第一跳用于"定位实体/文件/名称/编号"，第二跳用提取结果查目标事实。
2. queries 用 {slots.xxx} 占位符引用待填槽位，不要编造槽位值。
3. 如果问题不需要先定位中间实体就能直接检索，route 不要标 multi_hop，hops 留空。
```

新增规划规整函数（与现有 int/bool 规整放在一起）：

```python
def _normalize_hops(analysis: dict) -> list[dict]:
    """校验并截断 hops 计划；非法计划返回 [] 触发降级。"""
```

要求：

- hop 编号从 1 连续；`depends_on` 只能指向更早的跳；占位符必须在 `slots.name` 中有定义。
- 跳数截断到 `MULTI_HOP_MAX_HOPS`，每跳 queries 截断到 `MULTI_HOP_MAX_QUERIES_PER_HOP`。
- 任一校验失败 → 记 warning、返回 `[]`（后续走现有并发路径），**不要抛异常**。
- 规整结果写入 `state["query_plan"]["hops"]`。

兜底分支（prompt 解析失败/异常的两个 fallback dict，`nodes.py:443` 和 `:493`）中 `"hops": []`。

### 1.4 槽位抽取（新文件 `app/services/multi_hop.py`）

核心接口：

```python
@dataclass
class HopPlan:
    hop: int
    purpose: str
    queries: list[str]
    slots: list[dict]          # [{"name": ..., "instruction": ...}]

@dataclass
class HopExecution:
    hop: int
    purpose: str
    rendered_queries: list[str]
    documents: list[dict]
    ranked_groups: list[tuple[str, list[dict]]]   # 供最终全局 RRF
    extracted_slots: dict[str, str | None]
    errors: list[str]

class MultiHopExecutor:
    async def execute(
        self, request: RetrievalRequest, hops: list[HopPlan]
    ) -> tuple[list[dict], list[HopExecution]]:
        """返回 (融合后文档, 每跳执行记录)。失败时抛 MultiHopError 由调用方降级。"""
```

槽位抽取 prompt（温度 0、`max_tokens=200`、要求只输出 JSON）：

```text
你是信息抽取器。根据检索证据，提取指定槽位。
槽位：
- 文件名：从上一跳证据中提取被引用制度文件的完整名称，去掉书名号；找不到返回 null

证据：
[文档1] ...（trim_retrieval_results 截断后的 top N 文本）
[文档2] ...

只输出 JSON：{"文件名": "值或null"}，不要输出其他内容。
```

实现约束：

- 证据准备复用 `app.context.assembler.trim_retrieval_results(results, max_docs=MULTI_HOP_SLOT_EVIDENCE_DOCS)`，不要自己写截断。
- JSON 解析复用 `nodes._extract_json_object`（建议把它挪到 `app/utils/` 或在本模块重新实现一个小函数，避免跨层 import nodes）。
- 抽取调用用 `asyncio.wait_for` 包 `MULTI_HOP_SLOT_TIMEOUT_SECONDS`；超时/解析失败 → 该槽位记 None。
- **槽位为 None 时**：停止后续跳（证据不足），用已完成跳的结果继续融合，并在 trace 里标记 `stopped_reason="slot_not_found"`，交给后面的拒答/不确定性逻辑处理——不要编造槽位值继续检索。
- query 渲染：`str.format_map` 配合一个 missing 返回空串的 dict；渲染后为空白/与原问题等价的 query 丢弃。
- 多跳整体用 `asyncio.wait_for(..., MULTI_HOP_TOTAL_TIMEOUT_SECONDS)`；超时则返回已完成跳的融合结果，trace 标 `stopped_reason="timeout"`。

### 1.5 与检索编排器的衔接（`app/services/retrieval.py`）

现状 `retrieve_many` 内部完成"并发 + RRF"。多跳需要"每跳并发、最后跨跳统一融合"，改动：

1. 给 `RetrievalOrchestrator` 增加公开方法：

```python
async def retrieve_groups(
    self, request: RetrievalRequest, queries: list[str]
) -> tuple[list[tuple[str, list[dict]]], dict[str, RetrievalProviderResult]]:
    """执行一轮并发检索，返回未融合的 ranked groups 和 provider 结果（含错误）。"""

def fuse_groups(
    self, request: RetrievalRequest, ranked_groups: list[tuple[str, list[dict]]]
) -> list[dict]:
    """公开融合入口，内部委托现有 _fuse_ranked_groups。"""
```

2. 把现有 `retrieve_many` 改为调用这两个方法（行为保持不变，纯重构，先跑一遍全量测试确认 142 个测试全绿）。
3. `MultiHopExecutor` 每跳调 `retrieve_groups`，group label 加跳后缀（如 `vector:q1:h2`），最终把所有跳的 groups 一次性 `fuse_groups`。这样同一 chunk 在多跳重复命中仍能通过 RRF 累加分，不需要新的去重逻辑。

### 1.6 接入 retriever 节点（`app/agents/nodes.py:523`）

在现有取 plan 之后分叉：

```python
hops = _normalize_hops({"hops": (plan.get("hops") or [])})
if settings.MULTI_HOP_ENABLED and hops:
    try:
        documents, hop_runs = await multi_hop_executor.execute(
            RetrievalRequest(tenant_id=..., query=current_query, route=route,
                             top_k=top_k, dense_top_k=dense_top_k,
                             sparse_top_k=sparse_top_k, filters=...),
            [HopPlan(**h) for h in hops],
        )
        # 每跳一个 attempt payload（复用 RetrievalResponse.attempt_payload 的字段约定）
        # retrieval_feedback 形如：multi_hop hops=2, h1 fused=6, h2 queries=['xxx 报销标准'], stopped=null
    except Exception as exc:
        logger.warning(f"多跳执行失败，降级为并发检索: {exc}")
        # 落到现有 retrieve_many 路径
else:
    # 现有逻辑，原样保留
```

- 模块级单例 `multi_hop_executor = MultiHopExecutor()`，与 `default_retrieval_orchestrator` 同风格。
- provider 错误聚合方式与现在一致（vector/sparse/wiki error 拼接），多跳下把各跳同名 provider 错误去重合并。

### 1.7 状态与可观测（`app/agents/state.py`、返回结构）

- `AgenticRAGState` 增加 `multi_hop_trace: Optional[List[Dict[str, Any]]]`，manager 初始 state 与 stream 初始 state 两处都要补默认值（注意 `stream_query` 的 initial_state 目前字段不全，顺手对齐）。
- trace 每跳记录：`hop / purpose / rendered_queries / extracted_slots / dense_results / sparse_results / wiki_results / fused_results / elapsed_ms / errors / stopped_reason`。
- manager.query 返回体增加 `multi_hop_trace`；`AgenticRAGResponse`（`app/routes/agentic_rag.py:25`）加同名字段。
- 会话落库的 rag metadata（`app/routes/conversations.py` 里写 `query_analysis` 那段）把 `multi_hop_trace` 一并存入，方便 badcase 复盘。
- 前端本 Sprint **不做**专门可视化，trace 通过 API 返回即可（Sprint 4 再做过程时间线）。

### 1.8 comparison 类问题：本 Sprint 顺手修

comparison 不需要顺序跳，但现在和普通问题走完全相同的 prompt。两件小事：

1. planner prompt 已要求 comparison 拆 2-4 个子查询——补一条规则：**每个对比对象一条独立 query，且必须包含对象名**（防止"它的区别是什么"这种残缺子查询）。
2. `answer_generator`（`nodes.py:769`）消费 `query_plan.answer_style`（字段已存在但当前没用）：`table` 时要求"先给对比表格再给结论"，`steps` 时分步骤，`brief` 时三句话以内。

### 1.9 测试清单（新文件 `tests/test_multi_hop.py`）

沿用 `tests/test_agentic_rag_nodes.py` 的 Dummy/Sequenced LLM 风格：

1. `_normalize_hops`：合法计划截断；跳号不连续/悬空 depends_on/未定义占位符 → 返回 `[]`。
2. slot 抽取成功：DummyLLM 返回 `{"文件名": "差旅费管理办法"}`，断言 hop2 query 被渲染为 `差旅费管理办法 报销标准`，且 hop2 在 hop1 之后执行（用带时间戳的 fake orchestrator 验证调用顺序）。
3. slot 为 null：只执行 hop1，trace 带 `stopped_reason="slot_not_found"`，不调用 hop2。
4. slot LLM 超时：注入 sleep fake，断言降级为 None 且不抛异常。
5. 多跳总超时：hop1 慢于总预算 → 返回 hop1 结果 + `stopped_reason="timeout"`。
6. executor 内部异常：retriever 节点捕获后走旧 `retrieve_many` 路径，返回结构与无 hops 时完全一致（回归保护）。
7. group label 与融合：同一 chunk 在两跳都命中时 RRF 分数累加（构造固定 ranked groups 断言排序）。
8. `MULTI_HOP_ENABLED=false` 时即使计划含 hops 也走旧路径。
9. retriever 节点：multi_hop trace 中每跳 attempt 的字段齐全；provider 错误被聚合。
10. comparison：answer_style=table 时 answer prompt 中包含表格要求（检查传入 `chat_completion` 的 messages）。

全量回归：`agentic_rag_env/bin/pytest -q` 必须保持全绿（当前基线 142 passed）。

### 1.10 人工评测集（上线门槛）

新建 `tests/fixtures/multi_hop_golden.jsonl`，每行 `{"q": ..., "must_mention": [...], "intermediate_entity": ...}`，先由人工写 15 条：

- 10 条真两跳：引用文件型（"X 办法提到的 Y 规定了什么"）、实体属性型（"XX 项目负责人所在部门的职责"）、编号条款型。
- 5 条干扰项：看似多跳实则单跳的问题，断言它们**不被**标成 multi_hop（防止 planner 滥用，多一跳 = 多一次 LLM 调用和延迟）。

跑测脚本 `scripts/eval_multi_hop.py`（手工执行，不进 CI，因为依赖真实 LLM/知识库）：对每题打印 route、hops、渲染后的 hop2 query、答案、是否答出 `must_mention`。

**验收标准：**

- [ ] 15 题中 ≥12 题 hop2 query 正确填入中间实体（`intermediate_entity` 被命中）。
- [ ] 5 条干扰题 ≤1 题被误判 multi_hop。
- [ ] 任意单题多跳路径总延迟 ≤ 2 × 单跳 P95（从 trace 的 elapsed_ms 统计）。
- [ ] 关闭 `MULTI_HOP_ENABLED` 后行为与今天完全一致；强制异常时 100% 降级成功（测试 6 覆盖）。
- [ ] 全量 pytest 全绿；`npm run build` 不受影响。

### 1.11 工期分解

| 天 | 内容 |
|---|---|
| Day 1 | 1.2 配置 + 1.5 编排器重构（先保证全绿）+ 1.3 planner 协议与规整 |
| Day 2 | 1.4 executor + 1.6 节点接入 + 1.9 测试 1-8 |
| Day 3 | 1.7 trace 落库 + 1.8 comparison + 测试 9-10 + 1.10 golden 评测、文档更新 |

---

## Sprint 2：修复多轮对话失效（0.5-1 天，建议紧跟 Sprint 1）

这是一个现存 bug，成本极低收益明显：会话历史和摘要已经传入 `state["messages"]`，但 `query_analyzer`（`nodes.py:402`）和 `answer_generator`（`nodes.py:779`）的 prompt 完全不读它，追问"那它的第二条呢"必挂。

- 【入口文件】`app/agents/nodes.py`
- 【改动点】
  1. 查询分析 prompt 前注入"最近 3 轮对话 + 会话摘要"，要求先消解指代（把"它/这份文件/第二条"改写成独立可检索的 query），用改写后的 query 做后续检索（`state["current_query"]`），原始问题保留。
  2. 答案生成 prompt 附同样的对话上下文。
  3. 历史拼接复用 `app/routes/conversations.py` 已有的 `compose_history_with_summary` 思路，不要在节点里重新造。
- 【验收】补 3 条 e2e 节点测试：代词追问、省略主语追问、跨轮引用编号追问；断言 `current_query` 包含消解后的实体。
- 【注意】Sprint 1 的 hop query 渲染应基于消解后的 `current_query`，两项改动在 retriever 入口自然合流。

---

## 后续 Sprint（任务卡，按顺序领取）

### Sprint 3：效果可度量（1-2 天）

- 建立 50-100 条专家标注 golden set（问题 + 必中 chunk_id + 参考答案），脚本化计算：召回命中率@k、MRR、引用准确率、拒答正确率、P95 延迟。
- 质量分现状盘点：`AGENTIC_RAG_MAX_RETRIEVALS=1` 时低分分叉永远不触发（`nodes.py:908` decision_maker），本期明确质量分只做展示，或把默认检索次数恢复为 2 并重新评测延迟成本——二选一，不要维持"看起来会自适应重试实际不会"的状态。
- 验收：每次改 prompt/切分/rerank 前能跑出对比报告；golden 集纳入版本库。

### Sprint 4：回答体验（2-3 天）

- 工作台切 SSE（`/agentic-rag/stream` 已存在，前端 `http.ts` 目前 30s 硬超时且非流式），逐字渲染。
- 质量评估移到答案返回后异步进行，不阻塞首字。
- 前端展示 multi_hop_trace（Sprint 1 产物）：检索了几跳、每跳 query、填了什么槽——让用户看见"智能"，也方便一键反馈 badcase。
- 停止生成 / 重新生成 / 复制 / 推荐追问。

### Sprint 5：反馈飞轮（2-3 天）

- `answer_feedback` 表已具备 rating/reason/comment/corrected_answer 但零消费。
- 做最小运营台：按租户/原因聚合，点踩详情自动带 query_plan + multi_hop_trace + 命中 chunk；一键"加入 golden set"和"触发源文档重编 Wiki"。
- 验收：点踩一条 badcase 后，能在不翻日志的情况下定位是召回、槽位抽取还是生成的问题。

### Sprint 6：知识新鲜度（2-3 天）

- 文档上传做内容 hash 去重；入库状态机（parsed / vectorized / failed + 失败原因）暴露到文档列表，消除 README FAQ #3 的"有文档没向量靠查日志"。
- 源文档更新/删除后，关联 Wiki 页打 `stale` / 级联软删，提供批量重编译。
- 删除文档与向量、Wiki 的一致性补事务或补偿任务。

### Sprint 7：企业化底座（3-5 天）

- 控制台登录态（先接 OIDC/SSO），租户从身份推导，去掉手填 tenant 输入框；`http.ts` 注入认证头（现在 AUTH_ENABLED=true 控制台即不可用）。
- API key 多 key + 只读/读写角色 + 轮换；per-tenant 限流和 token 配额（当前无限流，LLM 费用可被单租户打穿）。
- 上传文件做真实类型校验（magic bytes），上下文加提示词注入的基本隔离提示。

### Sprint 8：运维与成本（2-3 天）

- Dockerfile + docker-compose（postgres/milvus）+ CI（ruff、pytest、npm build、alembic 检查）；依赖统一到 pyproject 单源，删除 requirements 双份维护。
- MetricsRegistry 导出 Prometheus（当前是进程内字典，重启清零）；按租户归集 token/成本/缓存命中率。
- embedding 与问答语义缓存。
- 稀疏检索从 LIKE 正则（`hybrid_search.py`）升级为 pg tsvector/BM25，并用 Sprint 3 的评测集验证 hybrid 增益。
- Wiki 编辑冲突提示、修订 diff、链接增量重建。

---

## 排期总览

| Sprint | 内容 | 工期 | 依赖 |
|---|---|---|---|
| **1** | **真·多跳（含 comparison 修正）** | **3 天** | **无，立即开始** |
| 2 | 多轮对话修复 | 0.5-1 天 | 与 S1 同处改 retriever，紧跟 |
| 3 | 评测集与离线跑分 | 1-2 天 | 无，可与 S1 并行准备标注 |
| 4 | 流式回答 + 过程可视化 | 2-3 天 | S1 的 trace |
| 5 | 反馈运营台 | 2-3 天 | S3、S4 |
| 6 | 知识新鲜度 | 2-3 天 | 无 |
| 7 | 认证/权限/限流 | 3-5 天 | 无（但需先定身份方案） |
| 8 | 部署/监控/成本 | 2-3 天 | 无 |

完成 S1-S3（约一周）后，系统就同时具备了"更强的推理能力（多跳、多轮）"和"证明它变强的能力（评测）"——之后的所有优化都应该在评测分数的驱动下排序，而不是凭感觉。
