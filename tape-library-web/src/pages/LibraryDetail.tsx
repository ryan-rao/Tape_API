import { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Tabs, Descriptions, Tag, Space, Button, message, Typography, Alert } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { api } from '../api/client';
import { SlotGrid, SlotDetailModal } from '../components/SlotGrid';
import { DeviceTree } from '../components/DeviceTree';
import { ConfirmOperation } from '../components/ConfirmDialog';
import { RiskTag } from '../components/RiskTag';
import type { LibraryInfo, SlotInfo, DriveInfo, TapeInfo } from '../types';

const { Title } = Typography;

export default function LibraryDetail() {
  const { changer } = useParams();
  const nav = useNavigate();
  const [lib, setLib] = useState<LibraryInfo | null>(null);
  const [slots, setSlots] = useState<SlotInfo[]>([]);
  const [drives, setDrives] = useState<DriveInfo[]>([]);
  const [tapes, setTapes] = useState<TapeInfo[]>([]);
  const [err, setErr] = useState('');
  const [pick, setPick] = useState<SlotInfo | null>(null);
  const [confirmLoad, setConfirmLoad] = useState<SlotInfo | null>(null);
  const [targetDrive, setTargetDrive] = useState(0);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!changer) return;
    const [st, inv, dr] = await Promise.all([
      api.libraryStatus(changer), api.libraryInventory(changer), api.listDrives(),
    ]);
    if (st.success) { setLib(st.data); setSlots(st.data.slots || []); setErr(''); }
    else setErr(`${st.code}: ${st.message}`);
    if (inv.success) setTapes(inv.data?.volumes || []);
    if (dr.success) setDrives(dr.data || []);
  }, [changer]);

  useEffect(() => { load(); const id = setInterval(load, 10000); return () => clearInterval(id); }, [load]);

  const doLoad = async () => {
    if (!changer || !confirmLoad) return;
    setBusy(true);
    const r = await api.load(changer, confirmLoad.slot, targetDrive);
    setBusy(false); setConfirmLoad(null);
    if (r.success) message.success(r.message);
    else message.error(`${r.code}: ${r.message}`);
    load();
  };

  if (err) return <Alert type="error" message="Failed to connect Tape API" description={err}
    action={<Button onClick={load}>Retry</Button>} />;
  if (!lib) return <p>Loading Library...</p>;

  return (
    <div>
      <Title level={3}>{lib.vendor} {lib.model}</Title>
      <Space style={{ marginBottom: 8 }}>
        <Tag color="green">Status: {lib.status}</Tag>
        <Tag>Serial: {lib.serial}</Tag>
        <Tag>Firmware: {lib.firmware}</Tag>
        <RiskTag level="LEVEL_1" />
        <Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
      </Space>

      <Tabs defaultActiveKey="slots" items={[
        { key: 'slots', label: 'Slots', children: (
          <Card size="small" title={`Slot Visualization — ${lib.occupied_slots}/${lib.slot_count} occupied`}>
            <SlotGrid slots={slots} onPick={(s) => setPick(s)} />
          </Card>) },
        { key: 'overview', label: 'Overview', children: (
          <Descriptions bordered column={2} size="small">
            <Descriptions.Item label="Device">/dev/{lib.changer}</Descriptions.Item>
            <Descriptions.Item label="Vendor / Model">{lib.vendor} {lib.model}</Descriptions.Item>
            <Descriptions.Item label="Drive Count">{lib.drive_count}</Descriptions.Item>
            <Descriptions.Item label="Slot Count">{lib.occupied_slots}/{lib.slot_count} occupied</Descriptions.Item>
            <Descriptions.Item label="Tape Count">{lib.tape_count}</Descriptions.Item>
            <Descriptions.Item label="Loaded Drives">{lib.loaded_drives}</Descriptions.Item>
            <Descriptions.Item label="Last Update">{lib.last_update}</Descriptions.Item>
            <Descriptions.Item label="Robot">Robot-01 (mtx)</Descriptions.Item>
          </Descriptions>) },
        { key: 'drives', label: 'Drives', children: (
          <Card size="small">{drives.map((d) => (
            <div key={d.nst} style={{ padding: 8, borderBottom: '1px solid #f0f0f0', cursor: 'pointer' }}
                 onClick={() => nav(`/drives/${d.nst}`)}>
              <b>/dev/{d.nst}</b> · {d.model} · <Tag color={d.loaded_tape ? 'blue' : 'default'}>{d.status}</Tag>
              {d.loaded_tape && <Tag color="blue">📼 {d.loaded_tape}</Tag>}
            </div>))}</Card>) },
        { key: 'tapes', label: 'Tapes', children: (
          <Card size="small">{tapes.map((t) => (
            <div key={t.barcode} style={{ padding: 6, borderBottom: '1px solid #f0f0f0' }}>
              <b>{t.barcode}</b> · {t.media_type} · {t.slot ? `Slot ${t.slot}` : `Drive ${t.drive}`}
            </div>))}</Card>) },
        { key: 'tree', label: 'Device Tree', children: (
          <Card size="small"><DeviceTree lib={lib} drives={drives} slots={slots} /></Card>) },
        { key: 'events', label: 'Events', children: (
          <Card size="small"><p style={{ color: '#999' }}>Robot events —— 见 Audit 页面（所有机器人动作均有审计记录）</p></Card>) },
      ]} />

      <SlotDetailModal slot={pick} open={!!pick} onClose={() => setPick(null)}
        onAction={(s, a) => {
          setPick(null);
          if (a === 'load') { setConfirmLoad(s); setTargetDrive(0); }
          else if (a === 'move') message.info('Move/Transfer：请使用 Test Center 的 Transfer 流程');
          else load();
        }} />

      <ConfirmOperation
        open={!!confirmLoad} title="Tape Library Operation — Mount"
        riskColor="orange" confirmText="Confirm Mount"
        items={[
          ['Library', `/dev/${changer}`],
          ['Tape', confirmLoad?.barcode || ''],
          ['Source', `Slot ${confirmLoad?.slot}`],
          ['Destination', `Drive ${targetDrive} (${drives[targetDrive]?.nst || '?'})`],
          ['Risk', '🟡 LEVEL_2 · 此操作将物理移动磁带'],
        ]}
        onCancel={() => setConfirmLoad(null)} onConfirm={doLoad}
      />
      {busy && <p style={{ marginTop: 12, color: '#1677ff' }}>Robot moving tape... (mock ~1.5s)</p>}
    </div>
  );
}
