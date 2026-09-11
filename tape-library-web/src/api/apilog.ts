// API 调用日志：localStorage 持久化（跨刷新保留历史）+ 内存环形缓冲（供 API Logs 页面展示）
export interface ApiLogEntry {
  id: number;
  ts: string;              // ISO 时间
  method: 'GET' | 'POST';
  path: string;            // /api/v1/...
  request_body?: any;      // POST 入参
  status: number;          // HTTP 状态码（0 = 网络失败/本地 mock）
  ok: boolean;             // success 字段
  code: string;            // 响应 code
  request_id?: string;     // 服务端 request_id
  duration_ms: number;     // 耗时
  response: any;           // 完整响应 JSON
}

const MAX = 500;
const STORE_KEY = 'tape-api-logs-v2';
let seq = 1;
let logs: ApiLogEntry[] = [];
const listeners = new Set<() => void>();

// 单条日志体积上限（字节）：超限则截断 data 字段，防止大响应（如 1840 槽位清单）拖垮序列化
const ENTRY_LIMIT = 48 * 1024;

function shrink(e: Omit<ApiLogEntry, 'id' | 'ts'>): Omit<ApiLogEntry, 'id' | 'ts'> {
  try {
    if (JSON.stringify(e).length <= ENTRY_LIMIT) return e;
    const r: any = e.response;
    return {
      ...e,
      response: {
        ...(r && typeof r === 'object' ? r : {}),
        data: `[truncated: original response exceeded ${ENTRY_LIMIT} bytes]`,
      },
    };
  } catch {
    return { ...e, response: { error: 'unserializable response' } };
  }
}

// ---- 持久化：启动时恢复历史 ----
try { localStorage.removeItem('tape-api-logs'); } catch { /* 无旧键 */ } // 无条件清理旧版键
try {
  const saved = JSON.parse(localStorage.getItem(STORE_KEY) || '[]') as ApiLogEntry[];
  if (Array.isArray(saved) && saved.length) {
    // 逐条瘦身（截断超大 data），并丢弃磁盘上可能遗留的旧键
    logs = saved.slice(0, 100).map((l) => ({ ...shrink({ ...l }), id: l.id, ts: l.ts }));
    seq = Math.max(...logs.map((l) => l.id)) + 1;
  }
} catch { /* 损坏则忽略 */ }

let flushTimer: any = null;
function persist() {
  // 防抖：1s 内多次调用只写一次
  if (flushTimer) return;
  flushTimer = setTimeout(() => {
    flushTimer = null;
    let items = logs.slice(0, 100); // 持久化最近 100 条（已截断单条体积）
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        localStorage.setItem(STORE_KEY, JSON.stringify(items));
        return;
      } catch {
        items = items.slice(0, Math.floor(items.length / 2)); // 超配额则减半重试
      }
    }
  }, 1000);
}

export function logApiCall(e: Omit<ApiLogEntry, 'id' | 'ts'>) {
  const entry: ApiLogEntry = { ...shrink(e), id: seq++, ts: new Date().toISOString() };
  logs.unshift(entry);
  if (logs.length > MAX) logs.length = MAX;
  persist();
  listeners.forEach((f) => f());
}

export function getApiLogs(): ApiLogEntry[] {
  return logs;
}

export function clearApiLogs() {
  logs.length = 0;
  try { localStorage.removeItem(STORE_KEY); } catch { /* ignore */ }
  listeners.forEach((f) => f());
}

export function subscribeApiLogs(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
