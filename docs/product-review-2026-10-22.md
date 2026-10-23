# AgenticRAG 产品改进分析（2026-10-22）

> 日期：2026-10-22
> 分支：v2（最近提交 88bfb49e，2026-06-15；本报告基于工作区当前代码，含大量未提交改动）
> 角色视角：AI 产品经理
> 盘点范围：后端 `app/`（约 11.6k 行）、React 控制台 `frontend/`、评测设施 `tests/eval/`、`scripts/`、Docker/CI、Wiki 与反馈闭环

## 一句话结论

项目在 4 个月里已经从"RAG Demo"进化成了**工程完成度相当高的 Agentic RAG 平台**：真·多跳检索、流式 SSE、引用证据卡、反馈 badcase 运营台、Wiki 编译任务队列、API Key/OIDC、限流配额、Prometheus、Docker/CI、离线评测集都已落地。

但当前处于一个危险节点：**一批"看起来已经生效"的能力实际上是断的或假的**，而且全部新代码尚未提交。当务之急不是加功能，而是先把"信任链"和"飞轮"补成真的。

---

## 当前已具备的能力（证据）

- LangGraph 六节点管线：query_analyzer → retriever → reranker → context_builder → answer_generator → quality_evaluator，带条件循环（`app/agents/manager.py:46-68`）。
- 真·顺序多跳检索（槽位填充，最多 2 跳、跨跳 RRF、失败降级、完整 trace），见 `app/services/multi_hop.py`。
- token 级 SSE 流式回答、停止生成、重新生成（`app/routes/conversations.py:389-462`，`app/agents/manager.py:276-363`）。
- 句级引用绑定 + 来源标记剥离展示 + 证据卡与原文片段抽屉（`app/agents/nodes.py:60-185`，`frontend/src/components/chat/ConversationPanel.tsx`）。
- 反馈提交、badcase 聚合、一键加入 Golden Set、一键触发 Wiki 重编、聚合分析接口（`app/routes/feedback.py`，`app/services/feedback_loop.py`）。
- Wiki 知识编译：持久化页面、修订历史、软删除、反链、后台 Postgres 任务队列 + 独立 worker + 启动恢复（`app/services/wiki.py`，`app/workers/wiki_worker.py`）。
- 企业底座：API Key（read/write/admin scope）、可信 OIDC 头、生产 fail-fast、租户限流与 token 日配额、上传流式限长与 magic bytes 校验。
- 运维：Dockerfile + docker-compose、GitHub Actions CI、Prometheus 指标（含租户 token/成本、缓存命中）、embedding/query-analysis TTL 缓存、Alembic 迁移。
- 离线评测：51 条 golden case，输出 recall@k、MRR、引用准确率、必提词准确率、拒答准确率、P95 延迟；多跳 15 条专项 case 带阈值门禁。

---

## P0：上线前必须修（已存在但失效/自相矛盾的能力）

### 1. Sprint 1-8 全部成果仍未提交

`v2` 最近提交停在 2026-06-15，`app/services/`、`app/workers/`、`app/routes/auth.py`、`tests/eval/`、`migrations/`、`Dockerfile`、`.github/` 全部为 untracked。约 188 个测试保护的代码没有任何 PR、评审和远端备份。

**行动**：第一件事是分批提交 + 开 PR，而不是继续堆功能。

### 2. "自适应重检索"是死逻辑

- `AGENTIC_RAG_MAX_RETRIEVALS` 默认 1（`app/config.py:122`），质量分 < 0.8 的重检索循环永远不触发；
- 即便打开，`retrieval_feedback` 只写不读（`app/agents/nodes.py:875`），重试会用完全相同的 query 再检索一遍，不会改写策略；
- 流式路径绕过整个 LangGraph，手写循环驱动节点（`app/agents/manager.py:276`）；
- checkpointer 是进程内 `MemorySaver`，每次请求随机 thread_id（`manager.py:30,88-94`），无跨请求图记忆。

