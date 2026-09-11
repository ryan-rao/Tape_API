import { useEffect, useState } from 'react';
import { Table, Tag, Drawer, Descriptions, Button, Space, Typography, message } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import { api } from '../api/client';
import type { AuditCommand } from '../types';

const { Title, Paragraph } = Typography;

export default function Audit() {
  const [list, setList] = useState<AuditCommand[]>([]);
  const [cur, setCur] = useState<AuditCommand | null>(null);

  useEffect(() => {
    (async () => {
      const r = await api.auditList();
      if (r.success) setList(r.data || []);
      else message.error(`${r.code}: ${r.message}`);
    })();
    const id = setInterval(async () => {
      const r = await api.auditList();
      if (r.success) setList(r.data || []);
    }, 10000);
    return () => clearInterval(id);
  }, []);

  const download = () => {
    if (!cur) return;
    const blob = new Blob([JSON.stringify(cur, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${cur.command_id}.json`;
    a.click();
  };

  return (
    <div>
      <Title level={3}>Audit — Command / API Audit</Title>
      <Table<AuditCommand> rowKey="command_id" dataSource={list} size="small"
        pagination={{ pageSize: 15 }}
        onRow={(r) => ({ onClick: () => setCur(r), style: { cursor: 'pointer' } })}
        columns={[
          { title: 'Command ID', dataIndex: 'command_id', render: (v) => (
              <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{v}</span>) },
          { title: 'Request ID', dataIndex: 'request_id', render: (v) => (
              <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{v}</span>) },
          { title: 'Operation', dataIndex: 'operation' },
          { title: 'Risk', dataIndex: 'risk', render: (v) => (
              <Tag color={v === 'LEVEL_1' ? 'green' : v === 'LEVEL_2' ? 'orange' : 'red'}>{v}</Tag>) },
          { title: 'Exit', dataIndex: 'exit_code', render: (v) => (
              <Tag color={v === 0 ? 'green' : 'red'}>{v}</Tag>) },
          { title: 'Duration', dataIndex: 'duration_ms', render: (v) => `${v} ms`, align: 'right' },
          { title: 'Created', dataIndex: 'created_at', width: 160 },
        ]} />

      <Drawer open={!!cur} onClose={() => setCur(null)} width={640} title={cur ? `Command ${cur.command_id}` : ''}
        extra={<Space>
          <Button icon={<DownloadOutlined />} onClick={download}>Download raw log</Button>
        </Space>}>
        {cur && (
          <>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="Operation">{cur.operation}</Descriptions.Item>
              <Descriptions.Item label="Risk Level">{cur.risk}</Descriptions.Item>
              <Descriptions.Item label="Request ID">{cur.request_id}</Descriptions.Item>
              <Descriptions.Item label="Exit Code">{cur.exit_code}</Descriptions.Item>
              <Descriptions.Item label="Duration">{cur.duration_ms} ms</Descriptions.Item>
              <Descriptions.Item label="Created">{cur.created_at}</Descriptions.Item>
            </Descriptions>
            <Paragraph strong style={{ marginTop: 16 }}>Command</Paragraph>
            <pre style={{ background: '#f6f6f6', padding: 12, borderRadius: 6, fontFamily: 'monospace' }}>{cur.command}</pre>
            <Paragraph strong>STDOUT</Paragraph>
            <pre style={{ background: '#f6f6f6', padding: 12, borderRadius: 6, maxHeight: 240, overflow: 'auto', fontSize: 12 }}>{cur.stdout || '(empty)'}</pre>
            <Paragraph strong>STDERR</Paragraph>
            <pre style={{ background: '#fff2f0', padding: 12, borderRadius: 6, fontSize: 12 }}>{cur.stderr || '(empty)'}</pre>
            {cur.parsed && (<><Paragraph strong>parsed (JSON)</Paragraph>
              <pre style={{ background: '#f0f7ff', padding: 12, borderRadius: 6, fontSize: 12, maxHeight: 240, overflow: 'auto' }}>{JSON.stringify(cur.parsed, null, 2)}</pre></>)}
          </>
        )}
      </Drawer>
    </div>
  );
}
