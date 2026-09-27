// Archive Gateway：磁带归档网关（元数据 + 缓存 + 小文件聚合）
// 数据源：/api/v1/archive/*（gateway 模块，186 后端 v1.2+）
import { useEffect, useRef, useState } from 'react';
import {
  Alert, AutoComplete, Button, Card, Col, Descriptions, Input, message, Popconfirm, Progress,
  Row, Segmented, Select, Space, Table, Tabs, Tag, Tooltip, Tree, Typography, Upload,
} from 'antd';
import { UploadOutlined, ReloadOutlined, DownloadOutlined,
  ScissorOutlined, ArrowUpOutlined, SaveOutlined, PlayCircleOutlined,
  FolderOutlined, FileOutlined, PartitionOutlined } from '@ant-design/icons';
import { rawRequest } from '../api/client';
import ArchiveDirTree from './ArchiveDirTree';

const { Title, Text, Paragraph } = Typography;

const API_BASE = 'http://172.16.12.186:8080/api/v1';
const CURL = {
  upload: `curl -F "file=@big.bin" ${API_BASE}/archive/upload`,
  files: `curl -s "${API_BASE}/archive/files?limit=100"`,
  filter: `curl -s "${API_BASE}/archive/files?state=archived&limit=10"`,
  search: `curl -s "${API_BASE}/archive/files?name=big&limit=10"`,
  detail: `curl -s "${API_BASE}/archive/files/<file_id>"`,
  archive: `curl -X POST "${API_BASE}/archive/files/<file_id>/archive"`,
  recall: `curl -X POST "${API_BASE}/archive/files/<file_id>/recall"`,
  job: `curl -s "${API_BASE}/jobs/<job_id>"`,
  jobProgress: `curl -s "${API_BASE}/jobs/<job_id>/progress"`,
  jobResult: `curl -s "${API_BASE}/jobs/<job_id>/result"`,
  task: `curl -s "${API_BASE}/archive/tasks/<task_id>"`,
  taskList: `curl -s "${API_BASE}/archive/tasks?kind=archive_file&state=running"`,
  download: `curl -OJ "${API_BASE}/archive/files/<file_id>/download?async=false"`,
};

type AnyObj = Record<string, any>;

