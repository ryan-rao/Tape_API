import { useEffect, useState } from 'react';
import { Card, Col, Row, Statistic, Typography, Switch, Button, Tag, List } from 'antd';
import {
  DatabaseOutlined, HddOutlined, PlayCircleOutlined, CheckCircleOutlined,
  WarningOutlined, CloseCircleOutlined, ReloadOutlined,
} from '@ant-design/icons';
import { api } from '../api/client';
import { Chart } from '../components/Chart';
import type * as echarts from 'echarts';
import type { LibraryInfo, DriveInfo, TestSession } from '../types';

const { Title } = Typography;

function healthColor(h: string): string {
  return h === 'Healthy' || h === 'Online' || h === 'PASS' ? '#52c41a'
    : h === 'Warning' ? '#faad14' : h === 'Critical' || h === 'Error' || h === 'FAIL' ? '#ff4d4f'
    : h === 'Running' ? '#1677ff' : '#8c8c8c';
}

export default function Dashboard() {
  const [libs, setLibs] = useState<LibraryInfo[]>([]);
  const [drives, setDrives] = useState<DriveInfo[]>([]);
  const [sessions, setSessions] = useState<TestSession[]>([]);
  const [auto, setAuto] = useState(true);
  const [tick, setTick] = useState(0);

  const load = async () => {
    const [l, d, s] = await Promise.all([api.listLibraries(), api.listDrives(), api.listSessions()]);
    if (l.success) setLibs(l.data || []);
    if (d.success) setDrives(d.data || []);
    if (s.success) setSessions((s.data || []).slice(0, 8));
    setTick((t) => t + 1);
  };

  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!auto) return;
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [auto]);

  const onlineLibs = libs.filter((x) => x.status === 'Healthy' || x.status === 'Online').length;
  const warnLibs = libs.filter((x) => x.status === 'Warning').length;
  const onlineDrives = drives.filter((d) => d.status !== 'OFFLINE' && d.status !== 'ERROR').length;
  const warnDrives = drives.filter((d) => d.health === 'Warning' || d.tapealert.triggered_count > 0).length;
  const totalTapes = libs.reduce((a, b) => a + b.tape_count, 0);
  const loadedTapes = libs.reduce((a, b) => a + b.loaded_drives, 0);
  const passed = sessions.filter((s) => s.status === 'PASS').length;
  const failed = sessions.filter((s) => s.status === 'FAIL').length;

  const pie = (name: string, data: [string, number][]): echarts.EChartsOption => ({
    title: { text: name, left: 'center', textStyle: { fontSize: 13 } },
    tooltip: { trigger: 'item' as const },
    series: [{
      type: 'pie', radius: ['40%', '65%'], label: { show: false },
      data: data.map(([n, v]) => ({ name: n, value: v, itemStyle: { color: healthColor(n) } })),
    }],
  });

  return (
    <div>
      <Title level={3}>Tape Library Management</Title>
      <div style={{ marginBottom: 16 }}>
        <Tag color={api.mode === 'mock' ? 'purple' : 'green'}>API MODE: {api.mode.toUpperCase()}</Tag>
        <Switch checkedChildren="Auto Refresh 10s" unCheckedChildren="Auto OFF" checked={auto} onChange={setAuto} />
        <Button icon={<ReloadOutlined />} onClick={load} style={{ marginLeft: 8 }}>Refresh Now</Button>
        <span style={{ marginLeft: 12, color: '#999', fontSize: 12 }}>updated #{tick}</span>
      </div>

      <Row gutter={16}>
        <Col span={6}>
          <Card hoverable><Statistic title="Tape Libraries" value={libs.length} prefix={<DatabaseOutlined />} />
            <div style={{ marginTop: 8 }}>
              <Tag color="green">{onlineLibs} Online</Tag>
              <Tag color="orange">{warnLibs} Warning</Tag>
              <Tag color="red">{libs.length - onlineLibs - warnLibs} Critical</Tag>
            </div></Card>
        </Col>
        <Col span={6}>
          <Card hoverable><Statistic title="Tape Drives" value={drives.length} prefix={<HddOutlined />} />
            <div style={{ marginTop: 8 }}>
              <Tag color="green">{onlineDrives} Online</Tag>
              <Tag color="orange">{warnDrives} Warning</Tag>
              <Tag>{drives.length - onlineDrives} Offline</Tag>
            </div></Card>
        </Col>
        <Col span={6}>
          <Card hoverable><Statistic title="Tapes" value={totalTapes} prefix={<PlayCircleOutlined />} />
            <div style={{ marginTop: 8 }}>
              <Tag color="blue">{loadedTapes} Loaded</Tag>
              <Tag color="green">{totalTapes - loadedTapes} Available</Tag>
            </div></Card>
        </Col>
        <Col span={6}>
          <Card hoverable><Statistic title="Test Sessions" value={sessions.length} />
            <div style={{ marginTop: 8 }}>
              <Tag color="green"><CheckCircleOutlined /> {passed} PASS</Tag>
              <Tag color="red"><CloseCircleOutlined /> {failed} FAIL</Tag>
              <Tag color="blue">{sessions.filter((s) => s.status === 'RUNNING').length} Running</Tag>
            </div></Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={8}><Card size="small"><Chart height={220} option={pie('Library Health', [
          ['Healthy', Math.max(onlineLibs, 0)], ['Warning', warnLibs],
          ['Critical', libs.length - onlineLibs - warnLibs]])} /></Card></Col>
        <Col span={8}><Card size="small"><Chart height={220} option={pie('Drive Status', [
          ['Healthy', onlineDrives - warnDrives], ['Warning', warnDrives], ['Offline', drives.length - onlineDrives]])} /></Card></Col>
        <Col span={8}><Card size="small"><Chart height={220} option={pie('Tape Status', [
          ['Available', totalTapes - loadedTapes], ['Loaded', loadedTapes]])} /></Card></Col>
      </Row>

      <Card size="small" title="Recent Test Sessions" style={{ marginTop: 16 }}>
        <List size="small" dataSource={sessions} locale={{ emptyText: 'No test sessions yet' }}
          renderItem={(s) => (
            <List.Item>
              <Tag color={s.status === 'PASS' ? 'green' : s.status === 'FAIL' ? 'red' : 'blue'}>{s.status}</Tag>
              <span style={{ fontFamily: 'monospace' }}>{s.session_id}</span>
              <span>{s.kind.toUpperCase()} · {s.drive} · {s.size_mb} MiB · {s.throughput_mbs} MiB/s</span>
              <span style={{ color: '#999' }}>{s.started_at}</span>
            </List.Item>
          )} />
      </Card>
    </div>
  );
}
