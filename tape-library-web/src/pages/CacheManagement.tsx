// Cache Management：归档网关缓存管理（目录树 + 文件详情 + 空间/数据量）
// 数据源：/api/v1/archive/tree + /cache + /stats（v1.2.2+）
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, Button, Card, Col, Descriptions, Empty, Input, message, Popconfirm, Progress,
  Row, Segmented, Space, Table, Tag, Tooltip, Tree, Typography,
} from 'antd';
import type { DataNode } from 'antd/es/tree';
import {
  DatabaseOutlined, DownloadOutlined, FileOutlined, FolderOpenOutlined,
  FolderOutlined, ReloadOutlined, SaveOutlined, ScissorOutlined,
} from '@ant-design/icons';
import { rawRequest } from '../api/client';

const { Title, Text } = Typography;

type AnyObj = Record<string, any>;

const STATE_COLORS: Record<string, string> = {
  cached: 'blue', archiving: 'orange', archived: 'green', failed: 'red',
};
const CSTATE_COLORS: Record<string, string> = {
  buffering: 'blue', flushing: 'orange', archiving: 'orange',
  archived: 'green', aborted: 'red',
};
const TAPE_STATE_COLORS: Record<string, string> = {
  appendable: 'green', scratch: 'blue', full: 'default', faulted: 'red', unknown: 'default',
};

function fmtBytes(n?: number | string | null): string {
  if (n === null || n === undefined) return '-';
  let v = Number(n);
  if (Number.isNaN(v)) return String(n);
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}
function fmtTime(s?: string | null): string {
  if (!s) return '-';
  return String(s).replace('T', ' ').replace(/\.\d+.*$/, '').replace(/\+.*$/, '');
}
function fmtPct(a?: number | string | null, b?: number | string | null): number {
  const x = Number(a), y = Number(b);
  if (!y) return 0;
  return Math.min(100, Math.round((x / y) * 1000) / 10);
}

interface TreeFile { name: string; path: string; size_bytes: number; meta: AnyObj | null }
interface TreeDir { name: string; path: string; size_bytes: number; children: TreeFile[] }

