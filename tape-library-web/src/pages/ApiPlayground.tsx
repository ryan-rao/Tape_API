// API Playground：全量端点目录（openapi 自动生成 catalog）+ 参数化调试
// 数据源：/api/v1/*（v1.2.1，99 端点；202 异步任务自动轮询 /jobs/{id}）
import { useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import {
  Button, Card, Empty, Input, message, Segmented, Space, Table, Tag, Typography,
} from 'antd';
import { PlayCircleOutlined, SearchOutlined } from '@ant-design/icons';
import { rawRequest } from '../api/client';
import { CATALOG, GROUPS, PATH_DEFAULTS } from '../api/catalog';
import type { Endpoint } from '../api/catalog';
import { apiToCli, extractCliOutput } from '../api/apiCliMap';
import { traceCommands } from '../api/cmdTrace';
import type { CmdRec } from '../api/cmdTrace';

const { Title, Text } = Typography;

const METHOD_COLORS: Record<string, string> = { GET: 'blue', POST: 'orange' };
const LEVEL_COLORS: Record<string, string> = { L1: 'green', L2: 'orange', L3: 'red', '-': 'default' };

const TERM: CSSProperties = {
  maxHeight: 260, overflow: 'auto', fontSize: 12, lineHeight: 1.5,
  background: '#0b1021', color: '#d6e2ff', padding: 12, borderRadius: 6,
  whiteSpace: 'pre-wrap', wordBreak: 'break-all', marginTop: 4, marginBottom: 0,
};

type AnyObj = Record<string, any>;

export default function ApiPlayground() {
  const [group, setGroup] = useState<string>(GROUPS[0]?.key || 'Meta');
  const [q, setQ] = useState('');
  const [selected, setSelected] = useState<Endpoint | null>(null);
  const [pathVals, setPathVals] = useState<Record<string, string>>({});
  const [queryVals, setQueryVals] = useState<Record<string, string>>({});
  const [bodyText, setBodyText] = useState('');
  const [upFile, setUpFile] = useState<File | null>(null);
  const [sending, setSending] = useState(false);
  const [resp, setResp] = useState<AnyObj | null>(null);
  const [jobState, setJobState] = useState<AnyObj | null>(null);
  const [cmdRecs, setCmdRecs] = useState<CmdRec[]>([]);

  // 响应/job 只回 command_id 时（如 Library inventory/load/transfer），
  // 自动追查 /commands/{id} 取回真实命令行 + stdout
  async function applyResp(r: AnyObj) {
    setResp(r);
    setCmdRecs([]);
    try {
      const recs = await traceCommands(r);
      if (recs.length) setCmdRecs(recs);
    } catch { /* 追查失败不影响响应展示 */ }
  }

  const list = useMemo(
    () => CATALOG.filter((e) => !e.hidden && e.group === group
      && (!q || e.path.toLowerCase().includes(q.toLowerCase())
        || (e.summary || '').toLowerCase().includes(q.toLowerCase()))),
    [group, q],
  );

  function pick(e: Endpoint) {
    setSelected(e);
    setResp(null);
    setJobState(null);
    setCmdRecs([]);
    const pv: Record<string, string> = {};
    e.params.filter((p) => p.in === 'path')
      .forEach((p) => { pv[p.name] = PATH_DEFAULTS[p.name] ?? String(p.default ?? ''); });
    setPathVals(pv);
    const qv: Record<string, string> = {};
    e.params.filter((p) => p.in === 'query')
      .forEach((p) => { qv[p.name] = p.default !== undefined && p.default !== null ? String(p.default) : ''; });
    setQueryVals(qv);
    setBodyText(e.bodyDefault || (e.hasBody ? '{\n  \n}' : ''));
    setUpFile(null);
  }

  async function send() {
    if (!selected) return;
    // catalog 路径含 /api/v1 前缀，rawRequest 的 axios baseURL 已含 —— 必须先去掉，否则 404
    let path = selected.path.replace(/^\/api\/v1/, '');
    Object.entries(pathVals).forEach(([k, v]) => { path = path.replace(`{${k}}`, encodeURIComponent(v)); });
    const query: Record<string, any> = {};
    Object.entries(queryVals).forEach(([k, v]) => { if (v !== '') query[k] = v; });
    // upload 端点：multipart 文件（表单字段 file）；download 端点：二进制流落盘
    const isUpload = selected.path.endsWith('/upload');
    const isDownload = selected.path.endsWith('/download');
    let body: any;
    if (isUpload) {
      if (!upFile) { message.error('请先选择要上传的文件'); return; }
      const fd = new FormData();
      fd.append('file', upFile, upFile.name);
      body = fd;
    } else if (selected.hasBody && bodyText.trim()) {
      try { body = JSON.parse(bodyText); } catch (err: any) {
        message.error(`请求体 JSON 无效: ${err.message}`);
        return;
      }
    }
    setSending(true);
    setJobState(null);
    try {
      const r = await rawRequest(selected.method, path, { body, query, binary: isDownload });
      // 二进制响应：触发浏览器保存到本地
      if (r.blob) {
        const url = URL.createObjectURL(r.blob);
        const a = document.createElement('a');
        a.href = url; a.download = r.filename || 'download.bin';
        a.click();
        URL.revokeObjectURL(url);
        message.success(`已保存 ${r.filename}（${(r.blob.size / 1024).toFixed(1)} KB）`);
      }
      await applyResp(r as AnyObj);
      if (r.http_status === 202 && r.data?.job_id) {
        const jobId: string = r.data.job_id;
        setJobState({ job_id: jobId, state: r.data.state || 'queued' });
        for (let i = 0; i < 240; i++) {
          await new Promise((res) => setTimeout(res, 3000));
          // 进度走轻量 progress 端点；终态后用 result 端点取完整载荷（result/error/commands）
          const j = await rawRequest('GET', `/jobs/${jobId}/progress`);
          if (!j.success) continue;
          setJobState({
            job_id: jobId, state: j.data?.state,
            progress: j.data?.progress,
          });
          if (['succeeded', 'failed', 'cancelled'].includes(j.data?.state)) {
            const fin = await rawRequest('GET', `/jobs/${jobId}/result`);
            if (fin.code === 'NOT_FINISHED') continue; // 状态竞争：继续轮询
            // result 端点返回与同步执行一致的业务信封；失败时 HTTP 502/404 已被信封化，直接展示
            const finResp = (fin.code && fin.code !== 'AGENT_UNAVAILABLE' ? fin : j) as AnyObj;
            await applyResp({ ...finResp, job_id: jobId, state: j.data?.state });
            if (j.data.state === 'succeeded') message.success('异步任务完成');
            else message.error(`异步任务 ${j.data?.state}`);
            break;
          }
        }
      }
    } finally {
      setSending(false);
    }
  }

  const pathParams = selected?.params.filter((p) => p.in === 'path') || [];
  const queryParams = selected?.params.filter((p) => p.in === 'query') || [];
  // 等价 CLI 命令行（随表单参数/请求体实时更新）
  const cliEq = selected ? apiToCli(selected.method, selected.path, pathVals, queryVals, bodyText) : null;
  const cliOut = resp ? extractCliOutput(resp.data?.result ?? resp.data) : null;

  return (
    <div>
      <Title level={3}>API Playground</Title>
      <Space style={{ margin: '8px 0 12px' }} wrap>
        <Segmented value={group} onChange={(v) => { setGroup(v as string); setSelected(null); }}
          options={GROUPS.map((g) => ({ value: g.key, label: g.label }))} />
        <Input allowClear prefix={<SearchOutlined />} placeholder="搜索路径/摘要" style={{ width: 220 }}
          value={q} onChange={(e) => setQ(e.target.value)} />
      </Space>

      <div className="pg-split" style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        <Card size="small" style={{ width: 460 }} title={`端点 (${list.length})`}
          styles={{ body: { padding: 0 } }}>
          <Table rowKey="id" size="small" dataSource={list} pagination={{ pageSize: 15 }}
            onRow={(r) => ({ onClick: () => pick(r), style: { cursor: 'pointer' } })}
            columns={[
              { title: '方法', dataIndex: 'method', width: 62,
                render: (v) => <Tag color={METHOD_COLORS[v]} style={{ marginInlineEnd: 0 }}>{v}</Tag> },
              { title: '路径', dataIndex: 'path', ellipsis: true },
              { title: '级别', dataIndex: 'level', width: 48,
                render: (v) => v === '-' ? <Text type="secondary">-</Text> : <Tag color={LEVEL_COLORS[v]} style={{ marginInlineEnd: 0 }}>{v}</Tag> },
              { title: '异步', dataIndex: 'isAsync', width: 46,
                render: (v) => v ? <Tag style={{ marginInlineEnd: 0 }}>202</Tag> : <Text type="secondary">-</Text> },
            ]} />
        </Card>

        <Card size="small" style={{ flex: 1, minWidth: 420 }} title={selected ? '调试' : '选择左侧端点'}>
          {!selected && <Empty description="点击左侧端点开始调试" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
          {selected && (
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <div>
                <Tag color={METHOD_COLORS[selected.method]}>{selected.method}</Tag>
                <Text code>{selected.path}</Text>
                {selected.level !== '-' && <Tag color={LEVEL_COLORS[selected.level]} style={{ marginLeft: 8 }}>{selected.level}</Tag>}
                {selected.isAsync && <Tag>异步 202</Tag>}
                {selected.summary && <div style={{ marginTop: 4 }}><Text type="secondary">{selected.summary}</Text></div>}
              </div>

              <div style={{ background: '#0b1021', borderRadius: 6, padding: '8px 12px' }}>
                <div style={{ color: '#8fa3c8', fontSize: 11 }}>等价 CLI 命令行（随参数实时更新）</div>
                {cliEq ? (
                  <>
                    <Text copyable={{ text: cliEq.cli }} style={{ color: '#7ee787', fontFamily: 'monospace', fontSize: 12, whiteSpace: 'pre-wrap' }}>
                      $ {cliEq.cli}
                    </Text>
                    {cliEq.note && <div style={{ color: '#8fa3c8', fontSize: 11, marginTop: 2 }}>※ {cliEq.note}</div>}
                  </>
                ) : (
                  <div style={{ color: '#8fa3c8', fontSize: 12 }}>纯 API 功能（jobs / 审计 / 归档网关），无直接 CLI 等价</div>
                )}
              </div>

              {pathParams.length > 0 && (
                <div>
                  <Text type="secondary">路径参数</Text>
                  {pathParams.map((p) => (
                    <div key={p.name} className="pg-param-row" style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
                      <Text code style={{ width: 130 }}>{p.name}</Text>
                      <Input size="small" style={{ width: 260 }} value={pathVals[p.name] ?? ''}
                        onChange={(e) => setPathVals({ ...pathVals, [p.name]: e.target.value })} />
                    </div>
                  ))}
                </div>
              )}

              {queryParams.length > 0 && (
                <div>
                  <Text type="secondary">查询参数</Text>
                  {queryParams.map((p) => (
                    <div key={p.name} className="pg-param-row" style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
                      <Text code style={{ width: 130 }}>{p.name}{p.required ? '*' : ''}</Text>
                      <Input size="small" style={{ width: 260 }} value={queryVals[p.name] ?? ''}
                        onChange={(e) => setQueryVals({ ...queryVals, [p.name]: e.target.value })} />
                    </div>
                  ))}
                </div>
              )}

              {selected.path.endsWith('/upload') ? (
                <div>
                  <Text type="secondary">上传文件（multipart 字段 file；目录用 dir 参数指定）</Text>
                  <div style={{ marginTop: 6 }}>
                    <input type="file" onChange={(e) => setUpFile(e.target.files?.[0] ?? null)} />
                    {upFile && <div style={{ marginTop: 4 }}><Text type="secondary">{upFile.name} · {(upFile.size / 1024).toFixed(1)} KB</Text></div>}
                  </div>
                </div>
              ) : selected.hasBody && (
                <div>
                  <Text type="secondary">请求体（JSON；confirm/allow_write 已按需预置）</Text>
                  <Input.TextArea rows={8} style={{ fontFamily: 'monospace', fontSize: 12 }}
                    value={bodyText} onChange={(e) => setBodyText(e.target.value)} />
                </div>
              )}

              <div>
                <Button type="primary" icon={<PlayCircleOutlined />} loading={sending} onClick={send}>
                  发送请求
                </Button>
                {jobState && (
                  <span style={{ marginLeft: 12 }}>
                    <Tag color={jobState.state === 'succeeded' ? 'green'
                      : jobState.state === 'failed' ? 'red' : 'orange'}>
                      {jobState.job_id} · {jobState.state}
                    </Tag>
                    {jobState.progress?.percent !== undefined && <Text type="secondary">{jobState.progress.percent}%</Text>}
                  </span>
                )}
              </div>

              {resp && (
                <div>
                  <Text type="secondary">
                    响应{resp.http_status ? ` · HTTP ${resp.http_status}` : ''}
                    {resp.code ? ` · ${resp.code}` : ''}
                    {resp.request_id ? ` · ${resp.request_id}` : ''}
                  </Text>
                  {cliOut && cliOut.kind !== 'none' && (
                    <div style={{ marginTop: 8 }}>
                      <Text type="secondary">CLI 命令输出</Text>
                      {cliOut.kind === 'multi' && (cliOut.extra || []).map(([k, t]) => (
                        <div key={k}>
                          <Tag style={{ marginTop: 6 }}>{k}</Tag>
                          <pre style={TERM}>{t || '(无输出)'}</pre>
                        </div>
                      ))}
                      {cliOut.kind !== 'multi' && <pre style={TERM}>{cliOut.text}</pre>}
                    </div>
                  )}
                  {cmdRecs.length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      <Text type="secondary">后端实际执行命令（自动追查 /commands 记录）</Text>
                      {cmdRecs.map((c) => (
                        <div key={c.command_id} style={{ marginTop: 6 }}>
                          <span style={{ color: '#7ee787', fontFamily: 'monospace', fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                            $ {c.command}
                          </span>
                          {(c.stdout || c.stderr) && (
                            <pre style={TERM}>{(c.stdout || '') + (c.stderr && String(c.stderr).trim() ? `\n[stderr]\n${c.stderr}` : '')}</pre>
                          )}
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            exit_code={c.exit_code}{c.result ? ` · ${c.result}` : ''}{c.duration_ms !== undefined && c.duration_ms !== null ? ` · ${c.duration_ms}ms` : ''} · {c.command_id}
                          </Text>
                        </div>
                      ))}
                    </div>
                  )}
                  <div style={{ marginTop: 8 }}>
                  <Text type="secondary">响应 JSON</Text>
                  <pre style={{ maxHeight: 420, overflow: 'auto', fontSize: 12, background: '#fafafa', padding: 8, borderRadius: 4 }}>
{JSON.stringify(resp.job_id ? resp : (resp.data ?? resp), null, 2)}
                  </pre>
                  </div>
                </div>
              )}
            </Space>
          )}
        </Card>
      </div>
    </div>
  );
}
