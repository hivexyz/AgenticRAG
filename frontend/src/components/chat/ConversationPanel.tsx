import { SendOutlined } from '@ant-design/icons';
import { Button, Card, Drawer, Empty, Input, List, Space, Tag, Typography, message } from 'antd';
import { useMemo, useState } from 'react';
import type { AnswerBlock, CitationItem, ConversationSession, DocumentFragment, EvidenceCard, FeedbackAction } from '../../types';
import { submitFeedback } from '../../services/feedback';

interface MessageItem {
  id: number | string;
  role: 'user' | 'assistant';
  content: string;
  answerBlocks?: AnswerBlock[];
  citations?: CitationItem[];
  evidenceCards?: EvidenceCard[];
  uncertainty?: { label?: string; message?: string } | null;
  refusal?: { should_refuse?: boolean; message?: string; next_steps?: string[] } | null;
  feedbackActions?: FeedbackAction[];
}

interface Props {
  tenantId: string;
  session?: ConversationSession | null;
  messages: MessageItem[];
  loading: boolean;
  onSend: (content: string) => Promise<void>;
  onOpenFragment: (documentId: number, chunkId: number) => Promise<DocumentFragment>;
}

export function ConversationPanel({ tenantId, session, messages, loading, onSend, onOpenFragment }: Props) {
  const [input, setInput] = useState('');
  const [fragment, setFragment] = useState<DocumentFragment | null>(null);
  const [fragmentOpen, setFragmentOpen] = useState(false);
  const latestAssistant = useMemo(() => [...messages].reverse().find((item) => item.role === 'assistant'), [messages]);

  const handleFeedback = async (action: FeedbackAction) => {
    if (!latestAssistant || typeof latestAssistant.id !== 'number') return;
    await submitFeedback({
      tenant_id: tenantId,
      session_id: session?.id,
      message_id: latestAssistant.id,
      rating: action.key === 'helpful' ? 'up' : 'down',
      reason: action.key,
    });
    message.success('反馈已提交');
  };

  const openFragment = async (documentId: number, chunkId: number) => {
    const data = await onOpenFragment(documentId, chunkId);
    setFragment(data);
    setFragmentOpen(true);
  };

  return (
    <>
      <Card className="page-card" title={session?.title || '问答工作台'} extra={<Tag color="blue">租户：{tenantId}</Tag>}>
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          {messages.length ? (
            <List
              dataSource={messages}
              renderItem={(item) => (
                <List.Item>
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Typography.Text strong>{item.role === 'user' ? '用户' : '助手'}</Typography.Text>
                    {item.answerBlocks?.length ? item.answerBlocks.map((block, index) => (
                      <div key={`${item.id}-${index}`} className="chat-answer-block">
                        <Typography.Paragraph style={{ marginBottom: 8 }}>{block.text}</Typography.Paragraph>
                        <Space>
                          {block.citation_ids.map((id) => <Tag key={id}>来源{id}</Tag>)}
                          {block.uncertainty_flag && <Tag color="orange">需确认</Tag>}
                        </Space>
                      </div>
                    )) : <Typography.Paragraph>{item.content}</Typography.Paragraph>}

                    {item.citations?.length ? (
                      <Space direction="vertical" style={{ width: '100%' }}>
                        <Typography.Text type="secondary">引用来源</Typography.Text>
                        {item.citations.map((citation, index) => (
                          <Card key={index} size="small" type="inner" title={citation.claim}>
                            {citation.sources.map((source, sourceIndex) => (
                              <Space key={sourceIndex} direction="vertical" style={{ width: '100%' }}>
                                <Typography.Text strong>{source.title}</Typography.Text>
                                <Typography.Text type="secondary">页码 {source.page || '-'} / 段落 {source.paragraph || '-'}</Typography.Text>
                                <Typography.Paragraph>{source.snippet}</Typography.Paragraph>
                                {source.open_fragment?.document_id && source.open_fragment?.chunk_id && (
                                  <Button type="link" onClick={() => openFragment(source.open_fragment!.document_id!, source.open_fragment!.chunk_id!)}>打开原文片段</Button>
                                )}
                              </Space>
                            ))}
                          </Card>
                        ))}
                      </Space>
                    ) : null}

                    {item.evidenceCards?.length ? (
                      <Card size="small" title="证据高亮">
                        {item.evidenceCards.map((card) => (
                          <div key={card.rank} style={{ marginBottom: 12 }}>
                            <Typography.Text strong>{card.source.title}</Typography.Text>
                            <Typography.Paragraph>{card.snippet}</Typography.Paragraph>
                            <Space wrap>
                              {card.highlighted_sentences.map((sentence, idx) => <Tag color="purple" key={idx}>{sentence}</Tag>)}
                            </Space>
                            {card.source.open_fragment?.document_id && card.source.open_fragment?.chunk_id ? (
                              <div style={{ marginTop: 8 }}>
                                <Button type="link" onClick={() => openFragment(card.source.open_fragment!.document_id!, card.source.open_fragment!.chunk_id!)}>查看完整上下文</Button>
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </Card>
                    ) : null}

                    {item.uncertainty?.label ? <Tag color="gold">{item.uncertainty.label}</Tag> : null}
                    {item.refusal?.should_refuse ? <Typography.Text type="warning">{item.refusal.message}</Typography.Text> : null}
                  </Space>
                </List.Item>
              )}
            />
          ) : <Empty description="开始新一轮知识库问答" />}

          <Space.Compact style={{ width: '100%' }}>
            <Input.TextArea value={input} onChange={(e) => setInput(e.target.value)} autoSize={{ minRows: 2, maxRows: 4 }} placeholder="请输入问题，例如：请总结请假制度的核心要求" />
            <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={async () => {
              if (!input.trim()) return;
              const content = input.trim();
              setInput('');
              await onSend(content);
            }} />
          </Space.Compact>

          {latestAssistant?.feedbackActions?.length ? (
            <Card size="small" title="这次回答对你有帮助吗？">
              <Space wrap>
                {latestAssistant.feedbackActions.map((action) => (
                  <Button key={action.key} size="small" onClick={() => handleFeedback(action)}>{action.label}</Button>
                ))}
              </Space>
            </Card>
          ) : null}
        </Space>
      </Card>

      <Drawer title={fragment?.title || '原文片段'} open={fragmentOpen} onClose={() => setFragmentOpen(false)} width={720}>
        {fragment ? (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Typography.Text type="secondary">页码：{fragment.page || '-'} ｜ 段落：{fragment.paragraph || '-'} ｜ 章节：{fragment.section_title || '-'}</Typography.Text>
            <Typography.Paragraph strong>前文</Typography.Paragraph>
            <Typography.Paragraph>{fragment.previous_context || '无'}</Typography.Paragraph>
            <Typography.Paragraph strong>当前片段</Typography.Paragraph>
            <Typography.Paragraph>{fragment.content}</Typography.Paragraph>
            <Typography.Paragraph strong>后文</Typography.Paragraph>
            <Typography.Paragraph>{fragment.next_context || '无'}</Typography.Paragraph>
          </Space>
        ) : null}
      </Drawer>
    </>
  );
}
