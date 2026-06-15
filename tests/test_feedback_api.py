from datetime import datetime

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
        if self._calls == 1:
            return FakeExecuteResult(scalars=self.feedback_items)
        if self._calls == 2:
            return FakeExecuteResult(scalars=self.messages)
        return FakeExecuteResult(scalars=self.documents)


def create_app(session: FakeSession):
    app = FastAPI()
    app.include_router(feedback_module.router, prefix='/feedback')

    async def override_session():
        yield session

    app.dependency_overrides[feedback_module.postgres_manager.get_session] = override_session
    return app


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
