import { useEffect, useRef, useState } from 'react';
import { Card, Select, Steps, Button, Space, Typography, message, Alert, Tag, Divider } from 'antd';
import { api, friendlyError } from '../api/client';
import { ConfirmOperation, ConfirmDestructive } from '../components/ConfirmDialog';
import { TestProgressView } from '../components/TestProgress';
import { RiskTag } from '../components/RiskTag';
import type { LibraryInfo, DriveInfo, SlotInfo, TestSession, TestKind } from '../types';

const { Title, Text } = Typography;
type OpKind = TestKind | 'mount' | 'unmount';

const OPS: { value: OpKind; label: string; risk: 'LEVEL_1' | 'LEVEL_2' | 'LEVEL_3'; desc: string }[] = [
  { value: 'mount', label: 'Mount Tape', risk: 'LEVEL_2', desc: '装带：槽 → 带机（物理移动）' },
  { value: 'unmount', label: 'Unmount Tape', risk: 'LEVEL_2', desc: '卸带：带机 → 槽（物理移动）' },
  { value: 'read', label: 'Read Test', risk: 'LEVEL_1', desc: '读测试 dd' },
  { value: 'write', label: 'Write Test (verify)', risk: 'LEVEL_3', desc: '写测试 + 读回校验（破坏性）' },
  { value: 'full', label: 'Full Test', risk: 'LEVEL_3', desc: '全链路综合测试（破坏性）' },
];

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
  const [plan, setPlan] = useState<string[]>([]);
  const timer = useRef<ReturnType<typeof setInterval>>();

  useEffect(() => {
    (async () => {
      const [l, s] = await Promise.all([api.listLibraries(), api.safety()]);
      if (l.success && l.data?.length) { setLibs(l.data); setLib(l.data[0].changer); }
      if (s.success) setSafety(s.data);
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
  const tape = op === 'unmount' ? (drive?.loaded_tape || '') : (selSlot?.barcode || drive?.loaded_tape || '');
  const needWrite = opConf.risk === 'LEVEL_3';
  const writeBlocked = needWrite && safety && !safety.allow_write;
  const opBlocked = opConf.risk === 'LEVEL_2' && safety && !safety.allow_device_operation;
  const isMock = api.mode === 'mock';

  const planSteps = (): string[] => op === 'mount' ? [
    'Verify Library', 'Verify Slot', 'Verify Tape', 'Verify Drive', 'Check Drive Busy',
    'Load Tape', 'Verify Tape Loaded', 'Update Inventory',
  ] : op === 'unmount' ? [
    'Verify Drive', 'Verify Tape', 'Rewind', 'Unload', 'Verify Drive Empty', 'Update Inventory',
  ] : ['Verify Drive', 'Verify Media', op === 'read' ? 'Sequential Read (dd)' : 'Write + Read-back Verify', 'Collect Stats', 'Report'];

  const start = () => {
    setConfirm(false); setConfirmWrite(false);
    setPlan(planSteps());
  };

  const executing = useRef(false);
  const execute = async () => {
    if (executing.current) return; // 防重入：确认按钮双击不会重复提交
    executing.current = true;
    try {
    setSession(null);
    if (op === 'mount' || op === 'unmount') {
      if (op === 'mount' && slot == null) { message.error('Select a tape slot first'); return; }
      if (op === 'unmount' && !drive?.loaded_tape) { message.error(`Drive ${drive?.nst} is empty`); return; }
      const r = op === 'mount' ? await api.load(lib, slot!, driveIdx) : await api.unload(lib, slot || 6, driveIdx);
      if (r.success) {
        setPlan((p) => [...p]);
        message.success(`${op === 'mount' ? 'Mount' : 'Unmount'} PASS — ${r.message}`);
        const st = await api.libraryStatus(lib); if (st.success) setSlots(st.data.slots || []);
        const dr = await api.listDrives(); if (dr.success) setDrives(dr.data || []);
      } else {
        const f = friendlyError(r);
        message.error(`${f.title}: ${f.detail}`);
      }
      return;
    }
    // read / write / full
    const r = await api.runTest(op as TestKind, drive ? `/dev/${drive.nst}` : 'nst1', sizeMb, tape, tape);
    if (!r.success) { const f = friendlyError(r); message.error(`${f.title}: ${f.detail}`); return; }
    message.success(`Test started: ${r.data?.session_id}`);
    // 轮询会话状态（mock 1s 推进；real API 为同步结果，直接展示）
    if (timer.current) clearInterval(timer.current);
    timer.current = setInterval(async () => {
      const g = await api.getSession(r.data!.session_id);
      if (g.success) {
        setSession(g.data);
        if (g.data.status !== 'RUNNING' && timer.current) clearInterval(timer.current);
      }
    }, isMock ? 1000 : 3000);
    } finally { executing.current = false; }
  };

  return (
    <div>
      <Title level={3}>Test Center</Title>
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
            <Text type="secondary" style={{ marginLeft: 12 }}>Unmount 目标槽默认 6</Text></div>
          <div><Text strong>③ Drive: </Text>
            <Select value={driveIdx} onChange={setDriveIdx} style={{ width: 280 }}
              options={drives.map((d) => ({ value: d.index, label: `Drive-${d.index + 1} / /dev/${d.nst} ${d.loaded_tape ? '📼 ' + d.loaded_tape : '(Empty)'}` }))} /></div>
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
            <Button type="primary" danger={needWrite}
              disabled={!!writeBlocked || !!opBlocked || (needWrite && !tape)}
              onClick={() => needWrite ? setConfirmWrite(true) : setConfirm(true)}>
              {opConf.label}
            </Button>
            {writeBlocked && <Text type="secondary">Disabled by Safety Policy</Text>}
            {opBlocked && <Text type="secondary">Disabled by Safety Policy</Text>}
            {needWrite && !writeBlocked && !tape && <Text type="warning">需要先装载测试介质</Text>}
          </Space>
        </Space>
      </Card>

      {plan.length > 0 && !session && (
        <Card size="small" title="Operation Plan" style={{ marginTop: 16 }}>
          {plan.map((p, i) => <div key={i}>✓ {p}</div>)}
          <div style={{ marginTop: 8 }}><Tag color="green">PLAN READY</Tag></div>
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
          ['Slot', selSlot ? `Slot ${selSlot.slot}` : '-'],
          ['Drive', drive ? `Drive-${drive.index + 1} (/dev/${drive.nst})` : '-'],
          ...(op === 'read' || op === 'write' || op === 'full' ? [['Size', `${sizeMb} MiB`]] : []) as [string, string][],
          ['Risk', `${opConf.risk} · ${opConf.desc}`],
        ]}
        onCancel={() => setConfirm(false)}
        onConfirm={() => { setConfirm(false); start(); setTimeout(execute, 50); }} />

      <ConfirmDestructive
        open={confirmWrite} tape={safety?.test_media || tape || ''}
        extra={[['Library', `/dev/${lib}`], ['Drive', drive ? `/dev/${drive.nst}` : '-'], ['Size', `${sizeMb} MiB`]]}
        onCancel={() => setConfirmWrite(false)}
        onConfirm={() => { setConfirmWrite(false); start(); setTimeout(execute, 50); }} />
    </div>
  );
}
