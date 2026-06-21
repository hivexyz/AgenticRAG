import { Button, Card, Col, Input, Row, Select, Space, message } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { DocumentTable } from '../../components/documents/DocumentTable';
import { DocumentUploadPanel } from '../../components/documents/DocumentUploadPanel';
import { bulkDeleteDocuments, fetchDocumentChunks, fetchDocumentPresets, fetchDocuments, fetchFragment, reindexDocument } from '../../services/documents';
import type { DocumentItem, PresetItem } from '../../types';

const DEFAULT_TENANT = 'default';

export function DocumentManagementPage() {
  const [tenantId, setTenantId] = useState(DEFAULT_TENANT);
  const [keyword, setKeyword] = useState('');
  const [knowledgeBase, setKnowledgeBase] = useState<string | undefined>();
  const [fileType, setFileType] = useState<string | undefined>();
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [presets, setPresets] = useState<PresetItem[]>([]);
  const [vectorLabel, setVectorLabel] = useState('生成并存储向量索引');
  const [loading, setLoading] = useState(false);

  const knowledgeBaseOptions = useMemo(() => {
    const values = Array.from(new Set(documents.map((item) => item.knowledge_base).filter(Boolean)));
    return values.map((value) => ({ label: value as string, value: value as string }));
  }, [documents]);

  const fileTypeOptions = useMemo(() => {
    const values = Array.from(new Set(documents.map((item) => item.file_type).filter(Boolean)));
    return values.map((value) => ({ label: value as string, value: value as string }));
  }, [documents]);

  const loadDocuments = async () => {
    setLoading(true);
    try {
      const data = await fetchDocuments({ tenant_id: tenantId, q: keyword || undefined, knowledge_base: knowledgeBase, file_type: fileType });
      setDocuments(data);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '加载文档列表失败');
      setDocuments([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocumentPresets()
      .then((data) => {
        setPresets(data.presets);
        setVectorLabel(data.vector_storage_label);
      })
      .catch((error: any) => {
        message.error(error?.response?.data?.detail || error?.message || '加载切分预设失败');
      });
  }, []);

  useEffect(() => {
    void loadDocuments();
  }, [tenantId, knowledgeBase, fileType]);

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Card className="page-card" title="知识库文档管理">
        <Row gutter={16}>
          <Col span={6}><Input value={tenantId} onChange={(e) => setTenantId(e.target.value)} placeholder="tenant_id" /></Col>
          <Col span={6}><Input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索文档名" onPressEnter={() => void loadDocuments()} /></Col>
          <Col span={5}><Select allowClear value={knowledgeBase} onChange={setKnowledgeBase} placeholder="知识库筛选" options={knowledgeBaseOptions} style={{ width: '100%' }} /></Col>
          <Col span={5}><Select allowClear value={fileType} onChange={setFileType} placeholder="文件类型筛选" options={fileTypeOptions} style={{ width: '100%' }} /></Col>
          <Col span={2}><Button type="primary" block onClick={() => void loadDocuments()}>查询</Button></Col>
        </Row>
      </Card>

      <DocumentUploadPanel tenantId={tenantId} presets={presets} vectorStorageLabel={vectorLabel} onCreated={loadDocuments} />

      <Card className="page-card" title="文档列表">
        <DocumentTable
          documents={documents}
          loading={loading}
          onReindex={async (item) => {
            await reindexDocument(item.id, tenantId);
            message.success('已触发重新向量化');
            await loadDocuments();
          }}
          onBulkDelete={async (ids) => {
            await bulkDeleteDocuments(tenantId, ids);
            message.success('批量删除请求已受理');
          }}
          onOpenDocumentDetail={async (item) => {
            const chunks = await fetchDocumentChunks(item.id, tenantId);
            const firstChunk = chunks[0];
            const fragment = firstChunk ? await fetchFragment(item.id, firstChunk.chunk_id, tenantId) : null;
            return { chunks, fragment };
          }}
          onOpenChunkFragment={(documentId, chunkId) => fetchFragment(documentId, chunkId, tenantId)}
        />
      </Card>
    </Space>
  );
}
