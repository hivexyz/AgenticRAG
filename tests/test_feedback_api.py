from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db_models.document import Document
from app.db_models.feedback import AnswerFeedback
from app.db_models.conversation import ConversationMessage
from app.routes import feedback as feedback_module


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
    def __init__(self, *, feedback_items=None, messages=None, documents=None):
        self.feedback_items = feedback_items or []
        self.messages = messages or []
        self.documents = documents or []
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None

    async def refresh(self, obj):
        if getattr(obj, 'id', None) is None:
            obj.id = len(self.added)
        if getattr(obj, 'created_at', None) is None:
            obj.created_at = datetime.utcnow()

    async def execute(self, _statement):
        if not hasattr(self, '_calls'):
            self._calls = 0
        self._calls += 1
        phase = (self._calls - 1) % 3
        if phase == 0:
            return FakeExecuteResult(scalars=self.feedback_items)
        if phase == 1:
            return FakeExecuteResult(scalars=self.messages)
        return FakeExecuteResult(scalars=self.documents)


def create_app(session: FakeSession):
    app = FastAPI()
    app.include_router(feedback_module.router, prefix='/feedback')

    async def override_session():
        yield session

    app.dependency_overrides[feedback_module.postgres_manager.get_session] = override_session
    return app


def make_badcase_context():
    feedback = AnswerFeedback(
        tenant_id='acme',
        session_id=1,
        message_id=2,
        feedback_type='answer',
        rating='down',
        reason='missing_information',
        corrected_answer='请假制度适用于实习生。',
        feedback_metadata={},
    )
    feedback.id = 1
    feedback.created_at = datetime.utcnow()

    user_msg = ConversationMessage(session_id=1, tenant_id='acme', role='user', content='它适用于实习生吗？', message_type='raw')
    user_msg.id = 1
    user_msg.created_at = datetime.utcnow()
    assistant_msg = ConversationMessage(session_id=1, tenant_id='acme', role='assistant', content='请假制度适用于正式员工。', message_type='raw')
    assistant_msg.id = 2
    assistant_msg.created_at = datetime.utcnow()
    assistant_msg.message_metadata = {
        'query_plan': {'route': 'hybrid', 'sub_queries': ['请假制度 适用范围 实习生']},
        'query_analysis': {'query_type': 'factual'},
        'standalone_query': '请假制度适用于实习生吗？',
        'query_rewrites': ['请假制度 适用范围 实习生'],
        'quality_score': 0.42,
        'quality_evaluation': {'groundedness': 0.4, 'relevance': 0.7},
        'multi_hop_trace': [{'hop': 1, 'rendered_queries': ['请假制度']}],
        'citations': [{
            'claim': '请假制度适用范围',
            'sources': [{
                'document_id': 10,
                'chunk_id': 101,
                'title': '请假制度',
                'snippet': '请假制度适用于正式员工和实习生。',
            }],
        }],
        'evidence_cards': [{'rank': 1, 'snippet': '请假制度适用于正式员工和实习生。'}],
        'answer_blocks': [{'text': '请假制度适用于正式员工。', 'citation_ids': [1]}],
    }

    doc = Document(title='请假制度', content='内容')
    doc.id = 10
    doc.tenant_id = 'acme'
    doc.vector_status = 'ready'
    doc.chunk_count = 3
    doc.created_at = datetime.utcnow()
    doc.updated_at = doc.created_at
    return feedback, user_msg, assistant_msg, doc


def test_submit_answer_feedback():
    session = FakeSession()
    app = create_app(session)

    with TestClient(app) as client:
        response = client.post('/feedback/answers', json={
            'tenant_id': 'acme',
            'session_id': 1,
            'message_id': 2,
            'rating': 'down',
            'reason': 'missing_information',
            'comment': '缺少制度细节',
        })

    assert response.status_code == 200
    data = response.json()
    assert data['reason'] == 'missing_information'
    assert session.added[0].rating == 'down'


