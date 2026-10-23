from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db_models.conversation import ConversationMessage, ConversationSession
from app.routes import conversations as conversations_module
from app.context import assembler as assembler_module


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
    def __init__(self, *, existing=None, items=None):
        self.existing = existing
        self.items = items or []
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
        if hasattr(obj, 'updated_at') and getattr(obj, 'updated_at', None) is None:
            obj.updated_at = datetime.utcnow()
        if hasattr(obj, 'summary_version') and getattr(obj, 'summary_version', None) is None:
            obj.summary_version = 0

    async def execute(self, _statement):
        if self.existing is not None:
            return FakeExecuteResult(scalar=self.existing)
        return FakeExecuteResult(scalars=self.items)


def create_app(session: FakeSession):
    app = FastAPI()
    app.include_router(conversations_module.router, prefix='/conversations')

    async def override_session():
        yield session

    app.dependency_overrides[conversations_module.postgres_manager.get_session] = override_session
    return app


def test_create_conversation():
    session = FakeSession()
    app = create_app(session)

    with TestClient(app) as client:
        response = client.post('/conversations/', json={'tenant_id': 'acme', 'title': '会话1'})

    assert response.status_code == 200
    data = response.json()
    assert data['tenant_id'] == 'acme'
    assert data['title'] == '会话1'
    assert data['summary_version'] == 0
    assert data['summary_message_cutoff_id'] is None


def test_list_conversations():
    existing = ConversationSession(tenant_id='acme', title='会话1', status='active')
    existing.id = 1
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    session = FakeSession(items=[existing])
    app = create_app(session)

    with TestClient(app) as client:
        response = client.get('/conversations/?tenant_id=acme')

    assert response.status_code == 200
    assert response.json()[0]['title'] == '会话1'


def test_get_conversation_404():
    session = FakeSession(existing=None)
    app = create_app(session)

    with TestClient(app) as client:
        response = client.get('/conversations/1?tenant_id=acme')

    assert response.status_code == 404


def test_send_message_persists_user_and_assistant_messages(monkeypatch):
    existing = ConversationSession(tenant_id='acme', title='会话1', status='active')
    existing.id = 1
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    session = FakeSession(existing=existing)
    app = create_app(session)

    async def fake_query(user_query, tenant_id='default', conversation_history=None, config=None):
        assert config is None
        return {
            'query': user_query,
            'answer': '你好，我在。',
            'quality_score': 1.0,
            'standalone_query': '你好',
            'query_rewrites': ['你好'],
            'query_analysis': {'query_type': 'greeting'},
            'search_results': [],
            'reranked_results': [],
            'retrieval_count': 0,
            'context': None,
            'citations': [{'claim': '问候来源'}],
            'answer_blocks': [{'text': '你好，我在。', 'citation_ids': [], 'uncertainty_flag': False}],
            'evidence_cards': [{'rank': 1, 'snippet': '问候'}],
            'multi_hop_trace': [{'hop': 1, 'rendered_queries': ['你好']}],
            'messages': [],
            'error': None,
        }

    monkeypatch.setattr(conversations_module.agentic_rag_manager, 'query', fake_query)

    with TestClient(app) as client:
        response = client.post('/conversations/1/messages', json={'tenant_id': 'acme', 'content': '你好'})

    assert response.status_code == 200
    data = response.json()
    assert data['user_message']['role'] == 'user'
    assert data['assistant_message']['role'] == 'assistant'
    assert data['assistant_message']['content'] == '你好，我在。'
    assert data['feedback']['message_id'] == data['assistant_message']['id']
    assert len(data['feedback']['actions']) == 8
    assert len(session.added) == 2
    assistant_metadata = data['assistant_message']['metadata']
    assert assistant_metadata['citations'][0]['claim'] == '问候来源'
    assert assistant_metadata['standalone_query'] == '你好'
    assert assistant_metadata['query_rewrites'] == ['你好']
    assert assistant_metadata['answer_blocks'][0]['text'] == '你好，我在。'
    assert assistant_metadata['evidence_cards'][0]['snippet'] == '问候'
    assert assistant_metadata['multi_hop_trace'][0]['hop'] == 1


