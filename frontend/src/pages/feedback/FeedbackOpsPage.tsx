import { AlertOutlined, DatabaseOutlined, ReloadOutlined } from '@ant-design/icons';
import { Button, Card, Col, Descriptions, Empty, Input, List, Row, Select, Space, Table, Tag, Timeline, Typography, message } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { useAuthContext } from '../../app/auth-context';
import { addFeedbackToGoldenSet, fetchFeedbackBadcases, triggerFeedbackWikiRecompile } from '../../services/feedback';
import type { FeedbackBadcaseItem, FeedbackHitChunk } from '../../types';

const reasonOptions = [
  { label: '全部原因', value: '' },
  { label: '没帮助', value: 'not_helpful' },
  { label: '答案不准确', value: 'incorrect' },
  { label: '没有引用来源', value: 'missing_citations' },
  { label: '遗漏关键信息', value: 'missing_information' },
  { label: '太长', value: 'too_long' },
  { label: '太短', value: 'too_short' },
  { label: '用户补充答案', value: 'user_corrected_answer' },
];

function scoreTag(value?: number | null) {
  if (typeof value !== 'number') return null;
  const color = value >= 0.8 ? 'green' : value >= 0.55 ? 'gold' : 'red';
  return <Tag color={color}>{Math.round(value * 100)}%</Tag>;
}

