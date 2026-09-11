import { useEffect, useState } from 'react';
import { Table, Tag, Button, Space, Typography, message } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { LibraryInfo } from '../types';

const { Title } = Typography;

function statusTag(s: string) {
  const c = s === 'Healthy' ? 'green' : s === 'Warning' ? 'orange' : s === 'Critical' ? 'red' : 'default';
  return <Tag color={c}>{s}</Tag>;
}

export default function Libraries() {
  const [libs, setLibs] = useState<LibraryInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const nav = useNavigate();

  const load = async () => {
    setLoading(true); setErr('');
    const r = await api.listLibraries();
    if (r.success) setLibs(r.data || []);
    else { setErr(r.message); message.error(`Failed to list libraries: ${r.code}`); }
    setLoading(false);
  };
  useEffect(() => { load(); const id = setInterval(load, 10000); return () => clearInterval(id); }, []);

  return (
    <div>
      <Title level={3}>Libraries</Title>
      {err && <p style={{ color: 'red' }}>Failed to connect Tape API: {err} <Button onClick={load}>Retry</Button></p>}
      <Space style={{ marginBottom: 12 }}><Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
        <span style={{ color: '#999', fontSize: 12 }}>auto refresh 10s</span></Space>
      <Table<LibraryInfo> rowKey="changer" loading={loading} dataSource={libs}
        locale={{ emptyText: 'No Tape Libraries Found' }} pagination={false}
        columns={[
          { title: 'Library', dataIndex: 'changer', render: (v) => `/dev/${v}` },
          { title: 'Vendor', dataIndex: 'vendor' },
          { title: 'Model', dataIndex: 'model' },
          { title: 'Serial', dataIndex: 'serial' },
          { title: 'Status', dataIndex: 'status', render: statusTag },
          { title: 'Firmware', dataIndex: 'firmware' },
          { title: 'Drives', dataIndex: 'drive_count', align: 'right' },
          { title: 'Slots', dataIndex: 'slot_count', align: 'right',
            render: (_, r) => `${r.occupied_slots}/${r.slot_count}` },
          { title: 'Tapes', dataIndex: 'tape_count', align: 'right' },
          { title: 'Last Update', dataIndex: 'last_update' },
          { title: 'Action', render: (_, r) => (
            <Space>
              <Button type="link" size="small" onClick={() => nav(`/libraries/${r.changer}`)}>View</Button>
              <a onClick={load}>Inventory</a>
            </Space>) },
        ]} />
    </div>
  );
}
