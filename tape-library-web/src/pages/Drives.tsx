import { useEffect, useState } from 'react';
import { Table, Tag, Button, Space, Typography, message } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { DriveInfo } from '../types';

const { Title } = Typography;

function driveStatusTag(s: string) {
  const c = s === 'READY' || s === 'LOADED' ? 'green' : s === 'ERROR' ? 'red' : s === 'OFFLINE' ? 'default' : 'blue';
  return <Tag color={c}>{s}</Tag>;
}

const gb = (b?: number | null) => (b == null ? '-' : `${(b / 1024 ** 3).toFixed(1)} GB`);

export default function Drives() {
  const [drives, setDrives] = useState<DriveInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const nav = useNavigate();

  const load = async () => {
    const r = await api.listDrives();
    if (r.success) setDrives(r.data || []);
    else message.error(`${r.code}: ${r.message}`);
    setLoading(false);
  };
  useEffect(() => { load(); const id = setInterval(load, 5000); return () => clearInterval(id); }, []);

  return (
    <div>
      <Title level={3}>Tape Drives</Title>
      <Space style={{ marginBottom: 12 }} wrap>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>Refresh</Button>
        <span style={{ color: '#999', fontSize: 12 }}>来源 GET /api/v1/drives/list（sg_inq 序列号 / LOG 0x3d 温度 / MAM 介质SN；湿度本机型不开放读取）· auto refresh 5s</span>
      </Space>
      <Table<DriveInfo> rowKey="nst" loading={loading} dataSource={drives} pagination={false} size="small"
        scroll={{ x: 1280 }}
        columns={[
          { title: 'Drive', width: 96, fixed: 'left' as const,
            render: (_, d) => <b>Drive-{String(d.index + 1).padStart(2, '0')}</b> },
          { title: '设备', width: 110, render: (_, d) => (
              <span>{d.nst ? `/dev/${d.nst}` : '-'}<br /><span style={{ color: '#999', fontSize: 11 }}>{d.sg ? `/dev/${d.sg}` : ''}</span></span>) },
          { title: '位置', width: 190, render: (_, d) => (
              <span style={{ fontSize: 12 }}>
                SCSI {d.scsi_address || '-'}<br />
                {d.library
                  ? <>带库 {d.library.changer} · DTE{d.library.dte}{d.source_slot != null ? ` ←槽${d.source_slot}` : ''}</>
                  : <span style={{ color: '#999' }}>未在带库 DTE</span>}
              </span>) },
          { title: '型号', width: 150, render: (_, d) => (
              <span>{d.vendor} {d.model}<br /><span style={{ color: '#999', fontSize: 11 }}>FW {d.firmware || '-'}</span></span>) },
          { title: 'SN(带机)', dataIndex: 'serial', width: 130,
            render: (v: string) => v ? <code>{v}</code> : '-' },
          { title: '状态', dataIndex: 'status', width: 100, render: driveStatusTag },
          { title: '在机磁带', width: 170, render: (_, d) => d.loaded_tape
              ? <span><Tag color="blue">📼 {d.loaded_tape}</Tag>{d.media_serial && <div style={{ fontSize: 11, color: '#999' }}>SN {d.media_serial}</div>}</span>
              : '-' },
          { title: '温度', dataIndex: 'temperature', width: 110, render: (v: number | null) => (
              v == null ? <span style={{ color: '#999' }}>N/A</span> : <Tag color={v > 45 ? 'orange' : 'geekblue'}>{v} °C</Tag>) },
          { title: '湿度', width: 80, render: (_, d) => (d as any).humidity == null
              ? <span style={{ color: '#999' }}>N/A</span> : `${(d as any).humidity}%` },
          { title: '寿命', width: 120, render: (_, d) => (
              <span style={{ fontSize: 12 }}>
                {d.power_on_hours != null ? <>上电 {d.power_on_hours} h</> : '-'}
                {d.media_loads != null && <><br />装载 {d.media_loads} 次</>}
              </span>) },
          { title: 'TapeAlert', width: 110, render: (_, d) => d.tapealert.all_clear
              ? <Tag color="green">All Clear</Tag>
              : <Tag color="red">{d.tapealert.triggered_count} alerts</Tag> },
          { title: '健康', dataIndex: 'health', width: 110, render: (v: string, d) => (
              d.errors && d.errors.length
                ? <Tag color="orange" title={d.errors.join('; ')}>{v} · {d.errors.length} warn</Tag>
                : <Tag color={v === 'Healthy' ? 'green' : v === 'Warning' ? 'orange' : v === 'Critical' ? 'red' : 'default'}>{v}</Tag>) },
          { title: 'Action', width: 80, render: (_, d) => <Button type="link" size="small" onClick={() => nav(`/drives/${d.nst}`)}>View</Button> },
        ]} />
    </div>
  );
}
