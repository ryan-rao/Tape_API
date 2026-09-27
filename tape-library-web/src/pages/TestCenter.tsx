import { useEffect, useRef, useState } from 'react';
import { Card, Select, Steps, Button, Space, Typography, message, Alert, Tag, Divider, Tabs } from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined,
  ClockCircleOutlined, MinusCircleOutlined, CopyOutlined,
} from '@ant-design/icons';
import { api, rawRequest, friendlyError } from '../api/client';
import { ConfirmOperation, ConfirmDestructive } from '../components/ConfirmDialog';
import { TestProgressView } from '../components/TestProgress';
import { RiskTag } from '../components/RiskTag';
import type { LibraryInfo, DriveInfo, SlotInfo, TestSession, TestKind } from '../types';
import HATestPlayground from './HATestPlayground';

const { Title, Text } = Typography;
type OpKind = TestKind | 'mount' | 'unmount';

const OPS: { value: OpKind; label: string; risk: 'LEVEL_1' | 'LEVEL_2' | 'LEVEL_3'; desc: string }[] = [
  { value: 'mount', label: 'Mount Tape', risk: 'LEVEL_2', desc: '装带：槽 → 带机（物理移动）' },
  { value: 'unmount', label: 'Unmount Tape', risk: 'LEVEL_2', desc: '卸带：带机 → 槽（物理移动）' },
  { value: 'read', label: 'Read Test', risk: 'LEVEL_1', desc: '读测试 dd' },
  { value: 'write', label: 'Write Test (verify)', risk: 'LEVEL_3', desc: '写测试 + 读回校验（破坏性）' },
  { value: 'full', label: 'Full Test', risk: 'LEVEL_3', desc: '全链路综合测试（破坏性）' },
];