**行动**：默认值改 2 并让低质反馈真正驱动 query 改写（放宽/换关键词/换 route）；或者明确删掉这个分叉。不要让图里存在"假思考"。

### 3. 低质答案的拒答在流式下时序颠倒

- 零证据硬拒答正常（`nodes.py:1033-1046`）；
- 但 `quality_score < 0.35` 的低置信只挂元数据、不拦截答案（`nodes.py:1296`）；
- 流式下答案全部吐完后才跑质量评估（`manager.py:322-345`）——用户读完不可信答案才看到"需确认"；
- 质量评估异常默认打 0.5 分（`nodes.py:1303-1312`），属 fail-silent。

**行动**：低质答案在 `answer_done` 前插入显著折叠/警示态；评估服务异常显式标"未质检"，不要静默给中分。

### 4. 评测体系不能发现回归，分数是"自我实现"

- `tests/eval/eval_runner.py` 的 `main()` 只打印不 assert，CI 中该步骤不可能失败（`.github/workflows/ci.yml:40-41`）；
- 51 条 case 跑的是**录制结果 fixture**，recall@5=1.0、MRR=0.977、其余全 1.0——录制物天然不会回归，数字无信息量；且 `tests/eval/` 整个目录尚未入 git，结果无时间戳、无历史；
- 指标全是字面匹配（chunk_id 命中、子串必提词），**没有忠实度/幻觉率的语义评测**——这恰是 RAG 产品第一指标；
- 多跳 live 评测脚本自述"故意不进 CI"（`scripts/eval_multi_hop.py:3-6`），上线前要求的真实模型验收目前仍是 recorded 模式。

**行动**：CI 加阈值门禁（recall@5、citation、refusal 任一下降即 fail）；建定期（nightly/手动）live LLM-judge 忠实度/相关性评测；接真实知识库前必须跑一次多跳 live 验收。

### 5. 反馈 → Golden Set 飞轮在生产部署中物理断裂

运营台"加入 Golden Set"写 `tests/eval/eval_cases.jsonl`（`app/routes/feedback.py:185-189`），但后端 Dockerfile 不拷贝 `tests/` 目录（`Dockerfile:17-22`）。容器内写入的是随容器销毁的临时路径，生产反馈永远进不了评测管线。

**行动**：Golden Set 落库（新建 eval_cases 表或挂持久卷），评测从存储层读取。

### 6. 查询规划产出的 filters 未被执行

planner 输出 `filters`（知识库/文档/时间范围），retriever 也构造了 `RetrievalRequest.filters`（`nodes.py:576,610`），但 vector/sparse provider 实际只按 tenant + top_k 检索（`app/services/retrieval.py:93-97`），只有 Wiki 认 knowledge_base。**"只基于这批文档回答"是部门库、单文档追问、权限隔离场景的硬需求。**

另外 rerank 用的是原始 query 而非指代消解后的 `standalone_query`（`nodes.py:959-963`），多轮场景排序质量白丢。

**行动**：filters 下推到 vector/sparse 检索；rerank 改用 standalone_query。

### 7. `answer_style=table` 承诺表格，前端不渲染 Markdown

planner 为对比类问题选择 table/steps/brief 风格并写入生成 prompt，但工作台答案用纯文本 `Typography.Paragraph` 渲染（`ConversationPanel.tsx`），表格、列表、代码块全部塌成纯文本。

**行动**：接入 Markdown renderer，或砍掉该规划字段。

---

## P1：产品纵深（从"内部工具"到"有人持续使用的产品"）

### 8. 引用可信度仍偏脆

- 无引用标记时整段答案兜底绑给前 3 个来源（`nodes.py:88-98`），`来源4+` 被静默丢弃（上下文 4 篇只引 3 篇）；
- "证据高亮"取 snippet 前 120 字符，不是与答案匹配的 span；claim 取 snippet 前缀而非真实论点（`nodes.py:153-185`）；
- 每句 `uncertainty_flag` 仅靠"可能/建议/不确定"等关键词启发式（`nodes.py:67-69`）；
- 前端块级引用角标不可点击，只有底部证据卡可点。