def test_stream_message_persists_final_assistant_metadata(monkeypatch):
    existing = ConversationSession(tenant_id='acme', title='会话1', status='active')
    existing.id = 1
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    session = FakeSession(existing=existing)
    app = create_app(session)

    async def fake_stream_query_response(user_query, tenant_id='default', conversation_history=None, config=None):
        assert user_query == '请总结制度'
        assert tenant_id == 'acme'
        yield {'event': 'answer_delta', 'delta': '制度'}
        yield {'event': 'answer_delta', 'delta': '要求'}
        yield {
            'event': 'answer_done',
            'answer': '制度要求',
            'answer_blocks': [{'text': '制度要求', 'citation_ids': [1], 'uncertainty_flag': False}],
            'citations': [{'claim': '制度来源'}],
            'evidence_cards': [{'rank': 1, 'snippet': '制度片段'}],
            'multi_hop_trace': [{'hop': 1, 'rendered_queries': ['制度']}],
        }
        yield {
            'event': 'quality_done',
            'quality_score': 0.9,
            'quality_evaluation': {'groundedness': 0.9, 'relevance': 0.92, 'quality_score': 0.91},
        }
        yield {
            'event': 'final',
            'result': {
                'query': user_query,
                'answer': '制度要求',
                'quality_score': 0.91,
                'quality_evaluation': {'groundedness': 0.9, 'relevance': 0.92, 'quality_score': 0.91},
                'standalone_query': '请总结制度',
                'query_rewrites': ['请总结制度'],
                'query_analysis': {'query_type': 'summary'},
                'search_results': [],
                'reranked_results': [],
                'retrieval_count': 1,
                'context': '制度片段',
                'citations': [{'claim': '制度来源'}],
                'answer_blocks': [{'text': '制度要求', 'citation_ids': [1], 'uncertainty_flag': False}],
                'evidence_cards': [{'rank': 1, 'snippet': '制度片段'}],
                'multi_hop_trace': [{'hop': 1, 'rendered_queries': ['制度']}],
                'messages': [],
                'error': None,
            },
        }

    monkeypatch.setattr(conversations_module.agentic_rag_manager, 'stream_query_response', fake_stream_query_response)

    with TestClient(app) as client:
        response = client.post('/conversations/1/messages/stream', json={'tenant_id': 'acme', 'content': '请总结制度'})

    assert response.status_code == 200
    assert 'event: answer_delta' in response.text
    assert '"delta": "制度"' in response.text
    assert 'event: final' in response.text
    assert len(session.added) == 2
    assistant = session.added[-1]
    assert assistant.content == '制度要求'
    assert assistant.message_metadata['quality_evaluation']['groundedness'] == 0.9
    assert assistant.message_metadata['answer_blocks'][0]['citation_ids'] == [1]
    assert assistant.message_metadata['multi_hop_trace'][0]['hop'] == 1


def test_send_message_uses_trimmed_history(monkeypatch):
    existing = ConversationSession(tenant_id='acme', title='会话1', status='active')
    existing.id = 1
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at

    older = []
    for i in range(10):
        msg = ConversationMessage(session_id=1, tenant_id='acme', role='user' if i % 2 == 0 else 'assistant', content=f'msg-{i}')
        msg.id = i + 100
        msg.created_at = datetime.utcnow()
        older.append(msg)

    class FakeSessionWithHistory(FakeSession):
        async def execute(self, _statement):
            if not hasattr(self, '_called'):
                self._called = 0
            self._called += 1
            if self._called == 1:
                return FakeExecuteResult(scalar=existing)
            return FakeExecuteResult(scalars=[*older, *self.added])

    session = FakeSessionWithHistory(existing=existing)
    app = create_app(session)
    captured = {}

    async def fake_query(user_query, tenant_id='default', conversation_history=None, config=None):
        captured['history'] = conversation_history
        return {
            'query': user_query,
            'answer': 'ok',
            'quality_score': 1.0,
            'query_analysis': None,
            'search_results': [],
            'reranked_results': [],
            'retrieval_count': 0,
            'context': None,
            'messages': [],
            'error': None,
        }

    async def fake_count_tokens(text):
        return 10

    monkeypatch.setattr(conversations_module.agentic_rag_manager, 'query', fake_query)
    monkeypatch.setattr(assembler_module.llm_manager, 'count_tokens', fake_count_tokens, raising=False)

    with TestClient(app) as client:
        response = client.post('/conversations/1/messages', json={'tenant_id': 'acme', 'content': '你好'})

    assert response.status_code == 200
    assert len(captured['history']) <= 12
    assert 'context_status' in response.json()
    assert response.json()['context_status']['history_token_count'] >= 0


