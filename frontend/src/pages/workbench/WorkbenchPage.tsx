import { Button, Card, Col, Input, List, Row, Space, Typography, message } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { useAuthContext } from '../../app/auth-context';
import { ConversationPanel, type MessageItem } from '../../components/chat/ConversationPanel';
import { createConversation, fetchConversationMessages, fetchConversations, streamConversationMessage } from '../../services/conversations';
import { fetchFragment } from '../../services/documents';
import type { ConversationMessageResponse, ConversationSession, DocumentFragment, RAGResult } from '../../types';

export function WorkbenchPage() {
  const { tenantId } = useAuthContext();
  const [conversations, setConversations] = useState<ConversationSession[]>([]);
  const [activeSession, setActiveSession] = useState<ConversationSession | null>(null);
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [abortController, setAbortController] = useState<AbortController | null>(null);

  const loadConversations = async (nextTenantId = tenantId) => {
    const items = await fetchConversations(nextTenantId);
    setConversations(items);
    setActiveSession((prev) => {
      if (prev && prev.tenant_id === nextTenantId && items.some((item) => item.id === prev.id)) {
        return prev;
      }
      return items[0] || null;
    });
  };

  const loadMessages = async (session: ConversationSession) => {
    const items = await fetchConversationMessages(session.id, tenantId);
    setMessages(items
      .filter((item) => item.role === 'user' || item.role === 'assistant')
      .map((item) => ({
        id: item.id,
        role: item.role as 'user' | 'assistant',
        content: item.content,
        feedbackActions: item.metadata?.feedback_actions as MessageItem['feedbackActions'],
        answerBlocks: item.metadata?.answer_blocks as MessageItem['answerBlocks'],
        citations: item.metadata?.citations as MessageItem['citations'],
        evidenceCards: item.metadata?.evidence_cards as MessageItem['evidenceCards'],
        multiHopTrace: item.metadata?.multi_hop_trace as MessageItem['multiHopTrace'],
        qualityScore: item.metadata?.quality_score as MessageItem['qualityScore'],
        qualityEvaluation: item.metadata?.quality_evaluation as MessageItem['qualityEvaluation'],
        qualityEvaluationStatus: item.metadata?.quality_evaluation_status as MessageItem['qualityEvaluationStatus'],
        uncertainty: item.metadata?.uncertainty as MessageItem['uncertainty'],
        refusal: item.metadata?.refusal as MessageItem['refusal'],
      })));
  };

  useEffect(() => {
    setActiveSession(null);
    setMessages([]);
    void loadConversations(tenantId);
  }, [tenantId]);

  useEffect(() => {
    if (activeSession) {
      void loadMessages(activeSession);
    }
  }, [activeSession]);

  const title = useMemo(() => activeSession?.title || '新会话', [activeSession]);

  const applyRagResult = (assistantId: string | number, ragResult: RAGResult, feedbackActions?: MessageItem['feedbackActions']) => {
    setMessages((prev) => prev.map((item) => (
      item.id === assistantId
        ? {
          ...item,
          content: ragResult.answer || item.content,
          answerBlocks: ragResult.answer_blocks || undefined,
          citations: ragResult.citations || undefined,
          evidenceCards: ragResult.evidence_cards || undefined,
          multiHopTrace: ragResult.multi_hop_trace || undefined,
          qualityScore: ragResult.quality_score,
          qualityEvaluation: ragResult.quality_evaluation,
          qualityEvaluationStatus: ragResult.quality_evaluation_status,
          uncertainty: ragResult.uncertainty,
          refusal: ragResult.refusal,
          feedbackActions,
          streaming: false,
        }
        : item
    )));
  };

  const handleSend = async (content: string) => {
    if (!activeSession) {
      message.warning('请先创建会话');
      return;
    }

    const timestamp = Date.now();
    const userTempId = `user-${timestamp}`;
    const assistantTempId = `assistant-${timestamp}`;
    const controller = new AbortController();
    let streamedAnswer = '';
    setAbortController(controller);
    setLoading(true);
    setMessages((prev) => [
      ...prev,
      { id: userTempId, role: 'user', content },
      { id: assistantTempId, role: 'assistant', content: '', streaming: true },
    ]);

    try {
      await streamConversationMessage(
        activeSession.id,
        { tenant_id: tenantId, content },
        {
          onEvent: (event) => {
            if (event.event === 'phase' && event.phase === 'retrieval_retry') {
              streamedAnswer = '';
              setMessages((prev) => prev.map((item) => (
                item.id === assistantTempId ? { ...item, content: '', streaming: true } : item
              )));
              return;
            }

            if (event.event === 'user_message') {
              const userMessage = (event.user_message || {}) as ConversationMessageResponse['user_message'];
              if (userMessage.id) {
                setMessages((prev) => prev.map((item) => (
                  item.id === userTempId ? { ...item, id: userMessage.id, content: userMessage.content } : item
                )));
              }
              return;
            }

            if (event.event === 'answer_delta') {
              const delta = String(event.delta || '');
              streamedAnswer += delta;
              setMessages((prev) => prev.map((item) => (
                item.id === assistantTempId ? { ...item, content: streamedAnswer } : item
              )));
              return;
            }

            if (event.event === 'answer_done') {
              const answer = String(event.answer || streamedAnswer);
              setMessages((prev) => prev.map((item) => (
                item.id === assistantTempId
                  ? {
                    ...item,
                    content: answer,
                    answerBlocks: event.answer_blocks as MessageItem['answerBlocks'],
                    citations: event.citations as MessageItem['citations'],
                    evidenceCards: event.evidence_cards as MessageItem['evidenceCards'],
                    multiHopTrace: event.multi_hop_trace as MessageItem['multiHopTrace'],
                    uncertainty: event.uncertainty as MessageItem['uncertainty'],
                    refusal: event.refusal as MessageItem['refusal'],
                    streaming: false,
                  }
                  : item
              )));
              return;
            }

            if (event.event === 'quality_done' || event.event === 'quality_warning') {
              setMessages((prev) => prev.map((item) => (
                item.id === assistantTempId
                  ? {
                    ...item,
                    qualityScore: event.quality_score as MessageItem['qualityScore'],
                    qualityEvaluation: event.quality_evaluation as MessageItem['qualityEvaluation'],
                    qualityEvaluationStatus: event.quality_evaluation_status as MessageItem['qualityEvaluationStatus'],
                    uncertainty: event.uncertainty as MessageItem['uncertainty'],
                    refusal: event.refusal as MessageItem['refusal'],
                  }
                  : item
              )));
              return;
            }

            if (event.event === 'final') {
              const response = event as unknown as ConversationMessageResponse;
              const assistant = response.assistant_message;
              setActiveSession(response.session);
              setMessages((prev) => prev.map((item) => (
                item.id === assistantTempId
                  ? { ...item, id: assistant.id, content: assistant.content, feedbackActions: response.feedback?.actions }
                  : item
              )));
              applyRagResult(assistant.id, response.rag_result, response.feedback?.actions);
              return;
            }

            if (event.event === 'error') {
              throw new Error(String(event.error || '流式问答失败'));
            }
          },
        },
        controller.signal,
      );
    } catch (error: any) {
      if (error?.name === 'AbortError') {
        setMessages((prev) => prev.map((item) => (
          item.id === assistantTempId ? { ...item, content: item.content || '已停止生成。', streaming: false } : item
        )));
      } else {
        setMessages((prev) => prev.filter((item) => item.id !== assistantTempId || item.content));
        message.error(error?.message || '发送消息失败');
      }
    } finally {
      setLoading(false);
      setAbortController(null);
    }
  };

  const handleRegenerate = async () => {
    const lastUser = [...messages].reverse().find((item) => item.role === 'user');
    if (lastUser?.content) {
      await handleSend(lastUser.content);
    }
  };

  return (
    <Row gutter={16}>
      <Col span={7}>
        <Card className="page-card" title="会话列表" extra={<Typography.Text type="secondary">租户：{tenantId}</Typography.Text>}>
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
          onSend={handleSend}
          onStop={() => abortController?.abort()}
          onRegenerate={handleRegenerate}
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
