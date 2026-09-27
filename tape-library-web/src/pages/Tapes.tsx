import { useEffect, useMemo, useState } from 'react';
import { Table, Tag, Input, Select, Space, Typography, Card, Button, message, Progress } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { api } from '../api/client';

const { Title } = Typography;

interface TapeRow {
  barcode: string;
  sn?: string | null;
  media_type?: string | null;
  generation?: string | null;
  slot: number | null;
  drive: string | null;
  changer?: string | null;
  dte?: number | null;
  source_slot?: number | null;
  status: 'Available' | 'Loaded' | 'Error' | 'Unknown';
  media_state?: string;
  registered?: boolean;
  write_protect?: boolean;
  health?: string;
  mount_count?: number | null;
  capacity_bytes?: number | null;
  used_bytes?: number | null;
  file_number?: number | null;
}

const gb = (b?: number | null) => (b == null ? '-' : `${(b / 1024 ** 3).toFixed(1)} GB`);

export default function Tapes() {
  const [tapes, setTapes] = useState<TapeRow[]>([]);
  const [slots, setSlots] = useState<{ total: number; occupied: number }>({ total: 0, occupied: 0 });
  const [ledgerErr, setLedgerErr] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);

  const load = async () => {
    const r = await api.listTapes();
    if (r.success) {
      const d: any = r.data;
      setTapes((Array.isArray(d) ? d : d?.tapes || []) as TapeRow[]);
      const extra: any = Array.isArray(d) ? r : d;
      setSlots(extra?.slots ?? { total: 0, occupied: 0 });
      setLedgerErr(extra?.ledger?.error ?? null);
    } else {
      message.error(`${r.code}: ${r.message}`);
    }
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const registered = (t: TapeRow) =>
    !!t.registered || (t.media_state != null && t.media_state !== 'unregistered');

  const data = useMemo(() => tapes.filter((t) => {
    if (filter === 'available' && t.status !== 'Available') return false;
    if (filter === 'loaded' && t.status !== 'Loaded') return false;
    if (filter === 'registered' && !registered(t)) return false;
    if (filter === 'unregistered' && registered(t)) return false;
    if (q && !(`${t.barcode} ${t.sn ?? ''} ${t.media_type ?? ''} ${t.slot ?? ''} ${t.drive ?? ''} ${t.changer ?? ''}`.toLowerCase().includes(q.toLowerCase()))) return false;
    return true;
  }), [tapes, q, filter]);

  return (
    <div>
      <Title level={3}>Tape Inventory</Title>
      <Space style={{ marginBottom: 12 }} wrap>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>Refresh</Button>
        <Input.Search placeholder="Search barcode / SN / slot / drive" allowClear
          onSearch={setQ} onChange={(e) => !e.target.value && setQ('')} style={{ width: 320 }} />
        <Select value={filter} onChange={setFilter} style={{ width: 180 }} options={[
          { value: 'all', label: 'All' },
          { value: 'loaded', label: 'In Drive' },
          { value: 'available', label: 'In Slot' },
          { value: 'registered', label: 'Registered (ledger)' },
          { value: 'unregistered', label: 'Unregistered' },
        ]} />
        <span style={{ color: '#999', fontSize: 12 }}>
          槽位 {slots.occupied || '-'}/{slots.total || '-'}
          {ledgerErr ? ` · 台账未合并(${ledgerErr.slice(0, 30)})` : ' · 台账已合并'}
        </span>
      </Space>
      <Table<TapeRow> rowKey="barcode" loading={loading} dataSource={data} size="small"
        pagination={{ pageSize: 20 }} scroll={{ x: 1100 }}
        columns={[
          { title: '磁带号 (Barcode)', dataIndex: 'barcode', width: 150, fixed: 'left' as const,
            render: (v) => <b>{v}</b> },
          { title: '介质 SN (MAM)', dataIndex: 'sn', width: 140,
            render: (v: string | null) => v ? <code>{v}</code> : <span style={{ color: '#999' }} title="仅装载在带机时可通过 READ ATTRIBUTE 读取">未装载·不可读</span> },
          { title: '介质', width: 90, render: (_, t) => `${t.media_type || 'LTO'}${t.generation ? '-' + t.generation : ''}` },
          { title: '位置', width: 210, render: (_, t) => (
              <span style={{ fontSize: 12 }}>
                {t.status === 'Loaded'
                  ? <>🖥 带机 <code>/dev/{t.drive}</code>{t.dte != null && <span style={{ color: '#999' }}> (DTE{t.dte})</span>}</>
                  : t.slot != null ? <>📦 槽位 <b>S{String(t.slot).padStart(3, '0')}</b></> : '-'}
                <br />
                <span style={{ color: '#999' }}>{t.changer ? `带库 ${t.changer}` : ''}{t.source_slot != null && t.status === 'Loaded' ? ` ← 来源槽 ${t.source_slot}` : ''}</span>
              </span>) },
          { title: '状态', width: 100, render: (_, t) => (
              <Tag color={t.status === 'Loaded' ? 'blue' : t.status === 'Available' ? 'green' : 'red'}>{t.status}</Tag>) },
          { title: '台账', dataIndex: 'media_state', width: 120, render: (v: string, t) => (
              <Tag color={v === 'appendable' ? 'green' : v === 'full' ? 'orange' : v === 'faulted' ? 'red' : 'default'}>
                {registered(t) ? (v || 'registered') : 'unregistered'}</Tag>) },
          { title: '已用 / 容量', width: 190, render: (_, t) => t.capacity_bytes
              ? <Progress percent={Math.min(100, Math.round((t.used_bytes || 0) / t.capacity_bytes * 100))} size="small"
                  format={() => `${gb(t.used_bytes)} / ${gb(t.capacity_bytes)}`} />
              : <span style={{ color: '#999' }}>-</span> },
          { title: '挂载次数', dataIndex: 'mount_count', width: 90, align: 'right' as const,
            render: (v: number | null) => v ?? '-' },
        ]} />
      <Card size="small" style={{ marginTop: 12 }}>
        <p style={{ color: '#999', fontSize: 12 }}>
          数据来源 GET /api/v1/tapes/list：带号=mtx 槽位条码；介质 SN=装载态 READ ATTRIBUTE(MAM) 实时读取，未装载时不可读；
          位置=带库槽位/带机 DTE；容量与挂载次数来自归档网关台账 tape_media（未注册带仅为物理可见）。
        </p>
      </Card>
    </div>
  );
}
