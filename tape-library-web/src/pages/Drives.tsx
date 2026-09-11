import { useEffect, useState } from 'react';
import { Table, Tag, Button, Space, Typography, message } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { DriveInfo } from '../types';

const { Title } = Typography;

function driveStatusTag(s: string) {
  const c = s === 'READY' || s === 'LOADED' ? 'green' : s === 'ERROR' ? 'red' : s === 'OFFLINE' ? 'default' : 'blue';
  return <Tag color={c}>{s}</Tag>;
}

export default function Drives() {
  const [drives, setDrives] = useState<DriveInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const nav = useNavigate();

  const load = async () => {
    setLoading(true);
    const r = await api.listDrives();
    if (r.success) setDrives(r.data || []);
    else message.error(`${r.code}: ${r.message}`);
    setLoading(false);
  };
  useEffect(() => { load(); const id = setInterval(load, 5000); return () => clearInterval(id); }, []);

  return (
    <div>
      <Title level={3}>Tape Drives</Title>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
        <span style={{ color: '#999', fontSize: 12 }}>auto refresh 5s</span>
      </Space>
      <Table<DriveInfo> rowKey="nst" loading={loading} dataSource={drives} pagination={false}
        columns={[
          { title: 'Drive', render: (_, d) => `Drive-${String(d.index + 1).padStart(2, '0')}` },
          { title: 'Vendor', dataIndex: 'vendor' },
          { title: 'Model', dataIndex: 'model' },
          { title: 'Serial', dataIndex: 'serial' },
          { title: 'Status', dataIndex: 'status', render: driveStatusTag },
          { title: 'Tape', dataIndex: 'loaded_tape', render: (v) => v ? <Tag color="blue">📼 {v}</Tag> : '-' },
          { title: '/dev/nstX', dataIndex: 'nst', render: (v) => `/dev/${v}` },
          { title: 'TapeAlert', render: (_, d) => d.tapealert.all_clear
              ? <Tag color="green">All Clear</Tag>
              : <Tag color="red">{d.tapealert.triggered_count} alerts</Tag> },
          { title: 'Action', render: (_, d) => <Button type="link" size="small" onClick={() => nav(`/drives/${d.nst}`)}>View</Button> },
        ]} />
    </div>
  );
}