function JsonBlock({ value }: { value?: unknown }) {
  if (!value) return <Typography.Text type="secondary">无</Typography.Text>;
  return (
    <pre style={{ margin: 0, maxHeight: 220, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function FeedbackOpsPage() {
  const { tenantId } = useAuthContext();
  const [reason, setReason] = useState('');
  const [items, setItems] = useState<FeedbackBadcaseItem[]>([]);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [activeId, setActiveId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const activeItem = useMemo(
    () => items.find((item) => item.feedback.id === activeId) || items[0],
    [items, activeId],
  );

  const loadBadcases = async () => {
    setLoading(true);
    try {
      const data = await fetchFeedbackBadcases({
        tenant_id: tenantId,
        rating: 'down',
        reason: reason || undefined,
        limit: 50,
      });
      setItems(data.items);
      setSummary(data.summary.reason_counts || {});
      setActiveId((prev) => {
        if (prev && data.items.some((item) => item.feedback.id === prev)) return prev;
        return data.items[0]?.feedback.id || null;
      });
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '加载反馈失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadBadcases();
  }, [tenantId, reason]);

  const addGoldenSet = async (item: FeedbackBadcaseItem) => {
    setActionLoading(`golden-${item.feedback.id}`);
    try {
      const result = await addFeedbackToGoldenSet(item.feedback.id, tenantId);
      message.success(result.added ? '已加入 Golden Set' : 'Golden Set 已存在');
      await loadBadcases();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '加入 Golden Set 失败');
    } finally {
      setActionLoading(null);
    }
  };

  const recompileWiki = async (item: FeedbackBadcaseItem) => {
    setActionLoading(`wiki-${item.feedback.id}`);
    try {
      const result = await triggerFeedbackWikiRecompile(item.feedback.id, tenantId);
      message.success(`已提交 Wiki 重编任务 #${result.job.id}`);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '触发 Wiki 重编失败');
    } finally {
      setActionLoading(null);
    }
  };

  const hitColumns = [
    { title: '文档', dataIndex: 'title', key: 'title', render: (value: string, row: FeedbackHitChunk) => value || row.document_id || '-' },
    { title: 'Chunk', dataIndex: 'chunk_id', key: 'chunk_id', width: 90, render: (value?: number | null) => value || '-' },
    { title: '类型', dataIndex: 'source_type', key: 'source_type', width: 120, render: (value?: string | null) => value || '-' },
    { title: '片段', dataIndex: 'snippet', key: 'snippet', render: (value?: string) => <Typography.Text>{value || '-'}</Typography.Text> },
  ];

  return (
    <Row gutter={16}>
      <Col span={8}>
        <Card
          className="page-card"
          title="反馈闭环"
          extra={<Tag color="blue">租户：{tenantId}</Tag>}
        >
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space wrap>
              <Select value={reason} options={reasonOptions} onChange={setReason} style={{ width: 160 }} />
              <Button icon={<ReloadOutlined />} loading={loading} onClick={loadBadcases} />
            </Space>
            <Space wrap>
              {Object.entries(summary).map(([key, count]) => (
                <Tag key={key}>{key}: {count}</Tag>
              ))}
            </Space>
            <List
              loading={loading}
              dataSource={items}
              locale={{ emptyText: <Empty description="暂无点踩 badcase" /> }}
              renderItem={(item) => (
                <List.Item
                  onClick={() => setActiveId(item.feedback.id)}
                  style={{
                    cursor: 'pointer',
                    background: activeItem?.feedback.id === item.feedback.id ? '#f0f5ff' : undefined,
                    borderRadius: 8,
                    padding: 12,
                  }}
                >
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Space wrap>
                      <Tag color="red">{item.feedback.reason || 'unknown'}</Tag>
                      {scoreTag(item.quality_score)}
                    </Space>
                    <Typography.Text strong ellipsis>{item.user_query || '未找到用户问题'}</Typography.Text>
                    <Typography.Text type="secondary" ellipsis>{item.assistant_answer || '未找到助手回答'}</Typography.Text>
                  </Space>
                </List.Item>
              )}
            />
          </Space>
        </Card>
      </Col>
      <Col span={16}>
        {activeItem ? (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Card
              className="page-card"
              title="Badcase 详情"
              extra={(
                <Space>
                  <Button
                    icon={<DatabaseOutlined />}
                    loading={actionLoading === `golden-${activeItem.feedback.id}`}
                    onClick={() => addGoldenSet(activeItem)}
                  >
                    加入 Golden Set
                  </Button>
                  <Button
                    icon={<AlertOutlined />}
                    disabled={!activeItem.wiki_recompile_document_ids.length}
                    loading={actionLoading === `wiki-${activeItem.feedback.id}`}
                    onClick={() => recompileWiki(activeItem)}
                  >
                    触发 Wiki 重编
                  </Button>
                </Space>
              )}
            >
              <Space direction="vertical" style={{ width: '100%' }} size="middle">
                <Descriptions bordered size="small" column={2}>
                  <Descriptions.Item label="反馈 ID">{activeItem.feedback.id}</Descriptions.Item>
                  <Descriptions.Item label="原因">{activeItem.feedback.reason || '-'}</Descriptions.Item>
                  <Descriptions.Item label="质量分">{scoreTag(activeItem.quality_score) || '-'}</Descriptions.Item>
                  <Descriptions.Item label="检索次数">{activeItem.retrieval_count || '-'}</Descriptions.Item>
                  <Descriptions.Item label="独立问题" span={2}>{activeItem.standalone_query || '-'}</Descriptions.Item>
                  <Descriptions.Item label="用户原问" span={2}>{activeItem.user_query || '-'}</Descriptions.Item>
                  <Descriptions.Item label="助手回答" span={2}>{activeItem.assistant_answer || '-'}</Descriptions.Item>
                  <Descriptions.Item label="用户修正" span={2}>{activeItem.feedback.corrected_answer || '-'}</Descriptions.Item>
                </Descriptions>

                <Card size="small" title="查询规划">
                  <JsonBlock value={activeItem.query_plan} />
                </Card>

                {activeItem.multi_hop_trace?.length ? (
                  <Card size="small" title="多跳 Trace">
                    <Timeline
                      items={activeItem.multi_hop_trace.map((trace, index) => ({
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
                              融合 {trace.fused_results || 0}，耗时 {trace.elapsed_ms || 0} ms
                            </Typography.Text>
                          </Space>
                        ),
                      }))}
                    />
                  </Card>
                ) : null}

                <Card size="small" title="命中 Chunk">
                  <Table
                    rowKey={(row) => `${row.document_id || 'doc'}-${row.chunk_id || row.wiki_page_id || row.title || row.snippet || 'hit'}`}
                    size="small"
                    columns={hitColumns}
                    dataSource={activeItem.hit_chunks}
                    pagination={false}
                  />
                </Card>

                <Card size="small" title="Golden Set 候选">
                  <JsonBlock value={activeItem.golden_candidate} />
                </Card>
              </Space>
            </Card>
          </Space>
        ) : (
          <Card className="page-card">
            <Empty description="暂无 badcase" />
          </Card>
        )}
      </Col>
    </Row>
  );
}
