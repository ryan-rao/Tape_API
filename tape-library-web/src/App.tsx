import { useState } from 'react';
import { Button, Drawer, Grid, Layout, Menu, Tag } from 'antd';
import { MenuOutlined } from '@ant-design/icons';
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
    { key: '/tests/gateway', label: 'Gateway Playground' },
    { key: '/tests/api', label: 'API Playground' },
    { key: '/tests/cli', label: 'CLI Playground' },
  ]},
  { key: 'grp-archive', label: 'Archive', children: [
    { key: '/archive', label: 'Archive Overview' },
    { key: '/cache', label: 'Cache Management' },
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
  // md=768 以上走桌面侧边栏；以下（手机/小平板）走抽屉导航
  const screens = Grid.useBreakpoint();
  const isMobile = screens.md === false;
  const [drawerOpen, setDrawerOpen] = useState(false);

  const menu = (
    <Menu theme="dark" mode="inline" selectedKeys={[loc.pathname]}
      defaultOpenKeys={['grp-lib', 'grp-drive', 'grp-test', 'grp-ops', 'grp-archive']}
      onClick={(e) => {
        if (e.key.startsWith('/')) nav(e.key);
        setDrawerOpen(false);
      }}
      items={MENU} />
  );

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ background: '#001529', display: 'flex', alignItems: 'center',
        gap: 12, padding: isMobile ? '0 12px' : '0 25px' }}>
        {isMobile && (
          <Button type="text" aria-label="menu"
            icon={<MenuOutlined style={{ color: '#fff', fontSize: 18 }} />}
            onClick={() => setDrawerOpen(true)} />
        )}
        <span style={{ color: '#fff', fontSize: isMobile ? 15 : 16, fontWeight: 600,
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          flex: 1, minWidth: 0 }}>
          {isMobile ? 'Tape Library' : 'Tape Library Management'}
        </span>
        <Tag color={api.mode === 'mock' ? 'purple' : 'green'}
          style={{ marginInlineEnd: 0, flexShrink: 0 }}>
          {api.mode.toUpperCase()}
        </Tag>
      </Header>
      <Layout>
        {!isMobile && <Sider width={210} theme="dark">{menu}</Sider>}
        <Content style={{ padding: isMobile ? 10 : 20, overflow: 'auto' }}>
          <Outlet />
        </Content>
      </Layout>
      <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} placement="left"
        width={240}
        title={<span style={{ color: '#fff' }}>Tape Library</span>}
        styles={{ header: { background: '#001529', borderBottom: 'none' }, body: { padding: 0 } }}>
        {menu}
      </Drawer>
    </Layout>
  );
}