def test_send_message_generates_initial_summary_with_cutoff_metadata(monkeypatch):
    existing = ConversationSession(tenant_id='acme', title='会话1', status='active')
    existing.id = 1
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at

    older = []
    for i in range(14):
        msg = ConversationMessage(session_id=1, tenant_id='acme', role='user' if i % 2 == 0 else 'assistant', content=f'msg-{i}')
        msg.id = i + 100
        msg.created_at = datetime.utcnow()
        older.append(msg)

    class FakeSessionWithHistory(FakeSession):
        async def execute(self, _statement):
            if not hasattr(self, '_called'):
                self._called = 0
            self._called += 1
            if self._called == 1:
                return FakeExecuteResult(scalar=existing)
            return FakeExecuteResult(scalars=[*older, *self.added])

    session = FakeSessionWithHistory(existing=existing)
    app = create_app(session)
    captured = {}

    async def fake_query(user_query, tenant_id='default', conversation_history=None, config=None):
        captured['history'] = conversation_history
        return {
            'query': user_query,
            'answer': 'ok',
            'quality_score': 1.0,
            'query_analysis': None,
            'search_results': [],
            'reranked_results': [],
            'retrieval_count': 0,
            'context': None,
            'context_status': None,
            'messages': [],
            'error': None,
        }

    async def fake_count_tokens(text):
        return 10

    async def fake_summary(history, existing_summary=None, keep_recent_turns=3, max_tokens=512, cutoff_message_id=None):
        assert existing_summary is None
        assert cutoff_message_id is None
        return {
            'summary': '用户想做生产级改造；偏好渐进式落地。',
            'cutoff_message_id': 108,
            'source_message_count': 9,
            'incremental': False,
        }

    async def always_refresh(history, latest_summary=None, cutoff_message_id=None):
        return True

    monkeypatch.setattr(conversations_module.agentic_rag_manager, 'query', fake_query)
    monkeypatch.setattr(assembler_module.llm_manager, 'count_tokens', fake_count_tokens, raising=False)
    monkeypatch.setattr(conversations_module, 'generate_session_summary', fake_summary)
    monkeypatch.setattr(conversations_module, 'should_refresh_summary', always_refresh)

    with TestClient(app) as client:
        response = client.post('/conversations/1/messages', json={'tenant_id': 'acme', 'content': '继续'})

    assert response.status_code == 200
    data = response.json()
    assert data['context_status']['summary_generated'] is True
    assert data['summary_message']['message_type'] == 'summary'
    assert data['summary_message']['role'] == 'system'
    assert data['summary_message']['metadata']['summary_version'] == 1
    assert data['summary_message']['metadata']['summary_message_cutoff_id'] == 108
    assert data['summary_message']['metadata']['previous_summary'] is None
    assert data['context_status']['summary_incremental'] is False
    assert data['context_status']['summary_source_message_count'] == 9
    assert data['context_status']['summary_message_cutoff_id'] == 108
    assert data['context_status']['summary_version'] == 1
    assert data['session']['summary_message_cutoff_id'] == 108
    assert data['session']['summary_version'] == 1
    assert existing.latest_summary == '用户想做生产级改造；偏好渐进式落地。'
    assert existing.summary_message_cutoff_id == 108
    assert existing.summary_updated_at is not None
    assert captured['history'][0]['role'] == 'system'
    assert '历史摘要' in captured['history'][0]['content']


