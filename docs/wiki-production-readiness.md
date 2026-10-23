# Wiki Production Readiness

This branch adds a wiki layer on top of the existing AgenticRAG document and retrieval system. The goal is to persist compiled knowledge pages, expose them in the console, and let AgenticRAG retrieve and cite them alongside raw document chunks.

## Implemented Scope

- `wiki_pages` persists compiled wiki pages with tenant isolation, source document traceability, source chunk IDs, status, and knowledge base metadata.
- `POST /api/v1/wiki/compile` compiles or refreshes a wiki page from a source document.
- `GET /api/v1/wiki/` lists and searches ready wiki pages as page objects for the console.
- `GET /api/v1/wiki/{page_id}` returns a page detail payload.
- `PUT /api/v1/wiki/{page_id}` allows manual correction of title, summary, content, and knowledge base.
- `DELETE /api/v1/wiki/{page_id}` soft-deletes a page by setting `status=deleted`.
- `GET /api/v1/wiki/{page_id}/revisions` lists recent page revision snapshots.
- `POST /api/v1/wiki/compile/bulk` compiles multiple source documents in one request.
- `POST /api/v1/wiki/compile/bulk` with `async_compile=true` creates a background compile job.
- `GET /api/v1/wiki/compile/jobs/{job_id}` returns the background compile job status and results.
- Pending or processing compile jobs are recovered and resubmitted during application startup.
- `GET /api/v1/wiki/index/summary` returns a knowledge-base topic index over ready wiki pages.
- `POST /api/v1/wiki/links/rebuild` rebuilds deterministic page links from title mentions.
- `GET /api/v1/wiki/{page_id}/links` returns outgoing links and backlinks for a page.
- AgenticRAG retrieval fuses vector hits, sparse chunk hits, and wiki page hits.
- Chat citations mark wiki-derived evidence and link back to the wiki page.
- The React console has a `Wiki 页面` section for list, search, compile, edit, detail, and delete workflows.
- The document table can compile a wiki page directly from a document row.

## Data Model

`wiki_pages` is created during startup through `postgres_manager.init_db()`.

Important columns:

- `tenant_id`: tenant boundary for list, detail, compile, update, delete, and retrieval.
- `knowledge_base`: optional logical grouping reused by filters.
- `slug`: stable page slug derived from the source document title.
- `summary` and `content`: compiled and manually editable wiki page content.
- `source_document_id`: source document trace.
- `source_chunk_ids`: source chunks used during compilation.
- `page_metadata`: source document metadata snapshot.
- `status`: `ready` or `deleted`.

`wiki_page_revisions` stores snapshots for compile, update, and delete actions.

The wiki schema also has an Alembic migration at `migrations/versions/20260807_0001_wiki_schema.py`.

## Operational Flow

1. Upload or create a document through the existing document workflow.
2. Ensure the document is ingested successfully; vectorization is useful for raw chunk retrieval but not required for wiki compilation.
3. Compile one wiki page from the document table action, compile a small batch synchronously, or submit a larger batch as an asynchronous compile job.
4. Review the generated page in the wiki detail drawer.
5. Edit title, summary, content, or knowledge base when the compiled page needs human correction.
6. Track asynchronous compile job status for larger batches.
7. Rebuild page links after larger wiki changes when backlink navigation should reflect the latest content.
8. Review the topic index, page relationships, and revision history when auditing compiled or manually corrected content.
9. Ask questions in the workbench; AgenticRAG can cite wiki pages and raw document chunks together.

## Verification Commands

Run backend tests that cover wiki APIs, RAG wiki retrieval, conversations, and document workflows:

```bash
PYTHONPATH=/Users/bytedance/Desktop/zkc/python/AgenticRAG agentic_rag_env/bin/pytest -q tests/test_wiki_api.py tests/test_agentic_rag_nodes.py tests/test_conversations_api.py tests/test_documents_api.py
```

Run syntax/import verification for the changed backend modules:

```bash
python3 -m py_compile app/db_models/wiki.py app/routes/wiki.py app/services/wiki.py app/agents/nodes.py app/agents/manager.py
```

Run frontend type and production build verification:

```bash
cd frontend
npm run build
```

Run production schema migration:

```bash
alembic upgrade head
```

## Production Checklist

- Confirm `alembic upgrade head` is part of the production deployment flow.
- Confirm `postgres_manager.init_db()` remains enabled for development self-bootstrap.
- Confirm API auth is enabled for production through `AUTH_ENABLED` and `AUTH_API_KEYS`.
- Confirm tenant IDs in document, wiki, and conversation requests match the expected auth mapping.
- Confirm LLM credentials are available if high-quality compilation is required; otherwise compilation falls back to rule-based summaries.
- Confirm backup policy includes `wiki_pages`, because manually edited wiki pages become knowledge assets.
- Confirm soft-deleted wiki pages are excluded from list and retrieval views.
- Confirm frontend `VITE_API_BASE_URL` points to the same API prefix used by the deployed FastAPI service.

## Operational Notes

- The task executor is still in-process. Jobs are persisted, recovered at startup, and conditionally claimed through the database; use an external queue if strict distributed scheduling is required.
- The React console uses route-level lazy loading. Keep `npm run build` in CI to catch bundle regressions.
