import { useEffect, useState } from 'react';
import { Table, Tag, Input, Space, Typography, message } from 'antd';
import { api } from '../api/client';
import type { OperationRecord } from '../types';

const { Title } = Typography;

function riskTag(risk: string) {
  const c = risk === 'LEVEL_1' ? 'green' : risk === 'LEVEL_2' ? 'orange' : 'red';
  return <Tag color={c}>{risk}</Tag>;
}

export default function Operations() {
  const [ops, setOps] = useState<OperationRecord[]>([]);
  const [q, setQ] = useState('');

  useEffect(() => {
    (async () => {
      const r = await api.operations();
      if (r.success) setOps(r.data || []);
      else message.error(`${r.code}: ${r.message}`);
    })();
    const id = setInterval(async () => {
      const r = await api.operations();
      if (r.success) setOps(r.data || []);
    }, 10000);
    return () => clearInterval(id);
  }, []);

  const data = q ? ops.filter((o) =>
    `${o.time} ${o.user} ${o.library} ${o.tape} ${o.drive} ${o.operation} ${o.request_id}`.toLowerCase().includes(q.toLowerCase())
  ) : ops;

  return (
    <div>
      <Title level={3}>Operation History</Title>
      <Space style={{ marginBottom: 12 }}>
        <Input.Search placeholder="Search tape / drive / operation / request_id" allowClear
          onSearch={setQ} onChange={(e) => !e.target.value && setQ('')} style={{ width: 360 }} />
      </Space>
      <Table<OperationRecord> rowKey="request_id" dataSource={data} size="small"
        pagination={{ pageSize: 15 }}
        columns={[
          { title: 'Time', dataIndex: 'time', width: 160 },
          { title: 'User', dataIndex: 'user', width: 80 },
          { title: 'Library', dataIndex: 'library', width: 90 },
          { title: 'Tape', dataIndex: 'tape', width: 110 },
          { title: 'Drive', dataIndex: 'drive', width: 90 },
          { title: 'Operation', dataIndex: 'operation', width: 100 },
          { title: 'Risk', dataIndex: 'risk', width: 110, render: riskTag },
          { title: 'Status', dataIndex: 'status', render: (v) => (
              <Tag color={v === 'PASS' ? 'green' : 'red'}>{v}</Tag>) },
          { title: 'Duration', dataIndex: 'duration_s', render: (v) => `${v}s`, align: 'right' },
          { title: 'Request ID', dataIndex: 'request_id', render: (v) => (
              <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{v}</span>) },
        ]} />
    </div>
  );
}