def test_send_message_incremental_summary_refresh(monkeypatch):
    existing = ConversationSession(tenant_id='acme', title='会话1', status='active')
    existing.id = 1
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at
    existing.latest_summary = '旧摘要'
    existing.summary_message_cutoff_id = 105
    existing.summary_version = 2

    older = []
    for i in range(18):
        msg = ConversationMessage(session_id=1, tenant_id='acme', role='user' if i % 2 == 0 else 'assistant', content=f'msg-{i}')
        msg.id = i + 100
        msg.created_at = datetime.utcnow()
        older.append(msg)

    class FakeSessionWithHistory(FakeSession):
        async def execute(self, _statement):
            if not hasattr(self, '_called'):
                self._called = 0
            self._called += 1
            if self._called == 1:
                return FakeExecuteResult(scalar=existing)
            return FakeExecuteResult(scalars=[*older, *self.added])

    session = FakeSessionWithHistory(existing=existing)
    app = create_app(session)

    async def fake_query(user_query, tenant_id='default', conversation_history=None, config=None):
        return {
            'query': user_query,
            'answer': 'ok',
            'quality_score': 1.0,
            'query_analysis': None,
            'search_results': [],
            'reranked_results': [],
            'retrieval_count': 0,
            'context': None,
            'context_status': None,
            'messages': [],
            'error': None,
        }

    async def fake_count_tokens(text):
        return 10

    async def fake_summary(history, existing_summary=None, keep_recent_turns=3, max_tokens=512, cutoff_message_id=None):
        assert existing_summary == '旧摘要'
        assert cutoff_message_id == 105
        return {
            'summary': '旧摘要 + 新增决策',
            'cutoff_message_id': 112,
            'source_message_count': 7,
            'incremental': True,
        }

    async def always_refresh(history, latest_summary=None, cutoff_message_id=None):
        assert latest_summary == '旧摘要'
        assert cutoff_message_id == 105
        return True

    monkeypatch.setattr(conversations_module.agentic_rag_manager, 'query', fake_query)
    monkeypatch.setattr(assembler_module.llm_manager, 'count_tokens', fake_count_tokens, raising=False)
    monkeypatch.setattr(conversations_module, 'generate_session_summary', fake_summary)
    monkeypatch.setattr(conversations_module, 'should_refresh_summary', always_refresh)

    with TestClient(app) as client:
        response = client.post('/conversations/1/messages', json={'tenant_id': 'acme', 'content': '继续推进'})

    assert response.status_code == 200
    data = response.json()
    assert data['context_status']['summary_generated'] is True
    assert data['summary_message']['message_type'] == 'summary'
    assert data['summary_message']['role'] == 'system'
    assert data['summary_message']['metadata']['summary_version'] == 3
    assert data['summary_message']['metadata']['summary_message_cutoff_id'] == 112
    assert data['summary_message']['metadata']['previous_summary'] == '旧摘要'
    assert data['context_status']['summary_incremental'] is True
    assert data['context_status']['summary_message_cutoff_id'] == 112
    assert data['context_status']['summary_version'] == 3
    assert data['summary_message']['metadata']['summary_incremental'] is True
    assert data['summary_message']['metadata']['previous_summary'] == '旧摘要'
    assert data['session']['latest_summary'] == '旧摘要 + 新增决策'
    assert data['session']['summary_message_cutoff_id'] == 112
    assert data['session']['summary_version'] == 3


def test_send_message_summary_failure_falls_back_to_recent_history(monkeypatch):
    existing = ConversationSession(tenant_id='acme', title='会话1', status='active')
    existing.id = 1
    existing.created_at = datetime.utcnow()
    existing.updated_at = existing.created_at

    older = []
    for i in range(14):
        msg = ConversationMessage(session_id=1, tenant_id='acme', role='user' if i % 2 == 0 else 'assistant', content=f'msg-{i}')
        msg.id = i + 100
        msg.created_at = datetime.utcnow()
        older.append(msg)

    class FakeSessionWithHistory(FakeSession):
        async def execute(self, _statement):
            if not hasattr(self, '_called'):
                self._called = 0
            self._called += 1
            if self._called == 1:
                return FakeExecuteResult(scalar=existing)
            return FakeExecuteResult(scalars=[*older, *self.added])

    session = FakeSessionWithHistory(existing=existing)
    app = create_app(session)
    captured = {}

    async def fake_query(user_query, tenant_id='default', conversation_history=None, config=None):
        captured['history'] = conversation_history
        return {
            'query': user_query,
            'answer': 'ok',
            'quality_score': 1.0,
            'query_analysis': None,
            'search_results': [],
            'reranked_results': [],
            'retrieval_count': 0,
            'context': None,
            'context_status': None,
            'messages': [],
            'error': None,
        }

    async def fake_count_tokens(text):
        return 10

    async def fake_summary(*args, **kwargs):
        raise RuntimeError('summary timeout')

    async def always_refresh(history, latest_summary=None, cutoff_message_id=None):
        return True

    monkeypatch.setattr(conversations_module.agentic_rag_manager, 'query', fake_query)
    monkeypatch.setattr(assembler_module.llm_manager, 'count_tokens', fake_count_tokens, raising=False)
    monkeypatch.setattr(conversations_module, 'generate_session_summary', fake_summary)
    monkeypatch.setattr(conversations_module, 'should_refresh_summary', always_refresh)

    with TestClient(app) as client:
        response = client.post('/conversations/1/messages', json={'tenant_id': 'acme', 'content': '继续'})

    assert response.status_code == 200
    data = response.json()
    assert data['context_status']['summary_generated'] is False
    assert data['summary_message'] is None
    assert data['context_status']['used_summary'] is False
    assert data['context_status']['summary_error'] == 'summary timeout'
    assert data['context_status']['summary_version'] == 0
    assert captured['history'][0]['role'] != 'system'


