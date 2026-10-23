import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db_models.document import Document
from app.routes import documents as documents_module
import app.auth as auth_module
from app.services.tenant_limits import tenant_limits




class FakeChunk:
    def __init__(self, *, id, document_id, tenant_id, chunk_index, content, page_number=None, section_title=None, chunk_metadata=None, token_count=None, document=None):
        self.id = id
        self.document_id = document_id
        self.tenant_id = tenant_id
        self.chunk_index = chunk_index
        self.content = content
        self.page_number = page_number
        self.section_title = section_title
        self.chunk_metadata = chunk_metadata or {}
        self.token_count = token_count if token_count is not None else max(1, len(content) // 4)
        self.document = document

    def to_fragment_dict(self, document=None, prev_chunk=None, next_chunk=None):
        owner = document or self.document
        return {
            'document_id': self.document_id,
            'chunk_id': self.id,
            'title': getattr(owner, 'title', None),
            'uploaded_at': getattr(owner, 'created_at', None).isoformat() if getattr(owner, 'created_at', None) else None,
            'page': self.page_number,
            'paragraph': self.chunk_metadata.get('paragraph_index', self.chunk_index),
            'section_title': self.section_title,
            'snippet': self.content[:300],
            'content': self.content,
            'previous_context': prev_chunk.content if prev_chunk else None,
            'next_context': next_chunk.content if next_chunk else None,
        }

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
    def __init__(self, *, existing_document=None, documents=None, fail_delete=False):
        self.existing_document = existing_document
        self.documents = documents or []
        self.added = []
        self.deleted = []
        self.committed = 0
        self.fail_delete = fail_delete

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed += 1

    async def refresh(self, obj):
        if getattr(obj, 'id', None) is None:
            obj.id = len(self.added)
        now = datetime.utcnow()
        obj.created_at = obj.created_at or now
        obj.updated_at = obj.updated_at or now

    async def execute(self, _statement):
        if self.existing_document is not None:
            return FakeExecuteResult(scalar=self.existing_document)
        return FakeExecuteResult(scalars=self.documents)

    async def delete(self, obj):
        if self.fail_delete:
            raise RuntimeError('delete failed')
        self.deleted.append(obj)


@pytest.fixture
def app_factory():
    def _create(session: FakeSession) -> FastAPI:
        app = FastAPI()
        app.include_router(documents_module.router, prefix='/documents')

        async def override_session():
            yield session

        app.dependency_overrides[documents_module.postgres_manager.get_session] = override_session
        return app

    return _create


def test_create_document_round_trips_metadata_as_object(app_factory):
    session = FakeSession()
    app = app_factory(session)

    with TestClient(app) as client:
        response = client.post(
            '/documents/',
            json={
                'tenant_id': 'Acme-Corp',
                'title': '测试文档',
                'content': '正文',
                'author': 'alice',
                'metadata': {'tenant': 'acme', 'tags': ['demo']},
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data['tenant_id'] == 'acme_corp'
    assert data['metadata']['tenant'] == 'acme'
    assert data['metadata']['tags'] == ['demo']
    assert data['metadata']['tenant_id'] == 'acme_corp'
    assert data['metadata']['split_preset'] == 'smart'
    assert session.added[0].tenant_id == 'acme_corp'
    persisted = json.loads(session.added[0].doc_metadata)
    assert persisted['tenant'] == 'acme'
    assert persisted['tags'] == ['demo']
    assert persisted['tenant_id'] == 'acme_corp'
    assert persisted['split_preset'] == 'smart'


def test_create_document_deduplicates_by_content_hash(app_factory, monkeypatch):
    existing = Document(title='已有文档', content='正文')
    existing.id = 9
    existing.tenant_id = 'acme'
    existing.content_hash = documents_module._hash_text_content('正文')
    existing.ingestion_status = 'ready'
    existing.vector_status = 'ready'
    existing.deletion_status = 'active'
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    session = FakeSession(documents=[existing])
    app = app_factory(session)

    def should_not_submit(*args, **kwargs):
        raise AssertionError('duplicate document must not schedule ingest')

    monkeypatch.setattr(documents_module.task_runner, 'submit', should_not_submit)

    with TestClient(app) as client:
        response = client.post('/documents/', json={
            'tenant_id': 'acme',
            'title': '重复文档',
            'content': '正文',
            'async_ingest': True,
        })

    assert response.status_code == 200
    data = response.json()
    assert data['id'] == 9
    assert data['title'] == '已有文档'
    assert len(session.added) == 0


def test_upload_document_sanitizes_filename_persists_metadata_and_hides_temp_path(app_factory, monkeypatch):
    session = FakeSession()
    app = app_factory(session)
    captured = {}

    monkeypatch.setattr(
        documents_module.DocumentParser,
        'parse',
        staticmethod(lambda _path: {'content': '解析后的内容', 'metadata': {'pages': 1}, 'file_type': 'txt'}),
    )
    monkeypatch.setattr(
        documents_module.TextSplitter,
        'split',
        staticmethod(
            lambda text, method, chunk_size, chunk_overlap: [
                {'text': text, 'metadata': {'split_method': method, 'chunk_index': 0}}
            ]
        ),
    )

    async def fake_create_embedding(_text):
        return [0.1, 0.2, 0.3]

    def fake_insert_vectors(vectors, metadata, tenant_id=None):
        captured['vectors'] = vectors
        captured['metadata'] = metadata
        captured['tenant_id'] = tenant_id
    async def fake_insert_vectors_async(vectors, metadata, tenant_id=None):
        fake_insert_vectors(vectors, metadata, tenant_id=tenant_id)

    monkeypatch.setattr(documents_module.embedding_manager, 'create_embedding', fake_create_embedding)
    monkeypatch.setattr(documents_module.vector_store, 'insert_vectors', fake_insert_vectors_async)

    with TestClient(app) as client:
        response = client.post(
            '/documents/upload',
            files={'file': ('../../secret.txt', b'hello', 'text/plain')},
            data={
                'author': 'bob',
                'tenant_id': 'Acme',
                'metadata': json.dumps({'tenant': 'acme'}, ensure_ascii=False),
                'split_method': 'semantic',
                'chunk_size': '128',
                'chunk_overlap': '16',
                'store_vectors': 'true',
                'async_ingest': 'false',
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data['tenant_id'] == 'acme'
    assert data['file_path'] is None
    assert data['metadata']['tenant'] == 'acme'
    assert data['metadata']['tenant_id'] == 'acme'
    assert data['metadata']['source_file_name'] == 'secret.txt'
    assert json.loads(session.added[0].doc_metadata)['source_file_name'] == 'secret.txt'
    assert session.added[0].tenant_id == 'acme'
    assert captured['metadata'][0]['document_id'] == data['id']
    assert captured['metadata'][0]['tenant_id'] == 'acme'
    assert captured['metadata'][0]['split_method'] == 'semantic'
    assert captured['tenant_id'] == 'acme'


def test_upload_document_stores_full_chunk_text_in_vector_metadata(app_factory, monkeypatch):
    session = FakeSession()
    app = app_factory(session)
    captured = {}
    chunk_text = 'A' * 700

    monkeypatch.setattr(
        documents_module.DocumentParser,
        'parse',
        staticmethod(lambda _path: {'content': chunk_text, 'metadata': {}, 'file_type': 'txt'}),
    )
    monkeypatch.setattr(
        documents_module.TextSplitter,
        'split',
        staticmethod(lambda text, method, chunk_size, chunk_overlap: [{'text': chunk_text, 'metadata': {}}]),
    )

    async def fake_create_embedding(_text):
        return [0.1, 0.2, 0.3]

    def fake_insert_vectors(vectors, metadata, tenant_id=None):
        captured['metadata'] = metadata
    async def fake_insert_vectors_async(vectors, metadata, tenant_id=None):
        fake_insert_vectors(vectors, metadata, tenant_id=tenant_id)

    monkeypatch.setattr(documents_module.embedding_manager, 'create_embedding', fake_create_embedding)
    monkeypatch.setattr(documents_module.vector_store, 'insert_vectors', fake_insert_vectors_async)

    with TestClient(app) as client:
        response = client.post(
            '/documents/upload',
            files={'file': ('demo.txt', b'hello', 'text/plain')},
            data={'tenant_id': 'default', 'store_vectors': 'true', 'async_ingest': 'false'},
        )

    assert response.status_code == 200
    assert captured['metadata'][0]['text'] == chunk_text
    assert len(captured['metadata'][0]['text']) == 700


def test_upload_document_rejects_non_object_metadata(app_factory):
    session = FakeSession()
    app = app_factory(session)

    with TestClient(app) as client:
        response = client.post(
            '/documents/upload',
            files={'file': ('demo.txt', b'hello', 'text/plain')},
            data={'metadata': '[1, 2, 3]'},
        )

    assert response.status_code == 400
    assert response.json()['detail'] == 'metadata 必须是 JSON 对象'


def test_upload_document_rejects_unsupported_extension(app_factory):
    session = FakeSession()
    app = app_factory(session)

    with TestClient(app) as client:
        response = client.post(
            '/documents/upload',
            files={'file': ('payload.exe', b'hello', 'application/octet-stream')},
        )

    assert response.status_code == 400
    assert '不支持的文件类型' in response.json()['detail']
    assert session.added == []


def test_upload_document_rejects_signature_mismatch_and_removes_temp_file(app_factory, monkeypatch, tmp_path):
    session = FakeSession()
    app = app_factory(session)
    temp_path = tmp_path / 'fake.pdf'

    monkeypatch.setattr(
        documents_module,
        'build_temp_upload_path',
        lambda _root, _name: (str(temp_path), 'upload-test'),
    )

    with TestClient(app) as client:
        response = client.post(
            '/documents/upload',
            files={'file': ('fake.pdf', b'not a pdf', 'application/pdf')},
        )

    assert response.status_code == 400
    assert '文件内容与扩展名不匹配' in response.json()['detail']
    assert not temp_path.exists()
    assert session.added == []


def test_upload_document_rejects_oversized_file_and_removes_temp_file(app_factory, monkeypatch, tmp_path):
    session = FakeSession()
    app = app_factory(session)
    temp_path = tmp_path / 'oversized.txt'

    monkeypatch.setattr(documents_module.settings, 'MAX_UPLOAD_SIZE_MB', 1)
    monkeypatch.setattr(
        documents_module,
        'build_temp_upload_path',
        lambda _root, _name: (str(temp_path), 'upload-test'),
    )

    with TestClient(app) as client:
        response = client.post(
            '/documents/upload',
            files={'file': ('large.txt', b'x' * (1024 * 1024 + 1), 'text/plain')},
        )

    assert response.status_code == 413
    assert response.json()['detail'] == '文件大小超过限制，最大允许 1 MB'
    assert not temp_path.exists()
    assert session.added == []


def test_list_documents_rejects_invalid_tenant_id(app_factory):
    session = FakeSession(documents=[])
    app = app_factory(session)

    with TestClient(app) as client:
        response = client.get('/documents/', params={'tenant_id': '___'})

    assert response.status_code == 400
    assert response.json()['detail'] == 'tenant_id 格式无效，只能包含字母、数字、连字符或下划线'


def test_read_only_api_key_can_list_but_cannot_create_document(app_factory):
    existing = Document(title='只读文档', content='内容')
    existing.id = 1
    existing.tenant_id = 'tenant_a'
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    session = FakeSession(documents=[existing])
    app = app_factory(session)
    auth_module.api_key_auth.enabled = True
    auth_module.api_key_auth._mapping = {'read-key': 'tenant_a'}
    auth_module.api_key_auth._scopes = {'read-key': frozenset({'read'})}

    with TestClient(app) as client:
        list_response = client.get('/documents/', headers={'X-API-Key': 'read-key'})
        create_response = client.post('/documents/', json={'title': '新文档', 'content': '正文'}, headers={'X-API-Key': 'read-key'})

    assert list_response.status_code == 200
    assert list_response.json()[0]['title'] == '只读文档'
    assert create_response.status_code == 403
    assert create_response.json()['detail'] == '当前 API Key 没有写权限'


def test_token_quota_exhaustion_blocks_request(app_factory, monkeypatch):
    session = FakeSession(documents=[])
    app = app_factory(session)
    auth_module.api_key_auth.enabled = True
    auth_module.api_key_auth._mapping = {'valid-key': 'tenant_a'}
    auth_module.api_key_auth._scopes = {'valid-key': frozenset({'read', 'write'})}
    monkeypatch.setattr(documents_module.settings, 'TENANT_TOKEN_QUOTA_PER_DAY', 5)
    tenant_limits.record_tokens('tenant_a', 5)

    with TestClient(app) as client:
        response = client.get('/documents/', headers={'X-API-Key': 'valid-key'})

    assert response.status_code == 429
    assert 'token 配额已用尽' in response.json()['detail']


def test_delete_document_also_cleans_vectors(app_factory, monkeypatch):
    existing = Document(title='文档', content='内容')
    existing.id = 7
    existing.tenant_id = 'acme'
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    session = FakeSession(existing_document=existing)
    app = app_factory(session)
    called = {}

    def fake_delete_vectors(document_id: int, tenant_id: str | None = None) -> int:
        called['document_id'] = document_id
        called['tenant_id'] = tenant_id
        return 4
    async def fake_delete_vectors_async(document_id: int, tenant_id: str | None = None) -> int:
        return fake_delete_vectors(document_id, tenant_id=tenant_id)

    monkeypatch.setattr(documents_module.vector_store, 'delete_vectors_by_document_id', fake_delete_vectors_async)

    with TestClient(app) as client:
        response = client.delete('/documents/7', params={'tenant_id': 'acme'})

    assert response.status_code == 200
    assert response.json()['deleted_vectors'] == 4
    assert called['document_id'] == 7
    assert called['tenant_id'] == 'acme'
    assert session.deleted == [existing]


def test_delete_document_soft_deletes_linked_wiki_before_db_delete(app_factory, monkeypatch):
    existing = Document(title='文档', content='内容')
    existing.id = 7
    existing.tenant_id = 'acme'
    existing.deletion_status = 'active'
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    session = FakeSession(existing_document=existing)
    app = app_factory(session)
    marked = {}

    async def fake_delete_vectors_async(document_id: int, tenant_id: str | None = None) -> int:
        return 4

    async def fake_mark_deleted(session, tenant_id, document_id):
        marked['tenant_id'] = tenant_id
        marked['document_id'] = document_id
        return [99]

    monkeypatch.setattr(documents_module.vector_store, 'delete_vectors_by_document_id', fake_delete_vectors_async)
    monkeypatch.setattr(documents_module, 'mark_wiki_pages_deleted_for_document', fake_mark_deleted)

    with TestClient(app) as client:
        response = client.delete('/documents/7', params={'tenant_id': 'acme'})

    assert response.status_code == 200
    assert marked == {'tenant_id': 'acme', 'document_id': 7}
    assert session.deleted == [existing]



def test_create_document_rejects_invalid_split_method(app_factory):
    session = FakeSession()
    app = app_factory(session)

    with TestClient(app) as client:
        response = client.post(
            '/documents/',
            json={
                'tenant_id': 'default',
                'title': '测试文档',
                'content': '正文',
                'split_method': 'unknown',
            },
        )

    assert response.status_code == 400
    assert 'split_method 无效' in response.json()['detail']


def test_create_document_rejects_invalid_overlap(app_factory):
    session = FakeSession()
    app = app_factory(session)

    with TestClient(app) as client:
        response = client.post(
            '/documents/',
            json={
                'tenant_id': 'default',
                'title': '测试文档',
                'content': '正文',
                'chunk_size': 100,
                'chunk_overlap': 100,
            },
        )

    assert response.status_code == 400
    assert response.json()['detail'] == 'chunk_overlap 必须小于 chunk_size'


def test_delete_document_returns_503_when_vector_cleanup_fails(app_factory, monkeypatch):
    existing = Document(title='文档', content='内容')
    existing.id = 7
    existing.tenant_id = 'acme'
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    session = FakeSession(existing_document=existing)
    app = app_factory(session)

    async def fake_delete_vectors_async(document_id: int, tenant_id: str | None = None) -> int:
        raise RuntimeError('milvus unavailable')

    monkeypatch.setattr(documents_module.vector_store, 'delete_vectors_by_document_id', fake_delete_vectors_async)

    with TestClient(app) as client:
        response = client.delete('/documents/7', params={'tenant_id': 'acme'})

    assert response.status_code == 503
    assert response.json()['detail'] == '删除文档向量失败，请稍后重试'
    assert session.deleted == []


def test_create_document_marks_vector_status_ready_when_index_succeeds(app_factory, monkeypatch):
    session = FakeSession()
    app = app_factory(session)

    async def fake_create_embedding(_text):
        return [0.1, 0.2, 0.3]

    async def fake_insert_vectors_async(vectors, metadata, tenant_id=None):
        return None

    monkeypatch.setattr(documents_module.embedding_manager, 'create_embedding', fake_create_embedding)
    monkeypatch.setattr(documents_module.vector_store, 'insert_vectors', fake_insert_vectors_async)

    with TestClient(app) as client:
        response = client.post(
            '/documents/',
            json={
                'tenant_id': 'default',
                'title': '测试文档',
                'content': '这是一个较长的正文，用于触发切片。' * 20,
                'store_vectors': True,
                'async_ingest': False,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data['vector_status'] == 'ready'
    assert data['vector_error'] is None


def test_create_document_marks_vector_status_failed_when_index_fails(app_factory, monkeypatch):
    session = FakeSession()
    app = app_factory(session)

    async def fake_create_embedding(_text):
        return [0.1, 0.2, 0.3]

    async def fake_insert_vectors_async(vectors, metadata, tenant_id=None):
        raise RuntimeError('embedding service unavailable')

    monkeypatch.setattr(documents_module.embedding_manager, 'create_embedding', fake_create_embedding)
    monkeypatch.setattr(documents_module.vector_store, 'insert_vectors', fake_insert_vectors_async)

    with TestClient(app) as client:
        response = client.post(
            '/documents/',
            json={
                'tenant_id': 'default',
                'title': '测试文档',
                'content': '这是一个较长的正文，用于触发切片。' * 20,
                'store_vectors': True,
                'async_ingest': False,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data['vector_status'] == 'failed'
    assert 'embedding service unavailable' in data['vector_error']


def test_list_documents_omits_content_and_exposes_status_fields(app_factory):
    existing = Document(title='文档', content='全文内容')
    existing.id = 3
    existing.tenant_id = 'acme'
    existing.vector_status = 'failed'
    existing.vector_error = 'index error'
    existing.deletion_status = 'active'
    existing.deletion_error = None
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    session = FakeSession(documents=[existing])
    app = app_factory(session)

    with TestClient(app) as client:
        response = client.get('/documents/', params={'tenant_id': 'acme'})

    assert response.status_code == 200
    item = response.json()[0]
    assert 'content' not in item
    assert item['vector_status'] == 'failed'
    assert item['deletion_status'] == 'active'


def test_delete_document_marks_failed_when_db_delete_fails(app_factory, monkeypatch):
    existing = Document(title='文档', content='内容')
    existing.id = 7
    existing.tenant_id = 'acme'
    existing.vector_status = 'ready'
    existing.deletion_status = 'active'
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    session = FakeSession(existing_document=existing, fail_delete=True)
    app = app_factory(session)

    async def fake_delete_vectors_async(document_id: int, tenant_id: str | None = None) -> int:
        return 4

    monkeypatch.setattr(documents_module.vector_store, 'delete_vectors_by_document_id', fake_delete_vectors_async)

    with TestClient(app) as client:
        response = client.delete('/documents/7', params={'tenant_id': 'acme'})

    assert response.status_code == 503
    assert response.json()['detail'] == '删除数据库记录失败，请稍后重试'
    assert existing.deletion_status == 'failed'
    assert 'delete failed' in existing.deletion_error


def test_delete_document_sets_failed_status_when_vector_cleanup_fails(app_factory, monkeypatch):
    existing = Document(title='文档', content='内容')
    existing.id = 8
    existing.tenant_id = 'acme'
    existing.vector_status = 'ready'
    existing.deletion_status = 'active'
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    session = FakeSession(existing_document=existing)
    app = app_factory(session)

    async def fake_delete_vectors_async(document_id: int, tenant_id: str | None = None) -> int:
        raise RuntimeError('milvus unavailable')

    monkeypatch.setattr(documents_module.vector_store, 'delete_vectors_by_document_id', fake_delete_vectors_async)

    with TestClient(app) as client:
        response = client.delete('/documents/8', params={'tenant_id': 'acme'})

    assert response.status_code == 503
    assert existing.deletion_status == 'failed'
    assert 'milvus unavailable' in existing.deletion_error


def test_delete_document_rejects_when_already_pending(app_factory):
    existing = Document(title='文档', content='内容')
    existing.id = 9
    existing.tenant_id = 'acme'
    existing.deletion_status = 'pending'
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    session = FakeSession(existing_document=existing)
    app = app_factory(session)

    with TestClient(app) as client:
        response = client.delete('/documents/9', params={'tenant_id': 'acme'})

    assert response.status_code == 409
    assert response.json()['detail'] == '文档正在删除中，请稍后重试'


def test_create_document_accepts_async_ingest_and_returns_pending(app_factory, monkeypatch):
    session = FakeSession()
    app = app_factory(session)
    scheduled = {}

    def fake_schedule(document_id, *, source_type, source_payload):
        scheduled['document_id'] = document_id
        scheduled['source_type'] = source_type
        scheduled['source_payload'] = source_payload

    monkeypatch.setattr(documents_module, '_schedule_document_ingest', fake_schedule)

    with TestClient(app) as client:
        response = client.post('/documents/', json={
            'tenant_id': 'default',
            'title': '异步文档',
            'content': '待后台处理内容',
            'async_ingest': True,
            'store_vectors': True,
        })

    assert response.status_code == 200
    data = response.json()
    assert data['ingestion_status'] == 'pending'
    assert data['vector_status'] == 'pending'
    assert data['content'] == ''
    assert scheduled['document_id'] == data['id']
    assert scheduled['source_type'] == 'text'


def test_upload_document_accepts_async_ingest_and_returns_pending(app_factory, monkeypatch):
    session = FakeSession()
    app = app_factory(session)
    scheduled = {}

    def fake_schedule(document_id, *, source_type, source_payload):
        scheduled['document_id'] = document_id
        scheduled['source_type'] = source_type
        scheduled['source_payload'] = source_payload

    monkeypatch.setattr(documents_module, '_schedule_document_ingest', fake_schedule)

    with TestClient(app) as client:
        response = client.post('/documents/upload', files={'file': ('demo.txt', b'hello', 'text/plain')}, data={'tenant_id': 'default', 'async_ingest': 'true'})

    assert response.status_code == 200
    data = response.json()
    assert data['ingestion_status'] == 'pending'
    assert scheduled['document_id'] == data['id']
    assert scheduled['source_type'] == 'file'


def test_create_document_sync_mode_still_works(app_factory, monkeypatch):
    session = FakeSession()
    app = app_factory(session)

    async def fake_background(document_id, *, source_type, source_payload):
        doc = session.added[0]
        doc.content = source_payload['content']
        doc.ingestion_status = 'ready'
        doc.chunk_count = 1

    monkeypatch.setattr(documents_module, '_background_ingest_document', fake_background)

    with TestClient(app) as client:
        response = client.post('/documents/', json={
            'tenant_id': 'default',
            'title': '同步文档',
            'content': '正文',
            'async_ingest': False,
        })

    assert response.status_code == 200
    data = response.json()
    assert data['ingestion_status'] == 'ready'
    assert data['content'] == '正文'


def test_reindex_document_sync_success(app_factory, monkeypatch):
    existing = Document(title='文档', content='内容')
    existing.id = 21
    existing.tenant_id = 'acme'
    existing.ingestion_status = 'ready'
    existing.vector_status = 'failed'
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    session = FakeSession(existing_document=existing)
    app = app_factory(session)

    class FakeChunk:
        def __init__(self):
            self.content = 'chunk text'
            self.chunk_metadata = {'page': 1}
            self.id = 11

    async def fake_execute(_statement):
        class _Result:
            def scalar_one_or_none(self_inner):
                return existing
            def scalars(self_inner):
                return self_inner
            def all(self_inner):
                return [FakeChunk()]
        return _Result()

    async def fake_insert_vectors(vectors, metadata, tenant_id=None):
        return None

    session.execute = fake_execute
    monkeypatch.setattr(documents_module.vector_store, 'insert_vectors', fake_insert_vectors)
    async def fake_create_embedding(_text):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(documents_module.embedding_manager, 'create_embedding', fake_create_embedding)

    with TestClient(app) as client:
        response = client.post('/documents/21/reindex?tenant_id=acme&async_reindex=false')

    assert response.status_code == 200
    assert response.json()['vector_status'] == 'ready'


def test_reindex_document_rejects_when_ingestion_not_ready(app_factory):
    existing = Document(title='文档', content='内容')
    existing.id = 22
    existing.tenant_id = 'acme'
    existing.ingestion_status = 'processing'
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    session = FakeSession(existing_document=existing)
    app = app_factory(session)

    with TestClient(app) as client:
        response = client.post('/documents/22/reindex?tenant_id=acme&async_reindex=false')

    assert response.status_code == 409
    assert response.json()['detail'] == '文档尚未完成摄取，暂不可重建索引'


def test_retry_delete_document_success(app_factory, monkeypatch):
    existing = Document(title='文档', content='内容')
    existing.id = 23
    existing.tenant_id = 'acme'
    existing.deletion_status = 'failed'
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    session = FakeSession(existing_document=existing)
    app = app_factory(session)

    async def fake_delete_vectors_async(document_id: int, tenant_id: str | None = None) -> int:
        return 3

    monkeypatch.setattr(documents_module.vector_store, 'delete_vectors_by_document_id', fake_delete_vectors_async)

    with TestClient(app) as client:
        response = client.post('/documents/23/retry-delete?tenant_id=acme')

    assert response.status_code == 200
    assert response.json()['deleted_vectors'] == 3


def test_retry_delete_document_rejects_when_not_failed(app_factory):
    existing = Document(title='文档', content='内容')
    existing.id = 24
    existing.tenant_id = 'acme'
    existing.deletion_status = 'active'
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    session = FakeSession(existing_document=existing)
    app = app_factory(session)

    with TestClient(app) as client:
        response = client.post('/documents/24/retry-delete?tenant_id=acme')

    assert response.status_code == 409
    assert response.json()['detail'] == '当前文档不处于可重试删除状态'


def test_get_document_fragment_returns_context_window(app_factory):
    existing = Document(title='制度A', content='全文')
    existing.id = 7
    existing.tenant_id = 'acme'
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at

    chunks = [
        FakeChunk(id=101, document_id=7, tenant_id='acme', chunk_index=0, content='前文', document=existing),
        FakeChunk(id=102, document_id=7, tenant_id='acme', chunk_index=1, content='目标片段', page_number=3, section_title='第二章', chunk_metadata={'paragraph_index': 8}, document=existing),
        FakeChunk(id=103, document_id=7, tenant_id='acme', chunk_index=2, content='后文', document=existing),
    ]

    class FragmentSession(FakeSession):
        async def execute(self, _statement):
            if not hasattr(self, '_called'):
                self._called = 0
            self._called += 1
            if self._called == 1:
                return FakeExecuteResult(scalar=existing)
            if self._called == 2:
                return FakeExecuteResult(scalar=chunks[1])
            return FakeExecuteResult(scalars=chunks)

    session = FragmentSession(existing_document=existing)
    app = app_factory(session)

    with TestClient(app) as client:
        response = client.get('/documents/7/chunks/102', params={'tenant_id': 'acme'})

    assert response.status_code == 200
    data = response.json()
    assert data['title'] == '制度A'
    assert data['page'] == 3
    assert data['paragraph'] == 8
    assert data['previous_context'] == '前文'
    assert data['next_context'] == '后文'


def test_get_document_fragment_returns_404_when_chunk_missing(app_factory):
    existing = Document(title='制度A', content='全文')
    existing.id = 7
    existing.tenant_id = 'acme'
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at

    class FragmentSession(FakeSession):
        async def execute(self, _statement):
            if not hasattr(self, '_called'):
                self._called = 0
            self._called += 1
            if self._called == 1:
                return FakeExecuteResult(scalar=existing)
            return FakeExecuteResult(scalar=None)

    session = FragmentSession(existing_document=existing)
    app = app_factory(session)

    with TestClient(app) as client:
        response = client.get('/documents/7/chunks/102', params={'tenant_id': 'acme'})

    assert response.status_code == 404
    assert response.json()['detail'] == '文档片段不存在'


def test_list_document_chunks_returns_chunk_summaries(app_factory):
    existing = Document(title='制度A', content='全文')
    existing.id = 7
    existing.tenant_id = 'acme'
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at

    chunks = [
        FakeChunk(id=101, document_id=7, tenant_id='acme', chunk_index=1, content='第二段内容', page_number=4, section_title='第二章', chunk_metadata={'paragraph_index': 9}, document=existing),
        FakeChunk(id=100, document_id=7, tenant_id='acme', chunk_index=0, content='第一段内容', page_number=3, section_title='第一章', chunk_metadata={'paragraph_index': 3}, document=existing),
    ]

    class ChunkListSession(FakeSession):
        async def execute(self, _statement):
            if not hasattr(self, '_called'):
                self._called = 0
            self._called += 1
            if self._called == 1:
                return FakeExecuteResult(scalar=existing)
            return FakeExecuteResult(scalars=chunks)

    session = ChunkListSession(existing_document=existing)
    app = app_factory(session)

    with TestClient(app) as client:
        response = client.get('/documents/7/chunks', params={'tenant_id': 'acme'})

    assert response.status_code == 200
    data = response.json()
    assert [item['chunk_id'] for item in data] == [100, 101]
    assert data[0]['chunk_index'] == 0
    assert data[0]['page'] == 3
    assert data[0]['paragraph'] == 3
    assert data[0]['section_title'] == '第一章'
    assert data[0]['snippet'] == '第一段内容'


def test_list_document_chunks_returns_404_when_document_missing(app_factory):
    class MissingDocumentSession(FakeSession):
        async def execute(self, _statement):
            return FakeExecuteResult(scalar=None)

    session = MissingDocumentSession()
    app = app_factory(session)

    with TestClient(app) as client:
        response = client.get('/documents/7/chunks', params={'tenant_id': 'acme'})

    assert response.status_code == 404
    assert response.json()['detail'] == '文档不存在'


def test_list_documents_supports_search_and_knowledge_base_filter(app_factory):
    doc1 = Document(title='员工手册', content='内容1')
    doc1.id = 1
    doc1.tenant_id = 'acme'
    doc1.file_type = 'pdf'
    doc1.author = 'alice'
    doc1.doc_metadata = json.dumps({'knowledge_base': 'hr', 'split_preset': 'policy'})
    doc1.ingestion_status = 'ready'
    doc1.vector_status = 'ready'
    doc1.created_at = datetime.utcnow()
    doc1.updated_at = doc1.created_at

    doc2 = Document(title='产品FAQ', content='内容2')
    doc2.id = 2
    doc2.tenant_id = 'acme'
    doc2.file_type = 'txt'
    doc2.author = 'bob'
    doc2.doc_metadata = json.dumps({'knowledge_base': 'product', 'split_preset': 'faq'})
    doc2.ingestion_status = 'pending'
    doc2.vector_status = 'not_requested'
    doc2.created_at = datetime.utcnow()
    doc2.updated_at = doc2.created_at

    session = FakeSession(documents=[doc1, doc2])
    app = app_factory(session)

    with TestClient(app) as client:
        response = client.get('/documents/', params={'tenant_id': 'acme', 'knowledge_base': 'hr', 'q': '员工'})

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]['title'] == '员工手册'
    assert data[0]['knowledge_base'] == 'hr'
    assert data[0]['status_display'] == '入库成功'
    assert data[0]['vector_status_display'] == '已生成向量索引'


def test_list_split_presets_returns_productized_labels(app_factory):
    session = FakeSession()
    app = app_factory(session)

    with TestClient(app) as client:
        response = client.get('/documents/management/presets')

    assert response.status_code == 200
    data = response.json()
    assert data['default'] == 'smart'
    assert data['vector_storage_label'] == '生成并存储向量索引'
    assert any(item['key'] == 'policy' for item in data['presets'])


def test_create_document_uses_split_preset_and_knowledge_base(app_factory, monkeypatch):
    session = FakeSession()
    app = app_factory(session)

    async def fake_background(document_id, *, source_type, source_payload):
        doc = session.added[0]
        doc.content = source_payload['content']
        doc.ingestion_status = 'ready'
        doc.chunk_count = 1

    monkeypatch.setattr(documents_module, '_background_ingest_document', fake_background)

    with TestClient(app) as client:
        response = client.post('/documents/', json={
            'tenant_id': 'acme',
            'title': '制度文档',
            'content': '正文',
            'knowledge_base': 'compliance',
            'split_preset': 'policy',
            'async_ingest': False,
        })

    assert response.status_code == 200
    data = response.json()
    assert data['knowledge_base'] == 'compliance'
    assert data['advanced_split_settings']['split_preset'] == 'policy'
    assert session.added[0].split_method == 'paragraph'


def test_bulk_delete_documents_executes_cleanup_for_multiple_ids(app_factory, monkeypatch):
    session = FakeSession()
    app = app_factory(session)
    deleted_vectors = []
    deleted_wiki = []

    async def fake_execute(_statement):
        class _Result:
            def __init__(self, scalar):
                self._scalar = scalar
            def scalar_one_or_none(self):
                return self._scalar
        if not hasattr(fake_execute, 'calls'):
            fake_execute.calls = 0
        fake_execute.calls += 1
        if fake_execute.calls == 1:
            doc = Document(title='a', content='c')
            doc.id = 1
            doc.tenant_id = 'acme'
            return _Result(doc)
        return _Result(None)

    session.execute = fake_execute

    async def fake_delete_vectors_async(document_id: int, tenant_id: str | None = None) -> int:
        deleted_vectors.append((document_id, tenant_id))
        return 2

    async def fake_mark_deleted(session, tenant_id, document_id):
        deleted_wiki.append((document_id, tenant_id))
        return [90 + document_id]

    monkeypatch.setattr(documents_module.vector_store, 'delete_vectors_by_document_id', fake_delete_vectors_async)
    monkeypatch.setattr(documents_module, 'mark_wiki_pages_deleted_for_document', fake_mark_deleted)

    with TestClient(app) as client:
        response = client.post('/documents/bulk-delete', json={'tenant_id': 'acme', 'document_ids': [1, 2]})

    assert response.status_code == 200
    data = response.json()
    assert data['accepted'] == [1]
    assert data['deleted'] == [1]
    assert data['results'][0]['deleted_vectors'] == 2
    assert data['results'][0]['deleted_wiki_pages'] == [91]
    assert data['failures'][0]['document_id'] == 2
    assert deleted_vectors == [(1, 'acme')]
    assert deleted_wiki == [(1, 'acme')]
