import { Layout, Menu, Tag } from 'antd';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { api } from './api/client';

const { Sider, Header, Content } = Layout;

const MENU = [
  { key: '/', label: 'Dashboard' },
  { key: 'grp-lib', label: 'Libraries', children: [
    { key: '/libraries', label: 'Library Overview' },
  ]},
  { key: 'grp-drive', label: 'Drives', children: [
    { key: '/drives', label: 'Drive Status' },
  ]},
  { key: '/tapes', label: 'Tapes' },
  { key: 'grp-test', label: 'Test Center', children: [
    { key: '/tests', label: 'Mount / Test' },
  ]},
  { key: 'grp-ops', label: 'Operations', children: [
    { key: '/operations', label: 'Operation History' },
  ]},
  { key: '/audit', label: 'Audit' },
    { key: '/api-logs', label: 'API Logs' },
];

export default function App() {
  const nav = useNavigate();
  const loc = useLocation();
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ background: '#001529', display: 'flex', alignItems: 'center', gap: 16 }}>
        <span style={{ color: '#fff', fontSize: 16, fontWeight: 600 }}>Tape Library Management</span>
        <Tag color={api.mode === 'mock' ? 'purple' : 'green'}>{api.mode.toUpperCase()} MODE</Tag>
      </Header>
      <Layout>
        <Sider width={210} theme="dark">
          <Menu theme="dark" mode="inline" selectedKeys={[loc.pathname]}
            defaultOpenKeys={['grp-lib', 'grp-drive', 'grp-test', 'grp-ops']}
            onClick={(e) => e.key.startsWith('/') && nav(e.key)}
            items={MENU} />
        </Sider>
        <Content style={{ padding: 20, overflow: 'auto' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
