from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db_models.document import Document
from app.routes import wiki as wiki_module
from app.services import wiki as wiki_service


class FakeExecuteResult:
    def __init__(self, scalar=None, scalars=None):
        self._scalar = scalar
        self._scalars = scalars if scalars is not None else ([] if scalar is None else [scalar])

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._scalars


class FakeSession:
    def __init__(self, document=None):
        self.document = document
        self.committed = 0
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, _statement):
        return FakeExecuteResult(scalar=self.document)

    async def commit(self):
        self.committed += 1

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = len(self.added)


def test_list_wiki_pages_returns_page_payloads():
    app = FastAPI()
    app.include_router(wiki_module.router, prefix="/wiki")

    class FakePage:
        id = 9
        tenant_id = "default"
        knowledge_base = "hr"
        slug = "leave-policy"
        title = "请假制度"
        summary = "请假需要审批"
        content = "请假制度正文"
        source_document_id = 12
        source_chunk_ids = [101]
        page_metadata = {"knowledge_base": "hr"}
        status = "ready"
        created_at = None
        updated_at = None

        def to_dict(self):
            return {
                "id": self.id,
                "tenant_id": self.tenant_id,
                "knowledge_base": self.knowledge_base,
                "slug": self.slug,
                "title": self.title,
                "summary": self.summary,
                "content": self.content,
                "source_document_id": self.source_document_id,
                "source_chunk_ids": self.source_chunk_ids,
                "metadata": self.page_metadata,
                "status": self.status,
                "created_at": None,
                "updated_at": None,
            }

    class ListSession(FakeSession):
        async def execute(self, _statement):
            return FakeExecuteResult(scalars=[FakePage()])

    session = ListSession()

    async def override_session():
        yield session

    app.dependency_overrides[wiki_module.postgres_manager.get_session] = override_session

    with TestClient(app) as client:
        response = client.get("/wiki/", params={"tenant_id": "default", "q": "请假"})

    assert response.status_code == 200
    data = response.json()
    assert data[0]["id"] == 9
    assert data[0]["title"] == "请假制度"
    assert "wiki_page_id" not in data[0]


def test_list_wiki_pages_returns_stale_pages_by_default():
    app = FastAPI()
    app.include_router(wiki_module.router, prefix="/wiki")

    class FakePage:
        id = 10
        tenant_id = "default"
        knowledge_base = "hr"
        slug = "leave-policy"
        title = "请假制度"
        summary = "请假摘要"
        content = "请假制度正文"
        source_document_id = 12
        source_chunk_ids = [101]
        page_metadata = {"stale_reason": "source_document_updated"}
        status = "stale"
        created_at = None
        updated_at = None

        def to_dict(self):
            return {
                "id": self.id,
                "tenant_id": self.tenant_id,
                "knowledge_base": self.knowledge_base,
                "slug": self.slug,
                "title": self.title,
                "summary": self.summary,
                "content": self.content,
                "source_document_id": self.source_document_id,
                "source_chunk_ids": self.source_chunk_ids,
                "metadata": self.page_metadata,
                "status": self.status,
                "created_at": None,
                "updated_at": None,
            }

    class ListSession(FakeSession):
        async def execute(self, _statement):
            return FakeExecuteResult(scalars=[FakePage()])

    session = ListSession()

    async def override_session():
        yield session

    app.dependency_overrides[wiki_module.postgres_manager.get_session] = override_session

    with TestClient(app) as client:
        response = client.get("/wiki/", params={"tenant_id": "default"})

    assert response.status_code == 200
    data = response.json()
    assert data[0]["status"] == "stale"
    assert data[0]["metadata"]["stale_reason"] == "source_document_updated"


def test_wiki_topic_index_groups_pages():
    app = FastAPI()
    app.include_router(wiki_module.router, prefix="/wiki")

    class FakePage:
        id = 9
        tenant_id = "default"
        knowledge_base = "hr"
        title = "请假制度"
        summary = "请假需要审批"
        updated_at = None

    class IndexSession(FakeSession):
        async def execute(self, _statement):
            return FakeExecuteResult(scalars=[FakePage()])

    session = IndexSession()

    async def override_session():
        yield session

    app.dependency_overrides[wiki_module.postgres_manager.get_session] = override_session

    with TestClient(app) as client:
        response = client.get("/wiki/index/summary", params={"tenant_id": "default"})

    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == "default"
    assert data["knowledge_bases"][0]["knowledge_base"] == "hr"
    assert data["knowledge_bases"][0]["page_count"] == 1
    assert data["knowledge_bases"][0]["pages"][0]["title"] == "请假制度"