// ---------- API 节点调用轨迹：每一次端点调用都保留原始响应信封，逐级可展开 ----------
type TStatus = 'idle' | 'running' | 'ok' | 'fail' | 'wait' | 'skip';
interface TStep {
  label: string; method: string; path: string; req?: any;
  http?: number; ms?: number; status: TStatus; env?: any; note?: string;
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const short = (s: string, n = 1800) => (s.length > n ? `${s.slice(0, n)}\n…(截断，共 ${s.length} 字符)` : s);
const ICON: Record<TStatus, React.ReactNode> = {
  idle: <MinusCircleOutlined style={{ color: '#bbb' }} />,
  running: <LoadingOutlined style={{ color: '#1677ff' }} />,
  wait: <ClockCircleOutlined style={{ color: '#faad14' }} />,
  ok: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  fail: <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
  skip: <MinusCircleOutlined style={{ color: '#d9d9d9' }} />,
};

function TraceRow({ step }: { step: TStep }) {
  const [open, setOpen] = useState(false);
  const json = step.env ? JSON.stringify(step.env, null, 2) : '';
  return (
    <div style={{ padding: '6px 0', borderBottom: '1px dashed #f0f0f0' }}>
      <Space wrap size={6}>
        {ICON[step.status]}
        <b>{step.label}</b>
        <Text code style={{ fontSize: 12 }}>{step.method} {step.path}</Text>
        {step.http !== undefined && <Tag>{step.http}</Tag>}
        {step.ms !== undefined && <Text type="secondary" style={{ fontSize: 12 }}>{step.ms}ms</Text>}
        {json && (
          <Button size="small" type="link" style={{ padding: 0 }} onClick={() => setOpen(!open)}>
            {open ? '收起原始响应' : '原始响应'}
          </Button>
        )}
        {json && open && (
          <Button size="small" type="link" style={{ padding: 0 }} icon={<CopyOutlined />}
            onClick={() => { navigator.clipboard.writeText(json).then(() => message.success('原始 JSON 已复制')); }} />
        )}
      </Space>
      {step.req !== undefined && (
        <pre style={preStyle('#fff7e6', '#614700')}>请求体: {short(JSON.stringify(step.req))}</pre>
      )}
      {step.note && <div style={{ color: '#555', fontSize: 12, marginLeft: 22 }}>{step.note}</div>}
      {open && json && <pre style={preStyle('#0d1117', '#c9d1d9')}>{short(json)}</pre>}
    </div>
  );
}
const preStyle = (bg: string, fg: string): React.CSSProperties => ({
  background: bg, color: fg, padding: 8, borderRadius: 6, fontSize: 12, lineHeight: 1.5,
  whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 320, overflow: 'auto', margin: '4px 0 0 22px',
});

export default function TestCenter() {
  const [libs, setLibs] = useState<LibraryInfo[]>([]);
  const [slots, setSlots] = useState<SlotInfo[]>([]);
  const [drives, setDrives] = useState<DriveInfo[]>([]);
  const [safety, setSafety] = useState<{ allow_device_operation: boolean; allow_write: boolean; test_media?: string } | null>(null);

  const [lib, setLib] = useState<string>('');
  const [slot, setSlot] = useState<number | null>(null);
  const [driveIdx, setDriveIdx] = useState(0);
  const [op, setOp] = useState<OpKind>('mount');
  const [sizeMb, setSizeMb] = useState(256);

  const [confirm, setConfirm] = useState(false);
  const [confirmWrite, setConfirmWrite] = useState(false);
  const [session, setSession] = useState<TestSession | null>(null);
  const [trace, setTrace] = useState<TStep[]>([]);
  const [running, setRunning] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval>>();

  useEffect(() => {
    (async () => {
      const [l, s] = await Promise.all([api.listLibraries(), rawRequest('GET', '/safety')]);
      if (l.success && l.data?.length) { setLibs(l.data); setLib(l.data[0].changer); }
      // 实测特例：GET /safety 返回裸对象无 success 信封（手册 §0.2），字段在顶层；mock 模式才是标准信封
      const sd: any = (s as any)?.data?.allow_device_operation !== undefined ? (s as any).data
        : (s as any)?.allow_device_operation !== undefined ? s : null;
      if (sd) setSafety(sd);
    })();
    return () => { if (timer.current) clearInterval(timer.current); };
  }, []);

  useEffect(() => {
    if (!lib) return;
    (async () => {
      const [st, dr] = await Promise.all([api.libraryStatus(lib), api.listDrives()]);
      if (st.success) { setSlots(st.data.slots || []); setDrives(dr.data || []); }
    })();
  }, [lib]);

  const opConf = OPS.find((o) => o.value === op)!;
  const drive = drives[driveIdx];
  const selSlot = slots.find((s) => s.slot === slot) || null;
  // 卸带/测试时展示磁带当前所在槽位（从 slots 反查，slot 参数缺省自动回原槽）
  const tapeHomeSlot = drive?.loaded_tape ? slots.find((s) => s.barcode === drive.loaded_tape) || null : null;
  const tape = op === 'unmount' ? (drive?.loaded_tape || '') : (selSlot?.barcode || drive?.loaded_tape || '');
  const needWrite = opConf.risk === 'LEVEL_3';
  const writeBlocked = needWrite && safety && !safety.allow_write;
  const opBlocked = opConf.risk === 'LEVEL_2' && safety && !safety.allow_device_operation;
  const isMock = api.mode === 'mock';

  // ---------- real 模式：逐节点执行 + 原始响应留痕 ----------
  const mark = (i: number, p: Partial<TStep>) =>
    setTrace((prev) => prev.map((st, j) => (j === i ? { ...st, ...p } : st)));

  async function node(i: number, method: 'GET' | 'POST', path: string, body?: any, note?: string): Promise<any> {
    const t0 = performance.now();
    mark(i, { status: 'running', note: note || '调用中…' });
    const r: any = await rawRequest(method, path, body !== undefined ? { body } : {});
    const okish = !!r.success;
    mark(i, {
      status: okish ? 'ok' : 'fail', http: r.http_status, ms: Math.round(performance.now() - t0),
      env: r, req: body, note: `${r.code || '-'} · request_id=${r.request_id || '-'}${okish ? '' : ' — 失败勿盲目重试，展开原始响应核对'}`,
    });
    return r;
  }

  async function pollJob(i: number, jobId: string): Promise<{ rs: any; state: string }> {
    let state = 'unknown';
    for (let n = 0; n < 320; n++) {
      await sleep(n === 0 ? 1200 : 3000);
      const p: any = await rawRequest('GET', `/jobs/${jobId}/progress`);
      state = p.data?.state || 'unknown';
      mark(i, {
        status: state === 'succeeded' ? 'ok' : state === 'unknown' ? 'wait' : state === 'running' || state === 'queued' ? 'wait' : 'fail',
        http: p.http_status, env: p,
        note: `第 ${n + 1} 次轮询 → ${state}（progress=${p.data?.progress ?? '-'}）`,
      });
      if (state === 'succeeded' || state === 'failed' || state === 'cancelled') break;
      if (n > 300) { state = 'poll_timeout'; break; }
    }
    const rs: any = await node(i + 1, 'GET', `/jobs/${jobId}/result`, undefined, '取 job 终态业务信封（同步风格原始返回）');
    return { rs, state };
  }

  function buildSteps(): TStep[] {
    const L = `/libraries/${lib}`;
    if (op === 'mount' || op === 'unmount') {
      return [
        { label: op === 'mount' ? '预检①槽位状态（含条码）' : '预检①槽位状态（回槽校验用）', method: 'GET', path: `${L}/status?refresh=true`, status: 'idle' },
        { label: op === 'mount' ? '预检②带机状态（SN/空带判定）' : '预检②带机状态（磁带在机判定）', method: 'GET', path: '/drives/list?refresh=true', status: 'idle' },
        { label: op === 'mount' ? '装带 load（v1.2: barcode+drive_sn）' : '卸带 unload（v1.2: barcode+slot）', method: 'POST', path: `${L}/${op === 'mount' ? 'load' : 'unload'}`, status: 'idle' },
        { label: '轮询 job 进度', method: 'GET', path: '/jobs/{job_id}/progress', status: 'idle' },
        { label: 'job 结果 result', method: 'GET', path: '/jobs/{job_id}/result', status: 'idle' },
        { label: '复核①槽位（物理移动后）', method: 'GET', path: `${L}/status?refresh=true`, status: 'idle' },
        { label: '复核②带机（物理移动后）', method: 'GET', path: '/drives/list?refresh=true', status: 'idle' },
      ];
    }
    const testPath = op === 'read' ? '/read' : op === 'write' ? '/tests/write-verify' : '/tests/full';
    return [
      { label: '预检：带机状态', method: 'GET', path: '/drives/list?refresh=true', status: 'idle' },
      { label: `提交 ${op} 测试`, method: 'POST', path: testPath, status: 'idle' },
      { label: '轮询 job 进度', method: 'GET', path: '/jobs/{job_id}/progress', status: 'idle' },
      { label: 'job 结果 result', method: 'GET', path: '/jobs/{job_id}/result', status: 'idle' },
    ];
  }

  const refreshUi = async () => {
    const st = await api.libraryStatus(lib); if (st.success) setSlots(st.data.slots || []);
    const dr = await api.listDrives(); if (dr.success) setDrives(dr.data || []);
  };

  const executing = useRef(false);
  const execute = async () => {
    if (executing.current) return; // 防重入：确认按钮双击不会重复提交
    executing.current = true;
    setRunning(true);
    try {
      if (isMock) { await executeMock(); return; }
      setSession(null);
      setTrace(buildSteps());

      if (op === 'mount' || op === 'unmount') {
        if (op === 'mount' && slot == null) { message.error('Select a tape slot first'); return; }
        if (op === 'unmount' && !drive?.loaded_tape) { message.error(`Drive ${drive?.nst} is empty`); return; }
        await node(0, 'GET', `/libraries/${lib}/status?refresh=true`, undefined, '带条码的槽位快照（?refresh=true 绕过 20s 缓存）');
        const dr0 = await node(1, 'GET', '/drives/list?refresh=true', undefined, '带机 SN + 装载状态（?refresh=true）');
        const driveNow = (dr0.data?.drives || []).find((d: any) => d.index === drive?.index);
        // v1.2 参数：load 用 barcode+drive_sn（带机序列号），unload 用 barcode+slot（缺省自动回原槽）
        const body: any = op === 'mount'
          ? { barcode: selSlot?.barcode, drive_sn: driveNow?.serial || drive?.serial, confirm: true }
          : { barcode: drive?.loaded_tape, ...(slot != null ? { slot } : {}), confirm: true };
        const r = await node(2, 'POST', `/libraries/${lib}/${op === 'mount' ? 'load' : 'unload'}`, body);
        const jobId = r.data?.job_id;
        let okEnd = r.success; let resData: any = r.data;
        if (r.success && jobId) {
          const { rs, state } = await pollJob(3, jobId);
          okEnd = !!rs.success && state === 'succeeded';
          resData = rs.data;
          if (!okEnd) mark(4, { note: `job 终态 ${state} —— 展开 result 原始响应对错（勘误：mtx 44/00 假失败以复核状态为准，勿盲目重试）` });
        } else if (r.success) {
          mark(3, { status: 'skip', note: '同步响应（无 job_id），跳过轮询' });
          mark(4, { status: 'skip', note: '同上' });
        } else {
          mark(3, { status: 'skip', note: `提交失败（${r.code}），未产生 job` });
          mark(4, { status: 'skip', note: '同上' });
        }
        const st1 = await node(5, 'GET', `/libraries/${lib}/status?refresh=true`, undefined, '物理移动后复核（服务端 mtx status 实读）');
        const dr1 = await node(6, 'GET', '/drives/list?refresh=true', undefined, '带机侧复核');
        if (okEnd) {
          const res = resData?.resolved;
          message.success(`${op === 'mount' ? 'Mount' : 'Unmount'} PASS — ${res ? `磁带${res.tape || ''} ↔ 带机${res.drive}（${res.drive_method}）` : '见 result 原始响应'}`);
        } else message.error(`${op} 未成功 —— 各节点原始响应见下方轨迹`);
        // 用复核节点数据回刷选择器
        const parsed = st1.data?.parsed;
        if (parsed) {
          const occ = (parsed.slots || []).filter((s: any) => !s.import_export);
          setSlots(occ.map((s: any) => ({ element: s.element, slot: s.element, barcode: s.barcode ?? null, media_type: null, status: s.occupied ? 'Occupied' : 'Empty' })));
        }
        if (dr1.data?.drives) setDrives(dr1.data.drives);
        return;
      }

      // read / write / full —— 真实模式走 202+job 链路（旧实现读 mock 形状 session_id，real 下拿不到进度，本次一并修复）
      const driveDev = drive ? `/dev/${drive.nst}` : '/dev/nst1';
      const body: any = op === 'read'
        ? { drive: driveDev, block_size: '1M', confirm: true }
        : op === 'write'
          ? { drive: driveDev, test_media: tape || safety?.test_media || '', size_mb: sizeMb, allow_write: true, confirm: true }
          : undefined;
      await node(0, 'GET', '/drives/list?refresh=true', undefined, '测试前带机状态');
      const testPath = op === 'read' ? '/read' : op === 'write' ? '/tests/write-verify' : '/tests/full';
      const r = await node(1, 'POST', testPath, body);
      const jobId = r.data?.job_id;
      if (r.success && jobId) {
        const { rs, state } = await pollJob(2, jobId);
        if (rs.success && state === 'succeeded') message.success(`${op} PASS — 原始业务结果见 result 节点`);
        else message.error(`${op} 未成功（${state}）—— 展开原始响应对错`);
      } else if (r.success) {
        mark(2, { status: 'skip', note: '同步响应' }); mark(3, { status: 'skip', note: '同步响应' });
        message.success(`${op} PASS`);
      } else {
        mark(2, { status: 'skip', note: '提交失败' }); mark(3, { status: 'skip', note: '提交失败' });
        const f = friendlyError(r); message.error(`${f.title}: ${f.detail}`);
      }
      refreshUi();
    } finally {
      executing.current = false; setRunning(false);
    }
  };

  // ---------- mock 模式：保留原会话轮询行为 ----------
  const executeMock = async () => {
    setTrace([]);
    if (op === 'mount' || op === 'unmount') {
      if (op === 'mount' && slot == null) { message.error('Select a tape slot first'); return; }
      if (op === 'unmount' && !drive?.loaded_tape) { message.error(`Drive ${drive?.nst} is empty`); return; }
      const posParams = {
        barcode: (op === 'mount' ? selSlot?.barcode : drive?.loaded_tape) || undefined,
        ...(op === 'mount'
          ? { drive_sn: drive?.serial || undefined }
          : { slot: slot != null ? slot : undefined }),
      };
      const r = op === 'mount' ? await api.load(lib, posParams) : await api.unload(lib, posParams);
      if (r.success) {
        message.success(`${op === 'mount' ? 'Mount' : 'Unmount'} PASS — ${r.message}`);
        const st = await api.libraryStatus(lib); if (st.success) setSlots(st.data.slots || []);
        const dr = await api.listDrives(); if (dr.success) setDrives(dr.data || []);
      } else {
        const f = friendlyError(r); message.error(`${f.title}: ${f.detail}`);
      }
      return;
    }
    const r = await api.runTest(op as TestKind, drive ? `/dev/${drive.nst}` : 'nst1', sizeMb, tape, tape);
    if (!r.success) { const f = friendlyError(r); message.error(`${f.title}: ${f.detail}`); return; }
    message.success(`Test started: ${r.data?.session_id}`);
    if (timer.current) clearInterval(timer.current);
    timer.current = setInterval(async () => {
      const g = await api.getSession(r.data!.session_id);
      if (g.success) {
        setSession(g.data);
        if (g.data.status !== 'RUNNING' && timer.current) clearInterval(timer.current);
      }
    }, 1000);
  };

  return (
    <div>
      <Title level={3}>Test Center</Title>
      <Tabs defaultActiveKey="device" items={[
        { key: 'device', label: '设备测试', children: (
          <>
      {safety && (
        <Alert type={safety.allow_write ? 'warning' : 'info'} style={{ marginBottom: 16 }} showIcon
          message={`Safety Policy: device_operation=${String(safety.allow_device_operation)} · allow_write=${String(safety.allow_write)} · TEST_MEDIA=${safety.test_media || '-'}`} />
      )}

      <Steps current={confirm || confirmWrite ? 4 : 3} size="small"
        items={[{ title: 'Select Library' }, { title: 'Select Tape' }, { title: 'Select Drive' }, { title: 'Operation' }, { title: 'Confirm' }, { title: 'Execute' }]} />

      <Card size="small" style={{ marginTop: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div><Text strong>① Library: </Text>
            <Select value={lib} onChange={setLib} style={{ width: 240 }}
              options={libs.map((l) => ({ value: l.changer, label: `${l.vendor} ${l.model} (/dev/${l.changer})` }))} /></div>
          <div><Text strong>② Tape / Slot: </Text>
            <Select value={slot ?? undefined} onChange={setSlot} style={{ width: 280 }} allowClear
              placeholder="选择槽位（Mount 用）"
              options={slots.filter((s) => s.barcode).map((s) => ({ value: s.slot, label: `${s.barcode} / Slot ${s.slot}` }))} />
            <Text type="secondary" style={{ marginLeft: 12 }}>Unmount 目标槽缺省自动回原槽</Text></div>
          <div><Text strong>③ Drive: </Text>
            <Select value={driveIdx} onChange={setDriveIdx} style={{ width: 360 }}
              options={drives.map((d) => ({ value: d.index, label: `Drive-${d.index + 1} /dev/${d.nst} SN:${d.serial || '-'} ${d.loaded_tape ? '📼 ' + d.loaded_tape + (tapeHomeSlot && d.index === drive?.index ? `（原槽 S${tapeHomeSlot.slot}）` : '') : '(Empty)'}` }))} /></div>
          <div><Text strong>④ Operation: </Text>
            <Select value={op} onChange={setOp} style={{ width: 240 }}
              options={OPS.map((o) => ({ value: o.value, label: o.label }))} />
            <span style={{ marginLeft: 12 }}>{opConf.desc}</span></div>
          {(op === 'read' || op === 'write' || op === 'full') && (
            <div><Text strong>Size (MiB): </Text>
              <Select value={sizeMb} onChange={setSizeMb} style={{ width: 140 }}
                options={[64, 256, 512, 1024].map((v) => ({ value: v, label: `${v} MiB` }))} /></div>
          )}
          <Divider style={{ margin: '4px 0' }} />
          <Space>
            <RiskTag level={opConf.risk} />
            <Button type="primary" danger={needWrite} loading={running}
              disabled={!!writeBlocked || !!opBlocked || (needWrite && !tape)}
              onClick={() => needWrite ? setConfirmWrite(true) : setConfirm(true)}>
              {opConf.label}
            </Button>
            {writeBlocked && <Text type="secondary">Disabled by Safety Policy</Text>}
            {opBlocked && <Text type="secondary">Disabled by Safety Policy</Text>}
            {needWrite && !writeBlocked && !tape && <Text type="warning">需要先装载测试介质</Text>}
            {!isMock && <Text type="secondary" style={{ fontSize: 12 }}>每次执行逐节点展示各 API 调用的原始响应信封（202 → 轮询 → result → 复核）</Text>}
          </Space>
        </Space>
      </Card>

      {trace.length > 0 && (
        <Card size="small" style={{ marginTop: 16 }}
          title="API 节点调用轨迹（原始响应）"
          extra={<Tag color={running ? 'blue' : trace.some((s) => s.status === 'fail') ? 'red' : 'green'}>{running ? 'RUNNING' : trace.some((s) => s.status === 'fail') ? 'DONE(有失败节点)' : 'DONE'}</Tag>}>
          {trace.map((s, i) => <TraceRow key={i} step={s} />)}
        </Card>)}

      {session && (
        <Card size="small" title="Test Progress" style={{ marginTop: 16 }}
          extra={<Tag color={session.status === 'PASS' ? 'green' : session.status === 'FAIL' ? 'red' : 'blue'}>{session.status}</Tag>}>
          <TestProgressView session={session} />
        </Card>)}

      <ConfirmOperation
        open={confirm} title={opConf.label} riskColor={opConf.risk === 'LEVEL_2' ? 'orange' : 'green'}
        confirmText={`Confirm ${opConf.label.split(' ')[0]}`}
        items={[
          ['Library', `/dev/${lib}`],
          ['Tape', tape || '-'],
          ['Slot', selSlot ? `Slot ${selSlot.slot}` : (op === 'unmount' ? (tapeHomeSlot ? `自动回原槽 S${tapeHomeSlot.slot}` : '自动（source_slot）') : '-')],
          ['Drive', drive ? `Drive-${drive.index + 1} (/dev/${drive.nst}${drive.serial ? ` · SN ${drive.serial}` : ''})` : '-'],
          ...(op === 'read' || op === 'write' || op === 'full' ? [['Size', `${sizeMb} MiB`]] : []) as [string, string][],
          ['Risk', `${opConf.risk} · ${opConf.desc}`],
        ]}
        onCancel={() => setConfirm(false)}
        onConfirm={() => { setConfirm(false); setTimeout(execute, 50); }} />

      <ConfirmDestructive
        open={confirmWrite} tape={safety?.test_media || tape || ''}
        extra={[['Library', `/dev/${lib}`], ['Drive', drive ? `/dev/${drive.nst}` : '-'], ['Size', `${sizeMb} MiB`]]}
        onCancel={() => setConfirmWrite(false)}
        onConfirm={() => { setConfirmWrite(false); setTimeout(execute, 50); }} />
          </>
        ) },
        { key: 'hatest', label: 'HATest Playground', children: <HATestPlayground /> },
      ]} />
    </div>
  );
}
