import { useEffect, useMemo, useState } from 'react';
import { Table, Tag, Input, Select, Space, Typography, Card, message } from 'antd';
import { api } from '../api/client';
import type { TapeInfo } from '../types';

const { Title } = Typography;

export default function Tapes() {
  const [tapes, setTapes] = useState<TapeInfo[]>([]);
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const libs = await api.listLibraries();
      if (!libs.success || !libs.data?.length) { message.error(`${libs.code}: ${libs.message}`); setLoading(false); return; }
      const inv = await api.libraryInventory(libs.data[0].changer);
      if (inv.success) setTapes(inv.data?.volumes || []);
      setLoading(false);
    })();
  }, []);

  const data = useMemo(() => tapes.filter((t) => {
    if (filter === 'available' && t.status !== 'Available') return false;
    if (filter === 'loaded' && t.status !== 'Loaded') return false;
    if (filter === 'error' && t.status !== 'Error') return false;
    if (filter === 'write_protect' && !t.write_protect) return false;
    if (q && !(`${t.barcode} ${t.media_type} ${t.generation} ${t.slot ?? ''} ${t.drive ?? ''}`.toLowerCase().includes(q.toLowerCase()))) return false;
    return true;
  }), [tapes, q, filter]);

  return (
    <div>
      <Title level={3}>Tape Inventory</Title>
      <Space style={{ marginBottom: 12 }}>
        <Input.Search placeholder="Search barcode / media / slot / drive" allowClear
          onSearch={setQ} onChange={(e) => !e.target.value && setQ('')} style={{ width: 320 }} />
        <Select value={filter} onChange={setFilter} style={{ width: 180 }} options={[
          { value: 'all', label: 'All' },
          { value: 'available', label: 'Available' },
          { value: 'loaded', label: 'Loaded' },
          { value: 'error', label: 'Error' },
          { value: 'write_protect', label: 'Write Protected' },
        ]} />
      </Space>
      <Table<TapeInfo> rowKey="barcode" loading={loading} dataSource={data} size="small"
        pagination={{ pageSize: 20 }}
        columns={[
          { title: 'Barcode', dataIndex: 'barcode', render: (v) => <b>{v}</b> },
          { title: 'Media', dataIndex: 'media_type' },
          { title: 'Generation', dataIndex: 'generation' },
          { title: 'Slot', dataIndex: 'slot', render: (v) => v ? `S${String(v).padStart(2, '0')}` : '-' },
          { title: 'Drive', dataIndex: 'drive', render: (v) => v ? `/dev/${v}` : '-' },
          { title: 'Status', dataIndex: 'status', render: (v) => (
              <Tag color={v === 'Available' ? 'green' : v === 'Loaded' ? 'blue' : 'red'}>{v}</Tag>) },
          { title: 'Write Protect', dataIndex: 'write_protect', render: (v) => v ? 'Yes' : 'No' },
          { title: 'Health', dataIndex: 'health', render: (v) => (
              <Tag color={v === 'Good' ? 'green' : v === 'Warning' ? 'orange' : 'red'}>{v}</Tag>) },
          { title: 'Mounts', dataIndex: 'mount_count', align: 'right' },
          { title: 'Errors', dataIndex: 'error_count', align: 'right' },
        ]} />
      <Card size="small" style={{ marginTop: 12 }}>
        <p style={{ color: '#999', fontSize: 12 }}>
          Tape Detail：点击 Dashboard → Library Detail → Slots 查看单盘介质详情；统计数据（读写字节/挂载次数）由 LOG SENSE 页 0x11/0x17 提供（parsed.volume_stats）。
        </p>
      </Card>
    </div>
  );
}
