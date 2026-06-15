# AgenticRAG Frontend

React + Vite + TypeScript + Ant Design 前端骨架，首批落地页面：

- 文档管理页 `/documents`
- 问答工作台 `/workbench`

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

## 当前已接接口

- `GET /api/v1/documents/`
- `GET /api/v1/documents/management/presets`
- `POST /api/v1/documents/`
- `POST /api/v1/documents/upload`
- `POST /api/v1/documents/{id}/reindex`
- `POST /api/v1/documents/bulk-delete`
- `GET /api/v1/documents/{document_id}/chunks/{chunk_id}`
- `GET /api/v1/conversations/`
- `POST /api/v1/conversations/`
- `GET /api/v1/conversations/{session_id}/messages`
- `POST /api/v1/conversations/{session_id}/messages`
- `POST /api/v1/feedback/answers`

## 当前注意事项

1. 文档管理页“查看切片”当前默认尝试用 `documentId` 直接打开片段，建议下一步补一个“文档切片列表接口”用于精准选择 chunk。
2. 问答工作台已支持：
   - 句级引用展示
   - 证据卡片
   - 不确定性提示
   - 反馈按钮
3. 仍建议保留现有 `front/` Gradio 作为内部调试界面，待新前端成熟后再决定是否移除。
