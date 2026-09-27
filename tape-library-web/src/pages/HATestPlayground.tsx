import { useEffect, useRef, useState } from 'react';
import {
  Alert, Button, Card, Col, Input, InputNumber, message, Popconfirm, Row,
  Space, Statistic, Switch, Tag, Typography,
} from 'antd';
import {
  CaretRightOutlined, PauseOutlined, ReloadOutlined, ClearOutlined,
  VerticalAlignBottomOutlined,
} from '@ant-design/icons';
import { rawRequest } from '../api/client';
import { Chart } from '../components/Chart';
import type { ChartOption } from '../components/Chart';

const { Text } = Typography;

interface HaRound {
  ts: number; drive: number; tape: string; round: number;
  api_ms: { upload: number; download: number };
  task_s: { archive: number; archive_small: number; recall: number };
  bytes: { created: number; downloaded: number };
  verify: string; cache_pct: number;
  media_used_bytes: number; media_capacity_bytes: number; wall_s: number;
}
interface HaStatus {
  active: boolean; pid?: number;
  meta?: { run_id?: string; started_at?: string; params?: any };
  setup?: any; done?: any;
  summary: { rounds: number; rounds_ok: number; rounds_fail: number;
             bytes_created: number; mb_created: number; throughput_mb_s: number };
  rounds: HaRound[]; log_size: number;
}

const MB = 1048576;