def test_build_conversation_context_uses_existing_summary(monkeypatch):
    async def fake_count_tokens(text):
        return 10

    monkeypatch.setattr(assembler_module.llm_manager, 'count_tokens', fake_count_tokens, raising=False)
    messages = [
        {'id': 1, 'role': 'user', 'content': '需求A'},
        {'id': 2, 'role': 'assistant', 'content': '回答A'},
        {'id': 3, 'role': 'user', 'content': '需求B'},
        {'id': 4, 'role': 'assistant', 'content': '回答B'},
    ]

    import asyncio
    result = asyncio.run(assembler_module.build_conversation_context(messages, latest_summary='这是摘要'))

    assert result['used_summary'] is True
    assert result['summary_present'] is True
    assert result['history'][0]['role'] == 'system'
    assert result['history_token_count'] == 40


def test_generate_session_summary_returns_incremental_cutoff(monkeypatch):
    async def fake_chat_completion(messages, temperature=0.2, max_tokens=512):
        assert '已有历史摘要' in messages[1]['content']
        assert '[11]' in messages[1]['content']
        return {
            'choices': [
                {'message': {'content': '新摘要'}}
            ]
        }

    monkeypatch.setattr(assembler_module.llm_manager, 'chat_completion', fake_chat_completion, raising=False)

    import asyncio
    result = asyncio.run(
        assembler_module.generate_session_summary(
            [
                {'id': 10, 'role': 'user', 'content': 'old'},
                {'id': 11, 'role': 'assistant', 'content': 'new1'},
                {'id': 12, 'role': 'user', 'content': 'new2'},
                {'id': 13, 'role': 'assistant', 'content': 'new3'},
                {'id': 14, 'role': 'user', 'content': 'new4'},
                {'id': 15, 'role': 'assistant', 'content': 'new5'},
                {'id': 16, 'role': 'user', 'content': 'recent1'},
                {'id': 17, 'role': 'assistant', 'content': 'recent2'},
            ],
            existing_summary='旧摘要',
            cutoff_message_id=10,
        )
    )

    assert result['summary'] == '新摘要'
    assert result['incremental'] is True
    assert result['cutoff_message_id'] == 11
    assert result['source_message_count'] == 1


def test_build_summary_message_metadata_contains_audit_fields():
    convo = ConversationSession(tenant_id='acme', title='会话1', status='active')
    convo.summary_version = 3
    convo.summary_message_cutoff_id = 120
    convo.summary_updated_at = datetime(2026, 6, 14, 12, 0, 0)

    metadata = conversations_module._build_summary_message_metadata(
        convo=convo,
        summary_result={
            'incremental': True,
            'source_message_count': 6,
        },
        previous_summary='旧摘要',
    )

    assert metadata['summary_version'] == 3
    assert metadata['summary_message_cutoff_id'] == 120
    assert metadata['summary_incremental'] is True
    assert metadata['summary_source_message_count'] == 6
    assert metadata['previous_summary'] == '旧摘要'
