import { Button, Card, Col, Input, List, Row, Space, Typography, message } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { ConversationPanel } from '../../components/chat/ConversationPanel';
import { createConversation, fetchConversationMessages, fetchConversations, sendConversationMessage } from '../../services/conversations';
import { fetchFragment } from '../../services/documents';
import type { ConversationSession, DocumentFragment } from '../../types';

const DEFAULT_TENANT = 'default';

export function WorkbenchPage() {
  const [tenantId, setTenantId] = useState(DEFAULT_TENANT);
  const [conversations, setConversations] = useState<ConversationSession[]>([]);
  const [activeSession, setActiveSession] = useState<ConversationSession | null>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const loadConversations = async () => {
    const items = await fetchConversations(tenantId);
    setConversations(items);
    if (!activeSession && items.length) {
      setActiveSession(items[0]);
    }
  };

  const loadMessages = async (session: ConversationSession) => {
    const items = await fetchConversationMessages(session.id, tenantId);
    setMessages(items.map((item) => ({
      id: item.id,
      role: item.role,
      content: item.content,
      feedbackActions: item.metadata?.feedback_actions,
      citations: item.metadata?.citations,
      uncertainty: item.metadata?.uncertainty,
      refusal: item.metadata?.refusal,
    })));
  };

  useEffect(() => {
    void loadConversations();
  }, [tenantId]);

  useEffect(() => {
    if (activeSession) {
      void loadMessages(activeSession);
    }
  }, [activeSession]);

  const title = useMemo(() => activeSession?.title || '新会话', [activeSession]);

  return (
    <Row gutter={16}>
      <Col span={7}>
        <Card className="page-card" title="会话列表" extra={<Input value={tenantId} onChange={(e) => setTenantId(e.target.value)} style={{ width: 140 }} />}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Button type="primary" onClick={async () => {
              try {
                const session = await createConversation({ tenant_id: tenantId, title: `会话 ${conversations.length + 1}` });
                setConversations((prev) => [session, ...prev]);
                setActiveSession(session);
                setMessages([]);
                message.success('新会话已创建');
              } catch (error: any) {
                message.error(error?.response?.data?.detail || error?.message || '新建会话失败');
              }
            }}>新建会话</Button>
            <List
              dataSource={conversations}
              renderItem={(item) => (
                <List.Item onClick={() => setActiveSession(item)} style={{ cursor: 'pointer', background: activeSession?.id === item.id ? '#f0f5ff' : undefined, borderRadius: 8, padding: 12 }}>
                  <Space direction="vertical" size={0}>
                    <Typography.Text strong>{item.title}</Typography.Text>
                    <Typography.Text type="secondary">{item.latest_summary ? '已有摘要记忆' : '新会话'}</Typography.Text>
                  </Space>
                </List.Item>
              )}
            />
          </Space>
        </Card>
      </Col>
      <Col span={17}>
        <ConversationPanel
          tenantId={tenantId}
          session={activeSession}
          messages={messages}
          loading={loading}
          onSend={async (content) => {
            if (!activeSession) {
              message.warning('请先创建会话');
              return;
            }
            setLoading(true);
            try {
              const response = await sendConversationMessage(activeSession.id, { tenant_id: tenantId, content });
              const assistant = response.assistant_message;
              setMessages((prev) => [
                ...prev,
                { id: response.user_message.id, role: 'user', content: response.user_message.content },
                {
                  id: assistant.id,
                  role: 'assistant',
                  content: assistant.content,
                  answerBlocks: response.rag_result.answer_blocks,
                  citations: response.rag_result.citations,
                  evidenceCards: response.rag_result.evidence_cards,
                  uncertainty: response.rag_result.uncertainty,
                  refusal: response.rag_result.refusal,
                  feedbackActions: response.feedback?.actions,
                },
              ]);
            } finally {
              setLoading(false);
            }
          }}
          onOpenFragment={async (documentId, chunkId): Promise<DocumentFragment> => {
            const fragment = await fetchFragment(documentId, chunkId, tenantId);
            message.info(`已加载片段：${fragment.title || title}`);
            return fragment;
          }}
        />
      </Col>
    </Row>
  );
}