export default function CacheManagement() {
  const [treeData, setTreeData] = useState<AnyObj | null>(null);
  const [data, setData] = useState<AnyObj | null>(null);
  const [stats, setStats] = useState<AnyObj | null>(null);
  const [entries, setEntries] = useState<AnyObj[]>([]);
  const [kindFilter, setKindFilter] = useState('all');
  const [dirtyFilter, setDirtyFilter] = useState('all');
  const [selected, setSelected] = useState<TreeFile | null>(null);
  const [selectedDir, setSelectedDir] = useState<TreeDir | null>(null);
  const [busy, setBusy] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const timer = useRef<any>(null);

  async function refresh() {
    setLoading(true);
    const query: Record<string, string | number> = { limit: 300 };
    if (kindFilter !== 'all') query.kind = kindFilter;
    if (dirtyFilter !== 'all') query.dirty = dirtyFilter;
    const [t, c, s] = await Promise.all([
      rawRequest('GET', '/archive/tree'),
      rawRequest('GET', '/archive/cache', { query }),
      rawRequest('GET', '/archive/stats'),
    ]);
    if (!c.success) { setErr(`${c.code}: ${c.message}`); setLoading(false); return; }
    setErr('');
    setTreeData(t.success ? t.data : null);
    setData(c.data);
    setEntries(c.data?.items || []);
    if (s.success) setStats(s.data);
    setLoading(false);
  }

  useEffect(() => {
    refresh();
    timer.current = setInterval(refresh, 10000);
    return () => clearInterval(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kindFilter, dirtyFilter]);

  async function evictNow() {
    const r = await rawRequest('POST', '/archive/evict');
    if (r.success) {
      const d = r.data || {};
      message.success(d.action === 'none'
        ? `未超水位（${fmtPct(data?.stats?.total_bytes, data?.stats?.quota_bytes)}%），无需淘汰`
        : `已淘汰 ${d.evicted} 项，释放 ${fmtBytes(d.freed_bytes)}`);
    } else message.error(`${r.code}: ${r.message}`);
    refresh();
  }

  async function archiveFile(fid: string, name: string) {
    setBusy(`ar-${fid}`);
    const r = await rawRequest('POST', `/archive/files/${fid}/archive`);
    setBusy('');
    if (!r.success) { message.error(`${r.code}: ${r.message}`); return; }
    message.success(r.data?.route === 'container'
      ? '已密封聚合容器，即将打包落带' : '已排队直写磁带');
    refresh();
  }

  async function recallFile(fid: string, name: string) {
    setBusy(`rc-${fid}`);
    const key = `rc-${fid}`;
    const hide = message.loading({ content: `召回 ${name}：从磁带复制到磁盘…`, key, duration: 0 });
    try {
      const r = await rawRequest('POST', `/archive/files/${fid}/recall`);
      if (!r.success) { hide(); message.error({ content: `${r.code}: ${r.message}`, key }); return; }
      if (r.http_status === 202 && r.data?.job_id) {
        const jobId: string = r.data.job_id;
        for (let i = 0; i < 120; i++) {
          await new Promise((res) => setTimeout(res, 3000));
          const j = await rawRequest('GET', `/jobs/${jobId}`);
          const st = j.data?.state;
          if (st === 'succeeded') break;
          if (st === 'failed' || !j.success) {
            hide(); message.error({ content: `召回失败: ${j.data?.error?.message || j.message}`, key }); setBusy(''); return;
          }
        }
      }
      hide();
      message.success({ content: `${name} 已复制到磁盘：${r.data?.path || 'recall 目录'}`, key });
    } finally { setBusy(''); }
    refresh();
  }

  // 目录树数据
  const treeNodes: DataNode[] = useMemo(() => {
    if (!treeData?.root) return [];
    const root = treeData.root;
    return [{
      title: (
        <Space size={4}>
          <DatabaseOutlined />
          <Text strong>{root.name}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{fmtBytes(root.size_bytes)}</Text>
        </Space>
      ),
      key: 'root',
      selectable: false,
      children: (root.children || []).map((d: TreeDir) => ({
        title: (
          <Space size={4}>
            <FolderOutlined style={{ color: '#faad14' }} />
            <Text strong>{d.name}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {(d.children || []).length} 项 · {fmtBytes(d.size_bytes)}
            </Text>
          </Space>
        ),
        key: d.name,
        selectable: false,
        children: (d.children || []).map((f: TreeFile) => {
          const m = f.meta;
          const st = m?.file?.state;
          return {
            title: (
              <Space size={6}>
                <FileOutlined style={{ color: m?.type === 'container' ? '#2f54eb' : '#8c8c8c' }} />
                <Text style={{ fontSize: 12 }} ellipsis={{ tooltip: f.name }}>{f.name}</Text>
                <Text type="secondary" style={{ fontSize: 11 }}>{fmtBytes(f.size_bytes)}</Text>
                {m?.type === 'container' && <Tag color="geekblue" style={{ marginInlineEnd: 0 }}>容器</Tag>}
                {st && <Tag color={STATE_COLORS[st]} style={{ marginInlineEnd: 0 }}>{st}</Tag>}
              </Space>
            ),
            key: f.path,
            isLeaf: true,
          };
        }),
      })),
    }];
  }, [treeData]);

  const cs = data?.stats || {};
  const cfg = data?.config || {};
  const dirs: AnyObj[] = data?.dirs || [];
  const usedPct = fmtPct(cs.total_bytes, cs.quota_bytes);
  const dirtyPct = cs.total_bytes ? fmtPct(cs.dirty_bytes, cs.total_bytes) : 0;
  const highPct = Number(cfg.watermarks_pct?.[1] ?? 85);
  const mediaStats = stats?.tape;

  const fm = selected?.meta?.file;   // 文件元数据视图
  const cm = selected?.meta?.container; // 容器元数据视图

  if (err) {
    return (
      <div>
        <Title level={3}>Cache Management 缓存管理</Title>
        <Alert type="error" showIcon message="缓存接口不可用" description={err} />
      </div>
    );
  }

  return (
    <div>
      <Title level={3}>Cache Management 缓存管理</Title>
      <Space style={{ margin: '8px 0 12px' }} wrap>
        <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>刷新</Button>
        <Popconfirm title="立即按水位淘汰净缓存？（只淘汰已安全落带的净数据）" onConfirm={evictNow}>
          <Button icon={<ScissorOutlined />}>强制淘汰</Button>
        </Popconfirm>
        <Text type="secondary">
          脏数据（未落带）绝不淘汰；净数据按 LRU 在高水位 {highPct}% 触发淘汰、降到低水位 {cfg.watermarks_pct?.[0] ?? 70}% 停止
        </Text>
      </Space>

      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        <Col span={8}>
          <Card size="small" title="缓存空间使用">
            <Progress type="dashboard" percent={usedPct} size={140}
              status={usedPct > highPct ? 'exception' : 'normal'}
              format={() => (<span style={{ fontSize: 14 }}>{usedPct}%<br />
                <Text type="secondary" style={{ fontSize: 12 }}>{fmtBytes(cs.total_bytes)}</Text></span>)} />
            <Descriptions size="small" column={1} style={{ marginTop: 8 }}>
              <Descriptions.Item label="配额">{fmtBytes(cs.quota_bytes)}</Descriptions.Item>
              <Descriptions.Item label="高/低水位线">
                {fmtBytes(cs.high_bytes)} / {fmtBytes(cs.low_bytes)}
              </Descriptions.Item>
              <Descriptions.Item label="磁盘剩余">
                <b style={{ color: Number(cs.fs_free_bytes) < 50 * 1024 ** 3 ? '#cf1322' : undefined }}>
                  {fmtBytes(cs.fs_free_bytes)}
                </b>
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" title="脏 / 净数据量">
            <Progress percent={dirtyPct} strokeColor="#fa8c16"
              format={() => `脏 ${fmtBytes(cs.dirty_bytes)}`} />
            <Progress percent={100 - dirtyPct} strokeColor="#52c41a" showInfo={false} />
            <Descriptions size="small" column={1} style={{ marginTop: 4 }}>
              <Descriptions.Item label="净数据（可淘汰）">
                <b style={{ color: '#389e0d' }}>{fmtBytes(cs.clean_bytes)}</b>
              </Descriptions.Item>
              <Descriptions.Item label="条目总数">{entries.length} / {data?.count}</Descriptions.Item>
              <Descriptions.Item label="累计淘汰">
                {stats?.metrics?.evictions ?? 0} 次 · {fmtBytes(stats?.metrics?.evicted_bytes)}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" title="目录数据量" extra={<Tooltip title={cfg.cache_dir}><FolderOpenOutlined /></Tooltip>}>
            <Descriptions size="small" column={1}>
              {dirs.map((d) => (
                <Descriptions.Item key={d.dir} label={d.dir}>
                  <Tooltip title={d.path} placement="left"><span>{fmtBytes(d.used_bytes)}</span></Tooltip>
                </Descriptions.Item>
              ))}
              <Descriptions.Item label="磁带累计读/写">
                {fmtBytes(stats?.metrics?.bytes_from_tape)} / {fmtBytes(stats?.metrics?.bytes_to_tape)}
              </Descriptions.Item>
              <Descriptions.Item label="召回命中/未命中">
                {stats?.metrics?.recall_hits ?? 0} / {stats?.metrics?.recall_misses ?? 0}
              </Descriptions.Item>
              <Descriptions.Item label="磁带介质">
                {(mediaStats?.blocks || []).map((b: AnyObj, i: number) => (
                  <Tooltip key={b.barcode || i} title={`${fmtBytes(b.bytes)} 已用`}>
                    <Tag style={{ marginInlineEnd: 4 }}>{b.barcode} · {b.blocks} 块</Tag>
                  </Tooltip>))
                  || (mediaStats?.media ? `${mediaStats.media} 卷` : '-')}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
      </Row>

      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        <Col span={10}>
          <Card size="small" title={`缓存目录树（${treeData?.file_count ?? 0} 文件${treeData?.unmatched ? ` · ${treeData.unmatched} 未关联` : ''}）`}
            styles={{ body: { maxHeight: 420, overflow: 'auto', padding: '4px 8px' } }}>
            {treeNodes.length
              ? <Tree showLine blockNode defaultExpandAll treeData={treeNodes}
                  selectedKeys={selected ? [selected.path] : []}
                  onSelect={(keys, info) => {
                    const n = info.node as AnyObj;
                    if (!n.isLeaf) return;
                    // 在原始数据里找回完整节点（含 meta）
                    for (const d of treeData?.root?.children || []) {
                      for (const f of d.children || []) {
                        if (f.path === keys[0]) { setSelected(f); setSelectedDir(d); return; }
                      }
                    }
                  }} />
              : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="目录树加载中" />}
          </Card>
        </Col>
        <Col span={14}>
          <Card size="small" title="文件详情" styles={{ body: { maxHeight: 420, overflow: 'auto' } }}>
            {!selected && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="点击左侧目录树中的文件查看详情" />}
            {selected && (
              <Space direction="vertical" style={{ width: '100%' }} size={8}>
                <div>
                  <Space wrap>
                    {selected.meta?.type === 'container' ? <Tag color="geekblue">聚合容器</Tag> : <Tag>文件</Tag>}
                    <Text strong copyable>{selected.name}</Text>
                    <Text type="secondary">· {fmtBytes(selected.size_bytes)}</Text>
                  </Space>
                  <div style={{ marginTop: 4 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>磁盘绝对路径：</Text>
                    <Text code style={{ fontSize: 12 }} copyable>{selected.path}</Text>
                  </div>
                  {selectedDir && (
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>缓存分区：</Text>
                      <Tag>{selectedDir.name}</Tag>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        （upload 待归档 / containers 聚合包 / recall 召回回填）
                      </Text>
                    </div>
                  )}
                </div>

                {/* 文件元数据 */}
                {selected.meta?.type === 'file' && fm && (
                  <>
                    <Descriptions size="small" bordered column={2} title="文件状态">
                      <Descriptions.Item label="文件 ID" span={2}>
                        <Text code style={{ fontSize: 11 }} copyable>{fm.file_id}</Text>
                      </Descriptions.Item>
                      <Descriptions.Item label="状态">
                        <Tag color={STATE_COLORS[fm.state]}>{fm.state}</Tag>
                        {fm.error && <Tooltip title={fm.error}><Tag color="red">错误</Tag></Tooltip>}
                      </Descriptions.Item>
                      <Descriptions.Item label="存储层">
                        <Tag>{fm.storage === 'container' ? '聚合包' : fm.storage === 'tape' ? '磁带' : '缓存'}</Tag>
                        {fm.kind === 'container_member' && <Tag color="cyan">聚合成员</Tag>}
                      </Descriptions.Item>
                      <Descriptions.Item label="归档时间">{fmtTime(fm.archived_at)}</Descriptions.Item>
                      <Descriptions.Item label="召回次数">
                        {fm.recalls?.n ?? 0} 次{fm.recalls?.last ? ` · 最近 ${fmtTime(fm.recalls.last)}` : ''}
                      </Descriptions.Item>
                      <Descriptions.Item label="创建时间">{fmtTime(fm.created_at)}</Descriptions.Item>
                      <Descriptions.Item label="最近访问">{fmtTime(fm.last_access_at)}</Descriptions.Item>
                      {fm.sha256 && (
                        <Descriptions.Item label="SHA256" span={2}>
                          <Text code style={{ fontSize: 11 }} ellipsis={{ tooltip: fm.sha256 }}>{fm.sha256}</Text>
                        </Descriptions.Item>
                      )}
                    </Descriptions>

                    <Descriptions size="small" bordered column={2} title="磁带存储位置">
                      <Descriptions.Item label="磁带（条码）">
                        {fm.media_barcode
                          ? <Tag color={TAPE_STATE_COLORS[fm.tape?.state || '']}>{fm.media_barcode}</Tag>
                          : <Text type="secondary">未落带</Text>}
                      </Descriptions.Item>
                      <Descriptions.Item label="磁带块号">
                        {fm.tape_block_index ?? '-'}
                      </Descriptions.Item>
                      {fm.container_id && (
                        <>
                          <Descriptions.Item label="所在容器" span={2}>
                            <Tooltip title={fm.container_id}>
                              <Text code style={{ fontSize: 11 }}>
                                {String(fm.container_id).slice(0, 8)}…
                              </Text>
                            </Tooltip>
                            <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                              容器内偏移 {fmtBytes(fm.offset_in_container)}
                            </Text>
                          </Descriptions.Item>
                        </>
                      )}
                      {fm.tape && (
                        <>
                          <Descriptions.Item label="磁带用量">
                            <Progress percent={fm.tape.used_pct ?? 0} size="small"
                              style={{ width: 140 }}
                              format={() => `${fmtBytes(fm.tape.used_bytes)} / ${fmtBytes(fm.tape.capacity_bytes)}`} />
                          </Descriptions.Item>
                          <Descriptions.Item label="磁带状态">
                            <Tag color={TAPE_STATE_COLORS[fm.tape.state]}>{fm.tape.state}</Tag>
                            · 挂载 {fm.tape.mount_count} 次
                          </Descriptions.Item>
                          <Descriptions.Item label="块记录数">{fm.tape.block_records}</Descriptions.Item>
                          <Descriptions.Item label="最后文件标记">{fm.tape.last_filemark ?? '-'}</Descriptions.Item>
                        </>
                      )}
                    </Descriptions>

                    <Space>
                      {(fm.state === 'cached' || fm.state === 'failed') && (
                        <Button size="small" type="primary" ghost icon={<SaveOutlined />}
                          loading={busy === `ar-${fm.file_id}`}
                          onClick={() => archiveFile(fm.file_id, fm.filename)}>归档到磁带</Button>
                      )}
                      {fm.state === 'archived' && (
                        <Button size="small" icon={<DownloadOutlined />}
                          loading={busy === `rc-${fm.file_id}`}
                          onClick={() => recallFile(fm.file_id, fm.filename)}>从磁带召回</Button>
                      )}
                    </Space>
                  </>
                )}

                {/* 容器元数据 */}
                {selected.meta?.type === 'container' && (
                  <>
                    {cm ? (
                      <>
                        <Descriptions size="small" bordered column={2} title="容器状态">
                          <Descriptions.Item label="容器 ID" span={2}>
                            <Text code style={{ fontSize: 11 }} copyable>{cm.container_id}</Text>
                          </Descriptions.Item>
                          <Descriptions.Item label="状态">
                            <Tag color={CSTATE_COLORS[cm.state]}>{cm.state}</Tag>
                          </Descriptions.Item>
                          <Descriptions.Item label="成员文件">{cm.file_count} 个</Descriptions.Item>
                          <Descriptions.Item label="容器大小">{fmtBytes(cm.size_bytes)}</Descriptions.Item>
                          <Descriptions.Item label="归档时间">{fmtTime(cm.archived_at)}</Descriptions.Item>
                          <Descriptions.Item label="成员清单" span={2}>
                            {(cm.members || []).length
                              ? (cm.members as string[]).map((m) => (
                                <Tooltip key={m} title={m}>
                                  <Tag style={{ fontSize: 11 }}>{String(m).slice(0, 8)}</Tag>
                                </Tooltip>))
                              : <Text type="secondary">-</Text>}
                          </Descriptions.Item>
                          {cm.archive_sha256 && (
                            <Descriptions.Item label="归档 SHA256" span={2}>
                              <Text code style={{ fontSize: 11 }} ellipsis={{ tooltip: cm.archive_sha256 }}>{cm.archive_sha256}</Text>
                            </Descriptions.Item>
                          )}
                        </Descriptions>
                        <Descriptions size="small" bordered column={2} title="磁带存储位置">
                          <Descriptions.Item label="磁带（条码）">
                            {cm.media_barcode
                              ? <Tag color={TAPE_STATE_COLORS[cm.tape?.state || '']}>{cm.media_barcode}</Tag>
                              : <Text type="secondary">未落带</Text>}
                          </Descriptions.Item>
                          <Descriptions.Item label="磁带块号">{cm.tape_block_index ?? '-'}</Descriptions.Item>
                          <Descriptions.Item label="带内偏移">{fmtBytes(cm.offset_on_tape)}</Descriptions.Item>
                          <Descriptions.Item label="带内长度">{fmtBytes(cm.length_on_tape)}</Descriptions.Item>
                          {cm.tape && (
                            <>
                              <Descriptions.Item label="磁带用量" span={2}>
                                <Progress percent={cm.tape.used_pct ?? 0} size="small"
                                  format={() => `${fmtBytes(cm.tape.used_bytes)} / ${fmtBytes(cm.tape.capacity_bytes)}`} />
                              </Descriptions.Item>
                              <Descriptions.Item label="磁带状态">
                                <Tag color={TAPE_STATE_COLORS[cm.tape.state]}>{cm.tape.state}</Tag>
                                · 挂载 {cm.tape.mount_count} 次
                              </Descriptions.Item>
                              <Descriptions.Item label="块记录数">{cm.tape.block_records}</Descriptions.Item>
                            </>
                          )}
                        </Descriptions>
                      </>
                    ) : <Alert type="info" showIcon message="容器无元数据（可能是残留文件）" />}
                  </>
                )}

                {!selected.meta && (
                  <Alert type="warning" showIcon message="未关联元数据"
                    description="磁盘上存在该文件，但数据库中没有匹配记录（可能是 selfheal 前的残留或外部写入）。" />
                )}
              </Space>
            )}
          </Card>
        </Col>
      </Row>

      <Card size="small" title={`缓存条目 (${entries.length})`}
        extra={(
          <Space>
            <Segmented value={kindFilter} onChange={(v) => setKindFilter(v as string)} options={[
              { value: 'all', label: '全部' }, { value: 'file', label: '文件' },
              { value: 'container', label: '容器' }]} />
            <Segmented value={dirtyFilter} onChange={(v) => setDirtyFilter(v as string)} options={[
              { value: 'all', label: '脏+净' }, { value: 'true', label: '脏' },
              { value: 'false', label: '净' }]} />
          </Space>
        )}>
        <Table rowKey="cache_key" size="small" dataSource={entries} loading={loading}
          pagination={{ pageSize: 15 }}
          columns={[
            { title: '缓存键', dataIndex: 'cache_key', width: 220, ellipsis: true,
              render: (v) => <Text code style={{ fontSize: 11 }}>{v}</Text> },
            { title: '类型', dataIndex: 'kind', width: 80,
              render: (v) => <Tag color={v === 'container' ? 'geekblue' : 'blue'}>{v === 'container' ? '容器' : '文件'}</Tag> },
            { title: '绝对路径', dataIndex: 'path', ellipsis: true,
              render: (v) => <Tooltip title={v}><Text copyable={{ text: v }} style={{ maxWidth: 340, fontSize: 12 }} ellipsis>{v}</Text></Tooltip> },
            { title: '大小', dataIndex: 'size_bytes', width: 90, render: fmtBytes },
            { title: '脏/净', dataIndex: 'dirty', width: 76,
              render: (v) => <Tag color={v ? 'orange' : 'green'}>{v ? '脏' : '净'}</Tag> },
            { title: '引用', dataIndex: 'refcount', width: 60 },
            { title: '最近访问', dataIndex: 'last_access_at', width: 150, render: fmtTime },
          ]} />
      </Card>
    </div>
  );
}
