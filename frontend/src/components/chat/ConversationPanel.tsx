import { CopyOutlined, ReloadOutlined, SendOutlined, StopOutlined } from '@ant-design/icons';
import { Button, Card, Drawer, Empty, Input, List, Space, Tag, Timeline, Typography, message } from 'antd';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { AnswerBlock, CitationItem, ConversationSession, DocumentFragment, EvidenceCard, FeedbackAction, MultiHopTraceItem, QualityEvaluation } from '../../types';
import { submitFeedback } from '../../services/feedback';

export interface MessageItem {
  id: number | string;
  role: 'user' | 'assistant';
  content: string;
  answerBlocks?: AnswerBlock[];
  citations?: CitationItem[];
  evidenceCards?: EvidenceCard[];
  multiHopTrace?: MultiHopTraceItem[];
  qualityScore?: number | null;
  qualityEvaluation?: QualityEvaluation | null;
  qualityEvaluationStatus?: string | null;
  uncertainty?: { label?: string; message?: string } | null;
  refusal?: { should_refuse?: boolean; message?: string; next_steps?: string[] } | null;
  feedbackActions?: FeedbackAction[];
  streaming?: boolean;
}

interface Props {
  tenantId: string;
  session?: ConversationSession | null;
  messages: MessageItem[];
  loading: boolean;
  onSend: (content: string) => Promise<void>;
  onStop?: () => void;
  onRegenerate?: () => Promise<void>;
  onOpenFragment: (documentId: number, chunkId: number) => Promise<DocumentFragment>;
}

function percent(value?: number | null) {
  if (typeof value !== 'number') return null;
  return `${Math.round(value * 100)}%`;
}

function qualityColor(value?: number | null) {
  if (typeof value !== 'number') return 'default';
  if (value >= 0.8) return 'green';
  if (value >= 0.55) return 'gold';
  return 'red';
}

const suggestedPrompts = ['有哪些例外情况？', '按表格总结一下', '对应的原文依据是什么？'];

type MarkdownBlock =
  | { type: 'paragraph'; text: string }
  | { type: 'code'; language?: string; text: string }
  | { type: 'ul' | 'ol'; items: string[] }
  | { type: 'table'; headers: string[]; rows: string[][] };

function splitTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