def test_rebuild_wiki_links(monkeypatch):
    app = FastAPI()
    app.include_router(wiki_module.router, prefix="/wiki")
    session = FakeSession()

    async def override_session():
        yield session

    async def fake_rebuild_wiki_page_links(session, tenant_id, knowledge_base=None):
        return {
            "tenant_id": tenant_id,
            "knowledge_base": knowledge_base,
            "page_count": 2,
            "link_count": 1,
        }

    app.dependency_overrides[wiki_module.postgres_manager.get_session] = override_session
    monkeypatch.setattr(wiki_module, "rebuild_wiki_page_links", fake_rebuild_wiki_page_links)

    with TestClient(app) as client:
        response = client.post("/wiki/links/rebuild", params={"tenant_id": "default"})

    assert response.status_code == 200
    data = response.json()
    assert data["page_count"] == 2
    assert data["link_count"] == 1


def test_get_wiki_page_links():
    app = FastAPI()
    app.include_router(wiki_module.router, prefix="/wiki")

    class FakePage:
        id = 7
        tenant_id = "default"
        status = "ready"

    class FakeLink:
        id = 1
        tenant_id = "default"
        source_page_id = 7
        target_page_id = 9
        link_type = "title_mention"
        evidence = "引用了请假制度"
        created_at = None
        source_page = None
        target_page = None

        def to_dict(self):
            return {
                "id": self.id,
                "tenant_id": self.tenant_id,
                "source_page_id": self.source_page_id,
                "target_page_id": self.target_page_id,
                "source_title": None,
                "target_title": None,
                "link_type": self.link_type,
                "evidence": self.evidence,
                "created_at": None,
            }

    class LinkSession(FakeSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, _statement):
            self.calls += 1
            if self.calls == 1:
                return FakeExecuteResult(scalar=FakePage())
            return FakeExecuteResult(scalars=[FakeLink()] if self.calls == 2 else [])

    session = LinkSession()

    async def override_session():
        yield session

    app.dependency_overrides[wiki_module.postgres_manager.get_session] = override_session

    with TestClient(app) as client:
        response = client.get("/wiki/7/links", params={"tenant_id": "default"})

    assert response.status_code == 200
    data = response.json()
    assert data["page_id"] == 7
    assert data["outgoing"][0]["target_page_id"] == 9
    assert data["incoming"] == []


def test_compile_wiki_page_from_document(monkeypatch):
    app = FastAPI()
    app.include_router(wiki_module.router, prefix="/wiki")

    document = Document(
        id=12,
        tenant_id="default",
        title="请假制度",
        content="员工请假需提前申请，并由直属主管审批。",
        file_type="md",
        chunk_count=1,
        doc_metadata='{"knowledge_base":"hr"}',
        created_at=datetime.utcnow(),
    )
    session = FakeSession(document=document)

    async def override_session():
        yield session

    async def fake_upsert_wiki_page_from_document(session, tenant_id, document, chunk_limit=8):
        class FakePage:
            id = 3

            def to_dict(self):
                return {
                    "id": 3,
                    "tenant_id": tenant_id,
                    "knowledge_base": "hr",
                    "slug": "请假制度",
                    "title": document.title,
                    "summary": "- 提前申请\n- 直属主管审批",
                    "content": "## 主题概述\n请假流程说明",
                    "source_document_id": document.id,
                    "source_chunk_ids": [101],
                    "metadata": {"knowledge_base": "hr"},
                    "status": "ready",
                    "created_at": None,
                    "updated_at": None,
                }

        return FakePage()

    app.dependency_overrides[wiki_module.postgres_manager.get_session] = override_session
    monkeypatch.setattr(wiki_module, "upsert_wiki_page_from_document", fake_upsert_wiki_page_from_document)

    with TestClient(app) as client:
        response = client.post("/wiki/compile", json={"tenant_id": "default", "document_id": 12})

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "请假制度"
    assert data["knowledge_base"] == "hr"
    assert data["source_document_id"] == 12