**行动**：来源数放宽到与上下文一致；高亮改为关键词/span 匹配；块级角标可点击。RAG 的立身之本是"每句话都能溯源"。

### 9. 反馈闭环只闭了一半

- 无分诊状态/负责人/已解决队列（`answer_feedback` 表无 status 字段，`app/db_models/feedback.py:13-31`）；任何持 write key 者都能加 Golden Set、触发 Wiki 重编，无审批；
- 工作台只能对**最新一条**答案反馈，UI 没有 comment 与"修正答案"输入框（API 已支持 `corrected_answer`）；
- 运营台硬编码只看点踩（`FeedbackOpsPage.tsx:53`），点赞案例不可见，无法沉淀"答得好的标准答案"；
- `/feedback/analytics` 聚合接口（负反馈率、原因分布、知识缺口、未命中文档、检索失败率、平均延迟）**前端没有任何页面消费**；
- 成本估算为硬编码公式 `len(messages)*$0.0002 + ...`（`routes/feedback.py:291`），与模型侧 token 记账互不对账。

**行动**：反馈分诊状态流 + 权限收口；工作台支持任意消息反馈 + comment/修正输入；建设真正的质量看板消费 analytics。

### 10. 企业身份模型撑不住多用户

- 无用户表：仅 env 静态 API key（无轮换接口、无自然人身份），OIDC 盲信代理头无验签；admin scope 存在但无任何 admin 专属接口（`app/auth.py`）；
- `AUTH_ALLOW_ANONYMOUS` 仅启动期检查，请求期无效果（`auth.py:78-91`），语义误导；
- 前端无登录页、无路由守卫、不检查 scopes，key 明文存 localStorage（`frontend/src/app/router.tsx`，`services/http.ts:3-19`）；
- 会话 `user_id` 由客户端自报（`routes/conversations.py:54`），不与身份绑定，审计落不到自然人；
- 文档级/知识库级权限不存在：同租户内所有人可见全部文档。对"部门制度库"场景是硬门槛。

### 11. 多进程一扩，限流/配额/指标/缓存全失真

限流、token 日配额、Prometheus 指标、TTL 缓存都是进程内字典：uvicorn 多 worker 与 wiki-worker 各算各的，重启清零（`app/services/tenant_limits.py:20` 注释已承认 Redis 计划）。Wiki 编译的 LLM 消耗记到 `default` 租户（`app/models/llm.py:43-44`）；成本单价表默认 $0 且不分 prompt/completion；流式 token 事前估算、事后不核对实际用量（`llm.py:101-116`）。

**行动**：Redis（或 DB）共享计数；后台任务按 job 归属租户记账；流式用量事后对账。

### 12. 中文稀疏检索这条腿基本是瘸的

稀疏路用 `to_tsvector('simple')`，对中文等于不切词，实际靠 pg_trgm + ILIKE 顶着（`app/database/hybrid_search.py:93-150`）；Wiki 搜索同样是 ILIKE 词频打分（`app/services/wiki.py:608-680`）。迁移 `20261021_0004_sparse_tsvector_index.py` 已建索引但**服务代码尚未切换使用**。

**行动**：接 zhparser/jieba 或 BM25，并用评测集验证 hybrid 相对纯向量的增益——无增益就不为复杂度买单。

### 13. 模型层韧性不足

LLM/Embedding 的 AsyncOpenAI 客户端无显式 timeout/retry 配置（`app/models/llm.py:33-36`，`app/models/embedding.py:39-42`），仅靠 SDK 默认；无多供应商/多模型 fallback；prompt 无版本管理，改 prompt 无法与效果回归挂钩。检索侧有 3s 超时与并发信号量（`retrieval.py:168,198-217`），rerank 60s 超时无重试（`models/reranker.py:223-234`）。

**行动**：统一显式超时/重试/熔断、按模型计价表、prompt 版本化。

---

## P2：体验与运营打磨

