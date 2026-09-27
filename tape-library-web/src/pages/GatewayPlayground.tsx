// Gateway Playground —— 《归档网关 API 使用手册（实测版 v1.0）》典型测试场景的一键可执行版
// 数据源：/api/v1/archive/* + /api/v1/libraries|drives|jobs|audit（rawRequest 直连真实网关，同 ArchiveGateway 模式）
// 运维纪律（与手册一致）：执行前查 /safety；LEVEL_2 复述参数并显式确认；202+job_id 轮询到终态；失败最多重试 1 次
import { useRef, useState } from 'react';
import {
  Alert, Button, Card, Col, Input, InputNumber, Row, Space, Tag,
  Typography, message,
} from 'antd';
import {
  CheckCircleOutlined, ClockCircleOutlined, CloseCircleOutlined,
  LoadingOutlined, PlayCircleOutlined, ReloadOutlined,
} from '@ant-design/icons';
import { rawRequest } from '../api/client';
import { sha256Hex, fillRandom, hasWebCrypto } from '../utils/hash';
import { RiskTag } from '../components/RiskTag';
import { ConfirmOperation } from '../components/ConfirmDialog';
import type { ApiResponse } from '../types';

type AnyObj = Record<string, any>;
type StepStatus = 'idle' | 'running' | 'ok' | 'fail' | 'wait';
const { Title, Text, Paragraph } = Typography;
const PUB = 'http://172.16.12.186:8080/api/v1';

// ---------- 工作台上下文：场景之间串联数据（上传→归档→召回→下载 全链路传递） ----------
export interface GwCtx {
  dir: string;            // 上传/召回目录前缀（手册 §4 dir 语义）
  size_kb: number;        // 合成样例文件大小
  changer: string;        // 带库 sg 设备名，如 sg1
  slot: number;           // 可选目标槽（unload 缺省自动回原槽 source_slot，此值仅供手动指定）
  drive: number;          // 带机 DTE 索引，场景 E 拼为 drive_position=DTE<drive>（nst0↔DTE0 / nst1↔DTE2）
  file_id: string;        // 最近一次上传/选中的文件
  container_id: string;   // 最近容器
  barcode: string;        // 最近介质条码
  sha256: string;         // 合成文件基准哈希（下载校验用）
}
const DEFAULT_CTX: GwCtx = {
  dir: 'gwplayground', size_kb: 100, changer: 'sg1', slot: 9, drive: 0,
  file_id: '', container_id: '', barcode: '', sha256: '',
};

// ---------- 步骤日志 ----------
interface Step { label: string; curl: string; status: StepStatus; note?: string; http?: number; env?: AnyObj | null; ms?: number }
interface Scenario {
  key: string; title: string; manual: string; // 手册章节
  risk: 'LEVEL_1' | 'LEVEL_2';
  desc: string;
  steps: { label: string; curl: string }[];
  confirmItems?: (c: GwCtx) => [string, string][];
  run: (mark: (i: number, p: Partial<Step>) => void, ctx: React.MutableRefObject<GwCtx>, patch: (p: Partial<GwCtx>) => void) => Promise<void>;
}

type Resp = ApiResponse & { http_status?: number; blob?: Blob; filename?: string };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const short = (s?: string | null, n = 1800) => {
  if (!s) return '';
  const t = typeof s === 'string' ? s : JSON.stringify(s);
  return t.length > n ? `${t.slice(0, n)}\n…(截断，共 ${t.length} 字符)` : t;
};
const curlOf = (m: string, path: string, body?: any) =>
  `curl -s -X ${m} "${PUB}${path}"${body !== undefined ? ` -H 'Content-Type: application/json' -d '${JSON.stringify(body)}'` : ''}`;

function makeSample(kb: number, name: string): File {
  const bytes = new Uint8Array(kb * 1024);
  fillRandom(bytes);
  return new File([bytes], name, { type: 'application/octet-stream' });
}

