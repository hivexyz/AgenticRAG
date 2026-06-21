import { FileTextOutlined, MessageOutlined } from '@ant-design/icons';
import { Layout, Menu, Typography } from 'antd';
import { Link, useLocation } from 'react-router-dom';
import type { PropsWithChildren } from 'react';

const { Header, Sider, Content } = Layout;

const items = [
  { key: '/documents', icon: <FileTextOutlined />, label: <Link to="/documents">文档管理</Link> },
  { key: '/workbench', icon: <MessageOutlined />, label: <Link to="/workbench">问答工作台</Link> },
];

export function AppLayout({ children }: PropsWithChildren) {
  const location = useLocation();

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider theme="light" width={240}>
        <div style={{ padding: 20 }}>
          <Typography.Title level={4} style={{ margin: 0 }}>AgenticRAG Console</Typography.Title>
          <Typography.Text type="secondary">知识库与问答工作台</Typography.Text>
        </div>
        <Menu mode="inline" selectedKeys={[location.pathname]} items={items} />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', borderBottom: '1px solid #f0f0f0', padding: '0 24px' }}>
          <Typography.Text strong>生产级知识库管理系统</Typography.Text>
        </Header>
        <Content style={{ padding: 24 }}>{children}</Content>
      </Layout>
    </Layout>
  );
}