def test_bulk_compile_wiki_pages(monkeypatch):
    app = FastAPI()
    app.include_router(wiki_module.router, prefix="/wiki")

    session = FakeSession()
    calls = []

    async def override_session():
        yield session

    async def fake_compile_documents_to_wiki_pages(session, tenant_id, document_ids):
        calls.extend(document_ids)
        return {
            "success_count": 1,
            "failure_count": 0,
            "pages": [{
                "id": 112,
                "tenant_id": tenant_id,
                "knowledge_base": "hr",
                "slug": "请假制度",
                "title": "请假制度",
                "summary": "摘要",
                "content": "正文",
                "source_document_id": 12,
                "source_chunk_ids": [],
                "metadata": {},
                "status": "ready",
                "created_at": None,
                "updated_at": None,
            }],
            "failures": [],
        }

    app.dependency_overrides[wiki_module.postgres_manager.get_session] = override_session
    monkeypatch.setattr(wiki_module, "compile_documents_to_wiki_pages", fake_compile_documents_to_wiki_pages)

    with TestClient(app) as client:
        response = client.post("/wiki/compile/bulk", json={"tenant_id": "default", "document_ids": [12]})

    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1
    assert data["failure_count"] == 0
    assert data["pages"][0]["source_document_id"] == 12
    assert calls == [12]


def test_async_bulk_compile_wiki_pages_submits_job(monkeypatch):
    app = FastAPI()
    app.include_router(wiki_module.router, prefix="/wiki")
    session = FakeSession()
    submitted = {}

    async def override_session():
        yield session

    def fake_submit(task_id, factory):
        submitted["task_id"] = task_id
        submitted["factory"] = factory

    app.dependency_overrides[wiki_module.postgres_manager.get_session] = override_session
    monkeypatch.setattr(wiki_module.task_runner, "submit", fake_submit)

    with TestClient(app) as client:
        response = client.post(
            "/wiki/compile/bulk",
            json={"tenant_id": "default", "document_ids": [12, 15], "async_compile": True},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == 1
    assert data["status"] == "pending"
    assert data["document_ids"] == [12, 15]
    assert submitted["task_id"] == "wiki-compile:1"


def test_get_wiki_compile_job():
    app = FastAPI()
    app.include_router(wiki_module.router, prefix="/wiki")

    class FakeJob:
        id = 2
        tenant_id = "default"
        status = "completed"
        document_ids = [12]
        success_count = 1
        failure_count = 0
        result_metadata = {"pages": [], "failures": []}
        error = None
        created_at = None
        updated_at = None

        def to_dict(self):
            return {
                "id": self.id,
                "tenant_id": self.tenant_id,
                "status": self.status,
                "document_ids": self.document_ids,
                "success_count": self.success_count,
                "failure_count": self.failure_count,
                "metadata": self.result_metadata,
                "error": self.error,
                "created_at": None,
                "updated_at": None,
            }

    session = FakeSession(document=FakeJob())

    async def override_session():
        yield session

    app.dependency_overrides[wiki_module.postgres_manager.get_session] = override_session

    with TestClient(app) as client:
        response = client.get("/wiki/compile/jobs/2", params={"tenant_id": "default"})

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == 2
    assert data["status"] == "completed"


def test_delete_wiki_page(monkeypatch):
    app = FastAPI()
    app.include_router(wiki_module.router, prefix="/wiki")

    class FakePage:
        id = 5
        tenant_id = "default"
        status = "ready"
        title = "请假制度"
        summary = "请假摘要"
        content = "请假正文"
        knowledge_base = "hr"

    session = FakeSession(document=FakePage())

    async def override_session():
        yield session

    app.dependency_overrides[wiki_module.postgres_manager.get_session] = override_session
    cleared = []

    async def fake_clear_wiki_page_links(session, tenant_id, page_id):
        cleared.append((tenant_id, page_id))

    monkeypatch.setattr(wiki_module, "clear_wiki_page_links", fake_clear_wiki_page_links)

    with TestClient(app) as client:
        response = client.delete("/wiki/5", params={"tenant_id": "default"})

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "page_id": 5}
    assert session.document.status == "deleted"
    assert session.committed == 1
    assert session.added[0].action == "delete"
    assert cleared == [("default", 5)]


