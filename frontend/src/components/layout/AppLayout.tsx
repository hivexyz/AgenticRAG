import { FileTextOutlined, MessageOutlined, ReadOutlined, WarningOutlined } from '@ant-design/icons';
import { Button, Input, Layout, Menu, Space, Typography, message } from 'antd';
import { Link, useLocation } from 'react-router-dom';
import { useEffect, useState, type PropsWithChildren } from 'react';
import { AuthContext, defaultAuthInfo } from '../../app/auth-context';
import { fetchAuthMe, type AuthInfo } from '../../services/auth';
import { getStoredApiKey, setStoredApiKey } from '../../services/http';

const { Header, Sider, Content } = Layout;

const items = [
  { key: '/documents', icon: <FileTextOutlined />, label: <Link to="/documents">文档管理</Link> },
  { key: '/wiki', icon: <ReadOutlined />, label: <Link to="/wiki">Wiki 页面</Link> },
  { key: '/workbench', icon: <MessageOutlined />, label: <Link to="/workbench">问答工作台</Link> },
  { key: '/feedback', icon: <WarningOutlined />, label: <Link to="/feedback">反馈闭环</Link> },
];

export function AppLayout({ children }: PropsWithChildren) {
  const location = useLocation();
  const [apiKey, setApiKey] = useState('');
  const [auth, setAuth] = useState<AuthInfo>(defaultAuthInfo);

  const reloadAuth = async () => {
    try {
      const nextAuth = await fetchAuthMe();
      setAuth(nextAuth);
    } catch {
      setAuth(defaultAuthInfo);
    }
  };

  useEffect(() => {
    setApiKey(getStoredApiKey());
    void reloadAuth();
  }, []);

  return (
    <AuthContext.Provider value={{ auth, tenantId: auth.tenant_id, reloadAuth }}>
      <Layout style={{ minHeight: '100vh' }}>
        <Sider theme="light" width={240}>
          <div style={{ padding: 20 }}>
            <Typography.Title level={4} style={{ margin: 0 }}>AgenticRAG Console</Typography.Title>
            <Typography.Text type="secondary">知识库与问答工作台</Typography.Text>
          </div>
          <Menu mode="inline" selectedKeys={[location.pathname]} items={items} />
        </Sider>
        <Layout>
          <Header style={{ background: '#fff', borderBottom: '1px solid #f0f0f0', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
            <Space>
              <Typography.Text strong>生产级知识库管理系统</Typography.Text>
              <Typography.Text type="secondary">租户：{auth.tenant_id}</Typography.Text>
              <Typography.Text type="secondary">{auth.authenticated ? `${auth.auth_method}:${auth.api_key_name}` : 'anonymous'}</Typography.Text>
            </Space>
            <Space.Compact style={{ width: 360 }}>
              <Input.Password value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="X-API-Key" />
              <Button onClick={async () => {
                setStoredApiKey(apiKey);
                await reloadAuth();
                message.success(apiKey.trim() ? 'API Key 已保存' : 'API Key 已清除');
              }}>保存</Button>
            </Space.Compact>
          </Header>
          <Content style={{ padding: 24 }}>{children}</Content>
        </Layout>
      </Layout>
    </AuthContext.Provider>
  );
}