def test_feedback_analytics_returns_summary(monkeypatch):
    feedback = AnswerFeedback(
        tenant_id='acme',
        session_id=1,
        message_id=2,
        feedback_type='answer',
        rating='down',
        reason='missing_information',
        corrected_answer='正确答案',
        feedback_metadata={'document_ids': [10]},
    )
    feedback.id = 1
    feedback.created_at = datetime.utcnow()

    user_msg = ConversationMessage(session_id=1, tenant_id='acme', role='user', content='如何请假？', message_type='raw')
    user_msg.id = 1
    user_msg.created_at = datetime.utcnow()
    assistant_msg = ConversationMessage(session_id=1, tenant_id='acme', role='assistant', content='请参考制度。', message_type='raw')
    assistant_msg.id = 2
    assistant_msg.created_at = datetime.utcnow()

    doc = Document(title='请假制度', content='内容')
    doc.id = 10
    doc.tenant_id = 'acme'
    doc.vector_status = 'ready'
    doc.chunk_count = 3
    doc.created_at = datetime.utcnow()
    doc.updated_at = doc.created_at

    session = FakeSession(feedback_items=[feedback], messages=[user_msg, assistant_msg], documents=[doc])
    app = create_app(session)

    monkeypatch.setattr(feedback_module.metrics_registry, 'snapshot', lambda: {
        'request_count': 10,
        'error_count': 2,
        'path_counts': {},
        'method_counts': {},
        'average_latency_ms': {'/api/v1/ai/agentic-rag/query': 120.0},
    })

    with TestClient(app) as client:
        response = client.get('/feedback/analytics', params={'tenant_id': 'acme'})

    assert response.status_code == 200
    data = response.json()
    assert data['feedback_summary']['total_feedback'] == 1
    assert data['feedback_summary']['reason_counts']['missing_information'] == 1
    assert data['top_hit_documents'][0][0] == '10'
    assert data['retrieval_failure_rate'] == 0.2
    assert data['optimization_suggestions']


def test_feedback_badcases_include_trace_and_hits():
    feedback, user_msg, assistant_msg, doc = make_badcase_context()
    session = FakeSession(feedback_items=[feedback], messages=[user_msg, assistant_msg], documents=[doc])
    app = create_app(session)

    with TestClient(app) as client:
        response = client.get('/feedback/badcases', params={'tenant_id': 'acme'})

    assert response.status_code == 200
    data = response.json()
    item = data['items'][0]
    assert item['user_query'] == '它适用于实习生吗？'
    assert item['query_plan']['route'] == 'hybrid'
    assert item['multi_hop_trace'][0]['hop'] == 1
    assert item['hit_chunks'][0]['document_id'] == 10
    assert item['hit_chunks'][0]['chunk_id'] == 101
    assert item['golden_candidate']['must_hit_chunk_ids'] == [101]


def test_add_feedback_to_golden_set_appends_case(tmp_path: Path, monkeypatch):
    feedback, user_msg, assistant_msg, doc = make_badcase_context()
    session = FakeSession(feedback_items=[feedback], messages=[user_msg, assistant_msg], documents=[doc])
    app = create_app(session)
    target = tmp_path / 'eval_cases.jsonl'
    monkeypatch.setattr(feedback_module.settings, 'FEEDBACK_GOLDEN_SET_PATH', str(target))

    with TestClient(app) as client:
        response = client.post('/feedback/answers/1/golden-set', json={'tenant_id': 'acme'})

    assert response.status_code == 200
    data = response.json()
    assert data['added'] is True
    assert data['candidate']['id'] == 'feedback_1'
    assert 'feedback_1' in target.read_text(encoding='utf-8')
    assert feedback.feedback_metadata['golden_set']['candidate_id'] == 'feedback_1'

    with TestClient(app) as client:
        response = client.post('/feedback/answers/1/golden-set', json={'tenant_id': 'acme'})

    assert response.status_code == 200
    assert response.json()['added'] is False


def test_trigger_feedback_wiki_recompile_creates_job(monkeypatch):
    feedback, user_msg, assistant_msg, doc = make_badcase_context()
    session = FakeSession(feedback_items=[feedback], messages=[user_msg, assistant_msg], documents=[doc])
    app = create_app(session)
    submitted = {}
    monkeypatch.setattr(feedback_module.task_runner, 'submit', lambda task_id, factory: submitted.setdefault('task_id', task_id))

    with TestClient(app) as client:
        response = client.post('/feedback/answers/1/wiki-recompile', json={'tenant_id': 'acme'})

    assert response.status_code == 200
    data = response.json()
    assert data['document_ids'] == [10]
    assert data['job']['document_ids'] == [10]
    assert session.added[-1].result_metadata['feedback_id'] == 1
    assert submitted['task_id'] == 'wiki-compile:1'
