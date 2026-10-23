import { InboxOutlined } from '@ant-design/icons';
import { Button, Card, Checkbox, Collapse, Form, Input, InputNumber, Select, Space, Typography, Upload, message } from 'antd';
import type { UploadProps } from 'antd';
import { useMemo, useState } from 'react';
import type { PresetItem } from '../../types';
import { createTextDocument, uploadDocumentFile } from '../../services/documents';

interface Props {
  tenantId: string;
  presets: PresetItem[];
  vectorStorageLabel: string;
  onCreated: () => Promise<void> | void;
}

export function DocumentUploadPanel({ tenantId, presets, vectorStorageLabel, onCreated }: Props) {
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();
  const presetOptions = useMemo(() => presets.map((item) => ({ label: item.label, value: item.key })), [presets]);

  const handleTextSubmit = async (values: Record<string, unknown>) => {
    setLoading(true);
    try {
      await createTextDocument({ tenant_id: tenantId, ...values });
      message.success('文档已提交入库');
      form.resetFields();
      await onCreated();
    } finally {
      setLoading(false);
    }
  };

  const uploadProps: UploadProps = {
    maxCount: 1,
    accept: '.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.md,.markdown',
    beforeUpload: () => false,
  };

  const handleFileUpload = async () => {
    const values = await form.validateFields();
    const fileList = values.file?.fileList;
    if (!fileList?.length) {
      message.warning('请先选择文件');
      return;
    }
    const formData = new FormData();
    formData.append('file', fileList[0].originFileObj);
    formData.append('tenant_id', tenantId);
    formData.append('title', values.title || '');
    formData.append('author', values.author || '');
    formData.append('knowledge_base', values.knowledge_base || '');
    formData.append('split_preset', values.split_preset || 'smart');
    formData.append('store_vectors', String(Boolean(values.store_vectors)));
    if (values.split_method) formData.append('split_method', values.split_method);
    if (values.chunk_size) formData.append('chunk_size', String(values.chunk_size));
    if (values.chunk_overlap !== undefined && values.chunk_overlap !== null) formData.append('chunk_overlap', String(values.chunk_overlap));

    setLoading(true);
    try {
      await uploadDocumentFile(formData);
      message.success('文件已上传，正在处理');
      form.resetFields(['file', 'title', 'author']);
      await onCreated();
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="page-card" title="文档入库">
      <Form form={form} layout="vertical" initialValues={{ split_preset: 'smart', store_vectors: true }} onFinish={handleTextSubmit}>
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <Space align="start" style={{ width: '100%' }} size="large">
            <Form.Item label="知识库" name="knowledge_base" style={{ flex: 1 }}>
              <Input placeholder="如：制度库 / FAQ / 产品文档" />
            </Form.Item>
            <Form.Item label="作者/上传人" name="author" style={{ flex: 1 }}>
              <Input placeholder="请输入上传人" />
            </Form.Item>
          </Space>

          <Space align="start" style={{ width: '100%' }} size="large">
            <Form.Item label="文档标题" name="title" style={{ flex: 1 }}>
              <Input placeholder="输入文档标题" />
            </Form.Item>
            <Form.Item label="切分预设" name="split_preset" style={{ width: 260 }}>
              <Select options={presetOptions} />
            </Form.Item>
          </Space>

          <Form.Item name="file" label="上传文件">
            <Upload.Dragger {...uploadProps}>
              <p><InboxOutlined style={{ fontSize: 28 }} /></p>
              <p>拖拽文件到这里，或点击上传</p>
              <Typography.Text type="secondary">默认使用智能切分，高级设置可在下方展开</Typography.Text>
            </Upload.Dragger>
          </Form.Item>

          <Form.Item label="纯文本内容" name="content">
            <Input.TextArea rows={6} placeholder="没有文件时可直接粘贴文本，提交为知识文档" />
          </Form.Item>

          <Collapse items={[{
            key: 'advanced',
            label: '高级设置',
            children: (
              <Space align="start" style={{ width: '100%' }} size="large">
                <Form.Item label="切分方法" name="split_method" style={{ width: 220 }}>
                  <Select options={[
                    { label: '语义切分', value: 'semantic' },
                    { label: '段落切分', value: 'paragraph' },
                    { label: '字符切分', value: 'character' },
                    { label: '递归切分', value: 'recursive' },
                  ]} allowClear />
                </Form.Item>
                <Form.Item label="Chunk Size" name="chunk_size">
                  <InputNumber min={100} max={4000} style={{ width: 140 }} />
                </Form.Item>
                <Form.Item label="Chunk Overlap" name="chunk_overlap">
                  <InputNumber min={0} max={1000} style={{ width: 140 }} />
                </Form.Item>
              </Space>
            ),
          }]} />

          <Form.Item name="store_vectors" valuePropName="checked">
            <Checkbox>{vectorStorageLabel}</Checkbox>
          </Form.Item>

          <Space>
            <Button type="primary" htmlType="submit" loading={loading}>提交纯文本入库</Button>
            <Button onClick={handleFileUpload} loading={loading}>上传文件入库</Button>
          </Space>
        </Space>
      </Form>
    </Card>
  );
}
