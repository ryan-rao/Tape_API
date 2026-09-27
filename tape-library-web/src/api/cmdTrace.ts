// 命令记录追查：响应/job 里只有 command_id 时，自动拉取 /commands/{id}
// 展示后端真实执行的命令行、stdout、exit code（Library inventory/load/transfer 等
// 202 异步端点与同步 inventory 都不直接返回 stdout，唯一来源是命令记录）
import { rawRequest } from './client';

export interface CmdRec {
  command_id: string;
  command: string;
  phase?: string;
  exit_code?: number | null;
  result?: string;
  stdout?: string;
  stderr?: string;
  duration_ms?: number;
  device?: string;
}

function collectIds(data: any): string[] {
  const ids: string[] = [];
  if (!data || typeof data !== 'object') return ids;
  const push = (v: any) => {
    if (typeof v === 'string' && v.startsWith('CMD-') && !ids.includes(v)) ids.push(v);
  };
  push(data.command_id);
  if (Array.isArray(data.command_ids)) data.command_ids.forEach(push);
  if (Array.isArray(data.commands)) data.commands.forEach((c: any) => push(c?.command_id ?? c));
  if (Array.isArray(data.steps)) data.steps.forEach((s: any) => push(s?.command_id));
  const r = data.result;
  if (r && typeof r === 'object') {
    push(r.command_id);
    if (r.data && typeof r.data === 'object') push(r.data.command_id);
  }
  if (data.data && typeof data.data === 'object') push(data.data.command_id);
  return ids;
}

// 从 API 响应（直接响应或 job 轮询响应）追查全部命令记录（上限 8 条）
export async function traceCommands(resp: any): Promise<CmdRec[]> {
  const d = resp?.data ?? resp;
  if (!d || typeof d !== 'object') return [];
  // 已直接携带 stdout 的响应无需追查（避免重复请求/重复展示）
  if (typeof d.stdout === 'string' && d.stdout.length) return [];
  const hasNested = Object.values(d).some(
    (v) => v && typeof v === 'object' && typeof (v as any).stdout === 'string' && (v as any).stdout.length,
  );
  if (hasNested) return [];
  const ids = collectIds(d);
  // 业务信封顶层（如 /jobs/{id}/result 的 command_ids）也要扫，与 data 内互补
  if (resp && resp !== d) collectIds(resp).forEach((i) => { if (!ids.includes(i)) ids.push(i); });
  const out: CmdRec[] = [];
  for (const id of ids.slice(0, 8)) {
    try {
      const r = await rawRequest('GET', `/commands/${encodeURIComponent(id)}`);
      if (r.success && (r.data as any)?.command) out.push(r.data as CmdRec);
    } catch { /* 单条失败不影响整体 */ }
  }
  return out;
}
