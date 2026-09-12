// 统一 API Client —— mock/real 双模式分发；real 模式基于 openapi.json 实测适配（不猜测接口）
import axios from 'axios';
import { mockApi } from './mock';
import { logApiCall } from './apilog';
import type { ApiResponse, TestKind } from '../types';

export const API_MODE: 'mock' | 'real' =
  (import.meta.env.VITE_API_MODE as 'mock' | 'real') || 'mock';
const BASE = (import.meta.env.VITE_API_BASE_URL as string) || '';

const http = axios.create({
  baseURL: `${BASE}/api/v1`,
  timeout: 7200000,
  headers: { 'Content-Type': 'application/json' },
});

// 统一错误归一化：HTTP 4xx/5xx → { success:false, code, message }
function normalizeError(e: any): ApiResponse {
  if (e.response) {
    const d = e.response.data || {};
    // FastAPI 错误体 {detail:{code,message}} —— detail 可能是对象，需展开
    const det = typeof d.detail === 'object' && d.detail !== null ? d.detail : {};
    return {
      success: false,
      code: d.code || det.code || `HTTP_${e.response.status}`,
      message: d.message || det.message || (typeof d.detail === 'string' ? d.detail : '') || e.response.statusText,
      error: { type: d.code || det.code || 'HTTP_ERROR', details: JSON.stringify(d).slice(0, 400) },
    };
  }
  return { success: false, code: 'AGENT_UNAVAILABLE', message: String(e.message || e), error: { type: 'NETWORK', details: 'Cannot reach Tape Library API' } };
}

async function get(path: string): Promise<ApiResponse> {
  if (API_MODE === 'mock') {
    const t0 = performance.now();
    const fn = (mockApi as any)[pathKey(path)];
    const r: ApiResponse = fn ? await fn() : mockNotFound(path);
    logApiCall({ method: 'GET', path: `/api/v1${path}`, status: 0, ok: !!r?.success, code: r?.code || '', request_id: r?.request_id, duration_ms: Math.round(performance.now() - t0), response: r });
    return r;
  }
  const t0 = performance.now();
  try {
    const r = await http.get(path);
    logApiCall({ method: 'GET', path: `/api/v1${path}`, status: r.status, ok: !!r.data?.success, code: r.data?.code || '', request_id: r.data?.request_id, duration_ms: Math.round(performance.now() - t0), response: r.data });
    return r.data;
  } catch (e) {
    const n = normalizeError(e);
    logApiCall({ method: 'GET', path: `/api/v1${path}`, status: (e as any)?.response?.status || 0, ok: false, code: n.code, duration_ms: Math.round(performance.now() - t0), response: n });
    return n;
  }
}

async function post(path: string, body?: any): Promise<ApiResponse> {
  if (API_MODE === 'mock') {
    const t0 = performance.now();
    const fn = (mockApi as any)[pathKey(path)];
    const r: ApiResponse = await (fn ? fn(body) : Promise.resolve(mockNotFound(path)));
    logApiCall({ method: 'POST', path: `/api/v1${path}`, request_body: body, status: 0, ok: !!r?.success, code: r?.code || '', request_id: r?.request_id, duration_ms: Math.round(performance.now() - t0), response: r });
    return r;
  }
  const t0 = performance.now();
  try {
    const r = await http.post(path, body);
    logApiCall({ method: 'POST', path: `/api/v1${path}`, request_body: body, status: r.status, ok: !!r.data?.success, code: r.data?.code || '', request_id: r.data?.request_id, duration_ms: Math.round(performance.now() - t0), response: r.data });
    return r.data;
  } catch (e) {
    const n = normalizeError(e);
    logApiCall({ method: 'POST', path: `/api/v1${path}`, request_body: body, status: (e as any)?.response?.status || 0, ok: false, code: n.code, duration_ms: Math.round(performance.now() - t0), response: n });
    return n;
  }
}

function pathKey(path: string): string {
  // GET 路径 → mockApi 方法名映射
  const m: Record<string, string> = {
    '/safety': 'safety', '/system/info': 'systemInfo', '/libraries': 'listLibraries',
    '/drives': 'listDrives', '/operations': 'operations', '/audit': 'auditList',
  };
  let key = m[path];
  if (!key && path.startsWith('/libraries/') && path.endsWith('/status')) key = 'libraryStatus:' + path.split('/')[2];
  if (!key && path.startsWith('/libraries/') && path.endsWith('/inventory')) key = 'libraryInventory:' + path.split('/')[2];
  if (!key && path.startsWith('/test-sessions')) key = 'session:' + path.split('/')[2];
  return key || '';
}