function isTableSeparator(line?: string) {
  if (!line || !line.includes('|')) return false;
  const cells = splitTableRow(line);
  return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function parseMarkdownBlocks(markdown: string): MarkdownBlock[] {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const blocks: MarkdownBlock[] = [];
  const paragraph: string[] = [];

  const flushParagraph = () => {
    const text = paragraph.join('\n').trim();
    if (text) blocks.push({ type: 'paragraph', text });
    paragraph.length = 0;
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      flushParagraph();
      continue;
    }

    const fence = trimmed.match(/^```(\w+)?/);
    if (fence) {
      flushParagraph();
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        code.push(lines[index]);
        index += 1;
      }
      blocks.push({ type: 'code', language: fence[1], text: code.join('\n') });
      continue;
    }

    if (line.includes('|') && isTableSeparator(lines[index + 1])) {
      flushParagraph();
      const headers = splitTableRow(line);
      index += 2;
      const rows: string[][] = [];
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
      }
      index -= 1;
      blocks.push({ type: 'table', headers, rows });
      continue;
    }

    const unordered = trimmed.match(/^[-*]\s+(.+)$/);
    if (unordered) {
      flushParagraph();
      const items = [unordered[1]];
      while (index + 1 < lines.length) {
        const next = lines[index + 1].trim().match(/^[-*]\s+(.+)$/);
        if (!next) break;
        items.push(next[1]);
        index += 1;
      }
      blocks.push({ type: 'ul', items });
      continue;
    }

    const ordered = trimmed.match(/^\d+\.\s+(.+)$/);
    if (ordered) {
      flushParagraph();
      const items = [ordered[1]];
      while (index + 1 < lines.length) {
        const next = lines[index + 1].trim().match(/^\d+\.\s+(.+)$/);
        if (!next) break;
        items.push(next[1]);
        index += 1;
      }
      blocks.push({ type: 'ol', items });
      continue;
    }

    paragraph.push(line);
  }

  flushParagraph();
  return blocks;
}

function MarkdownContent({ content, streaming }: { content: string; streaming?: boolean }) {
  const blocks = useMemo(() => parseMarkdownBlocks(content || ''), [content]);
  if (!blocks.length) {
    return streaming ? <Typography.Text type="secondary">|</Typography.Text> : null;
  }

  return (
    <div className="markdown-answer">
      {blocks.map((block, index) => {
        if (block.type === 'table') {
          return (
            <div className="markdown-table-wrap" key={index}>
              <table className="markdown-table">
                <thead>
                  <tr>
                    {block.headers.map((header, cellIndex) => <th key={cellIndex}>{header}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {block.headers.map((_, cellIndex) => <td key={cellIndex}>{row[cellIndex] || ''}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (block.type === 'code') {
          return (
            <pre className="markdown-code" key={index}>
              <code>{block.text}</code>
            </pre>
          );
        }
        if (block.type === 'ul') {
          return <ul key={index}>{block.items.map((item, itemIndex) => <li key={itemIndex}>{item}</li>)}</ul>;
        }
        if (block.type === 'ol') {
          return <ol key={index}>{block.items.map((item, itemIndex) => <li key={itemIndex}>{item}</li>)}</ol>;
        }
        if (block.type === 'paragraph') {
          return <Typography.Paragraph key={index}>{block.text}</Typography.Paragraph>;
        }
        return null;
      })}
      {streaming ? <Typography.Text type="secondary"> |</Typography.Text> : null}
    </div>
  );
}

export function ConversationPanel({ tenantId, session, messages, loading, onSend, onStop, onRegenerate, onOpenFragment }: Props) {
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

  const copyAnswer = async (content: string) => {
    await navigator.clipboard.writeText(content);
    message.success('已复制');
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
                        <MarkdownContent content={block.text} />
                        <Space>
                          {block.citation_note ? <Tag color="blue">{block.citation_note}</Tag> : null}
                          {block.citation_ids.map((id) => <Tag key={id}>来源{id}</Tag>)}
                          {block.uncertainty_flag && <Tag color="orange">需确认</Tag>}
                        </Space>
                      </div>
                    )) : <MarkdownContent content={item.content} streaming={item.streaming} />}

                    {item.role === 'assistant' ? (
                      <Space wrap>
                        <Button size="small" icon={<CopyOutlined />} onClick={() => copyAnswer(item.content)}>复制</Button>
                        {latestAssistant?.id === item.id && onRegenerate ? (
                          <Button size="small" icon={<ReloadOutlined />} disabled={loading} onClick={onRegenerate}>重新生成</Button>
                        ) : null}
                        {typeof item.qualityScore === 'number' ? (
                          <Tag color={qualityColor(item.qualityScore)}>质量 {percent(item.qualityScore)}</Tag>
                        ) : null}
                        {typeof item.qualityEvaluation?.groundedness === 'number' ? (
                          <Tag color={qualityColor(item.qualityEvaluation.groundedness)}>依据 {percent(item.qualityEvaluation.groundedness)}</Tag>
                        ) : null}
                        {typeof item.qualityEvaluation?.relevance === 'number' ? (
                          <Tag color={qualityColor(item.qualityEvaluation.relevance)}>相关 {percent(item.qualityEvaluation.relevance)}</Tag>
                        ) : null}
                        {item.qualityEvaluationStatus === 'failed' ? (
                          <Tag color="red">未质检</Tag>
                        ) : null}
                      </Space>
                    ) : null}

                    {item.multiHopTrace?.length ? (
                      <Timeline
                        style={{ marginTop: 8 }}
                        items={item.multiHopTrace.map((trace, index) => ({
                          color: trace.stopped_reason || trace.errors?.length ? 'orange' : 'blue',
                          children: (
                            <Space direction="vertical" size={4}>
                              <Typography.Text strong>第 {trace.hop || index + 1} 跳：{trace.purpose || '检索'}</Typography.Text>
                              <Space wrap>
                                {(trace.rendered_queries || []).map((query) => <Tag key={query}>{query}</Tag>)}
                              </Space>
                              {trace.extracted_slots && Object.keys(trace.extracted_slots).length ? (
                                <Typography.Text type="secondary">
                                  槽位：{Object.entries(trace.extracted_slots).map(([key, value]) => `${key}=${value || '-'}`).join('，')}
                                </Typography.Text>
                              ) : null}
                              <Typography.Text type="secondary">
                                命中：向量 {trace.dense_results || 0} / 稀疏 {trace.sparse_results || 0} / Wiki {trace.wiki_results || 0} / 融合 {trace.fused_results || 0}
                              </Typography.Text>
                            </Space>
                          ),
                        }))}
                      />
                    ) : null}

                    {item.citations?.length ? (
                      <Space direction="vertical" style={{ width: '100%' }}>
                        <Typography.Text type="secondary">引用来源</Typography.Text>
                        {item.citations.map((citation, index) => (
                          <Card key={index} size="small" type="inner" title={citation.claim}>
                            {citation.sources.map((source, sourceIndex) => (
                              <Space key={sourceIndex} direction="vertical" style={{ width: '100%' }}>
                                <Space>
                                  <Typography.Text strong>{source.title}</Typography.Text>
                                  {source.source_type === 'wiki_page' ? <Tag color="cyan">Wiki</Tag> : null}
                                </Space>
                                <Typography.Text type="secondary">页码 {source.page || '-'} / 段落 {source.paragraph || '-'}</Typography.Text>
                                <Typography.Paragraph>{source.snippet}</Typography.Paragraph>
                                {source.open_fragment?.document_id && source.open_fragment?.chunk_id && (
                                  <Button type="link" onClick={() => openFragment(source.open_fragment!.document_id!, source.open_fragment!.chunk_id!)}>打开原文片段</Button>
                                )}
                                {source.source_type === 'wiki_page' && source.wiki_page_id ? (
                                  <Link to={`/wiki?page_id=${source.wiki_page_id}`}>查看 Wiki 页面</Link>
                                ) : null}
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
                            <Space>
                              <Typography.Text strong>{card.source.title}</Typography.Text>
                              {card.source.source_type === 'wiki_page' ? <Tag color="cyan">Wiki</Tag> : null}
                            </Space>
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
            <Button icon={<StopOutlined />} disabled={!loading} onClick={onStop} />
            <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={async () => {
              if (!input.trim()) return;
              const content = input.trim();
              setInput('');
              await onSend(content);
            }} />
          </Space.Compact>

          {latestAssistant && !loading ? (
            <Space wrap>
              {suggestedPrompts.map((prompt) => (
                <Button key={prompt} size="small" onClick={() => setInput(prompt)}>{prompt}</Button>
              ))}
            </Space>
          ) : null}

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