// ---------- 通用轮询（手册 §0.3 jobs / §5.3 容器 / tasks） ----------
async function pollJob(mark: Function, i: number, jobId: string, label: string): Promise<Resp> {
  for (let n = 0; n < 150; n++) {
    await sleep(n === 0 ? 1500 : 2500);
    const p = await rawRequest('GET', `/jobs/${jobId}/progress`);
    const st = p.data?.state || 'unknown';
    mark(i, { status: 'wait', note: `${label}：GET /jobs/${jobId}/progress 第 ${n + 1} 次 → ${st}` });
    if (st === 'succeeded' || st === 'failed' || st === 'cancelled') {
      const rs = await rawRequest('GET', `/jobs/${jobId}/result`);
      mark(i, { status: rs.success ? 'ok' : 'fail', env: rs as AnyObj, note: `${label} 终态 ${st}（duration_ms=${rs.data?.duration_ms ?? '-'}）` });
      return rs;
    }
    if (n > 120) { const err: Resp = { success: false, code: 'POLL_TIMEOUT', message: 'job 轮询超时(>6min)' } as Resp; mark(i, { status: 'fail', env: err as AnyObj }); return err; }
  }
  return { success: false, code: 'POLL_TIMEOUT', message: '' } as Resp;
}
async function pollContainer(mark: Function, i: number, cid: string): Promise<Resp> {
  for (let n = 0; n < 60; n++) {
    await sleep(n === 0 ? 1500 : 2500);
    const c = await rawRequest('GET', `/archive/containers/${cid}`);
    const st = c.data?.state || c.data?.container?.state || 'unknown';
    mark(i, { status: 'wait', note: `GET /archive/containers/${cid} 第 ${n + 1} 次 → ${st}` });
    if (st === 'archived' || st === 'failed' || st === 'aborted') {
      mark(i, { status: st === 'archived' ? 'ok' : 'fail', env: c as AnyObj, note: `容器终态 ${st}` });
      return c;
    }
  }
  return { success: false, code: 'POLL_TIMEOUT', message: '容器落带轮询超时' } as Resp;
}
async function pollTask(mark: Function, i: number, tid: string): Promise<Resp> {
  for (let n = 0; n < 150; n++) {
    await sleep(n === 0 ? 1500 : 3000);
    const t = await rawRequest('GET', `/archive/tasks/${tid}`);
    const st = t.data?.state || 'unknown';
    mark(i, { status: 'wait', note: `GET /archive/tasks/${tid} 第 ${n + 1} 次 → ${st}` });
    if (st === 'succeeded' || st === 'failed') {
      mark(i, { status: st === 'succeeded' ? 'ok' : 'fail', env: t as AnyObj, note: `task 终态 ${st}` });
      return t;
    }
  }
  return { success: false, code: 'POLL_TIMEOUT', message: 'task 轮询超时' } as Resp;
}

// 请求 + 判错 + 记录信封（失败即抛出中断该场景，错误信封已展示，重试交给操作员——手册纪律：不盲目重试）
// 特例：/safety 实测返回裸对象无 success 信封（手册 §0.2），HTTP 200 + api_mode 字段存在即视为成功
async function call(mark: Function, i: number, curl: string, fn: () => Promise<Resp>): Promise<Resp> {
  mark(i, { status: 'running', curl });
  const t0 = Date.now();
  const r = await fn();
  const ms = Date.now() - t0;
  const ok = r.success === true || (r.http_status === 200 && (r as AnyObj).api_mode !== undefined);
  if (!ok) { mark(i, { status: 'fail', http: r.http_status, env: r as AnyObj, ms, note: `${r.code}: ${r.message}` }); throw new Error(`${r.code}: ${r.message}`); }
  mark(i, { status: 'ok', http: r.http_status, env: r as AnyObj, ms });
  return r;
}

