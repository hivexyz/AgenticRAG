# AgenticRAG Frontend

React + Vite + TypeScript + Ant Design 前端骨架，首批落地页面：

- 文档管理页 `/documents`
- Wiki 页面 `/wiki`
- 问答工作台 `/workbench`
- 反馈闭环 `/feedback`

## 本地启动

```bash
cd frontend
npm install
npm run dev
```

默认通过 Vite 代理访问：
- 前端：`http://127.0.0.1:5173`
- 后端代理目标：`http://127.0.0.1:8001`

如需改后端地址：

```bash
VITE_API_PROXY_TARGET=http://127.0.0.1:8001 npm run dev
```

认证开启时，可在控制台顶部输入 API Key，或通过环境变量预置：

```bash
VITE_API_KEY=your_key npm run dev
```

控制台会通过 `/api/v1/auth/me` 推导租户和权限，业务页面只展示当前租户，不再手填 `tenant_id`。

## 当前已接接口

- `GET /api/v1/documents/`
- `GET /api/v1/documents/management/presets`
- `POST /api/v1/documents/`
- `POST /api/v1/documents/upload`
- `POST /api/v1/documents/{id}/reindex`
- `POST /api/v1/documents/bulk-delete`
- `POST /api/v1/documents/{id}/retry-delete`
- `GET /api/v1/documents/{document_id}/chunks/{chunk_id}`
- `GET /api/v1/conversations/`
- `POST /api/v1/conversations/`
- `GET /api/v1/conversations/{session_id}/messages`
- `POST /api/v1/conversations/{session_id}/messages`
- `POST /api/v1/conversations/{session_id}/messages/stream`
- `POST /api/v1/feedback/answers`
- `GET /api/v1/feedback/badcases`
- `POST /api/v1/feedback/answers/{feedback_id}/golden-set`
- `POST /api/v1/feedback/answers/{feedback_id}/wiki-recompile`

## 当前注意事项

1. 文档管理页已展示内容 hash、入库状态、向量状态和 chunk 详情；重复内容会复用已有文档。
2. 问答工作台已支持：
   - 句级引用展示
   - 证据卡片
   - 不确定性提示
   - 流式回答
   - 反馈按钮
3. 反馈闭环页用于运营 badcase：查看 query_plan、multi_hop_trace、命中 chunk，并一键加入 Golden Set 或触发 Wiki 重编。
4. Wiki 页面支持查看 `ready` / `stale` 状态、编辑冲突提示和修订 diff；源文档更新后需要重新编译 stale 页面。
5. 仍建议保留现有 `front/` Gradio 作为内部调试界面，待新前端成熟后再决定是否移除。