function fmtBytes(n?: number | null): string {
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

function toTreeNode(n: AnyObj): AnyObj {
  const isDir = n.type === 'dir';
  const isMember = n.type === 'member';
  const meta = n.meta || {};
  const f = meta.file;
  const title = (
    <Space size={6}>
      {isDir ? <FolderOutlined style={{ color: '#faad14' }} />
        : isMember ? <PartitionOutlined style={{ color: '#722ed1' }} />
        : <FileOutlined />}
      <Text style={{ fontSize: 12 }}>{n.name}</Text>
      <Text type="secondary" style={{ fontSize: 11 }}>{fmtBytes(n.size_bytes)}</Text>
      {isMember && <Tag color="purple">已封箱 · 召回还原</Tag>}
      {!isDir && !isMember && f?.state && <Tag color={STATE_COLORS[f.state]}>{f.state}</Tag>}
      {!isDir && !isMember && f?.storage && <Tag>{f.storage === 'container' ? '聚合' : f.storage === 'tape' ? '磁带' : '缓存'}</Tag>}
      {!isDir && !isMember && f?.tape?.barcode && <Tag color="purple">{f.tape.barcode}</Tag>}
    </Space>
  );
  return {
    key: n.path || n.name,
    title,
    children: (n.children || []).map(toTreeNode),
  };
}
const STATE_COLORS: AnyObj = {
  cached: 'blue', archiving: 'orange', archived: 'green', failed: 'red',
  buffering: 'blue', flushing: 'orange', aborted: 'red',
  queued: 'default', running: 'orange', succeeded: 'green',
  cancelled: 'default', succeeded_: 'green',
};

export default function ArchiveGateway() {
  const [stats, setStats] = useState<AnyObj | null>(null);
  const [config, setConfig] = useState<AnyObj | null>(null);
  const [files, setFiles] = useState<AnyObj[]>([]);
  const [containers, setContainers] = useState<AnyObj[]>([]);
  const [media, setMedia] = useState<AnyObj[]>([]);
  const [tasks, setTasks] = useState<AnyObj[]>([]);
  const [nameQ, setNameQ] = useState('');
  const [fileState, setFileState] = useState('all');
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [gwError, setGwError] = useState('');
  const [tEp, setTEp] = useState('list');
  const [tQid, setTQid] = useState('');
  const [tFid, setTFid] = useState('');
  const [tState, setTState] = useState('');
  const [tName, setTName] = useState('');
  const [tLimit, setTLimit] = useState(10);
  const [tResp, setTResp] = useState<AnyObj | null>(null);
  const [tBusy, setTBusy] = useState(false);
  const [upDir, setUpDir] = useState('');
  const [tDir, setTDir] = useState('');
  const [tree, setTree] = useState<AnyObj | null>(null);
  const [treeLoading, setTreeLoading] = useState(false);
  const [tabKey, setTabKey] = useState('guide');
  const [ltfs, setLtfs] = useState<AnyObj | null>(null);
  const [ltfsCheck, setLtfsCheck] = useState<AnyObj | null>(null);
  const [regBc, setRegBc] = useState('');
  const [regState, setRegState] = useState('appendable');
  const [regFmt, setRegFmt] = useState('raw');
  const timer = useRef<any>(null);

  async function loadTree() {
    setTreeLoading(true);
    const r = await rawRequest('GET', '/archive/tree');
    if (r.success) setTree(r.data);
    setTreeLoading(false);
  }

  async function refreshAll() {
    setLoading(true);
    const st = await rawRequest('GET', '/archive/stats');
    if (!st.success) {
      setGwError(`${st.code}: ${st.message}`);
      setLoading(false);
      return;
    }
    setGwError('');
    setStats(st.data);
    const [cf, fs, cs, ms, ts] = await Promise.all([
      rawRequest('GET', '/archive/config'),
      fileState === 'all'
        ? rawRequest('GET', '/archive/files?limit=100')
        : rawRequest('GET', `/archive/files?state=${fileState}&limit=100`),
      rawRequest('GET', '/archive/containers?limit=100'),
      rawRequest('GET', '/archive/media'),
      rawRequest('GET', '/archive/tasks?limit=50'),
    ]);
    if (cf.success) setConfig(cf.data);
    if (fs.success) setFiles(fs.data?.items || []);
    if (cs.success) setContainers(cs.data?.items || []);
    if (ms.success) setMedia(ms.data?.items || []);
    if (ts.success) setTasks(ts.data?.items || []);
    loadLtfs();
    setLoading(false);
  }

  async function loadLtfs() {
    const r = await rawRequest('GET', '/archive/ltfs/status');
    if (r.success) setLtfs(r.data);
  }

  async function regMedia() {
    if (!regBc.trim()) { message.warning('条码必填'); return; }
    const r = await rawRequest('POST', '/archive/media',
      { body: { barcode: regBc.trim(), state: regState, format: regFmt } });
    if (r.success) {
      message.success(`已登记 ${regBc.trim()} (${regFmt})`);
      setRegBc('');
      refreshAll();
    } else message.error(`${r.code}: ${r.message}`);
  }

  async function fmtMedia(bc: string) {
    const r = await rawRequest('POST', `/archive/media/${bc}/format`,
      { body: { format: 'ltfs', confirm: true, force: true } });
    if (r.success) {
      message.success(`${bc} 已格式化为 LTFS`);
      refreshAll();
      loadLtfs();
    } else message.error(`${r.code}: ${r.message}`);
  }

  async function checkLtfs(bc: string) {
    setLtfsCheck({ barcode: bc, busy: true });
    const r = await rawRequest('POST', `/archive/ltfs/${bc}/check`);
    if (r.success) setLtfsCheck({ ...(r.data || {}), barcode: bc, busy: false });
    else { setLtfsCheck(null); message.error(`${r.code}: ${r.message}`); }
  }

  async function searchByName(q: string) {
    if (!q) { refreshAll(); return; }
    setLoading(true);
    const r = await rawRequest('GET', `/archive/files?name=${encodeURIComponent(q)}&limit=100`);
    if (r.success) setFiles(r.data?.items || []);
    setLoading(false);
  }

  useEffect(() => {
    refreshAll();
    timer.current = setInterval(refreshAll, 10000);
    return () => clearInterval(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileState]);

  async function uploadFiles(fl: any[]) {
    if (!fl.length) return;
    setUploading(true);
    const qs = upDir.trim() ? `?dir=${encodeURIComponent(upDir.trim())}` : '';
    for (const f of fl) {
      const fd = new FormData();
      fd.append('file', f.originFileObj || f);
      try {
        const r = await rawRequest('POST', `/archive/upload${qs}`, { body: fd });
        if (r.success) {
          const d = r.data || {};
          message.success(`${f.name}: ${d.route === 'tape' ? '大文件 → 直写磁带任务已排队' : '小文件 → 已进聚合容器'}${d.rel_path ? ` · ${d.rel_path}` : ''}`);
        } else {
          message.error(`${f.name}: ${r.code} ${r.message}`);
        }
      } catch (e: any) {
        message.error(`${f.name}: ${String(e?.message || e)}`);
      }
    }
    setUploading(false);
    refreshAll();
  }

  async function downloadFile(fid: string, name: string) {
    const key = `dl-${fid}`;
    const hide = message.loading({ content: `召回 ${name} 中…（冷数据需读磁带，可能需要几分钟）`, key, duration: 0 });
    try {
      const r = await rawRequest('GET', `/archive/files/${fid}/download`);
      if (!r.success) { hide(); message.error({ content: `${r.code}: ${r.message}`, key }); return; }
      if (r.http_status === 202 && r.data?.job_id) {
        const jobId: string = r.data.job_id;
        for (let i = 0; i < 120; i++) {
          await new Promise((res) => setTimeout(res, 3000));
          const j = await rawRequest('GET', `/jobs/${jobId}`);
          const st = j.data?.state;
          if (st === 'succeeded') break;
          if (st === 'failed' || !j.success) {
            hide();
            message.error({ content: `召回失败: ${j.data?.error?.message || j.message || st}`, key });
            return;
          }
        }
      }
      hide();
      // 命中缓存后由浏览器流式下载
      window.open(`/api/v1/archive/files/${fid}/download?async=false`, '_blank');
      message.success({ content: `${name} 已就绪，开始下载`, key });
    } catch (e: any) {
      hide();
      message.error(String(e?.message || e));
    }
  }

  async function sealContainer(cid: string) {
    const r = await rawRequest('POST', `/archive/containers/${cid}/seal`);
    if (r.success) message.success('容器已密封，即将打包落带');
    else message.error(`${r.code}: ${r.message}`);
    refreshAll();
  }

  async function archiveFile(fid: string, name: string) {
    const key = `ar-${fid}`;
    const hide = message.loading({ content: `提交 ${name} 归档…`, key, duration: 0 });
    const r = await rawRequest('POST', `/archive/files/${fid}/archive`);
    hide();
    if (!r.success) { message.error({ content: `${r.code}: ${r.message}`, key }); return; }
    const d = r.data || {};
    if (d.route === 'container') {
      message.success({ content: `已密封聚合容器（${String(d.container_id).slice(0, 8)}…），即将打包落带`, key });
    } else {
      message.success({ content: `已排队直写磁带（任务 ${String(d.task_id).slice(0, 12)}，状态 ${d.state}）`, key });
    }
    refreshAll();
  }

  async function recallFile(fid: string, name: string, dir?: string) {
    const key = `rc-${fid}`;
    const hide = message.loading({ content: `召回 ${name}：从磁带复制到磁盘…`, key, duration: 0 });
    try {
      const qs = dir ? `?dir=${encodeURIComponent(dir)}` : '';
      const r = await rawRequest('POST', `/archive/files/${fid}/recall${qs}`);
      if (!r.success) { hide(); message.error({ content: `${r.code}: ${r.message}`, key }); return; }
      let finalPath = r.data?.path || '';
      if (r.http_status === 202 && r.data?.job_id) {
        const jobId: string = r.data.job_id;
        for (let i = 0; i < 120; i++) {
          await new Promise((res) => setTimeout(res, 3000));
          const j = await rawRequest('GET', `/jobs/${jobId}`);
          const st = j.data?.state;
          if (st === 'succeeded') break;
          if (st === 'failed' || !j.success) {
            hide();
            message.error({ content: `召回失败: ${j.data?.error?.message || j.message || st}`, key });
            return;
          }
        }
        const rs = await rawRequest('GET', `/jobs/${jobId}/result`);
        finalPath = rs.data?.path || finalPath;
      }
      hide();
      message.success({ content: `${name} 已复制到磁盘：${finalPath || '缓存 recall 目录'}`, key });
    } catch (e: any) {
      hide();
      message.error({ content: String(e?.message || e), key });
    }
    refreshAll();
  }
  async function retryContainer(cid: string) {
    const r = await rawRequest('POST', `/archive/containers/${cid}/retry`);
    if (r.success) message.success('容器已重新排队归档');
    else message.error(`${r.code}: ${r.message}`);
    refreshAll();
  }
  async function evictNow() {
    const r = await rawRequest('POST', '/archive/evict');
    if (r.success) {
      const d = r.data || {};
      message.success(d.action === 'none' ? '未超水位，无需淘汰' : `已淘汰 ${d.evicted} 项，释放 ${fmtBytes(d.freed_bytes)}`);
    } else message.error(`${r.code}: ${r.message}`);
    refreshAll();
  }

  function testerCurl(): string {
    const qs = new URLSearchParams();
    if (tState) qs.set('state', tState);
    if (tName) qs.set('name', tName);
    qs.set('limit', String(tLimit));
    switch (tEp) {
      case 'list': return `curl -s "${API_BASE}/archive/files?${qs.toString()}"`;
      case 'detail': return `curl -s "${API_BASE}/archive/files/${tFid || '<file_id>'}"`;
      case 'archive': return `curl -X POST "${API_BASE}/archive/files/${tFid || '<file_id>'}/archive"`;
      case 'recall': return `curl -X POST "${API_BASE}/archive/files/${tFid || '<file_id>'}/recall"`;
      case 'download': return CURL.download.replace('<file_id>', tFid || '<file_id>');
      case 'trace': return tQid.startsWith('JOB-') ? `curl -s "${API_BASE}/jobs/${tQid}"`
        : tQid.startsWith('tsk-') ? `curl -s "${API_BASE}/archive/tasks/${tQid}"`
        : `curl -s "${API_BASE}/audit/${tQid || '<REQ-/JOB-/tsk->'}"`;
      default: return CURL.upload;
    }
  }

  async function runTest() {
    setTBusy(true);
    try {
      if (tEp === 'list') {
        const q: Record<string, any> = { limit: tLimit };
        if (tState) q.state = tState;
        if (tName) q.name = tName;
        setTResp(await rawRequest('GET', '/archive/files', { query: q }));
      } else if (tEp === 'detail') {
        const r = await rawRequest('GET', `/archive/files/${tFid}`);
        setTResp(r);
        const cid = r.data?.location?.container_id || r.data?.file?.container_id;
        if (cid) {
          const c = await rawRequest('GET', `/archive/containers/${cid}`);
          const cont = c.data?.container || {};
          if (cont.media_barcode || cont.state) {
            setTResp({ ...r, _container: cont, _note: cont.media_barcode
              ? `聚合容器成员：容器已落带 ${cont.media_barcode} · block ${cont.tape_block_index}（文件层磁带字段为 null，磁带信息在容器层，已自动追查 GET /archive/containers/${cid} 合并显示）`
              : `聚合容器成员：容器 state=${cont.state}，尚未落带（待容器 sealed/archived 后才有磁带信息）` });
          }
        }
      } else if (tEp === 'archive') {
        const r = await rawRequest('POST', `/archive/files/${tFid}/archive`);
        setTResp(r);
        if (!r.success) return;
        // 异步配套：大文件（tape 路由）响应自带 task_id；聚合容器成员需等 flusher 创建 archive_container 任务
        let tid: string | undefined = r.data?.task_id;
        const cid = r.data?.container_id;
        if (!tid && cid) {
          for (let i = 0; i < 20 && !tid; i++) {
            await new Promise((res) => setTimeout(res, 3000));
            const tl = await rawRequest('GET', '/archive/tasks', { query: { kind: 'archive_container', limit: 10 } });
            const hit = (tl.data?.items || []).find((t: AnyObj) => String(t.container_id) === String(cid));
            if (hit) tid = hit.task_id;
            else setTResp({ ...r, _note: `容器已密封（CONTAINER_SEALED），等待后台 flusher 创建落带任务… 扫描 #${i + 1}：GET /archive/tasks?kind=archive_container&limit=10` });
          }
        }
        if (!tid) {
          if (cid) setTResp({ ...r, _note: '容器已密封，但 60s 内未扫描到落带任务（flusher 周期未到）。稍后用「⑦追踪」粘贴该 tsk-…，或 curl GET /archive/tasks?kind=archive_container 查询。' });
          return;
        }
        for (let i = 0; i < 120; i++) {
          await new Promise((res) => setTimeout(res, 3000));
          const t = await rawRequest('GET', `/archive/tasks/${tid}`);
          if (!t.success) { setTResp({ ...t, _note: `任务查询失败：GET /archive/tasks/${tid}` }); break; }
          setTResp({ ...t, _note: `③归档任务进度 #${i + 1}：GET /archive/tasks/${tid}（3s 轮询；succeeded/failed/aborted 为终态即结果，result 含落带条码/块号/字节数）` });
          if (['succeeded', 'failed', 'aborted'].includes(t.data?.state)) { refreshAll(); break; }
        }
      } else if (tEp === 'recall') {
        const qs = tDir.trim() ? `?dir=${encodeURIComponent(tDir.trim())}` : '';
        const r = await rawRequest('POST', `/archive/files/${tFid}/recall${qs}`);
        setTResp(r);
        const jid = r.data?.job_id;
        if (r.http_status === 202 && jid) {
          // 配套①：轻量进度轮询 GET /jobs/{id}/progress（仅 state/progress/duration_ms，轮询友好）
          let done = false;
          for (let i = 0; i < 120 && !done; i++) {
            await new Promise((res) => setTimeout(res, 3000));
            const p = await rawRequest('GET', `/jobs/${jid}/progress`);
            if (!p.success) { setTResp({ ...p, _note: `进度查询失败：GET /jobs/${jid}/progress（job 可能已被清理）` }); break; }
            setTResp({ ...p, _note: `④召回任务进度 #${i + 1}：GET /jobs/${jid}/progress（轻量轮询；终态后自动调 GET /jobs/${jid}/result 取结果）` });
            if (['succeeded', 'failed', 'cancelled'].includes(p.data?.state)) done = true;
          }
          // 配套②：结果查询 GET /jobs/{id}/result —— 与同步执行一致的业务信封
          if (done) {
            const rs = await rawRequest('GET', `/jobs/${jid}/result`);
            setTResp({ ...rs, _note: `④召回任务结果：GET /jobs/${jid}/result —— 同步等价业务信封（RECALLED + path），附 duration_ms/command_ids/audit_url` });
            refreshAll();
          }
        }
      } else if (tEp === 'trace') {
        const id = tQid.trim();
        if (id.startsWith('JOB-')) {
          const j = await rawRequest('GET', `/jobs/${id}`);
          setTResp(j);
          if (j.data && ['pending', 'running'].includes(j.data.state)) {
            let done = false;
            for (let i = 0; i < 120 && !done; i++) {
              await new Promise((res) => setTimeout(res, 3000));
              const p = await rawRequest('GET', `/jobs/${id}/progress`);
              if (!p.success) { setTResp({ ...p, _note: '进度查询失败：GET /jobs/{id}/progress（job 可能已被清理）' }); break; }
              setTResp({ ...p, _note: `JOB 进度 #${i + 1}：GET /jobs/${id}/progress（轻量轮询；终态后自动调 /result 取结果）` });
              if (['succeeded', 'failed', 'cancelled'].includes(p.data?.state)) done = true;
            }
            if (done) {
              const rs = await rawRequest('GET', `/jobs/${id}/result`);
              setTResp({ ...rs, _note: `任务结果：GET /jobs/${id}/result —— 与同步执行一致的业务信封，附 duration_ms/command_ids/audit_url` });
            }
          }
        } else if (id.startsWith('tsk-')) {
          setTResp(await rawRequest('GET', `/archive/tasks/${id}`));
        } else if (id.startsWith('REQ-')) {
          const a = await rawRequest('GET', `/audit/${id}`);
          if (a.success) {
            setTResp(a);
          } else {
            const jl = await rawRequest('GET', '/jobs', { query: { limit: 100 } });
            const arr = Array.isArray(jl.data) ? jl.data : (jl.data?.items || []);
            const hit = arr.find((j: AnyObj) => j.request_id === id);
            setTResp({ ...a, _note: hit
              ? `audit 无此 REQ（仅设备命令入审计），但在 jobs 列表匹配到 ${hit.job_id}（${hit.state}）——请用该 JOB 号再查详情`
              : 'audit 无此 REQ：审计仅记录设备命令类请求。若这是同步接口（列表/详情等）的 request_id，则请求瞬时完成、无后台任务，结果即当时的响应体；request_id 仅用于日志排查。' });
          }
        } else {
          setTResp({ success: false, code: 'INPUT', message: '请输入 REQ- / JOB- / tsk- 开头的标识' });
        }
      } else if (tEp === 'download') {
        await downloadFile(tFid, files.find((f: AnyObj) => f.file_id === tFid)?.filename || tFid);
        setTResp({ _note: '已触发浏览器下载（两段式：冷数据先自动召回）' });
      }
    } finally { setTBusy(false); }
  }

  const tSelFile = files.find((f: AnyObj) => f.file_id === tFid);
  const tStateBad = tEp === 'archive' && tSelFile && !['cached', 'failed'].includes(tSelFile.state)
    ? `⚠ 该文件 state=${tSelFile.state}，仅 cached/failed 可归档（后端会拒：INVALID_STATE）`
    : tEp === 'recall' && tSelFile && tSelFile.state !== 'archived'
      ? `⚠ 该文件 state=${tSelFile.state}，仅 archived 可召回`
      : '';

  const fstats = stats?.files || {};
  const cache = stats?.cache || {};
  const cachePct = cache.quota_bytes ? Math.min(100, (Number(cache.total_bytes) / Number(cache.quota_bytes)) * 100) : 0;
  const dirtyPct = cache.total_bytes ? (Number(cache.dirty_bytes) / Number(cache.total_bytes)) * 100 : 0;

  if (gwError) {
    return (
      <div>
        <Title level={3}>Archive Gateway 磁带归档网关</Title>
        <Alert type="error" showIcon message="归档网关不可用"
          description={gwError} />
      </div>
    );
  }

  return (
    <div>
      <Title level={3}>Archive Gateway 磁带归档网关</Title>
      <Text type="secondary">
        大文件（&gt;{config?.small_file_mb ?? 64}MB）直写磁带；小文件自动聚合（目标
        {fmtBytes(config?.container_target_bytes ?? 1073741824)} / 最长滞留 {config?.container_flush_s ?? 120}s）顺序落带；缓存脏/净分层 + LRU 水位淘汰。
      </Text>
      <Space style={{ margin: '12px 0' }} wrap>
        <Input addonBefore="缓存目录" allowClear style={{ width: 360 }}
          placeholder="可选，如 projects/2026/alpha（留空=默认 upload/）"
          value={upDir} onChange={(e) => setUpDir(e.target.value)}
          suffix={<Tooltip title="目录树架构：文件按原文件名落入该目录（仅限 cache_dir 内）；同名自动加后缀。上传时同步作为容器内层级路径，封箱落带后召回仍还原到该目录"><PartitionOutlined /></Tooltip>} />
        <Upload multiple showUploadList={false} beforeUpload={() => false}
          onChange={({ fileList }) => {
            const pend = fileList.filter((f: any) => f.status === undefined);
            if (pend.length) uploadFiles(pend);
          }}>
          <Button type="primary" icon={<UploadOutlined />} loading={uploading}>上传归档</Button>
        </Upload>
        <Button icon={<ReloadOutlined />} onClick={refreshAll} loading={loading}>刷新</Button>
        <Popconfirm title="立即按水位淘汰净缓存？" onConfirm={evictNow}>
          <Button icon={<ScissorOutlined />}>强制淘汰</Button>
        </Popconfirm>
      </Space>

      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        <Col span={6}>
          <Card size="small" title="文件（统一入口 file_meta）">
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="cached 待归档"><b>{fstats.cached ?? 0}</b></Descriptions.Item>
              <Descriptions.Item label="archiving 归档中"><b>{fstats.archiving ?? 0}</b></Descriptions.Item>
              <Descriptions.Item label="archived 已落带"><b style={{ color: '#389e0d' }}>{fstats.archived ?? 0}</b></Descriptions.Item>
              <Descriptions.Item label="failed 失败"><b style={{ color: '#cf1322' }}>{fstats.failed ?? 0}</b></Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" title="缓存空间" extra={<Tooltip title={`配额 ${fmtBytes(cache.quota_bytes)}，水位 ${config?.watermarks_pct?.join('%→')}%`}><span>{fmtBytes(cache.total_bytes)}</span></Tooltip>}>
            <Progress percent={Math.round(cachePct * 10) / 10} size="small"
              status={cachePct > (config?.watermarks_pct?.[1] ?? 85) ? 'exception' : 'normal'} />
            <Progress percent={Math.round(dirtyPct)} size="small" strokeColor="#fa8c16"
              format={() => `脏 ${fmtBytes(cache.dirty_bytes)}`} />
            <div style={{ marginTop: 4 }}>
              <Text type="secondary">净 {fmtBytes(cache.clean_bytes)} · 磁盘剩余 {fmtBytes(cache.fs_free_bytes)}</Text>
            </div>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" title="聚合容器">
            <Descriptions size="small" column={1}>
              {(stats?.containers || []).map((c: AnyObj) => (
                <Descriptions.Item key={c.state} label={<Tag color={STATE_COLORS[c.state]}>{c.state}</Tag>}>
                  {c.count} 个 · {fmtBytes(c.bytes)}
                </Descriptions.Item>
              ))}
              {!(stats?.containers || []).length && <Descriptions.Item>-</Descriptions.Item>}
            </Descriptions>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" title="磁带介质 / 任务">
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="介质">{media.length} 卷</Descriptions.Item>
              {media.slice(0, 3).map((m: AnyObj) => (
                <Descriptions.Item key={m.barcode} label={m.barcode}>
                  <Tooltip title={`${m.block_records} blocks · mount ${m.mount_count}`}>
                    {fmtBytes(m.used_bytes)} / {fmtBytes(m.capacity_bytes)} <Tag>{m.state}</Tag>
                  </Tooltip>
                </Descriptions.Item>
              ))}
              <Descriptions.Item label="写带累计">{fmtBytes(stats?.metrics?.bytes_to_tape)}</Descriptions.Item>
              <Descriptions.Item label="召回命中/未命中">{stats?.metrics?.recall_hits ?? 0} / {stats?.metrics?.recall_misses ?? 0}</Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
      </Row>

      <Tabs activeKey={tabKey} onChange={(k) => {
        setTabKey(k);
        if (k === 'cachetree') loadTree();
      }} items={[
        {
          key: 'guide', label: '测试方法',
          children: (
            <div>
              <Alert type="info" showIcon style={{ marginBottom: 12 }}
                message="接口测试方法：上传 → 查询（位置状态 + 磁带存储信息）→ 召回 → 下载"
                description={<>API 基址 <Text code>{API_BASE}</Text>。以下命令均可点击复制直接执行；用本页按钮（上传归档 / 归档 / 召回 / 行尾下载）可完成同样的链路；「接口测试」页签可直接发送请求并查看原始 JSON。</>} />
              <Row gutter={[12, 12]}>
                <Col span={12}>
                  <Card size="small" title="① 上传 POST /archive/upload">
                    <Paragraph style={{ marginBottom: 6 }}>UI：点顶部「上传归档」选择文件（支持多选）。</Paragraph>
                    <Text code copyable style={{ display: 'block', whiteSpace: 'pre-wrap', fontSize: 12, marginBottom: 6 }}>{CURL.upload}</Text>
                    <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                      预期：&gt;{config?.small_file_mb ?? 64}MB 大文件返回 <Text code>TAPE_ARCHIVE_QUEUED</Text>（直写磁带异步任务，自动装载磁带）；
                      ≤{config?.small_file_mb ?? 64}MB 小文件返回 <Text code>CONTAINER_BUFFERED</Text>（进聚合容器，凑满 {fmtBytes(config?.container_target_bytes ?? 1073741824)} 或滞留 {config?.container_flush_s ?? 120}s 后自动落带）。
                    </Paragraph>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card size="small" title="② 查询 GET /archive/files —— 位置状态 + 磁带存储信息">
                    <Text code copyable style={{ display: 'block', whiteSpace: 'pre-wrap', fontSize: 12, marginBottom: 4 }}>{CURL.files}</Text>
                    <Text code copyable style={{ display: 'block', whiteSpace: 'pre-wrap', fontSize: 12, marginBottom: 4 }}>{CURL.filter}</Text>
                    <Text code copyable style={{ display: 'block', whiteSpace: 'pre-wrap', fontSize: 12, marginBottom: 8 }}>{CURL.search}</Text>
                    <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
                      <li><Text code>location.zone</Text>：cache 磁盘缓存 / container 聚合容器 / tape 磁带</li>
                      <li><Text code>location.in_cache / on_tape / needs_recall / download_ready</Text>：是否有磁盘副本、是否落带、是否需读带召回、能否直接下载</li>
                      <li><Text code>location.media_barcode + tape_block_index</Text>：数据在哪卷磁带哪个块（聚合容器成员的磁带信息在容器层，「②详情」会自动追查容器并合并显示）</li>
                      <li><Text code>tape.*</Text>：barcode / state / capacity_bytes / used_bytes / used_pct / block_records（整卷磁带用量）</li>
                      <li>响应含 <Text code>total</Text>（全量计数）；详情 <Text code>GET /archive/files/&lt;file_id&gt;</Text> 额外含 <Text code>location.hit</Text>（cache / container_cache / tape / none）、mode、available</li>
                    </ul>
                    <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                      UI 对应：「文件」表「位置」列（磁盘缓存 / 在带&lt;条码&gt; / 需读带召回）与「磁带用量」列（条码 + 用量%，悬停看容量/块数/状态）。
                    </Paragraph>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card size="small" title="③ 归档 POST /archive/files/{'<file_id>'}/archive（cached → 磁带）">
                    <Text code copyable style={{ display: 'block', whiteSpace: 'pre-wrap', fontSize: 12, marginBottom: 4 }}>{CURL.archive}</Text>
                    <Text code copyable style={{ display: 'block', whiteSpace: 'pre-wrap', fontSize: 12, marginBottom: 8 }}>{CURL.task}</Text>
                    <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                      预期（异步）：大文件 202 + <Text code>task_id</Text>（<Text code>TAPE_ARCHIVE_QUEUED</Text>，直写磁带）；聚合容器成员同步密封容器返回 <Text code>CONTAINER_SEALED</Text>，由后台 flusher 创建 <Text code>archive_container</Text> 任务落带。配套进度：轮询 <Text code>GET /archive/tasks/&lt;task_id&gt;</Text> 至 <Text code>succeeded</Text>，<Text code>result</Text> 即任务结果（含落带条码/块号/字节数）。UI：「③归档」按钮提交后自动轮询任务至终态。
                    </Paragraph>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card size="small" title="④ 召回 POST /archive/files/{'<file_id>'}/recall（冷数据 → 磁盘）">
                    <Text code copyable style={{ display: 'block', whiteSpace: 'pre-wrap', fontSize: 12, marginBottom: 4 }}>{CURL.recall}</Text>
                    <Text code copyable style={{ display: 'block', whiteSpace: 'pre-wrap', fontSize: 12, marginBottom: 4 }}>{CURL.jobProgress}</Text>
                    <Text code copyable style={{ display: 'block', whiteSpace: 'pre-wrap', fontSize: 12, marginBottom: 8 }}>{CURL.jobResult}</Text>
                    <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                      预期（异步）：202 + <Text code>job_id</Text>（机器人自动装载磁带 → 读带复制到磁盘）。配套进度：轻量轮询 <Text code>GET /jobs/&lt;job_id&gt;/progress</Text>（仅 state/progress/duration_ms）；终态后 <Text code>GET /jobs/&lt;job_id&gt;/result</Text> 返回与同步执行一致的业务信封（<Text code>RECALLED</Text> + path），该文件 <Text code>location.in_cache=true</Text>。UI：「④召回」按钮自动完成 提交 → 轮询 → 取结果。
                    </Paragraph>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card size="small" title="⑤ 下载 GET /archive/files/{'<file_id>'}/download">
                    <Text code copyable style={{ display: 'block', whiteSpace: 'pre-wrap', fontSize: 12, marginBottom: 8 }}>{CURL.download}</Text>
                    <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                      预期：缓存命中 → 200 直接流式返回文件；冷数据默认 202 返回 <Text code>job_id</Text>（转召回，完成后即可下载）。UI：行尾下载图标自动处理两段式（先召回后开下载）。
                    </Paragraph>
                  </Card>
                </Col>
                <Col span={24}>
                  <Card size="small" title="端到端验证清单（预期结果）">
                    <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
                      <li>上传小文件 → 几秒内「文件」表出现，<Text code>state=cached</Text>，「位置」= 磁盘缓存（聚合 Tag）</li>
                      <li>点「归档」或等容器自动密封 → <Text code>state=archived</Text>，「位置」= 在带&lt;条码&gt;；「磁带用量」used% 与块数增加（另见「介质」页签整卷容量/块数/挂载次数）</li>
                      <li>无磁盘副本的文件 → 「位置」= 需读带召回（<Text code>needs_recall=true</Text>）</li>
                      <li>点「召回」→ 任务 succeeded → 「位置」回到 磁盘缓存，可正常下载</li>
                      <li>查询响应 <Text code>total</Text> 与各状态计数一致；<Text code>?state=archived</Text> 过滤后全部已落带</li>
                    </ol>
                  </Card>
                </Col>
              </Row>
            </div>
          ),
        },
        {
          key: 'tester', label: '接口测试',
          children: (
            <div>
              <Alert type="info" showIcon style={{ marginBottom: 12 }}
                message="文件接口在线测试：选择接口 → 填参数 → 发送请求，查看原始 JSON 响应"
                description={<>与「测试方法」页签的 curl 一一对应；file_id 可从文件表自动带出，也可直接粘贴 UUID；③归档/④召回为异步提交，发送后自动轮询配套进度接口（task → /archive/tasks/&lt;id&gt;，job → /jobs/&lt;id&gt;/progress）并在终态拉取结果（/jobs/&lt;id&gt;/result）；⑦追踪支持 REQ-/JOB-/tsk- 一键查执行情况。</>} />
              <Row gutter={[12, 12]}>
                <Col span={10}>
                  <Card size="small" title="请求">
                    <Space direction="vertical" style={{ width: '100%' }} size={10}>
                      <Segmented value={tEp} onChange={(v) => setTEp(v as string)} options={[
                        { value: 'list', label: '①列表' },
                        { value: 'detail', label: '②详情' },
                        { value: 'archive', label: '③归档' },
                        { value: 'recall', label: '④召回' },
                        { value: 'download', label: '⑤下载' },
                        { value: 'upload', label: '⑥上传' },
                        { value: 'trace', label: '⑦追踪' },
                      ]} style={{ marginBottom: 2 }} />
                      {tEp === 'list' && (
                        <Space wrap>
                          <Input placeholder="name 文件名过滤" style={{ width: 170 }} value={tName} allowClear
                            onChange={(e) => setTName(e.target.value)} />
                          <Segmented value={tState || 'all'} onChange={(v) => setTState(v === 'all' ? '' : v as string)} options={[
                            { value: 'all', label: '全部' }, { value: 'cached', label: 'cached' },
                            { value: 'archived', label: 'archived' }, { value: 'failed', label: 'failed' }]} />
                          <Input addonBefore="limit" style={{ width: 120 }} value={tLimit}
                            onChange={(e) => setTLimit(Number(e.target.value) || 10)} />
                        </Space>
                      )}
                      {['detail', 'archive', 'recall', 'download'].includes(tEp) && (
                        <AutoComplete value={tFid}
                          options={files.map((f: AnyObj) => ({ value: f.file_id, label: `${f.filename} · ${f.state}` }))}
                          style={{ width: '100%' }}
                          onSelect={(v) => setTFid(v)} onChange={(v) => setTFid(v || '')}
                          placeholder="file_id（输入文件名筛选，或直接粘贴 UUID）"
                          filterOption={(iv, opt) => String(opt?.label ?? '').toLowerCase().includes(String(iv).toLowerCase())} />
                      )}
                      {(tEp === 'recall' || tEp === 'upload') && (
                        <Input addonBefore="dir" allowClear placeholder={tEp === 'upload'
                          ? '可选：缓存目录（如 projects/2026/alpha，或 cache_dir 内绝对路径）'
                          : '可选：召回落盘目录（留空=还原到原目录树位置）'}
                          value={tDir} onChange={(e) => setTDir(e.target.value)} />
                      )}
                      {tStateBad && (
                        <Alert type="warning" showIcon message={tStateBad}
                          description="换一个文件，或用「①列表」按状态筛选；仍可发送，响应当作错误案例参考。" />
                      )}
                      {tEp === 'upload' && (
                        <Upload multiple showUploadList={false} beforeUpload={() => false}
                          onChange={async ({ fileList }) => {
                            const pend = fileList.filter((f: any) => f.status === undefined);
                            if (!pend.length) return;
                            setTBusy(true);
                            try {
                              for (const f of pend as any[]) {
                                const fd = new FormData();
                                fd.append('file', f.originFileObj || f);
                                const qs = tDir.trim() ? `?dir=${encodeURIComponent(tDir.trim())}` : '';
                                const r = await rawRequest('POST', `/archive/upload${qs}`, { body: fd });
                                setTResp({ ...r, _file: f.name });
                              }
                              refreshAll();
                            } finally { setTBusy(false); }
                          }}>
                          <Button type="primary" icon={<UploadOutlined />} loading={tBusy}>选择文件上传（multipart）</Button>
                        </Upload>
                      )}
                      {tEp === 'trace' && (
                        <Input placeholder="粘贴 REQ-… / JOB-… / tsk-… 任一标识（自动识别类型）" value={tQid}
                          onChange={(e) => setTQid(e.target.value)} allowClear />
                      )}
                      <Text code copyable={{ text: testerCurl() }}
                        style={{ display: 'block', whiteSpace: 'pre-wrap', fontSize: 12 }}>{testerCurl()}</Text>
                      <Space>
                        {tEp !== 'upload' && (
                          <Button type="primary" icon={<PlayCircleOutlined />} loading={tBusy}
                            disabled={['detail', 'archive', 'recall', 'download'].includes(tEp) && !tFid}
                            onClick={runTest}>发送请求</Button>
                        )}
                        <Button onClick={() => { setTResp(null); setTName(''); }} disabled={tBusy}>清除</Button>
                      </Space>
                    </Space>
                  </Card>
                </Col>
                <Col span={14}>
                  <Card size="small" title="响应（原始 JSON）"
                    extra={tResp && (<Space size={4}>
                      {tResp.http_status !== undefined && <Tag color={tResp.success ? 'green' : 'red'}>{tResp.http_status}</Tag>}
                      {tResp.code && <Tag color={tResp.success ? undefined : 'red'}>{tResp.code}</Tag>}
                      {tResp._file && <Tag color="cyan">{String(tResp._file).slice(0, 24)}</Tag>}
                    </Space>)}>
                    <pre style={{ margin: 0, maxHeight: 520, overflow: 'auto', fontSize: 12 }}>
{tResp ? JSON.stringify(tResp, null, 2) : '选择接口并点击「发送请求」；③归档/④召回异步提交后，自动轮询配套进度接口、终态拉取结果。'}
                    </pre>
                  </Card>
                </Col>
              </Row>
            </div>
          ),
        },
        {
          key: 'files', label: `文件 (${files.length})`,
          children: (
            <div>
              <Space style={{ marginBottom: 8 }}>
                <Input.Search placeholder="按文件名搜索" allowClear style={{ width: 260 }}
                  onSearch={searchByName} onChange={(e) => !e.target.value && setNameQ('')} />
                <Segmented value={fileState} onChange={(v) => setFileState(v as string)} options={[
                  { value: 'all', label: '全部' }, { value: 'cached', label: '待归档' },
                  { value: 'archived', label: '已落带' }, { value: 'failed', label: '失败' },
                ]} />
              </Space>
              <Table rowKey="file_id" size="small" dataSource={files} loading={loading}
                pagination={{ pageSize: 15 }}
                columns={[
                  { title: '文件名', dataIndex: 'filename', ellipsis: true,
                    render: (v, r: AnyObj) => (<Space><Text copyable={{ text: r.file_id }} style={{ maxWidth: 200 }} ellipsis>{v}</Text>
                      {r.kind === 'container_member' && <Tag color="cyan">聚合</Tag>}</Space>) },
                  { title: '绝对路径', dataIndex: 'cache_path', ellipsis: true,
                    render: (v, r: AnyObj) => {
                      const shown = v || r.cache_rel_path;
                      if (shown) return <Tooltip title={shown}><Text copyable={{ text: shown }} style={{ maxWidth: 220, fontSize: 11 }} ellipsis>{shown}</Text></Tooltip>;
                      if (r.state === 'archived') {
                        const loc = r.container_id
                          ? `容器 ${String(r.container_id).slice(0, 8)}… · off ${r.file_offset_in_container ?? 0}B`
                          : `磁带 ${r.media_barcode || '-'} · block ${r.tape_block_index ?? '-'}`;
                        return <Tooltip title="数据在磁带上，未驻留磁盘；召回后还原到原目录树位置"><Text type="secondary" style={{ fontSize: 11 }} ellipsis>{loc}</Text></Tooltip>;
                      }
                      return <Text type="secondary">-</Text>;
                    } },
                  { title: '大小', dataIndex: 'size_bytes', width: 90, render: fmtBytes },
                  { title: '状态', dataIndex: 'state', width: 90,
                    render: (v) => <Tag color={STATE_COLORS[v]}>{v}</Tag> },
                  { title: '存储', dataIndex: 'storage', width: 90,
                    render: (v) => <Tag>{v === 'container' ? '聚合包' : v === 'tape' ? '磁带' : '缓存'}</Tag> },
                  { title: '位置', width: 150,
                    render: (v, r: AnyObj) => {
                      const loc = r.location;
                      if (!loc) return <Text type="secondary">-</Text>;
                      return (<Space size={4} wrap>
                        {loc.in_cache && <Tag color="green">磁盘缓存</Tag>}
                        {loc.on_tape && <Tag color="purple">在带 {loc.media_barcode || ''}</Tag>}
                        {loc.needs_recall && <Tag color="orange">需读带召回</Tag>}
                        {!loc.in_cache && !loc.on_tape && <Tag>{loc.zone || '未知'}</Tag>}
                      </Space>);
                    } },
                  { title: '磁带用量', width: 150,
                    render: (v, r: AnyObj) => {
                      const t = r.tape;
                      if (!t) return <Text type="secondary">-</Text>;
                      return (<Tooltip title={`${fmtBytes(t.used_bytes)} / ${fmtBytes(t.capacity_bytes)} · ${t.block_records ?? 0} 块记录 · 状态 ${t.state}`}>
                        <Space size={6}>
                          <b style={{ fontSize: 12 }}>{t.barcode}</b>
                          <Progress percent={Math.round(t.used_pct ?? 0)} size="small"
                            style={{ width: 50, margin: 0 }} showInfo={false} />
                          <Text type="secondary" style={{ fontSize: 11 }}>{t.used_pct ?? 0}%</Text>
                        </Space>
                      </Tooltip>);
                    } },
                  { title: '容器/块', width: 120,
                    render: (v, r: AnyObj) => r.container_id
                      ? <Tooltip title={r.container_id}><span>{String(r.container_id).slice(0, 8)} · off {fmtBytes(r.file_offset_in_container)}</span></Tooltip>
                      : (r.tape_block_index !== null && r.tape_block_index !== undefined ? `block ${r.tape_block_index}` : '-') },
                  { title: '创建时间', dataIndex: 'created_at', width: 150, render: fmtTime },
                  { title: '操作', width: 170, render: (v, r: AnyObj) => (
                    <Space>
                      {(r.state === 'cached' || r.state === 'failed' || r.state === 'archiving') && (
                        <Tooltip title={r.state === 'cached'
                          ? (r.storage === 'container'
                            ? '密封所在聚合容器并落带（其余小文件一并归档）'
                            : '排队直写磁带')
                          : r.state === 'failed' ? '重试归档' : '已在归档队列'}>
                          <Button size="small" type="primary" ghost icon={<SaveOutlined />}
                            disabled={r.state === 'archiving'}
                            onClick={() => archiveFile(r.file_id, r.filename)}>归档</Button>
                        </Tooltip>)}
                      {r.state === 'archived' && (
                        <Tooltip title="从磁带复制数据到磁盘（冷数据需读带，可能需要几分钟）">
                          <Button size="small" icon={<DownloadOutlined />}
                            onClick={() => recallFile(r.file_id, r.filename)}>召回</Button>
                        </Tooltip>)}
                      <Tooltip title="浏览器下载文件流">
                        <Button size="small" type="text" icon={<ArrowUpOutlined rotate={180} />}
                          onClick={() => downloadFile(r.file_id, r.filename)} />
                      </Tooltip>
                    </Space>) },
                ]} />
            </div>
          ),
        },
        {
          key: 'containers', label: `聚合容器 (${containers.length})`,
          children: (
            <Table rowKey="container_id" size="small" dataSource={containers} loading={loading}
              pagination={{ pageSize: 15 }}
              columns={[
                { title: '容器', dataIndex: 'container_id', width: 110,
                  render: (v) => <Text copyable={{ text: v }}>{String(v).slice(0, 8)}</Text> },
                { title: '状态', dataIndex: 'state', width: 100,
                  render: (v) => <Tag color={STATE_COLORS[v]}>{v}</Tag> },
                { title: '文件数', dataIndex: 'file_count', width: 70 },
                { title: '大小', dataIndex: 'size_bytes', width: 90, render: fmtBytes },
                { title: '介质/块', width: 130,
                  render: (v, r: AnyObj) => r.media_barcode ? `${r.media_barcode} · blk ${r.tape_block_index}` : '-' },
                { title: 'sha256', dataIndex: 'archive_sha256', ellipsis: true,
                  render: (v) => v ? <Text code style={{ fontSize: 11 }}>{String(v).slice(0, 16)}…</Text> : '-' },
                { title: '密封时限', dataIndex: 'first_flush_after', width: 150, render: fmtTime },
                { title: '错误', dataIndex: 'error', ellipsis: true, render: (v) => v ? <Text type="danger">{v}</Text> : '-' },
                { title: '', width: 150, render: (v, r: AnyObj) => (
                  <Space>
                    {(r.state === 'buffering') && (
                      <Button size="small" icon={<ArrowUpOutlined />} onClick={() => sealContainer(r.container_id)}>密封</Button>)}
                    {(r.state === 'aborted' || r.state === 'flushing' || r.state === 'archiving') && (
                      <Button size="small" onClick={() => retryContainer(r.container_id)}>重试归档</Button>)}
                  </Space>) },
              ]} />
          ),
        },
        {
          key: 'media', label: `介质 (${media.length})`,
          children: (
            <>
            <Card size="small" title="LTFS 栈与会话（GET /archive/ltfs/status · v1.3 双格式）" style={{ marginBottom: 8 }}
              extra={<Button size="small" icon={<ReloadOutlined />} onClick={() => loadLtfs()}>刷新</Button>}>
              {ltfs ? (
                <Space wrap size={6}>
                  <Tag color={ltfs.ltfs_device ? 'geekblue' : 'default'}>设备 {ltfs.ltfs_device || '-'}</Tag>
                  <Tag color={ltfs.ltfs_mounted ? 'orange' : 'green'}>
                    {ltfs.ltfs_mounted ? `会话持驱 ${ltfs.ltfs_mounted}` : '无 LTFS 会话（驱动器空闲）'}</Tag>
                  <Tag>策略 {ltfs.sync_policy}</Tag>
                  {Object.entries(ltfs.binaries || {}).map(([k, v]: any) => (
                    <Tag key={k} color={v ? 'green' : 'red'}>{k}{v ? ' ✓' : ' ✗'}</Tag>))}
                  {(ltfs.mounted_dirs || []).map((d: string) => (
                    <Tag key={d} color="orange">挂载 {d}</Tag>))}
                </Space>
              ) : <Text type="secondary">未获取（后端可能未部署 LTFS 栈或版本 &lt; v1.3）</Text>}
              {ltfsCheck && (
                <Alert style={{ marginTop: 8 }} showIcon
                  type={ltfsCheck.clean ? 'success' : 'warning'}
                  message={`ltfsck ${ltfsCheck.barcode}: ${ltfsCheck.clean ? '一致 (consistent)' : (ltfsCheck.verdict || '异常')}`}
                  description={<pre style={{ margin: 0, maxHeight: 160, overflow: 'auto', fontSize: 11 }}>{String(ltfsCheck.output || '').slice(-600)}</pre>} />
              )}
            </Card>
            <Space style={{ marginBottom: 8 }} wrap>
              <Input size="small" style={{ width: 170 }} placeholder="介质登记：条码 如 CSC006L9"
                value={regBc} onChange={(e) => setRegBc(e.target.value)} />
              <Select size="small" style={{ width: 130 }} value={regState} onChange={setRegState}
                options={['appendable', 'scratch', 'unknown', 'full', 'faulted'].map((s) => ({ value: s, label: s }))} />
              <Select size="small" style={{ width: 110 }} value={regFmt} onChange={setRegFmt}
                options={[{ value: 'raw', label: 'raw 裸块' }, { value: 'ltfs', label: 'LTFS' }]} />
              <Button size="small" type="primary" onClick={regMedia}>登记 POST /media</Button>
              <Text type="secondary" style={{ fontSize: 11 }}>format 决定归档路由（双格式同库共存）</Text>
            </Space>
            <Table rowKey="barcode" size="small" dataSource={media} loading={loading}
              pagination={false}
              columns={[
                { title: '条码', dataIndex: 'barcode', render: (v) => <b>{v}</b> },
                { title: '状态', dataIndex: 'state', width: 110,
                  render: (v) => <Tag color={v === 'appendable' ? 'green' : v === 'faulted' ? 'red' : 'default'}>{v}</Tag> },
                { title: '格式', dataIndex: 'format', width: 80,
                  render: (v) => <Tag color={v === 'ltfs' ? 'geekblue' : 'blue'}>{v || 'raw'}</Tag> },
                { title: '容量', dataIndex: 'capacity_bytes', width: 100, render: fmtBytes },
                { title: '已用', dataIndex: 'used_bytes', width: 100, render: fmtBytes },
                { title: '块数', dataIndex: 'block_records', width: 80 },
                { title: '末文件标记', dataIndex: 'last_filemark', width: 90 },
                { title: '挂载次数', dataIndex: 'mount_count', width: 90 },
                { title: '累计写入', dataIndex: 'bytes_written', width: 100, render: fmtBytes },
                { title: '更新时间', dataIndex: 'updated_at', width: 150, render: fmtTime },
                { title: '操作', width: 200,
                  render: (_: any, r: AnyObj) => (
                    <Space size={4}>
                      <Popconfirm
                        title="销毁性格式化"
                        description={`mkltfs 将抹掉 ${r.barcode} 上全部数据并转为 LTFS（L3），确认执行？`}
                        okText="格式化" okButtonProps={{ danger: true }} cancelText="取消"
                        onConfirm={() => fmtMedia(r.barcode)}>
                        <Button size="small" danger>格式化LTFS</Button>
                      </Popconfirm>
                      <Button size="small"
                        loading={!!ltfsCheck?.busy && ltfsCheck?.barcode === r.barcode}
                        onClick={() => checkLtfs(r.barcode)}>ltfsck</Button>
                    </Space>) },
              ]} />
            </>
          ),
        },
        {
          key: 'tasks', label: `任务 (${tasks.length})`,
          children: (
            <Table rowKey="task_id" size="small" dataSource={tasks} loading={loading}
              pagination={{ pageSize: 15 }}
              columns={[
                { title: '任务', dataIndex: 'task_id', width: 130, render: (v) => <Text copyable>{v}</Text> },
                { title: '类型', dataIndex: 'kind', width: 160 },
                { title: '状态', dataIndex: 'state', width: 90,
                  render: (v) => <Tag color={STATE_COLORS[v]}>{v}</Tag> },
                { title: '尝试', dataIndex: 'attempts', width: 60 },
                { title: '错误', dataIndex: 'error', ellipsis: true, render: (v) => v ? <Text type="danger">{v}</Text> : '-' },
                { title: '结果', dataIndex: 'result', ellipsis: true,
                  render: (v) => v ? <Tooltip title={<pre style={{ margin: 0, maxHeight: 300, overflow: 'auto' }}>{JSON.stringify(v, null, 2)}</pre>}><Text code style={{ fontSize: 11 }}>{JSON.stringify(v).slice(0, 80)}</Text></Tooltip> : '-' },
                { title: '创建', dataIndex: 'created_at', width: 150, render: fmtTime },
              ]} />
          ),
        },
        {
          key: 'dirtree', label: '归档目录树',
          children: <ArchiveDirTree />,
        },
        {
          key: 'cachetree', label: '缓存目录树',
          children: (
            <Card size="small" title="缓存目录树 GET /archive/tree"
              extra={<Space><Button size="small" icon={<ReloadOutlined />} loading={treeLoading} onClick={loadTree}>刷新</Button>
                {tree && <Text type="secondary">{tree.file_count} 物理文件 · {tree.virtual_count ?? 0} 已封箱虚节点 · {tree.unmatched} 未匹配</Text>}</Space>}>
              <Alert type="info" showIcon style={{ marginBottom: 8 }}
                message="目录树架构：上传可指定缓存目录（原文件名落盘）；小文件封箱后原位置显示虚节点（数据在容器/磁带），召回自动还原到原目录树位置。" />
              {tree?.root && (
                <Tree showLine defaultExpandAll
                  treeData={[toTreeNode(tree.root)] as any} />
              )}
            </Card>
          ),
        },
        {
          key: 'metrics', label: '指标',
          children: (
            <Card size="small" title="Prometheus 文本（可直接接入 Prometheus + Grafana）">
              <pre style={{ maxHeight: 400, overflow: 'auto', fontSize: 12 }}>
{stats ? Object.entries(stats.metrics || {}).map(([k, v]) => `${k}: ${v}`).join('\n') : ''}
{'\n'}--- /api/v1/archive/metrics 原文 ---
{(stats?.metrics_text || '')}
              </pre>
            </Card>
          ),
        },
      ]} />
    </div>
  );
}