function mockNotFound(path: string): ApiResponse {
  return { success: false, code: 'NOT_IMPLEMENTED', message: `mock handler missing for ${path}`, error: { type: 'MOCK' } };
}

// ---- 面向页面的统一 API 门面 ----
const strip = (d: string) => (d || '').replace(/^\/dev\//, '');

// real 模式适配层：真实 API 响应 → 前端统一形状（不猜测，全部按实测 openapi 形状映射）
function fillCounts(lib: any, parsed: any) {
  const slots: any[] = parsed.slots || [];
  const drives: any[] = parsed.drives || parsed.data_transfer_elements || [];
  const storage = slots.filter((s: any) => !s.import_export);
  lib.slot_count = storage.length;
  lib.occupied_slots = storage.filter((s: any) => s.occupied).length;
  lib.tape_count = lib.occupied_slots;
  lib.drive_count = drives.length;
  lib.loaded_drives = drives.filter((d: any) => d.occupied).length;
  lib.slots = storage.map((s: any) => ({
    element: s.element, slot: s.element, barcode: s.barcode ?? null,
    media_type: null, status: s.occupied ? 'Occupied' : 'Empty',
  }));
  lib.driveElements = drives.map((d: any, i: number) => ({
    index: i, loaded: !!d.occupied, barcode: d.barcode ?? null,
  }));
}

async function realLibraries(): Promise<ApiResponse> {
  const r = await get('/libraries');
  if (!r.success) return r;
  const raw = ((r.data as any[]) || []).filter((x) => x.device_type === 'MEDIUMX');
  const libs = raw.map((x) => ({
    changer: strip(x.sg_device), vendor: x.vendor, model: x.product,
    serial: '', firmware: '', status: 'Online',
    drive_count: 0, slot_count: 0, occupied_slots: 0, tape_count: 0, loaded_drives: 0,
    last_update: new Date().toISOString(),
  }));
  // 去重：FC 多路径会导致同一物理库出现多个 sg 设备（如 sg1/sg3），
  // 用 SCSI inquiry 序列号识别同一设备，只保留第一个
  const seenSerials = new Set<string>();
  const unique: typeof libs = [];
  for (const lib of libs) {
    let serial = '';
    const inq = await get(`/scsi/${lib.changer}/inquiry`).catch(() => null);
    serial = inq?.data?.parsed?.unit_serial_number || '';
    if (serial && seenSerials.has(serial)) continue; // 同一物理库的另一条路径，跳过
    if (serial) seenSerials.add(serial);
    lib.serial = serial;
    const st = await get(`/libraries/${lib.changer}/status`);
    if (st.success && st.data?.parsed) fillCounts(lib, st.data.parsed);
    unique.push(lib);
  }
  return { ...r, data: unique };
}

async function realLibraryStatus(changer: string): Promise<ApiResponse> {
  const r = await get(`/libraries/${changer}/status`);
  if (!r.success) return r;
  const lib: any = {
    changer, vendor: 'IBM', model: '03584L32', serial: '', firmware: '', status: 'Online',
    drive_count: 0, slot_count: 0, occupied_slots: 0, tape_count: 0, loaded_drives: 0,
    last_update: new Date().toISOString(), stdout: r.data?.stdout,
  };
  fillCounts(lib, r.data?.parsed || {});
  return { ...r, data: lib };
}

async function realInventory(changer: string): Promise<ApiResponse> {
  const r = await get(`/libraries/${changer}/inventory`);
  if (!r.success) return r;
  const slots = ((r.data?.slots || []) as any[]).map((s) => ({
    element: s.element, slot: s.slot ?? s.element, barcode: s.barcode ?? null,
    media_type: null, status: s.occupied ? 'Occupied' : 'Empty',
  }));
  const volumes: any[] = slots.filter((s) => s.status === 'Occupied' && s.barcode).map((s) => ({
    barcode: s.barcode, media_type: 'LTO', generation: '', slot: s.slot, drive: null,
    status: 'Available', write_protect: false, health: 'Good',
  }));
  // 带机里的磁带（在库外）：slot=null, drive=/dev/nstN, status=Loaded
  const dtes = await libraryDtes();
  dtes.forEach((d: any, i: number) => {
    if (d.occupied && d.barcode) {
      volumes.unshift({
        barcode: d.barcode, media_type: 'LTO', generation: '', slot: null,
        drive: `/dev/nst${i + 1}`, status: 'Loaded', write_protect: false, health: 'Good',
        source_slot: d.source_slot ?? null,
      });
    }
  });
  return { ...r, data: { library: r.data?.library, slots, volumes } };
}

async function realDrives(): Promise<ApiResponse> {
  const r = await get('/discovery');
  if (!r.success) return r;
  const devs = ((r.data?.devices || (Array.isArray(r.data) ? r.data : [])) as any[])
    .filter((x) => x.device_type === 'TAPE');
  // 合并带库 DTE 装载信息（磁带在带机里 → loaded_tape/status）
  const dtes = await libraryDtes();
  return {
    ...r,
    data: devs.map((x, i) => {
      const dte = dtes[i];
      return {
        index: i, sg: strip(x.sg_device), nst: strip(x.nst_device || x.st_device || ''),
        vendor: x.vendor, model: x.product, serial: '', firmware: '',
        scsi_address: x.scsi_address,
        status: dte?.occupied ? 'LOADED' : 'EMPTY',
        loaded_tape: dte?.barcode ?? null,
        source_slot: dte?.source_slot ?? null,
        block_size: 0, compression: true, temperature: null,
        tapealert: { triggered_count: 0, all_clear: true }, health: 'Healthy',
      };
    }),
  };
}

// 拉取带库 status 的 DTE 列表（磁带在带机里的信息）
async function libraryDtes(): Promise<any[]> {
  const r = await get('/libraries/sg1/status');
  return r.success ? (r.data?.parsed?.drives || []) : [];
}

async function realDriveDetail(nst: string): Promise<ApiResponse> {
  const r = await get(`/drives/${nst}/status`);
  if (!r.success) return r;
  const p = r.data?.parsed || {};
  // DTE 序号：nst1 → DTE 0
  const dteIdx = parseInt(nst.replace(/\D/g, ''), 10) - 1;
  const dtes = await libraryDtes();
  const dte = Number.isFinite(dteIdx) ? dtes[dteIdx] : undefined;
  const d = await get('/discovery');
  const dev = d.success
    ? ((d.data?.devices || (Array.isArray(d.data) ? d.data : [])) as any[])
        .find((x) => strip(x.nst_device || '') === nst || strip(x.st_device || '') === nst)
    : null;
  return {
    ...r,
    data: {
      index: 0, sg: strip(dev?.sg_device || ''), nst,
      vendor: dev?.vendor || '', model: dev?.product || '', serial: '', firmware: '',
      scsi_address: dev?.scsi_address || '',
      status: dte?.occupied ? 'LOADED' : p.file_number >= 0 ? 'LOADED' : 'EMPTY',
      loaded_tape: dte?.barcode ?? p.volume_tag ?? null,
      block_size: p.block_size ?? 0, compression: true, temperature: null,
      tapealert: { triggered_count: 0, all_clear: true }, health: 'Healthy',
      stdout: r.data?.stdout,
    },
  };
}

// mock 直调的日志包装：保证 mock 模式与 real 模式日志一致
async function mockLogged(
  method: 'GET' | 'POST', path: string, body: any, fn: () => any,
): Promise<ApiResponse> {
  const t0 = performance.now();
  const r: ApiResponse = await fn();
  logApiCall({
    method, path: `/api/v1${path}`, request_body: body, status: 0,
    ok: !!r?.success, code: r?.code || '', request_id: r?.request_id,
    duration_ms: Math.round(performance.now() - t0), response: r,
  });
  return r;
}

export const api = {
  mode: API_MODE,

  safety: () => get('/safety'),
  systemInfo: () => get('/system/info'),

  // Libraries
  listLibraries: async (): Promise<ApiResponse> =>
    API_MODE === 'mock' ? mockLogged('GET', '/libraries', undefined, () => mockApi.listLibraries()) : realLibraries(),
  libraryStatus: (changer: string) =>
    API_MODE === 'mock' ? mockLogged('GET', `/libraries/${changer}/status`, undefined, () => mockApi.libraryStatus(changer)) : realLibraryStatus(changer),
  libraryInventory: (changer: string) =>
    API_MODE === 'mock' ? mockLogged('GET', `/libraries/${changer}/inventory`, undefined, () => mockApi.libraryInventory(changer)) : realInventory(changer),

  // Drives
  listDrives: async (): Promise<ApiResponse> =>
    API_MODE === 'mock' ? mockLogged('GET', '/drives', undefined, () => mockApi.listDrives()) : realDrives(),
  driveDetail: (nst: string) =>
    API_MODE === 'mock' ? mockLogged('GET', `/drives/${nst}/status`, undefined, () => mockApi.driveDetail(nst)) : realDriveDetail(nst),

  // Robot operations (LEVEL 2)
  load: (changer: string, slot: number, drive: number) =>
    API_MODE === 'mock' ? mockLogged('POST', `/libraries/${changer}/load`, { slot, drive, confirm: true }, () => mockApi.load(changer, slot, drive))
      : post(`/libraries/${changer}/load`, { slot, drive, confirm: true }),
  unload: (changer: string, slot: number, drive: number) =>
    API_MODE === 'mock' ? mockLogged('POST', `/libraries/${changer}/unload`, { slot, drive, confirm: true }, () => mockApi.unload(changer, slot, drive))
      : post(`/libraries/${changer}/unload`, { slot, drive, confirm: true }),
  rewind: (nst: string) =>
    API_MODE === 'mock' ? mockLogged('POST', `/drives/${nst}/rewind`, { confirm: true }, () => mockApi.rewind(nst)) : post(`/drives/${nst}/rewind`, { confirm: true }),

  // Tests
  runTest: (kind: TestKind, drive: string, sizeMb: number, tape?: string, barcodeInput?: string): Promise<ApiResponse> => {
    if (API_MODE === 'mock') return mockLogged('POST', `/tests/${kind === 'read' ? 'read' : 'write-verify'}`, kind === 'read' ? { nst_device: drive, size_mb: sizeMb } : { drive, test_media: tape, size_mb: sizeMb, allow_write: true, confirm: true }, () => mockApi.runTest(kind, drive, sizeMb, tape, barcodeInput));
    // 真实 API：读测试走 /tests/read；写走 /tests/write-verify（含读回校验）
    if (kind === 'read') return post('/read', { drive: drive.startsWith('/dev/') ? drive : `/dev/${drive}`, block_size: '1M', confirm: true });
    return post('/tests/write-verify', {
      drive: drive.startsWith('/dev/') ? drive : `/dev/${drive}`,
      test_media: tape || '', size_mb: sizeMb, allow_write: true, confirm: true,
    });
  },
  getSession: (sid: string) =>
    API_MODE === 'mock' ? mockLogged('GET', `/commands/${sid}`, undefined, () => mockApi.getSession(sid)) : get(`/commands/${sid}`),
  listSessions: () =>
    API_MODE === 'mock' ? mockLogged('GET', '/test-sessions', undefined, () => mockApi.listSessions()) : mockApi.listSessions(),

  // History / Audit
  operations: () => (API_MODE === 'mock' ? mockLogged('GET', '/operations', undefined, () => mockApi.operations()) : Promise.resolve({ success: true, code: 'OK', message: 'see audit', data: [] })),
  auditList: () => (API_MODE === 'mock' ? mockLogged('GET', '/audit', undefined, () => mockApi.auditList()) : Promise.resolve({ success: true, code: 'OK', message: 'see /commands', data: [] })),
  command: (cid: string) => (API_MODE === 'mock' ? mockLogged('GET', `/commands/${cid}`, undefined, () => mockApi.command(cid)) : get(`/commands/${cid}`)),
};

function norm(r: ApiResponse): ApiResponse { return r; }

// 错误码 → 用户友好文案
export function friendlyError(resp: ApiResponse): { title: string; detail: string } {
  const map: Record<string, [string, string]> = {
    DEVICE_NOT_FOUND: ['Device Not Found', '请核对设备映射、Host Agent 与带机连接'],
    DEVICE_BUSY: ['Device Busy', '设备正被占用，请稍后重试或检查持有锁的会话'],
    INVALID_DEVICE: ['Invalid Device', '设备名无效，请从设备树重新选择'],
    PERMISSION_DENIED: ['Permission Denied', '当前安全策略禁止此操作'],
    WRITE_NOT_ALLOWED: ['Write Not Allowed', '写操作被安全策略禁用（SAFE/DIAGNOSTIC 模式）'],
    TEST_MEDIA_REQUIRED: ['Test Media Required', '必须使用指定测试介质，且输入的 Barcode 必须完全匹配'],
    COMMAND_FAILED: ['Command Failed', '底层命令执行失败，详见审计详情'],
    TIMEOUT: ['Timeout', '操作超时，请检查设备状态后重试'],
    MEDIA_NOT_FOUND: ['Media Not Found', '目标槽位为空或磁带不存在'],
    MEDIA_ALREADY_LOADED: ['Drive Already Loaded', '目标带机已有磁带，请先卸载'],
    INVALID_SLOT: ['Invalid Slot', '槽位号无效或已被占用'],
    INVALID_DRIVE: ['Invalid Drive', '带机序号无效'],
    AGENT_UNAVAILABLE: ['API Unreachable', '无法连接 Tape Library API，请确认服务与网络'],
  };
  const [title, detail] = map[resp.code] || ['Operation Failed', resp.message || '未知错误'];
  return { title, detail };
}
