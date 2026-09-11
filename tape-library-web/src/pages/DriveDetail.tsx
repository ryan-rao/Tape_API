import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Card, Descriptions, Tag, Space, Button, Tabs, message, Spin } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { api, friendlyError } from '../api/client';
import { RiskTag } from '../components/RiskTag';
import { ConfirmOperation } from '../components/ConfirmDialog';
import type { DriveInfo } from '../types';

export default function DriveDetail() {
  const { nst } = useParams();
  const [drive, setDrive] = useState<DriveInfo | null>(null);
  const [err, setErr] = useState('');
  const [confirmRewind, setConfirmRewind] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    if (!nst) return;
    const r = await api.driveDetail(nst);
    if (r.success) { setDrive(r.data); setErr(''); } else setErr(`${r.code}: ${r.message}`);
  };
  useEffect(() => { load(); const id = setInterval(load, 5000); return () => clearInterval(id); }, [nst]);

  const doRewind = async () => {
    if (!nst) return;
    setBusy(true);
    const r = await api.rewind(nst);
    setBusy(false); setConfirmRewind(false);
    if (r.success) message.success(r.message);
    else { const f = friendlyError(r); message.error(`${f.title}: ${f.detail}`); }
  };

  if (err) return <Card><p style={{ color: 'red' }}>❌ {friendlyError({ success: false, code: err.split(':')[0], message: err }).title}</p><p>{err}</p><Button onClick={load}>Retry</Button></Card>;
  if (!drive) return <Spin tip="Loading Drive..." />;
  const alerts = drive.tapealert;

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <h3>{drive.vendor} {drive.model}</h3>
        <Tag color={drive.status === 'ERROR' ? 'red' : 'green'}>Status: {drive.status}</Tag>
        <RiskTag level="LEVEL_1" />
      </Space>

      <Tabs defaultActiveKey="overview" items={[
        { key: 'overview', label: 'Overview', children: (
          <Descriptions bordered column={2} size="small">
            <Descriptions.Item label="Serial">{drive.serial}</Descriptions.Item>
            <Descriptions.Item label="Firmware">{drive.firmware}</Descriptions.Item>
            <Descriptions.Item label="/dev/nstX">/dev/{drive.nst}</Descriptions.Item>
            <Descriptions.Item label="/dev/sgX">/dev/{drive.sg}</Descriptions.Item>
            <Descriptions.Item label="SCSI Address">{drive.scsi_address}</Descriptions.Item>
            <Descriptions.Item label="Loaded Tape">{drive.loaded_tape ? <Tag color="blue">📼 {drive.loaded_tape}</Tag> : '-'}</Descriptions.Item>
            <Descriptions.Item label="Block Size">{drive.block_size || 'variable'}</Descriptions.Item>
            <Descriptions.Item label="Compression"><Tag color={drive.compression ? 'green' : 'default'}>{drive.compression ? 'Enabled' : 'Disabled'}</Tag></Descriptions.Item>
            <Descriptions.Item label="Temperature">{drive.temperature != null ? `${drive.temperature} °C` : 'N/A'}</Descriptions.Item>
            <Descriptions.Item label="TapeAlert">{alerts.all_clear ? <Tag color="green">All Clear (64 flags)</Tag> : <Tag color="red">{alerts.triggered_count} triggered</Tag>}</Descriptions.Item>
          </Descriptions>) },
        { key: 'diagnostics', label: 'Diagnostics', children: (
          <Card size="small">
            <p style={{ fontFamily: 'monospace', fontSize: 12, whiteSpace: 'pre-wrap' }}>
{`SCSI Inquiry:
  vendor  = ${drive.vendor}
  product = ${drive.model}
  rev     = ${drive.firmware}

VPD 0x80 Unit Serial: ${drive.serial}

TUR: ${drive.status === 'LOADED' || drive.status === 'READY' ? 'ready' : 'not ready (no media)'}

TapeAlert: ${alerts.all_clear ? 'all 64 flags clear' : alerts.triggered_count + ' flags triggered'}`}
            </p>
          </Card>) },
      ]} />

      <Space style={{ marginTop: 16 }}>
        <Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
        <Button danger onClick={() => setConfirmRewind(true)} disabled={!drive.loaded_tape}>Rewind</Button>
        <Button disabled>Eject（走库端 Unmount）</Button>
      </Space>

      <ConfirmOperation open={confirmRewind} title="Rewind Tape" riskColor="orange"
        confirmText="Confirm Rewind"
        items={[['Drive', `/dev/${drive.nst}`], ['Tape', drive.loaded_tape || '-'], ['Risk', '🟡 LEVEL_2 · 磁带倒带']]}
        onCancel={() => setConfirmRewind(false)} onConfirm={doRewind} />
      {busy && <p style={{ color: '#1677ff' }}>Rewinding...</p>}
    </div>
  );
}
