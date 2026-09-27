// API 端点 → 等价 CLI 命令行映射（供 API Playground 展示）
// 依据后端 app/commands/adapters.py + services.py 实测整理（186 v1.2.2）
// 返回 null 表示该端点无直接 CLI 等价（纯 API 功能：jobs/audit/archive/safety）

export interface CliEq {
  cli: string;
  note?: string;
}

function dev(v: string | undefined, fallback: string): string {
  const s = (v ?? '').trim() || fallback;
  return s.startsWith('/dev/') ? s : `/dev/${s}`;
}

function num(v: any, fallback: number | string): string {
  const n = typeof v === 'number' ? v : parseInt(String(v ?? ''), 10);
  return Number.isFinite(n) ? String(n) : String(fallback);
}

function parseBody(bodyText: string): any {
  if (!bodyText || !bodyText.trim()) return {};
  try { return JSON.parse(bodyText); } catch { return {}; }
}

const SYSINFO = 'cat /etc/os-release && uname -a && hostname && uname -m && id';

export function apiToCli(
  method: string,
  pattern: string, // catalog 里的路径模式，如 /api/v1/drives/{drive}/weof
  pathVals: Record<string, string>,
  queryVals: Record<string, string>,
  bodyText: string,
): CliEq | null {
  const p = pattern.replace('/api/v1', '');
  const b = parseBody(bodyText);
  const m = method.toUpperCase();

  // ---------- System ----------
  if (p === '/system/os-release') return { cli: 'cat /etc/os-release' };
  if (p === '/system/uname') return { cli: 'uname -a' };
  if (p === '/system/hostname') return { cli: 'hostname' };
  if (p === '/system/arch') return { cli: 'uname -m' };
  if (p === '/system/user') return { cli: 'id' };
  if (p === '/system/info') return { cli: SYSINFO, note: '后端一次执行 5 条命令并汇总' };
  if (p === '/system/kernel') {
    return { cli: "lsmod | grep -E '(^| )(st|sg|ch|lin_tape|IBMtape)( |$)'", note: '检查 st/sg/ch/lin_tape/IBMtape 内核模块' };
  }
  if (p === '/system/ibm') {
    return { cli: 'ls -l /dev/IBMtape* /dev/IBMchanger* 2>&1; command -v itdt', note: 'IBM lin_tape 驱动节点 + ITDT 检测' };
  }

  // ---------- Dependencies ----------
  if (p === '/dependencies' || p === '/dependencies/verify') {
    return {
      cli: 'for c in lsscsi sg_scan sg_map sg_inq sg_vpd sg_turs sg_modes sg_logs mtx mt tar '
        + 'jq python3 gzip file udevadm; do which $c; done; which dnf yum apt-get zypper',
      note: '后端逐个 which 检查必需/可选依赖 + 包管理器',
    };
  }
  if (p.startsWith('/dependencies/') && p !== '/dependencies/install') {
    const name = p.split('/')[2];
    return { cli: `which ${name}` };
  }
  if (p === '/dependencies/install') {
    const pkgs = Array.isArray(b.packages) ? b.packages.join(' ') : 'mt-st';
    return { cli: `dnf install -y ${pkgs}`, note: '实际包管理器由后端检测（dnf/yum/apt-get/zypper）' };
  }

  // ---------- Discovery ----------
  if (p === '/discovery') return { cli: 'lsscsi -g', note: '后端解析出设备类型分类' };
  if (p === '/discovery/detail') return { cli: 'sg_scan && sg_map -i' };

  // ---------- SCSI（devices/ 与 scsi/ 两套等价）----------
  const sgD = (fallback = 'sg2') => dev(pathVals.sg_device || pathVals.device, fallback);
  if (/(devices\/{sg_device}|scsi\/{device})\/inquiry/.test(p)) return { cli: `sg_inq ${sgD()}` };
  if (/(devices\/{sg_device}|scsi\/{device})\/vpd/.test(p)) {
    const page = (queryVals.page || '0x80').trim();
    return { cli: `sg_vpd -p ${page || '0x80'} ${sgD()}` };
  }
  if (/(devices\/{sg_device}|scsi\/{device})\/logs/.test(p)) {
    const page = (queryVals.page || '').trim();
    return { cli: page ? `sg_logs -p ${page} -a ${sgD()}` : `sg_logs -a ${sgD()}` };
  }
  if (p === '/devices/{sg_device}/tur') return { cli: `sg_turs ${sgD()}` };
  if (p === '/devices/{sg_device}/modes') return { cli: `sg_modes -a ${sgD()}` };
  if (/(drives\/{sg_device}|scsi\/{device})\/tapealert/.test(p)) {
    return { cli: `sg_logs -p 0x2e ${sgD()}`, note: 'TapeAlert 日志页' };
  }
  if (p === '/scsi/{device}/persist') return { cli: `sg_persist ${sgD()}` };
  if (p === '/scsi/{device}/reset') return { cli: `sg_reset -d ${sgD()}`, note: 'SCSI 设备复位（LEVEL_2）' };

  // ---------- Libraries（mtx）----------
  const ch = () => dev(pathVals.changer, 'sg1');
  if (p === '/libraries') return { cli: 'lsscsi -g', note: '后端过滤出 MEDIUM CHANGER 类型设备' };
  if (p === '/libraries/{changer}/inquiry') return { cli: `mtx -f ${ch()} inquiry` };
  if (p === '/libraries/{changer}/status') return { cli: `mtx -f ${ch()} status` };
  if (p === '/libraries/{changer}/inventory') return { cli: `mtx -f ${ch()} inventory` };
  if (p === '/libraries/{changer}/load') return { cli: `mtx -f ${ch()} load ${num(b.slot, 1)} ${num(b.drive, 0)}` };
  if (p === '/libraries/{changer}/unload') return { cli: `mtx -f ${ch()} unload ${num(b.slot, 6)} ${num(b.drive, 0)}` };
  if (p === '/libraries/{changer}/transfer') return { cli: `mtx -f ${ch()} transfer ${num(b.source, 1)} ${num(b.destination, 2)}` };
  if (p === '/libraries/{changer}/exchange') return { cli: `mtx -f ${ch()} exchange ${num(b.source, 1)} ${num(b.destination, 2)}` };
  if (p === '/libraries/{changer}/position' || p === '/libraries/{changer}/robot/position') {
    return { cli: `mtx -f ${ch()} position ${num(b.element, 1)}` };
  }
  if (p === '/libraries/{changer}/robot/first') return { cli: `mtx -f ${ch()} first` };
  if (p === '/libraries/{changer}/robot/next') return { cli: `mtx -f ${ch()} next` };
  if (p === '/libraries/{changer}/robot/last') return { cli: `mtx -f ${ch()} last` };

  // ---------- Drives（mt）----------
  const nst = () => dev(pathVals.drive || pathVals.nst_device, 'nst1');
  if (p === '/drives/{drive}/status') return { cli: `mt -f ${nst()} status` };
  if (p === '/drives/{drive}/tell') return { cli: `mt -f ${nst()} tell` };
  if (p === '/drives/{drive}/densities') return { cli: `mt -f ${nst()} densities` };
  if (p === '/drives/{drive}/options') return { cli: `mt -f ${nst()} stshowoptions` };
  if (p === '/drives/{drive}/compression' && m === 'GET') return { cli: `mt -f ${nst()} compression` };
  if (p === '/drives/{drive}/compression' && m === 'POST') {
    return { cli: `mt -f ${nst()} compression ${b.enable === false ? 0 : 1}` };
  }
  if (p === '/drives/{drive}/rewind') return { cli: `mt -f ${nst()} rewind` };
  if (p === '/drives/{drive}/offline') return { cli: `mt -f ${nst()} offline` };
  if (p === '/drives/{drive}/rewoffl') return { cli: `mt -f ${nst()} rewoffl` };
  if (p === '/drives/{drive}/eject') return { cli: `mt -f ${nst()} eject` };
  if (p === '/drives/{drive}/retension') return { cli: `mt -f ${nst()} retension` };
  if (p === '/drives/{drive}/eod' || p === '/drives/{drive}/seod') return { cli: `mt -f ${nst()} seod` };
  if (p === '/drives/{drive}/lock') return { cli: `mt -f ${nst()} lock` };
  if (p === '/drives/{drive}/unlock') return { cli: `mt -f ${nst()} unlock` };
  if (p === '/drives/{drive}/load') return { cli: `mt -f ${nst()} load` };
  if (p === '/drives/{drive}/position') {
    return { cli: `mt -f ${nst()} ${b.operation || 'fsf'} ${num(b.count, 1)}` };
  }
  if (p === '/drives/{drive}/seek') return { cli: `mt -f ${nst()} seek ${num(b.count, 0)}` };
  if (p === '/drives/{drive}/weof') return { cli: `mt -f ${nst()} weof ${num(b.count, 1)}` };
  if (p === '/drives/{drive}/wset') return { cli: `mt -f ${nst()} wset ${num(b.count, 1)}` };
  if (p === '/drives/{drive}/eof') return { cli: `mt -f ${nst()} eof ${num(b.count, 1)}` };
  if (p === '/drives/{drive}/erase') {
    const c = num(b.count, 0);
    return { cli: c === '0' ? `mt -f ${nst()} erase` : `mt -f ${nst()} erase ${c}`, note: '短擦（无参）/ 长擦（传 1）' };
  }
  if (p === '/drives/{drive}/block-size') return { cli: `mt -f ${nst()} setblk ${num(b.block_size, 0)}` };
  if (p === '/drives/{drive}/density') return { cli: `mt -f ${nst()} setdensity ${num(b.density, 0)}` };
  if (p === '/drives/{drive}/partition') {
    if (b.partition !== undefined && b.partition !== null) return { cli: `mt -f ${nst()} setpartition ${num(b.partition, 0)}` };
    return { cli: `mt -f ${nst()} mkpartition ${num(b.count, 1)}`, note: '重新分区（破坏性 LEVEL_3）' };
  }
  if (p === '/drives/{drive}/partition/seek') {
    return { cli: `mt -f ${nst()} partseek ${num(b.partition, 0)},${num(b.block, 0)}` };
  }

  // ---------- Diagnostics ----------
  if (p === '/diagnostics/dmesg') {
    const tail = (queryVals.tail || '100').trim() || '100';
    return {
      cli: "dmesg | grep -Ei 'tape|changer|scsi|st[0-9]|sg[0-9]|lto|ibm|quantum' | tail "
        + (tail === '100' ? '-100' : `-${tail}`),
    };
  }
  if (p === '/diagnostics/journalctl') {
    const tail = (queryVals.tail || '100').trim() || '100';
    return { cli: `journalctl -k --no-pager | tail -${tail}` };
  }
  if (p === '/diagnostics/system') {
    return { cli: 'dmesg | tail; journalctl -k --no-pager | tail', note: '两条命令各取尾部 20000 字符' };
  }
  if (p === '/diagnostics/tape/{sg_device}') {
    return { cli: `mt -f ${nst()} status && sg_inq ${sgD()} && sg_logs -p 0x2e ${sgD()}`, note: '带机综合诊断（多命令汇总）' };
  }

  // ---------- Tests（dd）----------
  if (p === '/write' || p === '/tests/write') {
    const size = num(b.size_mb, 1024);
    if (b.file) return { cli: `dd if=${b.file} of=${nst()} bs=1M conv=notrunc` };
    return { cli: `dd if=/dev/zero of=${nst()} bs=1M count=${size}` };
  }
  if (p === '/read' || p === '/tests/read') {
    const bs = b.block_size || '1M';
    const out = b.file || '/dev/null';
    return { cli: `dd if=${nst()} of=${out} bs=${bs}` };
  }
  if (p === '/tests/write-verify') {
    const size = num(b.size_mb, 256);
    return {
      cli: `mt -f ${nst()} rewind && dd if=/dev/zero of=${nst()} bs=1M count=${size} && mt -f ${nst()} weof 1 `
        + `&& mt -f ${nst()} rewind && dd if=${nst()} of=/dev/null bs=1M count=${size} && cmp`,
      note: '后端多步流水（rewind→写→weof→rewind→读回→cmp 比对），响应含 steps 明细',
    };
  }
  if (p === '/tests/erase') {
    const d = b.drive ? dev(b.drive, 'nst1') : nst();
    return { cli: `mt -f ${d} erase` };
  }
  if (p === '/tests/full') {
    return { cli: '# 综合测试：inventory → load → write → read → verify → unload 全链路', note: '后端编排的复合测试流程（多命令）' };
  }

  // ---------- Jobs / Audit / Archive / Meta：纯 API 功能 ----------
  return null;
}