// ---------- 场景定义（与手册章节一一对应） ----------
export const SCENARIOS: Scenario[] = [
  {
    key: 'A', title: '前置检查与带库概览', manual: '手册 §0.2/§1.1/§1.2/§2.3', risk: 'LEVEL_1',
    desc: 'GET /safety 确认 FULL 模式 → /libraries 找 changer → /libraries/{c}/status 槽位与带机全景 → /archive/media 介质台账。只读，随时可跑。',
    steps: [
      { label: '安全模式', curl: 'curl -s ${B}/safety' },
      { label: '带库列表', curl: 'curl -s ${B}/libraries' },
      { label: '带库全景', curl: '' },
      { label: '介质台账', curl: '' },
    ],
    async run(mark, ctxRef, patch) {
      const s = await call(mark, 0, curlOf('GET', '/safety'), () => rawRequest('GET', '/safety'));
      const allowDev = s.data?.allow_device_operation ?? (s as AnyObj).allow_device_operation; // /safety 裸对象：字段在顶层
      if (!allowDev) throw new Error('allow_device_operation=false，物理场景将被网关拒绝');
      mark(0, { note: `api_mode=${(s as AnyObj).api_mode || s.data?.api_mode} · device=${allowDev} · write=${String(s.data?.allow_write ?? (s as AnyObj).allow_write)}` });
      const l = await call(mark, 1, curlOf('GET', '/libraries'), () => rawRequest('GET', '/libraries'));
      const sg: string = (l.data?.[0]?.sg_device || '/dev/sg1').split('/').pop() || 'sg1';
      patch({ changer: sg });
      await call(mark, 2, curlOf('GET', `/libraries/${sg}/status`), () => rawRequest('GET', `/libraries/${sg}/status`));
      const m = await call(mark, 3, curlOf('GET', '/archive/media'), () => rawRequest('GET', '/archive/media'));
      const first = m.data?.items?.[0];
      if (first) patch({ barcode: first.barcode });
    },
  },
  {
    key: 'B', title: '库存清点与审计留痕（202 异步）', manual: '手册 §1.3/§1.4', risk: 'LEVEL_2',
    desc: 'GET /libraries/{c}/inventory 触发机器人重扫（202+job_id）→ 轮询 /jobs/{id}/progress 至终态 → /result → 用 request_id 查 /audit 看 mtx 命令原文。',
    confirmItems: (c) => [['Library', `/dev/${c.changer}`], ['Command', `mtx -f /dev/${c.changer} inventory`], ['Risk', 'LEVEL_2 · 机器人物理扫库，期间勿发起其它装载']],
    steps: [
      { label: '提交清点', curl: '' },
      { label: '轮询任务', curl: '' },
      { label: '审计回查', curl: '' },
    ],
    async run(mark, ctxRef) {
      const c = ctxRef.current.changer;
      const j = await call(mark, 0, curlOf('GET', `/libraries/${c}/inventory`), () => rawRequest('GET', `/libraries/${c}/inventory`));
      const jobId = j.data?.job_id; const rid = j.request_id;
      if (!jobId) throw new Error('响应缺少 data.job_id');
      await pollJob(mark, 1, jobId, '清点');
      if (rid) await call(mark, 2, curlOf('GET', `/audit/${rid}`), () => rawRequest('GET', `/audit/${rid}`));
    },
  },
  {
    key: 'C', title: '带机状态巡扫', manual: '手册 §2.1/§2.2', risk: 'LEVEL_1',
    desc: '从 /libraries/{c}/status 取带机清单 → 逐台 GET /drives/nst{N}/status（mt status 解析 file_number/flags）→ 对首台 GET /drives/sg{N}/tapealert。注意：/api/v1/drives 裸列表 404（勘误1）。',
    steps: [
      { label: '带机清单', curl: '' },
      { label: 'nst0 status', curl: '' },
      { label: 'nst1 status', curl: '' },
      { label: 'nst2 status', curl: '' },
      { label: 'TapeAlert', curl: '' },
    ],
    async run(mark, ctxRef) {
      const c = ctxRef.current.changer;
      const st = await call(mark, 0, curlOf('GET', `/libraries/${c}/status`), () => rawRequest('GET', `/libraries/${c}/status`));
      const drives: any[] = st.data?.parsed?.drives || [];
      for (let d = 0; d < 3; d++) {
        const loaded = drives[d]?.occupied ? `📼 ${drives[d].barcode}` : '空';
        await call(mark, 1 + d, curlOf('GET', `/drives/nst${d}/status`), () => rawRequest('GET', `/drives/nst${d}/status`)).catch(() => {});
        mark(1 + d, { note: `drive-${d} ${loaded}` });
      }
      const sgDev = drives[0] ? `sg${2 + Number(drives[0].drive ?? 0)}` : 'sg2'; // drive0↔sg2（手册 §2.2）
      await call(mark, 4, curlOf('GET', `/drives/${sgDev}/tapealert`), () => rawRequest('GET', `/drives/${sgDev}/tapealert`));
    },
  },
  {
    key: 'D', title: '查找空闲可写磁带', manual: '手册 §3.1', risk: 'LEVEL_1',
    desc: 'GET /archive/media 过滤 state=appendable（可追加=空闲可写）；带的位置看 /libraries/{c}/status drives[] 的 source_slot。结果写入工作台 barcode。',
    steps: [
      { label: '介质台账', curl: 'curl -s ${B}/archive/media' },
      { label: '带库现状', curl: '' },
    ],
    async run(mark, ctxRef, patch) {
      const m = await call(mark, 0, curlOf('GET', '/archive/media'), () => rawRequest('GET', '/archive/media'));
      const free = (m.data?.items || []).filter((x: AnyObj) => x.state === 'appendable');
      mark(0, { note: free.length ? `空闲可写: ${free.map((x: AnyObj) => `${x.barcode}(已用${Math.round(x.used_bytes / 1048576)}MB/${Math.round(x.capacity_bytes / 1073741824)}GB)`).join(', ')}` : '无 appendable 介质！' });
      if (free[0]) patch({ barcode: free[0].barcode });
      const st = await call(mark, 1, curlOf('GET', `/libraries/${ctxRef.current.changer}/status`), () => rawRequest('GET', `/libraries/${ctxRef.current.changer}/status`));
      const occ = (st.data?.parsed?.drives || []).filter((d: AnyObj) => d.occupied);
      mark(1, { note: occ.length ? `在带机上: ${occ.map((d: AnyObj) => `drive${d.drive}=${d.barcode}(原槽${d.source_slot})`).join(', ')}` : '带机全空' });
    },
  },
  {
    key: 'E', title: 'umount / mount 物理往返（v1.2 参数：barcode+slot / barcode+drive_sn）', manual: '手册 §3.2/§3.3', risk: 'LEVEL_2',
    desc: 'v1.2 推荐参数：unload 传 barcode(检查必在带机)+slot(检查存在且空，取该带原槽) → 轮询 job → status 复核 → load 传 barcode(检查必在槽)+drive_sn(带机序列号，从 /drives/list 现取，检查存在/可达/为空) → 轮询 → status 复核恢复原状。后端动作前双状态检查，响应 checks.* 回显。实测卸 20s / 装 13s。',
    confirmItems: (c) => [['Library', `/dev/${c.changer}`], ['Unload Body', `{ barcode: "取当前带机内磁带", slot: "原槽(source_slot)", confirm: true }`], ['Load Body', `{ barcode: "同上", drive_sn: "带机序列号(/drives/list)", confirm: true }`], ['Risk', 'LEVEL_2 · 机器人物理移带，全程约 40s，动作前逐项状态检查']],
    steps: [
      { label: '装前状态', curl: '' },
      { label: 'umount 提交', curl: '' },
      { label: '轮询 job', curl: '' },
      { label: '卸后复核', curl: '' },
      { label: 'mount 提交', curl: '' },
      { label: '轮询 job', curl: '' },
      { label: '装回复核', curl: '' },
    ],
    async run(mark, ctxRef) {
      const c = ctxRef.current;
      const st0 = await call(mark, 0, curlOf('GET', `/libraries/${c.changer}/status`), () => rawRequest('GET', `/libraries/${c.changer}/status`));
      const drv = (st0.data?.parsed?.drives || []).find((d: AnyObj) => d.drive === c.drive);
      const bc = drv?.barcode;
      if (!bc) throw new Error(`带机 DTE${c.drive} 当前无磁带，无法演示往返（先跑 D 或选带机索引）`);
      // v1.2：带机序列号从 /drives/list 现取（library.dte 或 nst 硬映射匹配）
      const dl = await rawRequest('GET', `/drives/list`);
      const drow = (dl.data?.drives || []).find((x: AnyObj) => x.library?.dte === c.drive)
        || (dl.data?.drives || []).find((x: AnyObj) => x.loaded_tape === bc);
      const sn = drow?.serial;
      mark(0, { note: `DTE${c.drive} 在机磁带 ${bc}（原槽 S${String(drv?.source_slot ?? '?').padStart(3, '0')}）${sn ? `· 带机 SN ${sn}(/dev/${drow.nst})` : ''}` });
      const uBody: AnyObj = { barcode: bc, confirm: true };
      if (drv?.source_slot) uBody.slot = drv.source_slot;
      const u = await call(mark, 1, curlOf('POST', `/libraries/${c.changer}/unload`, uBody), () => rawRequest('POST', `/libraries/${c.changer}/unload`, { body: uBody }));
      const uj = u.data?.job_id; if (!uj) throw new Error('缺少 job_id');
      await pollJob(mark, 2, uj, 'umount');
      const st1 = await call(mark, 3, curlOf('GET', `/libraries/${c.changer}/status`), () => rawRequest('GET', `/libraries/${c.changer}/status`));
      const landed = (st1.data?.parsed?.slots || []).find((x: AnyObj) => x.barcode === bc);
      mark(3, { note: `drive ${c.drive} 已空=${!(st1.data?.parsed?.drives || [])[c.drive]?.occupied}，磁带落槽 ${landed ? `S${String(landed.element).padStart(3, '0')}` : '?'}` });
      const lBody: AnyObj = sn ? { barcode: bc, drive_sn: sn, confirm: true } : { barcode: bc, drive_position: `DTE${c.drive}`, confirm: true };
      const l = await call(mark, 4, curlOf('POST', `/libraries/${c.changer}/load`, lBody), () => rawRequest('POST', `/libraries/${c.changer}/load`, { body: lBody }));
      const lj = l.data?.job_id; if (!lj) throw new Error('缺少 job_id');
      await pollJob(mark, 5, lj, 'mount');
      const st2 = await call(mark, 6, curlOf('GET', `/libraries/${c.changer}/status`), () => rawRequest('GET', `/libraries/${c.changer}/status`));
      const dv = (st2.data?.parsed?.drives || []).find((d: AnyObj) => d.drive === c.drive);
      mark(6, { note: `drive ${c.drive} occupied=${String(dv?.occupied)} barcode=${dv?.barcode || '-'}（应恢复 ${bc}）${sn ? '· 本次 load 用 drive_sn 定位' : ''}` });
    },
  },
  {
    key: 'F', title: '上传样例文件到指定目录', manual: '手册 §4', risk: 'LEVEL_1',
    desc: '本地合成随机文件（默认 100KB < 64MB 阈值 → 走聚合容器 CONTAINER_BUFFERED）→ POST /archive/upload?dir={dir} → file_id/container_id/sha256 写入工作台。',
    steps: [
      { label: '合成样例', curl: '' },
      { label: '上传', curl: '' },
    ],
    async run(mark, ctxRef, patch) {
      const c = ctxRef.current;
      const name = `gw-sample-${Date.now()}.bin`;
      const file = makeSample(c.size_kb, name);
      const hex = await sha256Hex(await file.arrayBuffer());
      mark(0, { status: 'ok', curl: `// 本地生成 ${c.size_kb}KB 随机文件 ${name}`, note: `sha256=${hex}（${hasWebCrypto() ? 'WebCrypto' : 'JS 回退实现：非 HTTPS 安全上下文无 crypto.subtle，校验结果等价'}）` });
      const fd = new FormData(); fd.append('file', file);
      const path = `/archive/upload?dir=${encodeURIComponent(c.dir)}`;
      const r = await call(mark, 1, `curl -s -F "file=@${name}" "${PUB}/archive/upload?dir=${c.dir}"`, () => rawRequest('POST', path, { body: fd }));
      const d = r.data || {};
      patch({ file_id: d.file_id || '', container_id: d.container_id || '', sha256: hex });
      mark(1, { note: `${d.code || r.code} · route=${d.route} · rel_path=${d.rel_path} → file_id 已入工作台` });
    },
  },
  {
    key: 'G', title: '归档文件到磁带并等待落带', manual: '手册 §5', risk: 'LEVEL_1',
    desc: 'POST /archive/files/{file_id}/archive（小文件→CONTAINER_SEALED 封箱；大文件→TAPE_ARCHIVE_QUEUED+task_id）→ 轮询容器/任务至 archived → 详情看 location。',
    steps: [
      { label: '提交归档', curl: '' },
      { label: '等待落带', curl: '' },
      { label: '文件详情', curl: '' },
    ],
    async run(mark, ctxRef, patch) {
      const fid = ctxRef.current.file_id;
      if (!fid) throw new Error('工作台缺少 file_id——先跑场景 F 或手工填入');
      const a = await call(mark, 0, curlOf('POST', `/archive/files/${fid}/archive`), () => rawRequest('POST', `/archive/files/${fid}/archive`));
      const d = a.data || {};
      mark(0, { note: `${a.code} · route=${d.route} · state=${d.state}` });
      if (d.route === 'container' || d.container_id) {
        if (d.container_id) patch({ container_id: d.container_id });
        await pollContainer(mark, 1, d.container_id || ctxRef.current.container_id);
      } else if (d.task_id) {
        await pollTask(mark, 1, d.task_id);
      } else { mark(1, { status: 'ok', note: '无容器/任务句柄（可能已 archived）' }); }
      await call(mark, 2, curlOf('GET', `/archive/files/${fid}`), () => rawRequest('GET', `/archive/files/${fid}`));
      mark(2, { note: '判定看 location.needs_recall（勘误4：容器成员 on_tape=false 属正常，看 download_ready）' });
    },
  },
  {
    key: 'H', title: '路径/文件状态查询', manual: '手册 §6', risk: 'LEVEL_1',
    desc: '列表过滤 ?name=&state= → 单文件详情（权威位置判定 location.*）→ 目录树 /archive/tree。',
    steps: [
      { label: '列表过滤', curl: '' },
      { label: '文件详情', curl: '' },
      { label: '目录树', curl: '' },
    ],
    async run(mark, ctxRef) {
      const c = ctxRef.current;
      await call(mark, 0, curlOf('GET', '/archive/files?limit=10&state=archived'), () => rawRequest('GET', '/archive/files', { query: { limit: 10, state: 'archived', name: c.file_id ? undefined : 'gw-sample' } }));
      if (c.file_id) await call(mark, 1, curlOf('GET', `/archive/files/${c.file_id}`), () => rawRequest('GET', `/archive/files/${c.file_id}`));
      else mark(1, { status: 'ok', note: '工作台无 file_id，跳过详情（可先跑 F 或点「取列表首条」）', curl: curlOf('GET', '/archive/files/<file_id>') });
      await call(mark, 2, curlOf('GET', '/archive/tree'), () => rawRequest('GET', '/archive/tree'));
    },
  },
  {
    key: 'I', title: '缓存容量检查与强制淘汰', manual: '手册 §7', risk: 'LEVEL_2',
    desc: 'GET /archive/stats 水位总览（quota/高/低水位/metrics）→ GET /archive/cache 目录明细 → POST /archive/evict 强制水位检查（实测 action=none 即健康）。',
    confirmItems: (c) => [['Action', 'POST /archive/evict · 立即执行 LRU 水位检查'], ['Rule', '脏数据（未落带）绝不淘汰；净数据按 LRU，跳 refcount>0'], ['Risk', 'LEVEL_2 · 可能删除可再生缓存副本（磁带始终保有底本）']],
    steps: [
      { label: '水位总览', curl: 'curl -s ${B}/archive/stats' },
      { label: '缓存明细', curl: '' },
      { label: '强制淘汰', curl: '' },
    ],
    async run(mark) {
      const s = await call(mark, 0, curlOf('GET', '/archive/stats'), () => rawRequest('GET', '/archive/stats'));
      const cache = s.data?.cache || {};
      mark(0, { note: `缓存 ${Math.round(Number(cache.total_bytes || 0) / 1048576)}MB / 配额 ${Math.round((cache.quota_bytes || 0) / 1073741824)}GB · 磁盘余 ${Math.round((cache.fs_free_bytes || 0) / 1099511627776)}TB` });
      await call(mark, 1, curlOf('GET', '/archive/cache?limit=5'), () => rawRequest('GET', '/archive/cache', { query: { limit: 5 } }));
      await call(mark, 2, curlOf('POST', '/archive/evict'), () => rawRequest('POST', '/archive/evict'));
    },
  },
  {
    key: 'J', title: '召回归档文件（热/冷自动判定）', manual: '手册 §8', risk: 'LEVEL_1',
    desc: '先读详情 location.needs_recall：false→同步 RECALL_HIT（毫秒）；true→202+job 冷召回（自动装带→定位 block→读带→落盘→卸带，实测 73MB/3.6s）。dir 是还原根，原目录树在其下重建。',
    steps: [
      { label: '预判位置', curl: '' },
      { label: '提交召回', curl: '' },
      { label: '轮询结果', curl: '' },
    ],
    async run(mark, ctxRef) {
      const c = ctxRef.current;
      if (!c.file_id) throw new Error('工作台缺少 file_id——先跑 F(+G) 或手工填入');
      const det = await call(mark, 0, curlOf('GET', `/archive/files/${c.file_id}`), () => rawRequest('GET', `/archive/files/${c.file_id}`));
      const loc = det.data?.location || {};
      mark(0, { note: `zone=${loc.zone} hit=${loc.hit} needs_recall=${String(loc.needs_recall)}` });
      const path = `/archive/files/${c.file_id}/recall?dir=${encodeURIComponent(c.dir)}`;
      const r = await call(mark, 1, curlOf('POST', path), () => rawRequest('POST', path));
      if (r.http_status === 202 && r.data?.job_id) {
        await pollJob(mark, 2, r.data.job_id, '冷召回');
      } else {
        mark(2, { status: 'ok', note: `同步命中 ${r.code}（热数据，无 job）→ ${r.data?.path || ''}`, curl: `// 热召回直接返回，无需轮询` });
      }
    },
  },
  {
    key: 'K', title: '下载归档文件（两段式 + SHA 校验）', manual: '手册 §9', risk: 'LEVEL_1',
    desc: 'GET /archive/files/{id}/download：热=直接文件流；冷=202 提交召回→轮询 job→重发 download 取流（官方 hint: "GET download again to stream"）。取回后与工作台 sha256 比对。',
    steps: [
      { label: '首次请求', curl: '' },
      { label: '轮询召回', curl: '' },
      { label: '取流校验', curl: '' },
    ],
    async run(mark, ctxRef) {
      const fid = ctxRef.current.file_id;
      if (!fid) throw new Error('工作台缺少 file_id');
      const path = `/archive/files/${fid}/download`;
      mark(0, { status: 'running', curl: `curl -s -o out.bin "${PUB}${path}"` });
      let r = await rawRequest('GET', path, { binary: true }) as Resp;
      const t0 = Date.now();
      if (r.success && r.code === 'BINARY') {
        mark(0, { status: 'ok', http: r.http_status, ms: Date.now() - t0, note: '热命中，直接文件流', env: r.data as AnyObj });
        mark(1, { status: 'ok', note: '无 job（跳过轮询）', curl: '// 冷数据才会走到这一步' });
      } else if (!r.success) {
        mark(0, { status: 'fail', env: r as AnyObj, note: `${r.code}: ${r.message}` }); throw new Error(`${r.code}`);
      } else {
        r.http_status === 202
          ? mark(0, { status: 'ok', http: 202, ms: Date.now() - t0, env: r as AnyObj, note: '冷数据 → JOB_SUBMITTED，两段式生效' })
          : mark(0, { status: 'ok', env: r as AnyObj });
        const rs = await pollJob(mark, 1, r.data?.job_id, '下载前召回');
        if (!rs.success) throw new Error('召回 job 失败');
        const t1 = Date.now();
        r = await rawRequest('GET', path, { binary: true }) as Resp;
        mark(1, { note: '第二段：重发同一 GET download → 流式取回' });
        if (r.code !== 'BINARY') { mark(2, { status: 'fail', env: r as AnyObj }); throw new Error(String(r.code)); }
        mark(2, { status: 'ok', ms: Date.now() - t1, env: r.data as AnyObj });
      }
      if (r.blob) {
        const hex = await sha256Hex(await r.blob.arrayBuffer());
        const base = ctxRef.current.sha256;
        const match = base ? (hex === base ? 'YES ✅' : 'NO ❌') : '（无基准，仅记录）';
        mark(2, { note: `${r.filename} ${r.blob.size}B sha256=${hex.slice(0, 16)}… SHA_MATCH=${match}` });
        const url = URL.createObjectURL(r.blob);
        const a = document.createElement('a'); a.href = url; a.download = r.filename || 'download.bin'; a.click();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
      }
    },
  },
  {
    key: 'L', title: '端到端全链路（上传→落带→召回→下载校验）', manual: '手册 附录A 时间线', risk: 'LEVEL_1',
    desc: '串联 F→G→H→J→K：合成样例上传 → 归档封箱等落带 → 状态查询 → 召回 → 下载并 SHA 校验。一次跑通即复现手册实测链路（当日全程约 30s）。',
    steps: [
      { label: '合成+上传', curl: '' },
      { label: '归档+落带', curl: '' },
      { label: '状态详情', curl: '' },
      { label: '召回', curl: '' },
      { label: '下载校验', curl: '' },
    ],
    async run(mark, ctxRef, patch) {
      const F = SCENARIOS.find((x) => x.key === 'F')!, G = SCENARIOS.find((x) => x.key === 'G')!;
      const J = SCENARIOS.find((x) => x.key === 'J')!, K = SCENARIOS.find((x) => x.key === 'K')!;
      const relay = (base: number, sc: Scenario, mapping: Record<number, number>) =>
        sc.run((i, p) => mark(mapping[i] ?? i, p), ctxRef, patch);
      const wrap = async (labelIdx: number, fn: () => Promise<void>, curl: string) => {
        mark(labelIdx, { status: 'running', curl }); await fn();
      };
      await wrap(0, () => relay(0, F, { 0: 0, 1: 0 }), 'curl -s -F "file=@sample.bin" "${PUB}/archive/upload?dir=..."');
      mark(0, { note: `file_id=${ctxRef.current.file_id}` });
      await wrap(1, () => relay(0, G, { 0: 1, 1: 1, 2: 2 }), 'curl -X POST "${PUB}/archive/files/<file_id>/archive"');
      await relay(0, J, { 0: 3, 1: 3, 2: 3 });
      await relay(0, K, { 0: 4, 1: 4, 2: 4 });
      const det = await rawRequest('GET', `/archive/files/${ctxRef.current.file_id}`);
      mark(2, { note: `state=${det.data?.state} · location.zone=${det.data?.location?.zone} · 全链路 ✅` });
    },
  },
];

