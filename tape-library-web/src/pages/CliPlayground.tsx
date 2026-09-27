// CLI Playground：全部 CLI 命令（mt/mtx/sg3_utils/lsscsi/系统探测/dd）↔ HTTP 端点 1:1 调试
// 布局参考 ApiPlayground：左侧命令目录 + 右侧参数表单/终端式输出
// L3 破坏性命令需 confirm:true（body 已预置）；job 类命令自动轮询 /jobs/{id}
import { useMemo, useState } from 'react';
import {
  Alert, Button, Card, Empty, Input, message, Segmented, Space, Switch, Table, Tag, Typography,
} from 'antd';
import { CodeOutlined, PlayCircleOutlined, SearchOutlined, ClearOutlined } from '@ant-design/icons';
import { rawRequest } from '../api/client';
import { traceCommands } from '../api/cmdTrace';
import type { CmdRec } from '../api/cmdTrace';
import { CLI_CATALOG, CLI_GROUPS, LEVEL_COLORS, TOOL_COLORS } from '../api/cliCatalog';
import type { AnyObj } from '../api/catalog';
import type { CliCommand } from '../api/cliCatalog';

const { Title, Text } = Typography;

const MAX_HISTORY = 50;

interface HistoryItem {
  key: string;
  cmd: CliCommand;
  success?: boolean;
  code?: string;
  ms: number;
  time: string;
  resp: AnyObj & { http_status?: number };
}

