import pytest

from app.database import hybrid_search


class FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeResult:
    def __init__(self, *, mappings=None, scalars=None):
        self._mappings = mappings or []
        self._scalars = scalars or []

    def mappings(self):
        return FakeMappings(self._mappings)

    def scalars(self):
        return FakeScalars(self._scalars)


class FakeSession:
    def __init__(self, *, rows=None, raise_first=False, fallback_chunks=None):
        self.rows = rows or []
        self.raise_first = raise_first
        self.fallback_chunks = fallback_chunks or []
        self.statements = []
        self.params = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params or {})
        if self.raise_first and len(self.statements) == 1:
            raise RuntimeError("fts unavailable")
        if len(self.statements) > 1:
            return FakeResult(scalars=self.fallback_chunks)
        return FakeResult(mappings=self.rows)


class FakeChunk:
    def to_retrieval_dict(self):
        return {
            "id": 7,
            "chunk_id": 7,
            "document_id": 1,
            "document_title": "fallback",
            "text": "fallback text",
            "content": "fallback text",
            "metadata": {},
        }


@pytest.mark.asyncio
async def test_sparse_search_uses_postgres_full_text_rank(monkeypatch):
    session = FakeSession(rows=[{
        "id": 3,
        "document_id": 2,
        "chunk_index": 0,
        "content": "请假制度适用于实习生",
        "page_number": 1,
        "section_title": "范围",
        "chunk_metadata": {"paragraph": 1},
        "document_title": "请假制度",
        "file_type": "txt",
        "sparse_score": 1.25,
    }])
    monkeypatch.setattr(hybrid_search, "async_session_maker", lambda: session)

    hits = await hybrid_search.sparse_search_chunks("请假制度 实习生", tenant_id="acme", top_k=3)

    assert "to_tsvector" in session.statements[0]
    assert "plainto_tsquery" in session.statements[0]
    assert session.params[0]["fts_query"] == "请假制度 实习生"
    assert hits[0]["document_title"] == "请假制度"
    assert hits[0]["sparse_score"] == 1.25


@pytest.mark.asyncio
async def test_sparse_search_pushes_supported_filters(monkeypatch):
    session = FakeSession(rows=[{
        "id": 3,
        "document_id": 2,
        "chunk_index": 0,
        "content": "请假制度适用于实习生",
        "page_number": 1,
        "section_title": "范围",
        "chunk_metadata": {"paragraph": 1, "knowledge_base": "hr"},
        "document_title": "请假制度",
        "file_type": "txt",
        "sparse_score": 1.25,
    }])
    monkeypatch.setattr(hybrid_search, "async_session_maker", lambda: session)

    hits = await hybrid_search.sparse_search_chunks(
        "请假制度 实习生",
        tenant_id="acme",
        top_k=3,
        filters={"knowledge_base": "hr", "document_ids": [2], "file_type": "txt"},
    )

    statement = session.statements[0]
    params = session.params[0]
    assert "dc.document_id IN" in statement
    assert "COALESCE(dc.chunk_metadata ->> 'knowledge_base'" in statement
    assert "LOWER(d.file_type)" in statement
    assert params["filter_document_id_0"] == 2
    assert params["filter_knowledge_base_0"] == "hr"
    assert hits[0]["document_id"] == 2


@pytest.mark.asyncio
async def test_sparse_search_falls_back_to_orm_ilike(monkeypatch):
    session = FakeSession(raise_first=True, fallback_chunks=[FakeChunk()])
    monkeypatch.setattr(hybrid_search, "async_session_maker", lambda: session)

    hits = await hybrid_search.sparse_search_chunks("请假制度", tenant_id="acme", top_k=3)

    assert len(session.statements) == 2
    assert "ILIKE" in session.statements[1]
    assert hits[0]["document_title"] == "fallback"
    assert hits[0]["sparse_score"] == 0.0