// ---------- 步骤时间线 ----------
const ICON: Record<StepStatus, any> = {
  idle: <ClockCircleOutlined style={{ color: '#999' }} />,
  running: <LoadingOutlined style={{ color: '#1677ff' }} />,
  wait: <LoadingOutlined style={{ color: '#faad14' }} />,
  ok: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  fail: <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
};
function StepRow({ step }: { step: Step }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ padding: '6px 0', borderBottom: '1px dashed #f0f0f0' }}>
      <Space wrap size={6}>
        {ICON[step.status]}
        <b>{step.label}</b>
        {step.http !== undefined && <Tag>{step.http}</Tag>}
        {step.ms !== undefined && <span style={{ color: '#999', fontSize: 12 }}>{step.ms}ms</span>}
        {step.env && (
          <Button size="small" type="link" style={{ padding: 0 }} onClick={() => setOpen(!open)}>
            {open ? '收起响应' : '原始响应'}
          </Button>
        )}
      </Space>
      {step.note && <div style={{ color: '#555', fontSize: 12, marginLeft: 22 }}>{step.note}</div>}
      {step.curl && <pre style={preStyle('#f6f8fa', '#444')}>{short(step.curl, 400)}</pre>}
      {open && step.env && <pre style={preStyle('#0d1117', '#c9d1d9')}>{short(JSON.stringify(step.env, null, 2))}</pre>}
    </div>
  );
}
const preStyle = (bg: string, fg: string): React.CSSProperties => ({
  background: bg, color: fg, padding: 8, borderRadius: 6, fontSize: 12, lineHeight: 1.5,
  whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 300, overflow: 'auto', margin: '4px 0 0 22px',
});

