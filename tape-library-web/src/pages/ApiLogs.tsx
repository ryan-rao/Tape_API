import { useEffect, useState, useMemo } from 'react';
import {
  Card, Table, Tag, Button, Drawer, Descriptions, Switch, Space, Tooltip, message,
} from 'antd';
import {
  ApiOutlined, ReloadOutlined, ClearOutlined, DownloadOutlined, CopyOutlined,
} from '@ant-design/icons';
import { getApiLogs, clearApiLogs, subscribeApiLogs, type ApiLogEntry } from '../api/apilog';


function methodColor(m: string) {
  return m === 'GET' ? 'blue' : 'orange';
}

export default function ApiLogs() {
  const [logs, setLogs] = useState<ApiLogEntry[]>([]);
  const [detail, setDetail] = useState<ApiLogEntry | null>(null);
  const [onlyFail, setOnlyFail] = useState(false);
  const [auto, setAuto] = useState(true);

  useEffect(() => {
    const upd = () => setLogs([...getApiLogs()]);
    upd();
    // 10 秒自动刷新 + 变更即时订阅
    const sub = subscribeApiLogs(upd);
    let timer: any = null;
    if (auto) timer = setInterval(upd, 10000);
    return () => { sub(); if (timer) clearInterval(timer); };
  }, [auto]);

  const data = useMemo(
    () => (onlyFail ? logs.filter((l) => !l.ok) : logs),
    [logs, onlyFail],
  );

  const exportJson = () => {
    if (!logs.length) { message.warning('暂无日志可导出'); return; }
    const blob = new Blob([JSON.stringify(logs, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `api-logs-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const copy = (text: string) => {
    navigator.clipboard?.writeText(text).then(() => message.success('已复制到剪贴板'));
  };

  return (
    <Card
      title={<><ApiOutlined /> API Call Logs（输入 / 输出）</>}
      extra={
        <Space>
          <span>10s 刷新</span>
          <Switch size="small" checked={auto} onChange={setAuto} />
          <span>仅看失败</span>
          <Switch size="small" checked={onlyFail} onChange={setOnlyFail} />
          <Button icon={<ReloadOutlined />} size="small" onClick={() => setLogs([...getApiLogs()])} />
          <Button icon={<DownloadOutlined />} size="small" onClick={exportJson}>导出 JSON</Button>
          <Button icon={<ClearOutlined />} size="small" danger onClick={() => { clearApiLogs(); message.info('已清空'); }}>清空</Button>
        </Space>
      }
    >
      <Table
        rowKey="id"
        size="small"
        dataSource={data}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          {
            title: '时间', dataIndex: 'ts', width: 110,
            render: (t: string) => new Date(t).toLocaleTimeString('zh-CN', { hour12: false }),
          },
          {
            title: '方法', dataIndex: 'method', width: 70,
            render: (m: string) => <Tag color={methodColor(m)}>{m}</Tag>,
          },
          {
            title: '接口路径', dataIndex: 'path', ellipsis: true,
            render: (p: string) => <code style={{ fontSize: 12 }}>{p}</code>,
          },
          {
            title: 'HTTP', dataIndex: 'status', width: 70,
            render: (s: number) => (s === 0 ? <Tag>local</Tag> : <Tag color={s < 400 ? 'green' : 'red'}>{s}</Tag>),
          },
          {
            title: '结果', dataIndex: 'code', width: 200,
            render: (c: string, r: ApiLogEntry) => (
              <Tag color={r.ok ? 'green' : 'red'} style={{ fontSize: 12 }}>{c || '-'}</Tag>
            ),
          },
          { title: 'request_id', dataIndex: 'request_id', width: 220, ellipsis: true, render: (v: string) => v || '-' },
          {
            title: '耗时', dataIndex: 'duration_ms', width: 90, sorter: (a: ApiLogEntry, b: ApiLogEntry) => a.duration_ms - b.duration_ms,
            render: (d: number) => (d >= 1000 ? `${(d / 1000).toFixed(2)}s` : `${d}ms`),
          },
          {
            title: '', width: 90,
            render: (_: any, r: ApiLogEntry) => (
              <Button type="link" size="small" onClick={() => setDetail(r)}>查看</Button>
            ),
          },
        ]}
      />

      <Drawer
        title={detail ? `${detail.method} ${detail.path}` : ''}
        width={720}
        open={!!detail}
        onClose={() => setDetail(null)}
      >
        {detail && (
          <>
            <Descriptions size="small" column={2} bordered style={{ marginBottom: 16 }}>
              <Descriptions.Item label="时间">{new Date(detail.ts).toLocaleString('zh-CN', { hour12: false })}</Descriptions.Item>
              <Descriptions.Item label="HTTP 状态">{detail.status || 'local(mock)'}</Descriptions.Item>
              <Descriptions.Item label="结果码">
                <Tag color={detail.ok ? 'green' : 'red'}>{detail.code || '-'}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="耗时">{detail.duration_ms} ms</Descriptions.Item>
              <Descriptions.Item label="request_id" span={2}>{detail.request_id || '-'}</Descriptions.Item>
            </Descriptions>

            {detail.request_body != null && (
              <>
                <h4>📤 请求输入（Request Body）</h4>
                <pre
                  style={{ background: '#001529', color: '#ffa940', padding: 12, borderRadius: 6, fontSize: 12, maxHeight: 240, overflow: 'auto' }}
                >
                  {JSON.stringify(detail.request_body, null, 2)}
                </pre>
              </>
            )}

            <h4 style={{ marginTop: 8 }}>
              📥 响应输出（Response）
              <Button size="small" icon={<CopyOutlined />} style={{ marginLeft: 8 }}
                onClick={() => copy(JSON.stringify(detail.response, null, 2))}>
                复制
            </Button>
            </h4>
            <pre
              style={{ background: '#001529', color: '#69db7c', padding: 12, borderRadius: 6, fontSize: 12, maxHeight: 420, overflow: 'auto' }}
            >
              {JSON.stringify(detail.response, null, 2)}
            </pre>
          </>
        )}
      </Drawer>
    </Card>
  );
}
