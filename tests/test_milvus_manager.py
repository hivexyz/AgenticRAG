from types import SimpleNamespace

import pytest

import app.database.milvus as milvus_module
from app.database.milvus import MilvusManager


class FakeCollection:
    def __init__(self, name: str, dimension: int = 1536):
        self.name = name
        self.schema = SimpleNamespace(
            fields=[SimpleNamespace(name='embedding', params={'dim': dimension})]
        )
        self.indexes = []
        self.loaded = False
        self.created_index = None
        self.insert_rows = None
        self.delete_expr = None
        self.flush_count = 0

    def create_index(self, field_name, index_params):
        self.created_index = (field_name, index_params)
        self.indexes = [SimpleNamespace(field_name=field_name)]

    def load(self):
        self.loaded = True

    def insert(self, rows):
        self.insert_rows = rows

    def flush(self):
        self.flush_count += 1

    def delete(self, expr):
        self.delete_expr = expr
        return SimpleNamespace(delete_count=3)


def test_ensure_ready_initializes_collection_index_and_load(monkeypatch):
    manager = MilvusManager()
    manager.connected = True
    manager.dimension = 1536
    fake_collection = FakeCollection('vectors_default', dimension=1536)
    events = []

    monkeypatch.setattr(milvus_module.utility, 'has_collection', lambda name: False)

    def fake_create_collection(collection_name=None, dimension=None, tenant_id=None):
        events.append(('create_collection', collection_name, dimension))
        manager.collection = fake_collection
        return fake_collection

    def fake_create_index(collection_name=None, index_type=None, metric_type=None):
        events.append(('create_index', collection_name, index_type, metric_type))

    def fake_load_collection(collection_name=None, tenant_id=None):
        events.append(('load_collection', collection_name))
        manager.collection = fake_collection
        manager.loaded = True

    monkeypatch.setattr(manager, 'create_collection', fake_create_collection)
    monkeypatch.setattr(manager, 'create_index', fake_create_index)
    monkeypatch.setattr(manager, 'load_collection', fake_load_collection)

    collection = manager.ensure_ready()

    assert collection is fake_collection
    assert events == [
        ('create_collection', 'vectors_default', 1536),
        ('create_index', 'vectors_default', None, None),
        ('load_collection', 'vectors_default'),
    ]
    assert manager.loaded is True


def test_ensure_ready_rejects_existing_collection_with_dimension_mismatch(monkeypatch):
    manager = MilvusManager()
    manager.connected = True
    manager.dimension = 1536

    monkeypatch.setattr(milvus_module.utility, 'has_collection', lambda name: True)
    monkeypatch.setattr(milvus_module, 'Collection', lambda name: FakeCollection(name, dimension=768))

    with pytest.raises(RuntimeError, match='维度'):
        manager.ensure_ready()


def test_insert_vectors_validates_dimension_before_insert(monkeypatch):
    manager = MilvusManager()
    manager.connected = True
    manager.dimension = 4
    manager.collection = FakeCollection('vectors_default', dimension=4)

    monkeypatch.setattr(manager, 'ensure_ready', lambda tenant_id=None: manager.collection)

    with pytest.raises(ValueError, match='向量维度不匹配'):
        manager.insert_vectors([[0.1, 0.2, 0.3]], metadata=[{}])


def test_delete_vectors_by_document_id_flushes_collection(monkeypatch):
    manager = MilvusManager()
    manager.connected = True
    manager.collection = FakeCollection('vectors_acme', dimension=1536)

    monkeypatch.setattr(manager, 'ensure_ready', lambda tenant_id=None: manager.collection)

    deleted_count = manager.delete_vectors_by_document_id(42, tenant_id='acme')

    assert deleted_count == 3
    assert manager.collection.delete_expr == '(metadata["tenant_id"] == "acme") and (metadata["document_id"] == 42)'
    assert manager.collection.flush_count == 1


def test_get_collection_name_uses_tenant_suffix():
    manager = MilvusManager()

    assert manager.get_collection_name('Acme-Corp') == 'vectors_acme_corp'