// ---------- 主组件 ----------
export default function GatewayPlayground() {
  const [ctx, setCtx] = useState<GwCtx>(DEFAULT_CTX);
  const ctxRef = useRef<GwCtx>(ctx);
  const patch = (p: Partial<GwCtx>) => { ctxRef.current = { ...ctxRef.current, ...p }; setCtx(ctxRef.current); };
  const [confirmKey, setConfirmKey] = useState<string | null>(null);
  // 卡片句柄注册表：{reset,setBusy,mark}，由 ScenarioCard 挂载时写入
  const cardRefs = useRef<Record<string, any>>({});

  const runScenario = async (sc: Scenario) => {
    const api = cardRefs.current[sc.key];
    if (!api) return;
    api.reset();
    api.setBusy(true);
    try {
      await sc.run(api.mark, ctxRef, patch);
      message.success(`场景 ${sc.key}「${sc.title}」完成`);
    } catch (e: any) {
      message.error(`场景 ${sc.key} 中断：${e?.message || e}（信封已存档于对应步骤，勿盲目重试）`);
    } finally {
      api.setBusy(false);
    }
  };

  return (
    <div>
      <Title level={3} style={{ marginBottom: 4 }}>Gateway Playground</Title>
      <Paragraph type="secondary" style={{ marginTop: 0 }}>
        把《归档网关 API 使用手册（实测版 v1.0·2026.09.19）》的典型测试场景做成一键执行。
        202/异步任务自动轮询到终态，LEVEL_2 操作先复述参数再执行，所有原始响应可展开回查。
      </Paragraph>

      <Card size="small" title="工作台上下文（场景间自动流转，可手工改写）" style={{ marginBottom: 16 }}>
        <Row gutter={[12, 8]}>
          <Col xs={24} md={12} lg={8}><Text type="secondary">上传/召回 dir：</Text>
            <Input size="small" value={ctx.dir} onChange={(e) => patch({ dir: e.target.value })} style={{ width: 'calc(100% - 130px)' }} /></Col>
          <Col xs={12} md={6} lg={4}><Text type="secondary">样例 KB：</Text>
            <InputNumber size="small" min={1} max={204800} value={ctx.size_kb} onChange={(v) => patch({ size_kb: Number(v) || 100 })} style={{ width: 90 }} /></Col>
          <Col xs={12} md={6} lg={4}><Text type="secondary">changer：</Text>
            <Input size="small" value={ctx.changer} onChange={(e) => patch({ changer: e.target.value })} style={{ width: 70 }} /></Col>
          <Col xs={12} md={6} lg={5}><Text type="secondary">目标槽/带机DTE：</Text>
            <InputNumber size="small" min={0} value={ctx.slot} onChange={(v) => patch({ slot: Number(v) || 0 })} style={{ width: 60 }} />
            <span style={{ margin: '0 2px' }}>/</span>
            <InputNumber size="small" min={0} max={2} value={ctx.drive} onChange={(v) => patch({ drive: Number(v) || 0 })} style={{ width: 54 }} /></Col>
          <Col xs={12} md={6} lg={8}><Text type="secondary">file_id：</Text>
            <Input size="small" value={ctx.file_id} placeholder="上传后自动填入"
              onChange={(e) => patch({ file_id: e.target.value.trim() })} style={{ width: 'calc(100% - 70px)' }} /></Col>
          <Col xs={24}>
            <Space wrap size={6}>
              <Tag color="blue">container: {ctx.container_id ? ctx.container_id.slice(0, 8) + '…' : '-'}</Tag>
              <Tag color="purple">media: {ctx.barcode || '-'}</Tag>
              <Tag color="geekblue">sha256: {ctx.sha256 ? ctx.sha256.slice(0, 12) + '…' : '-'}</Tag>
              <Button size="small" icon={<ReloadOutlined />} onClick={() => { ctxRef.current = { ...DEFAULT_CTX }; setCtx(ctxRef.current); }}>重置</Button>
            </Space>
          </Col>
        </Row>
      </Card>

      <Row gutter={[16, 16]}>
        {SCENARIOS.map((sc) => (
          <Col key={sc.key} xs={24} xl={12}>
            <ScenarioCard sc={sc} ctx={ctx} cardRefs={cardRefs}
              onRun={() => (sc.risk === 'LEVEL_2' ? setConfirmKey(sc.key) : runScenario(sc))}
              confirmOpen={confirmKey === sc.key}
              onConfirm={() => { setConfirmKey(null); runScenario(sc); }}
              onCancel={() => setConfirmKey(null)} />
          </Col>
        ))}
      </Row>

      <Alert style={{ marginTop: 16 }} type="info" showIcon
        message="提示" description={
          <>① 冷召回/冷下载需机器人装带读带，分钟级属正常；② 场景失败先展开「原始响应」看 code/request_id，最多手动重试 1 次；③ 大文件（&gt;64MB）上传走直写磁带 task 路径；④ 对应端点级调试请用 API Playground，curl 逐条复制请用手册。</>
        } />
    </div>
  );
}
function ScenarioCard({ sc, ctx, cardRefs, onRun, confirmOpen, onConfirm, onCancel }: {
  sc: Scenario; ctx: GwCtx; cardRefs: React.MutableRefObject<Record<string, any>>;
  onRun: () => void; confirmOpen: boolean; onConfirm: () => void; onCancel: () => void;
}) {
  const [steps, setSteps] = useState<Step[]>(sc.steps.map((s) => ({ ...s, status: 'idle', env: null })));
  const [busy, setBusy] = useState(false);
  cardRefs.current[sc.key] = {
    reset: () => setSteps(sc.steps.map((s) => ({ ...s, status: 'idle', env: null }))),
    setBusy, mark: (i: number, p: Partial<Step>) => setSteps((prev) => prev.map((st, j) => (j === i ? { ...st, ...p } : st))),
  };
  return (
    <Card size="small" style={{ height: '100%' }}
      title={<Space wrap><Tag>{sc.key}</Tag>{sc.title}<RiskTag level={sc.risk} /></Space>}
      extra={
        <Space>
          <Text type="secondary" style={{ fontSize: 12 }}>{sc.manual}</Text>
          <Button type="primary" size="small" icon={<PlayCircleOutlined />} loading={busy} disabled={busy} onClick={onRun}>运行</Button>
        </Space>
      }>
      <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>{sc.desc}</Paragraph>
      {steps.map((s, i) => <StepRow key={i} step={s} />)}
      <ConfirmOperation
        open={confirmOpen} title={`场景 ${sc.key} · ${sc.title}`} riskColor="orange"
        confirmText="确认执行（含 confirm:true）"
        items={sc.confirmItems ? sc.confirmItems(ctx) : []}
        onCancel={onCancel} onConfirm={onConfirm} />
    </Card>
  );
}