def test_update_wiki_page(monkeypatch):
    app = FastAPI()
    app.include_router(wiki_module.router, prefix="/wiki")

    class FakePage:
        id = 7
        tenant_id = "default"
        status = "ready"
        title = "旧标题"
        summary = "旧摘要"
        content = "旧正文"
        knowledge_base = "old"
        slug = "old-title"
        source_document_id = 12
        source_chunk_ids = [101]
        page_metadata = {}
        created_at = None
        updated_at = None

        def to_dict(self):
            return {
                "id": self.id,
                "tenant_id": self.tenant_id,
                "knowledge_base": self.knowledge_base,
                "slug": self.slug,
                "title": self.title,
                "summary": self.summary,
                "content": self.content,
                "source_document_id": self.source_document_id,
                "source_chunk_ids": self.source_chunk_ids,
                "metadata": self.page_metadata,
                "status": self.status,
                "created_at": None,
                "updated_at": None,
            }

    page = FakePage()
    session = FakeSession(document=page)

    async def override_session():
        yield session

    async def refresh(obj):
        return None

    session.refresh = refresh
    app.dependency_overrides[wiki_module.postgres_manager.get_session] = override_session
    rebuilt = []

    async def fake_rebuild_wiki_page_links_for_page(session, tenant_id, page_id):
        rebuilt.append(("page", tenant_id, page_id))
        return {"tenant_id": tenant_id, "page_id": page_id, "page_count": 1, "link_count": 0}

    async def fake_rebuild_wiki_page_links(session, tenant_id, knowledge_base=None):
        rebuilt.append(("kb", tenant_id, knowledge_base))
        return {"tenant_id": tenant_id, "knowledge_base": knowledge_base, "page_count": 1, "link_count": 0}

    monkeypatch.setattr(wiki_module, "rebuild_wiki_page_links_for_page", fake_rebuild_wiki_page_links_for_page)
    monkeypatch.setattr(wiki_module, "rebuild_wiki_page_links", fake_rebuild_wiki_page_links)

    with TestClient(app) as client:
        response = client.put(
            "/wiki/7",
            json={
                "tenant_id": "default",
                "title": "新标题",
                "summary": "新摘要",
                "content": "新正文",
                "knowledge_base": "hr",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "新标题"
    assert data["summary"] == "新摘要"
    assert data["content"] == "新正文"
    assert data["knowledge_base"] == "hr"
    assert session.committed == 1
    assert session.added[0].action == "update"
    assert session.added[0].title == "新标题"
    assert session.added[0].revision_metadata["fields"] == ["title", "summary", "content", "knowledge_base"]
    assert session.added[0].revision_metadata["diff"]["title"] == {"before": "旧标题", "after": "新标题"}
    assert rebuilt == [("page", "default", 7), ("kb", "default", "old")]


def test_update_wiki_page_detects_edit_conflict():
    app = FastAPI()
    app.include_router(wiki_module.router, prefix="/wiki")

    class FakePage:
        id = 7
        tenant_id = "default"
        status = "ready"
        title = "旧标题"
        summary = "旧摘要"
        content = "旧正文"
        knowledge_base = "hr"
        slug = "old-title"
        source_document_id = 12
        source_chunk_ids = [101]
        page_metadata = {}
        created_at = None
        updated_at = datetime(2026, 10, 21, 12, 0, 0)

        def to_dict(self):
            return {}

    session = FakeSession(document=FakePage())

    async def override_session():
        yield session

    app.dependency_overrides[wiki_module.postgres_manager.get_session] = override_session

    with TestClient(app) as client:
        response = client.put(
            "/wiki/7",
            json={
                "tenant_id": "default",
                "title": "新标题",
                "expected_updated_at": "2026-10-21T11:59:00",
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"]["message"] == "Wiki 页面已被其他人更新，请刷新后再编辑"


def test_list_wiki_page_revisions():
    app = FastAPI()
    app.include_router(wiki_module.router, prefix="/wiki")

    class FakeRevision:
        id = 1
        tenant_id = "default"
        page_id = 7
        action = "update"
        title = "新标题"
        summary = "新摘要"
        content = "新正文"
        knowledge_base = "hr"
        revision_metadata = {"fields": ["title", "content"]}
        created_at = None

        def to_dict(self):
            return {
                "id": self.id,
                "tenant_id": self.tenant_id,
                "page_id": self.page_id,
                "action": self.action,
                "title": self.title,
                "summary": self.summary,
                "content": self.content,
                "knowledge_base": self.knowledge_base,
                "metadata": self.revision_metadata,
                "created_at": None,
            }

    class RevisionSession(FakeSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, _statement):
            self.calls += 1
            if self.calls == 1:
                return FakeExecuteResult(scalar=type("FakePage", (), {"id": 7, "status": "ready"})())
            return FakeExecuteResult(scalars=[FakeRevision()])

    session = RevisionSession()

    async def override_session():
        yield session

    app.dependency_overrides[wiki_module.postgres_manager.get_session] = override_session

    with TestClient(app) as client:
        response = client.get("/wiki/7/revisions", params={"tenant_id": "default"})

    assert response.status_code == 200
    data = response.json()
    assert data[0]["action"] == "update"
    assert data[0]["title"] == "新标题"


def test_get_deleted_wiki_page_returns_404():
    app = FastAPI()
    app.include_router(wiki_module.router, prefix="/wiki")
    session = FakeSession(document=None)

    async def override_session():
        yield session

    app.dependency_overrides[wiki_module.postgres_manager.get_session] = override_session

    with TestClient(app) as client:
        response = client.get("/wiki/7", params={"tenant_id": "default"})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rebuild_links_for_empty_knowledge_base_does_not_delete():
    class EmptyKnowledgeBaseSession:
        def __init__(self):
            self.delete_called = False
            self.committed = 0

        async def execute(self, statement):
            if statement.__class__.__name__ == "Delete":
                self.delete_called = True
                raise AssertionError("empty scoped rebuild must not delete tenant links")
            return FakeExecuteResult(scalars=[])

        async def commit(self):
            self.committed += 1

    session = EmptyKnowledgeBaseSession()

    result = await wiki_service.rebuild_wiki_page_links(
        session=session,
        tenant_id="default",
        knowledge_base="missing",
    )

    assert result == {
        "tenant_id": "default",
        "knowledge_base": "missing",
        "page_count": 0,
        "link_count": 0,
    }
    assert not session.delete_called
    assert session.committed == 0


@pytest.mark.asyncio
async def test_rebuild_wiki_page_links_for_page_rebuilds_touching_links():
    class FakePage:
        def __init__(self, id, title, summary, content):
            self.id = id
            self.tenant_id = "default"
            self.status = "ready"
            self.title = title
            self.summary = summary
            self.content = content

    class IncrementalLinkSession:
        def __init__(self):
            self.pages = [
                FakePage(1, "请假制度", "涉及住宿标准", "引用住宿标准"),
                FakePage(2, "住宿标准", "摘要", "正文"),
                FakePage(3, "报销制度", "提到请假制度", "正文"),
            ]
            self.added = []
            self.delete_calls = 0
            self.committed = 0

        def add(self, obj):
            self.added.append(obj)

        async def execute(self, statement):
            if statement.__class__.__name__ == "Delete":
                self.delete_calls += 1
                return FakeExecuteResult()
            return FakeExecuteResult(scalars=self.pages)

        async def commit(self):
            self.committed += 1

    session = IncrementalLinkSession()

    result = await wiki_service.rebuild_wiki_page_links_for_page(
        session=session,
        tenant_id="default",
        page_id=1,
    )

    assert result["link_count"] == 2
    assert session.delete_calls == 1
    assert {(item.source_page_id, item.target_page_id) for item in session.added} == {(1, 2), (3, 1)}
    assert session.committed == 1


@pytest.mark.asyncio
async def test_mark_wiki_pages_stale_for_document_records_revision():
    class FakePage:
        id = 9
        tenant_id = "default"
        knowledge_base = "hr"
        title = "请假制度"
        summary = "摘要"
        content = "正文"
        source_document_id = 12
        source_chunk_ids = [101]
        page_metadata = {}
        status = "ready"

    class StaleSession:
        def __init__(self):
            self.page = FakePage()
            self.added = []
            self.committed = 0
            self.delete_calls = 0

        def add(self, obj):
            self.added.append(obj)

        async def execute(self, statement):
            if statement.__class__.__name__ == "Delete":
                self.delete_calls += 1
                return FakeExecuteResult()
            return FakeExecuteResult(scalars=[self.page])

        async def commit(self):
            self.committed += 1

    session = StaleSession()

    result = await wiki_service.mark_wiki_pages_stale_for_document(
        session=session,
        tenant_id="default",
        document_id=12,
    )

    assert result == [9]
    assert session.page.status == "stale"
    assert session.page.page_metadata["stale_reason"] == "source_document_updated"
    assert session.added[0].action == "stale"
    assert session.delete_calls == 1


@pytest.mark.asyncio
async def test_recover_wiki_compile_jobs_submits_after_commit(monkeypatch):
    class FakeJob:
        id = 42
        status = "processing"
        error = "interrupted"

    class RecoverSession:
        def __init__(self):
            self.job = FakeJob()
            self.committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, _statement):
            return FakeExecuteResult(scalars=[self.job])

        async def commit(self):
            self.committed = True

    session = RecoverSession()
    submitted = []

    def fake_session_maker():
        return session

    def submit_job(job_id):
        assert session.committed
        submitted.append(job_id)

    monkeypatch.setattr(wiki_service, "async_session_maker", fake_session_maker)

    result = await wiki_service.recover_wiki_compile_jobs(submit_job)

    assert result == {"recovered_count": 1, "job_ids": [42]}
    assert session.job.status == "pending"
    assert session.job.error is None
    assert submitted == [42]


@pytest.mark.asyncio
async def test_bulk_compile_rolls_back_failed_document_and_continues(monkeypatch):
    class FakeDocument:
        def __init__(self, document_id):
            self.id = document_id
            self.tenant_id = "default"
            self.title = f"doc-{document_id}"

    class BulkSession:
        def __init__(self):
            self.documents = [FakeDocument(1), FakeDocument(2)]
            self.execute_count = 0
            self.rollbacks = 0

        async def execute(self, _statement):
            document = self.documents[self.execute_count]
            self.execute_count += 1
            return FakeExecuteResult(scalar=document)

        async def rollback(self):
            self.rollbacks += 1

    class FakePage:
        def __init__(self, document):
            self.document = document

        def to_dict(self):
            return {
                "id": self.document.id + 100,
                "tenant_id": "default",
                "title": self.document.title,
            }

    session = BulkSession()
    seen = []

    async def fake_upsert_wiki_page_from_document(session, tenant_id, document, chunk_limit=8):
        seen.append(document.id)
        if document.id == 1:
            raise RuntimeError("db failed")
        return FakePage(document)

    monkeypatch.setattr(wiki_service, "upsert_wiki_page_from_document", fake_upsert_wiki_page_from_document)

    result = await wiki_service.compile_documents_to_wiki_pages(
        session=session,
        tenant_id="default",
        document_ids=[1, 2],
    )

    assert seen == [1, 2]
    assert session.rollbacks == 1
    assert result["success_count"] == 1
    assert result["failure_count"] == 1
    assert result["pages"][0]["id"] == 102
    assert result["failures"][0]["document_id"] == 1


@pytest.mark.asyncio
async def test_run_wiki_compile_job_marks_completed_and_releases_lock(monkeypatch):
    class FakeJob:
        id = 77
        tenant_id = "default"
        status = "pending"
        document_ids = [1, 2]
        retry_count = 0
        max_retries = 3
        locked_by = None
        locked_at = None
        next_run_at = None
        success_count = 0
        failure_count = 0
        result_metadata = None
        error = "previous error"
        updated_at = None

    class JobSession:
        def __init__(self):
            self.job = FakeJob()
            self.execute_count = 0
            self.commits = 0
            self.rollbacks = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, _statement):
            self.execute_count += 1
            if self.execute_count == 1:
                self.job.status = "processing"
                self.job.locked_by = "worker-a"
                return FakeExecuteResult(scalar=self.job.id)
            return FakeExecuteResult(scalar=self.job)

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

    session = JobSession()

    def fake_session_maker():
        return session

    async def fake_compile_documents_to_wiki_pages(session, tenant_id, document_ids):
        return {
            "success_count": 2,
            "failure_count": 0,
            "pages": [{"id": 1}, {"id": 2}],
            "failures": [],
        }

    monkeypatch.setattr(wiki_service, "async_session_maker", fake_session_maker)
    monkeypatch.setattr(wiki_service, "compile_documents_to_wiki_pages", fake_compile_documents_to_wiki_pages)

    await wiki_service.run_wiki_compile_job(77, worker_id="worker-a")

    assert session.job.status == "completed"
    assert session.job.success_count == 2
    assert session.job.failure_count == 0
    assert session.job.error is None
    assert session.job.locked_by is None
    assert session.job.locked_at is None
    assert session.job.next_run_at is None
    assert session.commits == 2
    assert session.rollbacks == 0


@pytest.mark.asyncio
async def test_run_wiki_compile_job_retries_job_level_failure(monkeypatch):
    class FakeJob:
        id = 78
        tenant_id = "default"
        status = "pending"
        document_ids = [1]
        retry_count = 0
        max_retries = 3
        locked_by = "worker-a"
        locked_at = datetime.utcnow()
        next_run_at = None
        success_count = 0
        failure_count = 0
        result_metadata = None
        error = None
        updated_at = None

    class JobSession:
        def __init__(self):
            self.job = FakeJob()
            self.execute_count = 0
            self.commits = 0
            self.rollbacks = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, _statement):
            self.execute_count += 1
            if self.execute_count == 1:
                self.job.status = "processing"
                return FakeExecuteResult(scalar=self.job.id)
            return FakeExecuteResult(scalar=self.job)

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

    session = JobSession()

    def fake_session_maker():
        return session

    async def raise_compile_error(*args, **kwargs):
        raise RuntimeError("worker crashed")

    monkeypatch.setattr(wiki_service, "async_session_maker", fake_session_maker)
    monkeypatch.setattr(wiki_service, "compile_documents_to_wiki_pages", raise_compile_error)

    await wiki_service.run_wiki_compile_job(78, worker_id="worker-a")

    assert session.job.status == "pending"
    assert session.job.retry_count == 1
    assert session.job.error == "worker crashed"
    assert session.job.locked_by is None
    assert session.job.locked_at is None
    assert session.job.next_run_at is not None
    assert session.rollbacks == 1
    assert session.commits == 2


@pytest.mark.asyncio
async def test_run_wiki_compile_job_marks_failed_after_retry_exhausted(monkeypatch):
    class FakeJob:
        id = 79
        tenant_id = "default"
        status = "pending"
        document_ids = [1]
        retry_count = 3
        max_retries = 3
        locked_by = "worker-a"
        locked_at = datetime.utcnow()
        next_run_at = None
        success_count = 0
        failure_count = 0
        result_metadata = None
        error = None
        updated_at = None

    class JobSession:
        def __init__(self):
            self.job = FakeJob()
            self.execute_count = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, _statement):
            self.execute_count += 1
            if self.execute_count == 1:
                self.job.status = "processing"
                return FakeExecuteResult(scalar=self.job.id)
            return FakeExecuteResult(scalar=self.job)

        async def commit(self):
            return None

        async def rollback(self):
            return None

    session = JobSession()

    def fake_session_maker():
        return session

    async def raise_compile_error(*args, **kwargs):
        raise RuntimeError("still failing")

    monkeypatch.setattr(wiki_service, "async_session_maker", fake_session_maker)
    monkeypatch.setattr(wiki_service, "compile_documents_to_wiki_pages", raise_compile_error)

    await wiki_service.run_wiki_compile_job(79, worker_id="worker-a")

    assert session.job.status == "failed"
    assert session.job.retry_count == 4
    assert session.job.error == "still failing"
    assert session.job.next_run_at is None