def test_ensure_ready_reuses_legacy_default_collection_when_new_default_missing(monkeypatch):
    manager = MilvusManager()
    manager.connected = True
    manager.dimension = 1536
    fake_collection = FakeCollection('vectors', dimension=1536)
    events = []

    def fake_has_collection(name):
        return name == 'vectors'

    monkeypatch.setattr(milvus_module.utility, 'has_collection', fake_has_collection)
    monkeypatch.setattr(milvus_module, 'Collection', lambda name: fake_collection)

    def fake_create_index(collection_name=None, index_type=None, metric_type=None):
        events.append(('create_index', collection_name))

    def fake_load_collection(collection_name=None, tenant_id=None):
        events.append(('load_collection', collection_name))
        manager.collection = fake_collection
        manager.loaded = True

    monkeypatch.setattr(manager, 'create_index', fake_create_index)
    monkeypatch.setattr(manager, 'load_collection', fake_load_collection)

    collection = manager.ensure_ready()

    assert collection is fake_collection
    assert manager.collection.name == 'vectors'
    assert events == [('create_index', 'vectors'), ('load_collection', 'vectors')]


def test_search_vectors_skips_tenant_expr_for_legacy_default_collection(monkeypatch):
    manager = MilvusManager()
    manager.connected = True
    manager.dimension = 3

    class SearchableCollection(FakeCollection):
        def search(self, data, anns_field, param, limit, expr, output_fields):
            self.last_search = {
                'data': data,
                'anns_field': anns_field,
                'param': param,
                'limit': limit,
                'expr': expr,
                'output_fields': output_fields,
            }
            return [[SimpleNamespace(id=1, distance=0.1, entity={'metadata': {'text': 'legacy doc'}})]]

    collection = SearchableCollection('vectors', dimension=3)
    manager.collection = collection

    results = manager.search_vectors([[0.1, 0.2, 0.3]], tenant_id='default')

    assert results[0][0]['metadata']['text'] == 'legacy doc'
    assert collection.last_search['expr'] is None


def test_delete_vectors_by_document_id_skips_tenant_expr_for_legacy_default_collection(monkeypatch):
    manager = MilvusManager()
    manager.connected = True
    manager.collection = FakeCollection('vectors', dimension=1536)

    monkeypatch.setattr(manager, 'ensure_ready', lambda tenant_id=None: manager.collection)

    deleted_count = manager.delete_vectors_by_document_id(42, tenant_id='default')

    assert deleted_count == 3
    assert manager.collection.delete_expr == 'metadata["document_id"] == 42'


def test_get_collection_name_defaults_to_default_suffix():
    manager = MilvusManager()

    assert manager.get_collection_name() == 'vectors_default'


def test_search_vectors_returns_empty_when_collection_missing_without_creating(monkeypatch):
    manager = MilvusManager()
    manager.connected = True
    manager.dimension = 3
    events = []

    monkeypatch.setattr(milvus_module.utility, 'has_collection', lambda name: False)
    monkeypatch.setattr(manager, 'create_collection', lambda *args, **kwargs: events.append('create_collection'))
    monkeypatch.setattr(manager, 'create_index', lambda *args, **kwargs: events.append('create_index'))
    monkeypatch.setattr(manager, 'load_collection', lambda *args, **kwargs: events.append('load_collection'))

    results = manager.search_vectors([[0.1, 0.2, 0.3]], tenant_id='new-tenant')

    assert results == [[]]
    assert events == []


def test_delete_vectors_by_document_id_returns_zero_when_collection_missing_without_creating(monkeypatch):
    manager = MilvusManager()
    manager.connected = True
    events = []

    monkeypatch.setattr(milvus_module.utility, 'has_collection', lambda name: False)
    monkeypatch.setattr(manager, 'create_collection', lambda *args, **kwargs: events.append('create_collection'))

    deleted_count = manager.delete_vectors_by_document_id(42, tenant_id='new-tenant')

    assert deleted_count == 0
    assert events == []