// 从响应 data 提取 CLI 输出文本：优先 stdout；嵌套多命令结果；dd parsed；steps
export function extractCliOutput(data: any): { kind: 'stdout' | 'multi' | 'parsed' | 'steps' | 'none'; text: string; extra?: [string, string][] } {
  if (!data || typeof data !== 'object') return { kind: 'none', text: '' };
  if (typeof data.stdout === 'string' && data.stdout.length) {
    let t = data.stdout;
    if (data.stderr && String(data.stderr).trim()) t += `\n[stderr]\n${data.stderr}`;
    return { kind: 'stdout', text: t };
  }
  if (typeof data.stdout === 'string') {
    // 命令已执行但输出为空（如 mt compression 查询）
    const pe = data.parsed && typeof data.parsed === 'object'
      ? `\n(parsed: ${JSON.stringify(data.parsed)})` : '';
    return { kind: 'stdout', text: '(无输出)' + pe };
  }
  const multi: [string, string][] = [];
  Object.entries(data).forEach(([k, v]) => {
    if (v && typeof v === 'object' && typeof (v as any).stdout === 'string') {
      multi.push([k, (v as any).stdout || '(空输出)']);
    }
  });
  if (multi.length) return { kind: 'multi', text: '', extra: multi };
  if (data.parsed && typeof data.parsed === 'object' && Object.keys(data.parsed).length) {
    const lines = Object.entries(data.parsed)
      .filter(([, v]) => v !== null && v !== undefined)
      .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`);
    if (lines.length) return { kind: 'parsed', text: lines.join('\n') };
  }
  if (Array.isArray(data.steps)) {
    const lines = data.steps.map((s: any) => {
      const parts = [`step=${s.step}`];
      if (s.duration_ms !== undefined) parts.push(`${s.duration_ms}ms`);
      if (s.bytes !== undefined) parts.push(`${s.bytes}B`);
      if (s.content_ok !== undefined) parts.push(s.content_ok ? '内容一致 ✓' : '内容不一致 ✗');
      if (s.error) parts.push(String(s.error));
      return parts.join('  ');
    });
    return { kind: 'steps', text: lines.join('\n') };
  }
  return { kind: 'none', text: '' };
}