function fmtMs(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60000)}m${Math.round((ms % 60000) / 1000)}s`;
}

// 从响应中提取最值得展示的文本（stdout / parsed / 整体 data）
function extractOut(data: any): { stdout?: string; parsed?: any } {
  if (!data || typeof data !== 'object') return {};
  // 嵌套命令结果（如 sg_scan/sg_map、诊断汇总）
  for (const k of Object.keys(data)) {
    const v = data[k];
    if (v && typeof v === 'object' && typeof v.stdout === 'string' && v.parsed) {
      // 多命令结果，全部拼接
    }
  }
  return { stdout: data.stdout, parsed: data.parsed };
}

export default function CliPlayground() {
  const [group, setGroup] = useState<string>(CLI_GROUPS[0]?.key || 'sg');
  const [q, setQ] = useState('');
  const [selected, setSelected] = useState<CliCommand | null>(null);
  const [pathVals, setPathVals] = useState<Record<string, string>>({});
  const [queryVals, setQueryVals] = useState<Record<string, string>>({});
  const [bodyText, setBodyText] = useState('');
  const [sending, setSending] = useState(false);
  const [syncMode, setSyncMode] = useState(false);
  const [jobState, setJobState] = useState<AnyObj | null>(null);
  const [resp, setResp] = useState<AnyObj | null>(null);
  const [cmdRecs, setCmdRecs] = useState<CmdRec[]>([]);

  // 响应/job 只回 command_id 时（如 mtx inventory/load/transfer），
  // 自动追查 /commands/{id} 取回真实命令行 + stdout
  async function applyResp(r: AnyObj) {
    setResp(r);
    setCmdRecs([]);
    try {
      const recs = await traceCommands(r);
      if (recs.length) setCmdRecs(recs);
    } catch { /* 追查失败不影响响应展示 */ }
  }
  const [history, setHistory] = useState<HistoryItem[]>([]);

  const list = useMemo(
    () => CLI_CATALOG.filter((c) => c.group === group
      && (!q || c.name.toLowerCase().includes(q.toLowerCase())
        || c.cli.toLowerCase().includes(q.toLowerCase())
        || (c.summary || '').toLowerCase().includes(q.toLowerCase()))),
    [group, q],
  );

  function pick(c: CliCommand) {
    setSelected(c);
    setResp(null);
    setJobState(null);
    setCmdRecs([]);
    const pv: Record<string, string> = {};
    c.params.filter((p) => p.in === 'path').forEach((p) => { pv[p.name] = p.default ?? ''; });
    setPathVals(pv);
    const qv: Record<string, string> = {};
    c.params.filter((p) => p.in === 'query').forEach((p) => { qv[p.name] = p.default ?? ''; });
    setQueryVals(qv);
    setBodyText(c.bodyDefault || (c.hasBody ? '{\n  \n}' : ''));
    setSyncMode(!c.isJob); // 普通命令默认同步；dd 类 202 轮询
  }

  function buildPath(c: CliCommand): string {
    let p = c.path;
    Object.entries(pathVals).forEach(([k, v]) => { p = p.replace(`{${k}}`, encodeURIComponent(v)); });
    if (syncMode) p += (p.includes('?') ? '&' : '?') + 'async=false';
    return p;
  }

  async function pollJob(jobId: string) {
    for (let i = 0; i < 240; i++) {
      await new Promise((res) => setTimeout(res, 3000));
      // 进度走轻量 progress 端点；终态后用 result 端点取完整载荷（result/error/commands）
      const j = await rawRequest('GET', `/jobs/${jobId}/progress`);
      if (!j.success) continue;
      setJobState({
        job_id: jobId, state: j.data?.state,
        percent: j.data?.progress?.percent,
        bytes: j.data?.progress?.bytes_human || j.data?.progress?.rate,
      });
      if (['succeeded', 'failed', 'cancelled'].includes(j.data?.state)) {
        const fin = await rawRequest('GET', `/jobs/${jobId}/result`);
        if (fin.code === 'NOT_FINISHED') continue; // 状态竞争：继续轮询
        // result 端点返回与同步执行一致的业务信封；失败时 HTTP 502/404 已被信封化，直接展示
        const finResp = (fin.code && fin.code !== 'AGENT_UNAVAILABLE' ? fin : j) as AnyObj;
        await applyResp({ ...finResp, job_id: jobId, state: j.data?.state });
        if (j.data.state === 'succeeded') message.success('任务完成');
        else message.error(`任务 ${j.data?.state}`);
        return;
      }
    }
    message.warning('轮询超时（12 分钟），可在 Jobs 页继续查询');
  }

  async function send() {
    if (!selected) return;
    let path = buildPath(selected);
    const query: Record<string, any> = {};
    if (!syncMode) {
      // async 模式下 query 参数拼 URL（sync 模式已用 async=false 占位）
    }
    Object.entries(queryVals).forEach(([k, v]) => { if (v !== '') query[k] = v; });
    if (Object.keys(query).length) {
      const qs = Object.entries(query).map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&');
      path += (path.includes('?') ? '&' : '?') + qs;
    }
    let body: any;
    if (selected.hasBody && bodyText.trim()) {
      try { body = JSON.parse(bodyText); } catch (err: any) {
        message.error(`请求体 JSON 无效: ${err.message}`);
        return;
      }
      if (selected.level === 'L3' && body.confirm !== true) {
        message.warning('L3 破坏性命令需要 "confirm": true（清空该字段则改为显式拒绝）');
      }
    }
    setSending(true);
    setJobState(null);
    const t0 = performance.now();
    try {
      const r = await rawRequest(selected.method, path, { body });
      await applyResp(r as AnyObj);
      if (r.http_status === 202 && r.data?.job_id) {
        setJobState({ job_id: r.data.job_id, state: r.data.state || 'queued' });
        await pollJob(r.data.job_id);
      }
      const item: HistoryItem = {
        key: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        cmd: selected,
        success: (r as any).success,
        code: r.code,
        ms: Math.round(performance.now() - t0),
        time: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
        resp: r as AnyObj,
      };
      setHistory((h) => [item, ...h].slice(0, MAX_HISTORY));
    } finally {
      setSending(false);
    }
  }

  const pathParams = selected?.params.filter((p) => p.in === 'path') || [];
  const queryParams = selected?.params.filter((p) => p.in === 'query') || [];
  const { stdout, parsed } = resp?.data ? extractOut(resp.data) : {};
  const nested = resp?.data && typeof resp.data === 'object'
    ? Object.entries(resp.data).filter(([, v]) => v && typeof v === 'object' && typeof (v as any).stdout === 'string')
    : [];

  return (
    <div>
      <Title level={3}>CLI Playground</Title>
      <Text type="secondary">
        后端白名单 CLI 命令 1:1 调试（mt / mtx / sg3_utils / lsscsi / 系统探测 / dd 测试）——参数即 CLI 缺省值
      </Text>

      <Space style={{ margin: '12px 0' }} wrap>
        <Segmented value={group} onChange={(v) => { setGroup(v as string); setSelected(null); }}
          options={CLI_GROUPS.map((g) => ({ value: g.key, label: g.label }))} />
        <Input allowClear prefix={<SearchOutlined />} placeholder="搜索命令" style={{ width: 200 }}
          value={q} onChange={(e) => setQ(e.target.value)} />
      </Space>

      <div className="pg-split" style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        <Card size="small" style={{ width: 460 }} title={`命令 (${list.length})`}
          styles={{ body: { padding: 0 } }}>
          <Table rowKey="id" size="small" dataSource={list} pagination={{ pageSize: 15 }}
            onRow={(r) => ({ onClick: () => pick(r), style: { cursor: 'pointer' } })}
            columns={[
              { title: '命令', dataIndex: 'name', width: 150, ellipsis: true,
                render: (v, r: CliCommand) => (
                  <Space size={4}><Tag color={TOOL_COLORS[r.tool]} style={{ marginInlineEnd: 0 }}>{r.tool}</Tag>{v}</Space>
                ) },
              { title: '说明', dataIndex: 'summary', ellipsis: true },
              { title: '级别', dataIndex: 'level', width: 44,
                render: (v: string) => <Tag color={LEVEL_COLORS[v as keyof typeof LEVEL_COLORS]} style={{ marginInlineEnd: 0 }}>{v}</Tag> },
            ]} />
        </Card>

        <Card size="small" style={{ flex: 1, minWidth: 420 }} title={selected ? `调试 · ${selected.name}` : '选择左侧命令'}>
          {!selected && <Empty description="点击左侧命令开始调试（绿 L1 只读 / 橙 L2 物理操作 / 红 L3 破坏性）" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
          {selected && (
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <div>
                <Tag color={LEVEL_COLORS[selected.level]}>{selected.level}</Tag>
                <Tag color={TOOL_COLORS[selected.tool]}>{selected.tool}</Tag>
                {selected.isJob && <Tag>任务 202</Tag>}
                <span style={{ marginLeft: 8, fontFamily: 'monospace', fontSize: 12 }}>
                  {selected.method} /api/v1{buildPath(selected)}
                </span>
                <div style={{ marginTop: 4 }}>
                  <Text code style={{ fontSize: 12 }}>$ {selected.cli}</Text>
                  <Text type="secondary" style={{ marginLeft: 8 }}>{selected.summary}</Text>
                </div>
              </div>

              {pathParams.length > 0 && (
                <div>
                  <Text type="secondary">设备参数</Text>
                  {pathParams.map((p) => (
                    <div key={p.name} className="pg-param-row" style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
                      <Text code style={{ width: 110 }}>{p.name}</Text>
                      <Input size="small" style={{ width: 200 }} value={pathVals[p.name] ?? ''}
                        onChange={(e) => setPathVals({ ...pathVals, [p.name]: e.target.value })} />
                    </div>
                  ))}
                </div>
              )}

              {queryParams.length > 0 && (
                <div>
                  <Text type="secondary">参数（缺省值已预填）</Text>
                  {queryParams.map((p) => (
                    <div key={p.name} className="pg-param-row" style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
                      <Text code style={{ width: 110 }}>{p.name}</Text>
                      {p.options
                        ? (
                          <Input size="small" style={{ width: 200 }} value={queryVals[p.name] ?? ''}
                            onChange={(e) => setQueryVals({ ...queryVals, [p.name]: e.target.value })} />
                        )
                        : (
                          <Input size="small" style={{ width: 200 }} value={queryVals[p.name] ?? ''}
                            onChange={(e) => setQueryVals({ ...queryVals, [p.name]: e.target.value })} />
                        )}
                      {p.options && (
                        <span>{p.options.filter((o) => o).map((o) => (
                          <Tag key={o} style={{ cursor: 'pointer', marginInlineEnd: 4 }}
                            onClick={() => setQueryVals({ ...queryVals, [p.name]: o })}>{o}</Tag>
                        ))}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {selected.hasBody && (
                <div>
                  <Text type="secondary">请求体（JSON；缺省参数已预置，confirm 为 true 表示确认执行）</Text>
                  <Input.TextArea rows={8} style={{ fontFamily: 'monospace', fontSize: 12 }}
                    value={bodyText} onChange={(e) => setBodyText(e.target.value)} />
                </div>
              )}

              <div>
                <Space>
                  <Button type="primary" icon={<PlayCircleOutlined />} loading={sending}
                    danger={selected.level === 'L3'} onClick={send}>
                    执行{selected.level === 'L3' ? '（破坏性）' : ''}
                  </Button>
                  <span>
                    <Switch size="small" checked={syncMode} onChange={setSyncMode} />
                    <Text type="secondary" style={{ marginLeft: 6 }}>同步执行（async=false）</Text>
                  </span>
                </Space>
                {jobState && (
                  <span style={{ marginLeft: 12 }}>
                    <Tag color={jobState.state === 'succeeded' ? 'green'
                      : jobState.state === 'failed' ? 'red' : 'orange'}>
                      {jobState.job_id} · {jobState.state}
                    </Tag>
                    {jobState.percent !== undefined && <Text type="secondary">{jobState.percent}%</Text>}
                    {jobState.bytes && <Text type="secondary"> {String(jobState.bytes)}</Text>}
                  </span>
                )}
              </div>

              {resp && (
                <div>
                  <Text type="secondary">
                    结果 {resp.http_status ? `· HTTP ${resp.http_status}` : ''}
                    {resp.code ? ` · ${resp.code}` : ''} · {(resp as any).success ? '✅' : '❌'}
                  </Text>
                  {typeof stdout === 'string' && stdout.length > 0 && (
                    <div>
                      <Text type="secondary">stdout（终端输出）</Text>
                      <pre style={{
                        maxHeight: 260, overflow: 'auto', fontSize: 12, lineHeight: 1.5,
                        background: '#0b1021', color: '#d6e2ff', padding: 12, borderRadius: 6,
                        whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                      }}>{stdout}</pre>
                    </div>
                  )}
                  {nested.length > 0 && (
                    <div>
                      <Text type="secondary">命令输出（多段）</Text>
                      {nested.map(([k, v]: [string, any]) => (
                        <div key={k} style={{ marginBottom: 8 }}>
                          <Tag>{k}</Tag>
                          <pre style={{
                            maxHeight: 200, overflow: 'auto', fontSize: 12,
                            background: '#0b1021', color: '#d6e2ff', padding: 12, borderRadius: 6,
                            whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                          }}>{v.stdout || '(空)'}</pre>
                        </div>
                      ))}
                    </div>
                  )}
                  {cmdRecs.length > 0 && (
                    <div>
                      <Text type="secondary">后端实际执行命令（自动追查 /commands 记录）</Text>
                      {cmdRecs.map((c) => (
                        <div key={c.command_id} style={{ marginBottom: 8 }}>
                          <span style={{ color: '#7ee787', fontFamily: 'monospace', fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                            $ {c.command}
                          </span>
                          {(c.stdout || c.stderr) && (
                            <pre style={{
                              maxHeight: 200, overflow: 'auto', fontSize: 12,
                              background: '#0b1021', color: '#d6e2ff', padding: 12, borderRadius: 6,
                              whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                            }}>{(c.stdout || '') + (c.stderr && String(c.stderr).trim() ? `\n[stderr]\n${c.stderr}` : '')}</pre>
                          )}
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            exit_code={c.exit_code}{c.result ? ` · ${c.result}` : ''}{c.duration_ms !== undefined && c.duration_ms !== null ? ` · ${c.duration_ms}ms` : ''} · {c.command_id}
                          </Text>
                        </div>
                      ))}
                    </div>
                  )}
                  <div>
                    <Text type="secondary">响应 JSON（含 parsed 结构化解析）</Text>
                    <pre style={{
                      maxHeight: 320, overflow: 'auto', fontSize: 12,
                      background: '#fafafa', padding: 8, borderRadius: 4,
                    }}>{JSON.stringify(resp.job_id ? resp : (resp.data ?? resp), null, 2)}</pre>
                  </div>
                </div>
              )}
            </Space>
          )}
        </Card>
      </div>

      {history.length > 0 && (
        <Card size="small" title={<Space><CodeOutlined />执行历史（本次会话）</Space>}
          style={{ marginTop: 16 }}
          extra={<Button size="small" icon={<ClearOutlined />} onClick={() => setHistory([])}>清空</Button>}
          styles={{ body: { padding: 0 } }}>
          <Table rowKey="key" size="small" dataSource={history} pagination={false}
            onRow={(r) => ({ onClick: () => pick(r.cmd), style: { cursor: 'pointer' } })}
            columns={[
              { title: '时间', dataIndex: 'time', width: 100 },
              { title: '命令', width: 200, render: (_, r: HistoryItem) => (
                <Space size={4}>
                  <Tag color={LEVEL_COLORS[r.cmd.level]} style={{ marginInlineEnd: 0 }}>{r.cmd.level}</Tag>
                  <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{r.cmd.name}</span>
                </Space>
              ) },
              { title: '结果', dataIndex: 'code', width: 200, render: (v, r: HistoryItem) => (
                <Tag color={r.success ? 'green' : 'red'} style={{ marginInlineEnd: 0 }}>{v || 'ERROR'}</Tag>
              ) },
              { title: '耗时', dataIndex: 'ms', width: 100, render: (v) => fmtMs(v) },
              { title: 'request_id', ellipsis: true, render: (_, r: HistoryItem) => (
                <Text code style={{ fontSize: 11 }}>{r.resp?.request_id || '-'}</Text>
              ) },
            ]} />
        </Card>
      )}

      <Alert style={{ marginTop: 16 }} type="info" showIcon
        message="说明"
        description={
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            <li>每个命令对应后端一条白名单 CLI（argv 直构、shell=False），请求体字段即 CLI 参数缺省值</li>
            <li>L2 物理操作（装/卸带、定位）与 L3 破坏性（weof/erase/mkpartition/dd 写）需 <code>confirm:true</code>，且受安全策略 <code>allow_device_operation / allow_write</code> 限制</li>
            <li>同步执行（async=false）直接返回结果；关闭后 202 异步并自动轮询任务进度（dd 测试类默认异步）</li>
            <li>stdout 保留原始终端输出供审计追溯（command_id / request_id 可回查 Audit 页）</li>
          </ul>
        } />
    </div>
  );
}