export default function HATestPlayground() {
  const [st, setSt] = useState<HaStatus | null>(null);
  const [script, setScript] = useState('');
  const [apiBase, setApiBase] = useState('http://127.0.0.1:8001/api/v1');
  const [rounds, setRounds] = useState(2);
  const [bigMb, setBigMb] = useState(100);
  const [bigCount, setBigCount] = useState(10);
  const [smallMb, setSmallMb] = useState(1);
  const [smallCount, setSmallCount] = useState(0);
  const [fill, setFill] = useState(false);
  const [logText, setLogText] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const [wm, setWm] = useState<[number, number] | null>(null);
  const [unsaved, setUnsaved] = useState(false);
  const logOff = useRef(0);
  const logBox = useRef<HTMLPreElement>(null);
  const autoRef = useRef(true);
  const timer = useRef<ReturnType<typeof setInterval>>();

  useEffect(() => { autoRef.current = autoScroll; }, [autoScroll]);

  const poll = async () => {
    const s = await rawRequest('GET', '/archive/hatest/status');
    if (s.success) setSt(s.data);
    const l = await rawRequest('GET', '/archive/hatest/log',
      { query: { offset: logOff.current } });
    if (l.success && l.data) {
      if (l.data.text) setLogText((t) => (t + l.data.text).slice(-262144));
      logOff.current = l.data.next_offset ?? logOff.current;
      if (autoRef.current && logBox.current)
        logBox.current.scrollTop = logBox.current.scrollHeight;
    }
  };

  const loadScript = async () => {
    const s = await rawRequest('GET', '/archive/hatest/script');
    if (s.success) { setScript(s.data.script || ''); setUnsaved(false); }
  };

  useEffect(() => {
    loadScript();
    poll();
    rawRequest('GET', '/archive/cache', { query: { limit: 1 } }).then((r) => {
      if (r.success && r.data?.config?.watermarks_pct) setWm(r.data.config.watermarks_pct);
    });
    timer.current = setInterval(poll, 3000);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, []);

  const start = async () => {
    const r = await rawRequest('POST', '/archive/hatest/start', {
      body: {
        script: script || undefined,
        params: { api: apiBase, rounds, big_mb: bigMb, big_count: bigCount, small_mb: smallMb, small_count: smallCount, fill: fill ? 1 : 0 },
        confirm: true,
      },
    });
    if (r.success) {
      message.success(`HATest 已启动 pid=${r.data?.pid}（setsid 脱离网关，重启网关不死）`);
      setLogText(''); logOff.current = 0; poll();
    } else message.error(`${r.code}: ${r.message}`);
  };

  const stop = async () => {
    const r = await rawRequest('POST', '/archive/hatest/stop');
    if (r.success) { message.success('已停止'); poll(); }
    else message.error(`${r.code}: ${r.message}`);
  };

  const rs = st?.rounds || [];
  const labels = rs.map((_, i) => `R${i + 1}`);
  const sum = st?.summary;

  const base = (name: string, extra: any = {}): any => ({
    tooltip: { trigger: 'axis' },
    grid: { left: 48, right: 16, top: 30, bottom: 24 },
    xAxis: { type: 'category', data: labels },
    yAxis: { type: 'value', scale: true },
    series: [], legend: { top: 0, textStyle: { fontSize: 11 } },
    ...extra, name,
  });

  const msOpt: ChartOption = {
    ...base('ms'),
    yAxis: { type: 'value', name: 'ms', scale: true },
    series: [
      { name: '上传 api ms', type: 'line', data: rs.map((r) => r.api_ms?.upload), connectNulls: true },
      { name: '下载 api ms', type: 'line', data: rs.map((r) => r.api_ms?.download), connectNulls: true },
    ],
  } as ChartOption;

  const taskOpt: ChartOption = {
    ...base('s'),
    yAxis: { type: 'value', name: '秒', scale: true },
    series: [
      { name: '归档(大文件) s', type: 'line', data: rs.map((r) => r.task_s?.archive), connectNulls: true },
      { name: '归档(小文件) s', type: 'line', data: rs.map((r) => r.task_s?.archive_small), connectNulls: true },
      { name: '召回 s', type: 'line', data: rs.map((r) => r.task_s?.recall), connectNulls: true },
    ],
  } as ChartOption;

  let acc = 0;
  const dataOpt: ChartOption = {
    ...base('MB'),
    yAxis: { type: 'value', name: 'MB' },
    series: [
      { name: '累计写入 MB', type: 'line', areaStyle: {}, data: rs.map((r) => (acc += (r.bytes?.created || 0) / MB) && Math.round(acc * 10) / 10) },
    ],
  } as ChartOption;

  const cacheOpt: ChartOption = {
    ...base('cache'),
    yAxis: { type: 'value', name: '%', max: 100 },
    series: [{
      name: '缓存水线 %', type: 'line', data: rs.map((r) => r.cache_pct),
      markLine: wm ? {
        silent: true, symbol: 'none',
        data: [
          { yAxis: wm[1], lineStyle: { color: '#faad14', type: 'dashed' }, label: { formatter: `high ${wm[1]}%` } },
          { yAxis: wm[0], lineStyle: { color: '#52c41a', type: 'dashed' }, label: { formatter: `low ${wm[0]}%` } },
        ],
      } : undefined,
    }],
  } as ChartOption;

  const last = rs[rs.length - 1];
  const doneEvt = st?.done;
  const active = !!st?.active;

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={12}>
      {!st && <Alert type="warning" showIcon message="后端未提供 /archive/hatest/*（需 v1.4.0+）——请先部署带 HATest 控制器的网关" />}

      {/* ============ 上区：统计汇总 + 曲线图 ============ */}
      <Row gutter={8}>
        <Col span={4}><Card size="small"><Statistic title="运行态"
          value={active ? 'RUNNING' : (doneEvt ? (doneEvt.event === 'done' ? 'DONE' : 'ERROR') : 'IDLE')}
          valueStyle={{ color: active ? '#1677ff' : doneEvt?.event === 'error' ? '#ff4d4f' : undefined, fontSize: 22 }} />
          <Text type="secondary" style={{ fontSize: 11 }}>{st?.meta?.run_id || '-'} · pid {st?.pid ?? '-'}</Text>
        </Card></Col>
        <Col span={4}><Card size="small"><Statistic title="轮次 通过/失败"
          value={`${sum?.rounds_ok ?? 0}/${sum?.rounds_fail ?? 0}`} valueStyle={{ fontSize: 22 }} />
          <Text type="secondary" style={{ fontSize: 11 }}>共 {sum?.rounds ?? 0} 轮 · {doneEvt?.reason || (active ? '进行中' : '-')}</Text>
        </Card></Col>
        <Col span={4}><Card size="small"><Statistic title="测试数据量" value={sum?.mb_created ?? 0} suffix="MB" valueStyle={{ fontSize: 22 }} />
          <Text type="secondary" style={{ fontSize: 11 }}>吞吐 {sum?.throughput_mb_s ?? 0} MB/s</Text>
        </Card></Col>
        <Col span={4}><Card size="small"><Statistic title="介质水位"
          value={last && last.media_capacity_bytes ? (Math.round(last.media_used_bytes / last.media_capacity_bytes * 1000) / 10) : 0} suffix="%" valueStyle={{ fontSize: 22 }} />
          <Text type="secondary" style={{ fontSize: 11 }}>{last?.tape || '-'} · {last ? (last.media_used_bytes / MB / 1024).toFixed(1) : 0}/{(last?.media_capacity_bytes || 0) / MB / 1024} GiB</Text>
        </Card></Col>
        <Col span={4}><Card size="small"><Statistic title="校验"
          value={sum && sum.rounds ? Math.round(sum.rounds_ok * 1000 / sum.rounds) / 10 : 0} suffix="% PASS" valueStyle={{ fontSize: 22, color: sum?.rounds_fail ? '#faad14' : '#52c41a' }} />
          <Text type="secondary" style={{ fontSize: 11 }}>sha256 逐轮比对</Text>
        </Card></Col>
        <Col span={4}><Card size="small"><Statistic title="测试计划" value={st?.setup ? `${st.setup.drives}×${(st.setup.tapes || '').split(' ').filter(Boolean).length}` : '-'} valueStyle={{ fontSize: 22 }} />
          <Text type="secondary" style={{ fontSize: 11 }}>带机×磁带 · {st?.setup?.format || '-'} 格式</Text>
        </Card></Col>
      </Row>
      <Row gutter={8}>
        <Col span={12}><Card size="small" title="API 调用响应时间 (ms)"><Chart option={msOpt} height={190} /></Card></Col>
        <Col span={12}><Card size="small" title="任务执行时间 (秒：归档/召回)"><Chart option={taskOpt} height={190} /></Card></Col>
        <Col span={12}><Card size="small" title="测试数据量 (累计 MB)"><Chart option={dataOpt} height={190} /></Card></Col>
        <Col span={12}><Card size="small" title="缓存空间水线 (%)"><Chart option={cacheOpt} height={190} /></Card></Col>
      </Row>

      {/* ============ 中区：测试脚本 + 参数 ============ */}
      <Card size="small" title={
        <Space size={6}>
          <span>HATest 测试脚本（curl 调 API · 可编辑）</span>
          {unsaved && <Tag color="orange">已修改</Tag>}
          <Tag color={active ? 'blue' : 'default'}>{active ? '运行中——编辑不影响当前运行' : '空闲'}</Tag>
        </Space>
      } extra={
        <Space size={6}>
          <Popconfirm
            title="启动 HATest 压测（L3）"
            description={`将创建测试数据并占用带机${fill ? '（写满模式可能持续数小时）' : ''}：rounds=${rounds} big=${bigCount}×${bigMb}MB smalls=${smallCount}×${smallMb}MB。确认执行？`}
            okText="启动" okButtonProps={{ danger: true }} cancelText="取消"
            onConfirm={start}>
            <Button type="primary" danger icon={<CaretRightOutlined />} disabled={!st || active}>运行</Button>
          </Popconfirm>
          <Popconfirm title="停止 HATest？" description="将 kill 测试进程组" okText="停止" okButtonProps={{ danger: true }} onConfirm={stop}>
            <Button icon={<PauseOutlined />} disabled={!active}>停止</Button>
          </Popconfirm>
          <Button icon={<ReloadOutlined />} onClick={loadScript}>恢复默认脚本</Button>
        </Space>
      }>
        <Space wrap size={6} style={{ marginBottom: 8 }}>
          <Text strong>API:</Text>
          <Input size="small" style={{ width: 250 }} value={apiBase} onChange={(e) => setApiBase(e.target.value)} />
          <Text strong>轮数(0=不限):</Text>
          <InputNumber size="small" min={0} max={100000} value={rounds} onChange={(v) => setRounds(v || 0)} />
          <Text strong>大文件 MB:</Text>
          <InputNumber size="small" min={1} max={16384} value={bigMb} onChange={(v) => setBigMb(v || 100)} />
          <Text strong>大文件个数:</Text>
          <InputNumber size="small" min={1} max={1000} value={bigCount} onChange={(v) => setBigCount(v || 10)} />
          <Text strong>小文件 MB:</Text>
          <InputNumber size="small" min={1} max={1024} value={smallMb} onChange={(v) => setSmallMb(v || 1)} />
          <Text strong>小文件个数:</Text>
          <InputNumber size="small" min={0} max={1000} value={smallCount} onChange={(v) => setSmallCount(v || 0)} />
          <Text strong>写满介质:</Text>
          <Switch size="small" checked={fill} onChange={setFill} />
          {fill && rounds > 0 && <Tag color="orange">轮数优先（到轮即停）</Tag>}
          {!fill && rounds === 0 && <Tag color="red">无停止条件——后端将拒绝启动</Tag>}
        </Space>
        <Input.TextArea
          rows={14} value={script}
          onChange={(e) => { setScript(e.target.value); setUnsaved(true); }}
          style={{ fontFamily: 'ui-monospace, Menlo, Consolas, monospace', fontSize: 11.5, lineHeight: 1.45 }}
          spellCheck={false} />
        <Text type="secondary" style={{ fontSize: 11 }}>
          脚本经 setsid 脱离网关进程执行：网关重启压测不死（WAIT_GATEWAY 退避重试 ≤30 分钟）；指标每轮一行 JSONL 落盘，图表轮询 3s 刷新。
        </Text>
      </Card>

      {/* ============ 下区：原始输出 ============ */}
      <Card size="small" title={
        <Space size={6}><span>测试脚本原始输出</span>
          <Tag color={active ? 'blue' : 'default'}>{active ? 'LIVE' : 'IDLE'}</Tag>
          <Text type="secondary" style={{ fontSize: 11 }}>log_size {st?.log_size ?? 0}B · 每 3s 增量拉取</Text>
        </Space>
      } extra={
        <Space size={6}>
          <Text type="secondary" style={{ fontSize: 11 }}>自动滚动</Text>
          <Switch size="small" checked={autoScroll} onChange={setAutoScroll} />
          <Button size="small" icon={<VerticalAlignBottomOutlined />} onClick={() => { if (logBox.current) logBox.current.scrollTop = logBox.current.scrollHeight; }}>到底部</Button>
          <Button size="small" icon={<ClearOutlined />} onClick={() => setLogText('')}>清屏</Button>
        </Space>
      }>
        <pre ref={logBox}
          style={{ margin: 0, maxHeight: 380, overflow: 'auto', background: '#0d1117', color: '#c9d1d9', padding: 10, borderRadius: 6, fontSize: 11, lineHeight: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
          {logText || '（暂无输出——点击「运行」后此处实时滚动脚本 stdout/stderr）'}
        </pre>
      </Card>
    </Space>
  );
}