| 领域 | 具体缺口 |
|---|---|
| 文档管理 | 不支持多文件、无上传进度/大小预警、入库状态不自动轮询、无重新解析（仅重向量化）、无分页、无原文下载/预览、编译 Wiki 需手输数字文档 ID；上传异常无 catch（`DocumentUploadPanel.tsx:57-65`） |
| 工作台 | 无会话重命名/删除、推荐追问硬编码 3 条、多跳 trace 仅结束后展示（建议做实时阶段进度，让"智能体被看见"）、无 onboarding，落地页直接是管理员文档列表 |
| Wiki | 无修订 side-by-side diff/回滚、纯 textarea 无 Markdown 预览、无页面关系图；编译任务无列表接口（只能按 ID 查单个） |
| 反馈运营 | 点赞案例不可见、无分诊/负责人/SLA、无分页/导出（固定 50 条）、无 Golden Set 浏览器 |
| 安全 | 仅系统提示词声明上下文不可信（`nodes.py:243-247,1080`），无结构化工具边界防注入；API key 存 localStorage（XSS 暴露）；上传无病毒扫描 |
| 运维 | 无跨节点 tracing（OTEL）、无告警/SLO、审计仅日志行不可查；CI 无类型检查、无安全扫描、无带 Postgres/Milvus 的集成测试；ruff 仅查 E9/F 且忽略 F401 |
| 产品化 | Gradio 仍打入后端镜像且为主依赖（`Dockerfile:20`，`pyproject.toml:26`），建议明确退役；React 控制台在 docker-compose 独立构建但未进后端镜像；中文硬编码无 i18n；无答案分享/对外嵌入；`/agentic-rag/query` 的 `stream` 字段定义了但被忽略（`routes/agentic_rag.py:22`） |

---

## 建议的迭代排序

| 时间 | 主题 | 内容 |
|---|---|---|
| 第 0 周 | 止血 | 分批提交 v2 全部代码并入主干；Golden Set 落库；eval 加阈值门禁 |
| 第 1 周 | 把"真"补上 | filters 下推 vector/sparse + 知识库范围问答；rerank 改用 standalone query；低质答案时序治理；前端 Markdown 渲染 |
| 第 2 周 | 让飞轮转起来 | LLM-judge 忠实度语义评测 + 多跳 live 验收；质量看板消费 analytics；反馈分诊状态流；引用精度修补 |
| 第 3-4 周 | 企业化 | 真实用户身份（OIDC 验签/用户表）+ 文档级权限；Redis 共享配额/指标；中文稀疏检索切换并以评测验证增益 |

完成第 0-2 周后，后续所有优化都应在评测分数驱动下排序，而不是凭感觉。

---

## 收尾判断

> 这个项目现在最稀缺的不是新能力，而是"它声称具备的能力都为真"的证据链——**可 fail 的评测、可溯源的引用、可闭环的反馈、可对账的成本**。这四件事补齐之前，加任何新 Agent 能力都是在沙子上盖楼。

---

## 附：本次评审的关键代码索引

| 主题 | 位置 |
|---|---|
| 图拓扑与条件循环 | `app/agents/manager.py:46-68` |
| 流式绕过图、质检时序 | `app/agents/manager.py:276-363` |
| 引用解析/兜底/高亮 | `app/agents/nodes.py:23-229` |
| 零证据拒答 / 低质标记 | `app/agents/nodes.py:1033-1046, 1296` |
| filters 未下推 | `app/services/retrieval.py:93-97` |
| 多跳执行 | `app/services/multi_hop.py` |
| 反馈运营动作 | `app/routes/feedback.py:138-322` |
| Golden Set 写入路径 | `app/routes/feedback.py:185-189` |
| 评测 runner（无 assert） | `tests/eval/eval_runner.py:97-104` |
| 进程内配额 | `app/services/tenant_limits.py:20` |
| 认证与 scope | `app/auth.py`，`app/routes/auth.py` |
| 镜像不含 tests | `Dockerfile:17-22` |
| 配置项全集 | `app/config.py` |
