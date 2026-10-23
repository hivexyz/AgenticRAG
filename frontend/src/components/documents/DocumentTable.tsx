import { DeleteOutlined, EyeOutlined, FileSyncOutlined, ReloadOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { Button, Drawer, List, Space, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useMemo, useState } from 'react';
import dayjs from 'dayjs';
import type { DocumentChunkItem, DocumentFragment, DocumentItem } from '../../types';

interface DetailPayload {
  chunks: DocumentChunkItem[];
  fragment?: DocumentFragment | null;
}

interface Props {
  documents: DocumentItem[];
  loading: boolean;
  onReindex: (item: DocumentItem) => Promise<void> | void;
  onCompileWiki: (item: DocumentItem) => Promise<void> | void;
  onBulkDelete: (ids: number[]) => Promise<void> | void;
  onOpenDocumentDetail: (item: DocumentItem) => Promise<DetailPayload>;
  onOpenChunkFragment: (documentId: number, chunkId: number) => Promise<DocumentFragment>;
}

export function DocumentTable({ documents, loading, onReindex, onCompileWiki, onBulkDelete, onOpenDocumentDetail, onOpenChunkFragment }: Props) {
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [detailOpen, setDetailOpen] = useState(false);
  const [activeDocument, setActiveDocument] = useState<DocumentItem | null>(null);
  const [chunks, setChunks] = useState<DocumentChunkItem[]>([]);
  const [fragment, setFragment] = useState<DocumentFragment | null>(null);

  const columns: ColumnsType<DocumentItem> = useMemo(() => [
    { title: '文档名', dataIndex: 'title', key: 'title', width: 220 },
    { title: '知识库', dataIndex: 'knowledge_base', key: 'knowledge_base', width: 120, render: (value) => value || '-' },
    { title: '类型', dataIndex: 'file_type', key: 'file_type', width: 100, render: (value) => value || '-' },
    { title: '状态', dataIndex: 'status_display', key: 'status_display', width: 120, render: (value) => <Tag color={value === '入库成功' ? 'green' : value === '入库失败' ? 'red' : 'blue'}>{value || '-'}</Tag> },
    { title: '内容 Hash', dataIndex: 'content_hash', key: 'content_hash', width: 130, render: (value) => value ? <Typography.Text code>{String(value).slice(0, 10)}</Typography.Text> : '-' },
    { title: '块数', dataIndex: 'chunk_count', key: 'chunk_count', width: 90 },
    { title: '上传人', dataIndex: 'uploaded_by', key: 'uploaded_by', width: 120, render: (value) => value || '-' },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 180, render: (value) => value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '-' },
    { title: '向量索引', dataIndex: 'vector_status_display', key: 'vector_status_display', width: 160, render: (value) => <Tag>{value || '-'}</Tag> },
    {
      title: '操作', key: 'actions', fixed: 'right', width: 260,
      render: (_, record) => (
        <Space>
          <Button size="small" icon={<UnorderedListOutlined />} onClick={async () => {
            const detail = await onOpenDocumentDetail(record);
            setActiveDocument(record);
            setChunks(detail.chunks);
            setFragment(detail.fragment || null);
            setDetailOpen(true);
          }}>文档详情</Button>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => onReindex(record)}>重新向量化</Button>
          <Button size="small" icon={<FileSyncOutlined />} onClick={() => onCompileWiki(record)}>生成 Wiki</Button>
        </Space>
      ),
    },
  ], [onCompileWiki, onOpenDocumentDetail, onReindex]);

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button danger icon={<DeleteOutlined />} disabled={!selectedRowKeys.length} onClick={() => onBulkDelete(selectedRowKeys as number[])}>批量删除</Button>
        <Typography.Text type="secondary">已选择 {selectedRowKeys.length} 项</Typography.Text>
      </Space>
      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={documents}
        scroll={{ x: 1400 }}
        rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }}
        expandable={{
          expandedRowRender: (record) => (
            <Space direction="vertical" size="small">
              <Typography.Text>失败原因：{record.failure_reason || '无'}</Typography.Text>
              <Typography.Text>内容 Hash：{record.content_hash || '无'}</Typography.Text>
              <Typography.Text>可重试动作：{record.retryable_actions?.join(' / ') || '无'}</Typography.Text>
              <Typography.Text>切分设置：{JSON.stringify(record.advanced_split_settings || {}, null, 2)}</Typography.Text>
            </Space>
          ),
        }}
      />
      <Drawer title={activeDocument?.title || '文档详情'} open={detailOpen} onClose={() => setDetailOpen(false)} width={920}>
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Typography.Text type="secondary">知识库：{activeDocument?.knowledge_base || '-'}</Typography.Text>
            <Typography.Text type="secondary">状态：{activeDocument?.status_display || '-'}</Typography.Text>
            <Typography.Text type="secondary">向量索引：{activeDocument?.vector_status_display || '-'}</Typography.Text>
          </Space>

          <Typography.Title level={5}>Chunk 列表</Typography.Title>
          <List
            bordered
            dataSource={chunks}
            renderItem={(item) => (
              <List.Item actions={[
                <Button key="open" type="link" icon={<EyeOutlined />} onClick={async () => {
                  if (!activeDocument) return;
                  const nextFragment = await onOpenChunkFragment(activeDocument.id, item.chunk_id);
                  setFragment(nextFragment);
                }}>查看原文</Button>,
              ]}>
                <List.Item.Meta
                  title={`Chunk #${item.chunk_index} ｜ 页码 ${item.page || '-'} ｜ 段落 ${item.paragraph || '-'}`}
                  description={<>
                    <Typography.Text type="secondary">{item.section_title || '未命名章节'}</Typography.Text>
                    <Typography.Paragraph style={{ marginTop: 8 }}>{item.snippet}</Typography.Paragraph>
                  </>}
                />
              </List.Item>
            )}
          />

          <Typography.Title level={5}>Fragment Drawer</Typography.Title>
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
          ) : <Typography.Text type="secondary">选择一个 chunk 查看原文片段</Typography.Text>}
        </Space>
      </Drawer>
    </>
  );
}
