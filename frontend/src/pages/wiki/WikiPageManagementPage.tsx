import { DeleteOutlined, EditOutlined, FileSyncOutlined, HistoryOutlined, LinkOutlined, ReadOutlined, ReloadOutlined, SaveOutlined, SearchOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Col, Drawer, Form, Input, InputNumber, List, Popconfirm, Row, Select, Space, Table, Tag, Typography, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import dayjs from 'dayjs';
import { useAuthContext } from '../../app/auth-context';
import { bulkCompileWikiPages, compileWikiPage, deleteWikiPage, fetchWikiCompileJob, fetchWikiPage, fetchWikiPageLinks, fetchWikiPageRevisions, fetchWikiPages, fetchWikiTopicIndex, rebuildWikiLinks, updateWikiPage } from '../../services/wiki';
import type { WikiCompileJobItem, WikiPageItem, WikiPageLinksResponse, WikiPageRevisionItem, WikiTopicIndexItem } from '../../types';

function parseDocumentIds(value: string) {
  return Array.from(new Set(
    value
      .split(/[\s,，]+/)
      .map((item) => Number(item.trim()))
      .filter((item) => Number.isInteger(item) && item > 0),
  ));
}

function renderRevisionDiff(item: WikiPageRevisionItem) {
  const diff = item.metadata?.diff;
  if (!diff || typeof diff !== 'object') return null;
  return (
    <Space wrap>
      {Object.keys(diff as Record<string, unknown>).map((field) => <Tag color="purple" key={field}>{field}</Tag>)}
    </Space>
  );
}

export function WikiPageManagementPage() {
  const [searchParams] = useSearchParams();
  const { tenantId } = useAuthContext();
  const [keyword, setKeyword] = useState('');
  const [knowledgeBase, setKnowledgeBase] = useState('');
  const [pageStatus, setPageStatus] = useState<string | undefined>();
  const [sourceDocumentId, setSourceDocumentId] = useState<number | null>(null);
  const [bulkDocumentIds, setBulkDocumentIds] = useState('');
  const [pages, setPages] = useState<WikiPageItem[]>([]);
  const [topicIndex, setTopicIndex] = useState<WikiTopicIndexItem[]>([]);
  const [activePage, setActivePage] = useState<WikiPageItem | null>(null);
  const [revisions, setRevisions] = useState<WikiPageRevisionItem[]>([]);
  const [links, setLinks] = useState<WikiPageLinksResponse | null>(null);
  const [activeJob, setActiveJob] = useState<WikiCompileJobItem | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [compiling, setCompiling] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const loadPages = async () => {
    setLoading(true);
    try {
      const params = {
        tenant_id: tenantId,
        q: keyword || undefined,
        knowledge_base: knowledgeBase || undefined,
        status: pageStatus,
        limit: 50,
      };
      const [data, indexData] = await Promise.all([
        fetchWikiPages(params),
        fetchWikiTopicIndex({ tenant_id: tenantId, knowledge_base: knowledgeBase || undefined }),
      ]);
      setPages(data);
      setTopicIndex(indexData.knowledge_bases);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '加载 Wiki 页面失败');
      setPages([]);
      setTopicIndex([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadPages();
  }, [tenantId, knowledgeBase, pageStatus]);

  useEffect(() => {
    if (!activeJob || !['pending', 'processing'].includes(activeJob.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const nextJob = await fetchWikiCompileJob(activeJob.id, tenantId);
        setActiveJob(nextJob);
        if (!['pending', 'processing'].includes(nextJob.status)) {
          window.clearInterval(timer);
          await loadPages();
        }
      } catch (error: any) {
        window.clearInterval(timer);
        message.error(error?.response?.data?.detail || error?.message || '刷新编译任务失败');
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [activeJob?.id, activeJob?.status, tenantId]);

  useEffect(() => {
    const pageId = Number(searchParams.get('page_id'));
    if (!pageId) return;
    void openPageDetail(pageId);
  }, [searchParams, tenantId]);

  const openPageDetail = async (pageId: number) => {
    try {
      const [detail, revisionItems, linkItems] = await Promise.all([
        fetchWikiPage(pageId, tenantId),
        fetchWikiPageRevisions(pageId, tenantId),
        fetchWikiPageLinks(pageId, tenantId),
      ]);
      setActivePage(detail);
      setRevisions(revisionItems);
      setLinks(linkItems);
      form.setFieldsValue(detail);
      setEditing(false);
      setDetailOpen(true);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '加载 Wiki 页面详情失败');
    }
  };

  const knowledgeBaseOptions = useMemo(() => Array.from(new Set(pages.map((item) => item.knowledge_base).filter(Boolean))), [pages]);

  const columns: ColumnsType<WikiPageItem> = [
    {
      title: '页面标题',
      dataIndex: 'title',
      key: 'title',
      width: 240,
      render: (value, record) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{value}</Typography.Text>
          <Typography.Text type="secondary">{record.slug}</Typography.Text>
        </Space>
      ),
    },
    { title: '知识库', dataIndex: 'knowledge_base', key: 'knowledge_base', width: 140, render: (value) => value || '-' },
    { title: '来源文档', dataIndex: 'source_document_id', key: 'source_document_id', width: 120, render: (value) => value ? `#${value}` : '-' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (value) => <Tag color={value === 'ready' ? 'green' : value === 'stale' ? 'orange' : 'blue'}>{value}</Tag> },
    {
      title: '摘要',
      dataIndex: 'summary',
      key: 'summary',
      ellipsis: true,
      render: (value) => value || '-',
    },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 180, render: (value) => value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '-' },
    {
      title: '操作',
      key: 'actions',
      fixed: 'right',
      width: 190,
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            icon={<ReadOutlined />}
            onClick={() => void openPageDetail(record.id)}
          >
            查看
          </Button>
          <Popconfirm
            title="删除 Wiki 页面"
            description="删除后不会影响源文档。"
            onConfirm={async () => {
              await deleteWikiPage(record.id, tenantId);
              message.success('Wiki 页面已删除');
              await loadPages();
            }}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Card className="page-card" title="Wiki 页面管理">
        <Row gutter={[16, 16]}>
          <Col xs={24} md={5}><Tag color="blue">租户：{tenantId}</Tag></Col>
          <Col xs={24} md={6}><Input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索标题或正文" onPressEnter={() => void loadPages()} prefix={<SearchOutlined />} /></Col>
          <Col xs={24} md={4}><Input value={knowledgeBase} onChange={(event) => setKnowledgeBase(event.target.value)} placeholder="知识库筛选" list="wiki-kb-options" /></Col>
          <Col xs={24} md={3}>
            <Select
              allowClear
              value={pageStatus}
              onChange={setPageStatus}
              placeholder="状态"
              style={{ width: '100%' }}
              options={[
                { label: 'Ready', value: 'ready' },
                { label: 'Stale', value: 'stale' },
              ]}
            />
          </Col>
          <Col xs={24} md={3}><Button type="primary" block icon={<SearchOutlined />} onClick={() => void loadPages()}>查询</Button></Col>
          <Col xs={24} md={3}><Button block icon={<ReloadOutlined />} onClick={() => void loadPages()}>刷新</Button></Col>
          <Col xs={24} md={2}><Button block icon={<LinkOutlined />} onClick={async () => {
            const result = await rebuildWikiLinks(tenantId, knowledgeBase || undefined);
            message.success(`已重建 ${result.link_count} 条关系`);
            await loadPages();
          }}>关系</Button></Col>
        </Row>
        <datalist id="wiki-kb-options">
          {knowledgeBaseOptions.map((item) => <option key={item as string} value={item as string} />)}
        </datalist>
      </Card>

      <Card className="page-card" title="从文档编译 Wiki">
        <Row gutter={[16, 16]}>
          <Col xs={24} md={6}>
            <InputNumber
              min={1}
              precision={0}
              value={sourceDocumentId}
              onChange={(value) => setSourceDocumentId(value)}
              placeholder="源文档 ID"
              style={{ width: '100%' }}
            />
          </Col>
          <Col xs={24} md={3}>
            <Button
              type="primary"
              block
              icon={<FileSyncOutlined />}
              loading={compiling}
              onClick={async () => {
                if (!sourceDocumentId) {
                  message.warning('请输入源文档 ID');
                  return;
                }
                setCompiling(true);
                try {
                  const page = await compileWikiPage(tenantId, sourceDocumentId);
                  message.success(`已生成 Wiki 页面：${page.title}`);
                  setSourceDocumentId(null);
                  await loadPages();
                } catch (error: any) {
                  message.error(error?.response?.data?.detail || error?.message || '编译 Wiki 页面失败');
                } finally {
                  setCompiling(false);
                }
              }}
            >
              编译
            </Button>
          </Col>
          <Col xs={24} md={9}>
            <Input
              value={bulkDocumentIds}
              onChange={(event) => setBulkDocumentIds(event.target.value)}
              placeholder="批量文档 ID，例如 12, 15, 18"
            />
          </Col>
          <Col xs={24} md={4}>
            <Button
              block
              icon={<FileSyncOutlined />}
              loading={compiling}
              onClick={async () => {
                const ids = parseDocumentIds(bulkDocumentIds);
                if (!ids.length) {
                  message.warning('请输入有效的文档 ID');
                  return;
                }
                setCompiling(true);
                try {
                  const result = await bulkCompileWikiPages(tenantId, ids);
                  if ('success_count' in result) {
                    message.success(`批量编译完成：成功 ${result.success_count}，失败 ${result.failure_count}`);
                  }
                  setBulkDocumentIds('');
                  await loadPages();
                } catch (error: any) {
                  message.error(error?.response?.data?.detail || error?.message || '批量编译 Wiki 页面失败');
                } finally {
                  setCompiling(false);
                }
              }}
            >
              批量编译
            </Button>
          </Col>
          <Col xs={24} md={2}>
            <Button
              block
              icon={<FileSyncOutlined />}
              loading={compiling}
              onClick={async () => {
                const ids = parseDocumentIds(bulkDocumentIds);
                if (!ids.length) {
                  message.warning('请输入有效的文档 ID');
                  return;
                }
                setCompiling(true);
                try {
                  const job = await bulkCompileWikiPages(tenantId, ids, true);
                  if ('status' in job) {
                    setActiveJob(job);
                    message.success(`已提交异步任务 #${job.id}`);
                  }
                  setBulkDocumentIds('');
                } catch (error: any) {
                  message.error(error?.response?.data?.detail || error?.message || '提交异步编译任务失败');
                } finally {
                  setCompiling(false);
                }
              }}
            >
              异步
            </Button>
          </Col>
        </Row>
        {activeJob ? (
          <Alert
            style={{ marginTop: 16 }}
            type={activeJob.status === 'failed' ? 'error' : activeJob.status === 'completed' ? 'success' : 'info'}
            showIcon
            message={`编译任务 #${activeJob.id}：${activeJob.status}`}
            description={`成功 ${activeJob.success_count}，失败 ${activeJob.failure_count}${activeJob.error ? `，错误：${activeJob.error}` : ''}`}
          />
        ) : null}
      </Card>

      <Card className="page-card" title="主题索引">
        <List
          grid={{ gutter: 12, xs: 1, sm: 1, md: 2, lg: 3 }}
          dataSource={topicIndex}
          locale={{ emptyText: '暂无主题索引' }}
          renderItem={(item) => (
            <List.Item>
              <Space direction="vertical" style={{ width: '100%' }}>
                <Space>
                  <Typography.Text strong>{item.knowledge_base}</Typography.Text>
                  <Tag>{item.page_count} 页</Tag>
                </Space>
                {item.pages.slice(0, 3).map((page) => (
                  <Typography.Link key={page.id} onClick={() => void openPageDetail(page.id)}>
                    {page.title}
                  </Typography.Link>
                ))}
              </Space>
            </List.Item>
          )}
        />
      </Card>

      <Card className="page-card" title="Wiki 页面列表">
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={pages}
          scroll={{ x: 1200 }}
        />
      </Card>

      <Drawer
        title={activePage?.title || 'Wiki 页面'}
        open={detailOpen}
        onClose={() => {
          setDetailOpen(false);
          setEditing(false);
          setRevisions([]);
          setLinks(null);
        }}
        width={920}
        extra={activePage ? (
          <Space>
            <Button icon={<EditOutlined />} onClick={() => setEditing((value) => !value)}>{editing ? '取消编辑' : '编辑'}</Button>
            {editing ? (
              <Button
                type="primary"
                icon={<SaveOutlined />}
                loading={saving}
                onClick={async () => {
                  const values = await form.validateFields();
                  setSaving(true);
                  try {
                    const updated = await updateWikiPage(activePage.id, tenantId, {
                      ...values,
                      expected_updated_at: activePage.updated_at,
                    });
                    setActivePage(updated);
                    form.setFieldsValue(updated);
                    setEditing(false);
                    message.success('Wiki 页面已更新');
                    const revisionItems = await fetchWikiPageRevisions(activePage.id, tenantId);
                    setRevisions(revisionItems);
                    await loadPages();
                  } catch (error: any) {
                    const detail = error?.response?.data?.detail;
                    if (error?.response?.status === 409 && detail?.message) {
                      message.warning(detail.message);
                      await openPageDetail(activePage.id);
                    } else {
                      message.error(detail || error?.message || '更新 Wiki 页面失败');
                    }
                  } finally {
                    setSaving(false);
                  }
                }}
              >
                保存
              </Button>
            ) : null}
          </Space>
        ) : null}
      >
        {activePage ? (
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <Space wrap>
              <Tag color="blue">租户：{activePage.tenant_id}</Tag>
              <Tag>知识库：{activePage.knowledge_base || '-'}</Tag>
              <Tag>来源文档：{activePage.source_document_id ? `#${activePage.source_document_id}` : '-'}</Tag>
              <Tag color={activePage.status === 'ready' ? 'green' : activePage.status === 'stale' ? 'orange' : 'default'}>{activePage.status}</Tag>
            </Space>
            {activePage.status === 'stale' ? (
              <Alert
                type="warning"
                showIcon
                message="源文档已变化"
                description="此 Wiki 页面基于旧版本源文档编译，建议重新编译后再作为正式知识资产使用。"
              />
            ) : null}
            {editing ? (
              <Form form={form} layout="vertical">
                <Form.Item name="title" label="页面标题" rules={[{ required: true, message: '请输入页面标题' }]}>
                  <Input />
                </Form.Item>
                <Form.Item name="knowledge_base" label="知识库">
                  <Input />
                </Form.Item>
                <Form.Item name="summary" label="摘要">
                  <Input.TextArea autoSize={{ minRows: 3, maxRows: 6 }} />
                </Form.Item>
                <Form.Item name="content" label="页面正文" rules={[{ required: true, message: '请输入页面正文' }]}>
                  <Input.TextArea autoSize={{ minRows: 12, maxRows: 24 }} />
                </Form.Item>
              </Form>
            ) : (
              <>
                <Typography.Paragraph type="secondary">{activePage.summary || '暂无摘要'}</Typography.Paragraph>
                <Typography.Title level={5}>页面正文</Typography.Title>
                <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{activePage.content}</Typography.Paragraph>
              </>
            )}
            <Typography.Title level={5}>来源 Chunk</Typography.Title>
            <Typography.Text type="secondary">{activePage.source_chunk_ids?.length ? activePage.source_chunk_ids.map((item) => `#${item}`).join(' / ') : '暂无来源 chunk'}</Typography.Text>
            <Typography.Title level={5}>页面关系</Typography.Title>
            <Row gutter={16}>
              <Col span={12}>
                <List
                  bordered
                  header="出链"
                  dataSource={links?.outgoing || []}
                  locale={{ emptyText: '暂无出链' }}
                  renderItem={(item) => (
                    <List.Item>
                      <Space direction="vertical" size={0}>
                        <Typography.Link onClick={() => void openPageDetail(item.target_page_id)}>{item.target_title || `#${item.target_page_id}`}</Typography.Link>
                        <Typography.Text type="secondary">{item.evidence || '-'}</Typography.Text>
                      </Space>
                    </List.Item>
                  )}
                />
              </Col>
              <Col span={12}>
                <List
                  bordered
                  header="反链"
                  dataSource={links?.incoming || []}
                  locale={{ emptyText: '暂无反链' }}
                  renderItem={(item) => (
                    <List.Item>
                      <Space direction="vertical" size={0}>
                        <Typography.Link onClick={() => void openPageDetail(item.source_page_id)}>{item.source_title || `#${item.source_page_id}`}</Typography.Link>
                        <Typography.Text type="secondary">{item.evidence || '-'}</Typography.Text>
                      </Space>
                    </List.Item>
                  )}
                />
              </Col>
            </Row>
            <Typography.Title level={5}>修订历史</Typography.Title>
            <List
              bordered
              dataSource={revisions}
              locale={{ emptyText: '暂无修订记录' }}
              renderItem={(item) => (
                <List.Item>
                  <List.Item.Meta
                    avatar={<HistoryOutlined />}
                    title={<Space><Tag>{item.action}</Tag><Typography.Text>{item.title}</Typography.Text></Space>}
                    description={(
                      <Space direction="vertical" size={0}>
                        <Typography.Text type="secondary">{item.created_at ? dayjs(item.created_at).format('YYYY-MM-DD HH:mm') : '-'}</Typography.Text>
                        <Typography.Text type="secondary">知识库：{item.knowledge_base || '-'}</Typography.Text>
                        {renderRevisionDiff(item)}
                      </Space>
                    )}
                  />
                </List.Item>
              )}
            />
          </Space>
        ) : null}
      </Drawer>
    </Space>
  );
}
