// Mock 引擎 —— 模拟带库/带机/磁带状态与测试会话，供无硬件环境完整演示 GUI
import type {
  ApiResponse, LibraryInfo, SlotInfo, DriveInfo, TapeInfo,
  TestSession, OperationRecord, AuditCommand, SafetyState, TestKind,
} from '../types';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const now = () => new Date().toISOString().replace('T', ' ').slice(0, 19);
let reqSeq = 0, cmdSeq = 0, sessSeq = 0;
const rid = () => `REQ-MOCK-${String(++reqSeq).padStart(4, '0')}`;
const cid = () => `CMD-MOCK-${String(++cmdSeq).padStart(4, '0')}`;

// ---- 模拟世界状态：1 个 IBM 03584L32 带库 + 2 个 ULT3580-TDA 带机 + 12 槽 ----
const SLOTS: SlotInfo[] = Array.from({ length: 12 }, (_, i) => ({
  element: 0x100 + i + 1, slot: i + 1, barcode: null, media_type: null, status: 'Empty',
}));
[['IBM006LA', 'LTO8'], ['IBM014LA', 'LTO8'], ['IBM009LA', 'LTO8'], ['IBM013LA', 'LTO8'], ['IBM021L9', 'LTO9'],
 ['IBM015LA', 'LTO9'], ['IBM027L9', 'LTO9'], ['IBM033L9', 'LTO9'], ['IBMERRL9', 'LTO9']]
  .forEach(([bc, mt], i) => { Object.assign(SLOTS[i], { barcode: bc, media_type: mt, status: 'Occupied' as const }); });

const DRIVES: DriveInfo[] = [
  {
    index: 0, sg: 'sg2', nst: 'nst1', vendor: 'IBM', model: 'ULT3580-TDA', serial: '78P0123',
    firmware: 'D9E9', scsi_address: '1:0:0:0', status: 'EMPTY', loaded_tape: null,
    block_size: 0, compression: true, temperature: 34,
    tapealert: { triggered_count: 0, all_clear: true }, health: 'Healthy',
  },
  {
    index: 1, sg: 'sg3', nst: 'nst0', vendor: 'IBM', model: 'ULT3580-TDA', serial: '78P0456',
    firmware: 'D9E9', scsi_address: '1:0:0:1', status: 'EMPTY', loaded_tape: null,
    block_size: 0, compression: true, temperature: 35,
    tapealert: { triggered_count: 0, all_clear: true }, health: 'Healthy',
  },
];

const LIB: LibraryInfo = {
  changer: 'sg1', vendor: 'IBM', model: '03584L32', serial: '78X0028', firmware: '9.24',
  status: 'Healthy', drive_count: 2, slot_count: 12, occupied_slots: 8, tape_count: 8,
  loaded_drives: 0, last_update: now(),
};

const SAFETY: SafetyState = { mode: 'FULL', allow_device_operation: true, allow_write: true, test_media: 'IBM015LA' };

const OPERATIONS: OperationRecord[] = [];
const AUDIT: AuditCommand[] = [];
const SESSIONS: Record<string, TestSession> = {};

function refreshLib() {
  LIB.occupied_slots = SLOTS.filter((s) => s.barcode).length;
  LIB.tape_count = LIB.occupied_slots;
  LIB.loaded_drives = DRIVES.filter((d) => d.loaded_tape).length;
  LIB.last_update = now();
}

function audit(requestId: string, operation: string, command: string, risk: AuditCommand['risk'], exit = 0, dur = 800) {
  AUDIT.unshift({
    command_id: cid(), request_id: requestId, operation, command, risk,
    exit_code: exit, duration_ms: dur, created_at: now(),
    stdout: `${command}\n[MOCK] exit=${exit}`, stderr: exit ? 'device error (mock)' : '',
  });
  if (AUDIT.length > 500) AUDIT.pop();
}

function op(rec: Omit<OperationRecord, 'time' | 'user' | 'duration_s' | 'request_id' | 'status'>, status: 'PASS' | 'FAIL', dur: number, requestId: string) {
  OPERATIONS.unshift({ ...rec, time: now(), user: 'admin', status, duration_s: dur, request_id: requestId });
  if (OPERATIONS.length > 200) OPERATIONS.pop();
}

const ok = (data: any, code = 'OK', message = 'success', request_id = rid()): ApiResponse => ({ success: true, code, message, request_id, data });
const fail = (type: string, details: string, request_id = rid()): ApiResponse => ({ success: false, code: type, message: details, request_id, error: { type, details } });

// ---- 测试会话：进度随时间推进 ----
function startSession(kind: TestKind, drive: string, tape: string | undefined, sizeMb: number, requestId: string): TestSession {
  const s: TestSession = {
    session_id: `TL-MOCK-${String(++sessSeq).padStart(3, '0')}`,
    kind, drive, tape, size_mb: sizeMb, status: 'RUNNING', progress: 0,
    transferred_mb: 0, throughput_mbs: 240 + Math.round(Math.random() * 60),
    elapsed_s: 0, errors: 0, verify: null, started_at: now(), request_id: requestId, commands: [],
  };
  SESSIONS[s.session_id] = s;
  return s;
}

export function tickSessions() {
  Object.values(SESSIONS).forEach((s) => {
    if (s.status !== 'RUNNING') return;
    s.elapsed_s += 1;
    s.progress = Math.min(100, Math.round((s.elapsed_s * s.throughput_mbs / s.size_mb) * 100));
    s.transferred_mb = Math.min(s.size_mb, Math.round(s.elapsed_s * s.throughput_mbs));
    if (s.progress >= 100) {
      s.status = 'PASS';
      s.finished_at = now();
      if (s.kind === 'write-verify' || s.kind === 'full') s.verify = 'PASS';
      s.commands = [
        { command_id: cid(), command: `dd of=/dev/${s.drive} bs=1M count=${s.size_mb}`, exit_code: 0, duration_ms: s.elapsed_s * 1000 },
      ];
    }
  });
}

// ---- Mock API 实现 ----
export const mockApi = {
  async safety(): Promise<ApiResponse> { await sleep(50); return ok(SAFETY); },

  async systemInfo(): Promise<ApiResponse> {
    await sleep(80);
    return ok({ os: 'Red Hat Enterprise Linux 9.6 (Plow)', kernel: '5.14.0-570.12.1.el9_6.x86_64', hostname: 'node186' });
  },

  async listLibraries(): Promise<ApiResponse> { await sleep(80); refreshLib(); return ok([LIB]); },

  async libraryStatus(changer: string): Promise<ApiResponse> {
    await sleep(80); refreshLib();
    return ok({ ...LIB, slots: SLOTS, drives: DRIVES.map(({ sg, nst, status, loaded_tape }) => ({ sg, nst, status, loaded_tape })) });
  },

  async libraryInventory(changer: string): Promise<ApiResponse> {
    await sleep(80);
    const tapes: TapeInfo[] = SLOTS.filter((s) => s.barcode).map((s) => ({
      barcode: s.barcode!, media_type: s.media_type!, generation: s.media_type!.toUpperCase(),
      slot: s.slot, drive: null, status: 'Available', write_protect: false, health: 'Good',
      mount_count: Math.floor(Math.random() * 100), error_count: 0,
      read_bytes: Math.floor(Math.random() * 1e12), write_bytes: Math.floor(Math.random() * 1e12),
    }));
    DRIVES.filter((d) => d.loaded_tape).forEach((d) => tapes.push({
      barcode: d.loaded_tape!, media_type: 'LTO9', generation: 'LTO9', slot: null,
      drive: d.nst, status: 'Loaded', write_protect: false, health: 'Good',
    }));
    return ok({ volumes: tapes });
  },

  async listDrives(): Promise<ApiResponse> { await sleep(80); return ok(DRIVES); },

  // /drives/list 聚合形状（mock：包装 DRIVES，直接输出页面所需的 DriveInfo 字段）
  async driveList(): Promise<ApiResponse> {
    await sleep(80);
    return ok(DRIVES.map((d) => ({
      index: d.index, sg: d.sg, nst: d.nst, scsi_address: d.scsi_address,
      vendor: d.vendor, model: d.model, serial: d.serial, firmware: d.firmware,
      status: d.status, loaded_tape: d.loaded_tape, media_serial: d.loaded_tape ? 'T5KVFD2NT4' : null,
      source_slot: d.loaded_tape ? d.index + 1 : null,
      library: d.loaded_tape ? { changer: 'sg1', dte: d.index, source_slot: d.index + 1 } : null,
      temperature: d.temperature ?? 34, humidity: null,
      power_on_hours: 1200 + d.index * 30, media_loads: 40 + d.index * 7,
      errors: [],
      block_size: d.block_size, compression: true,
      tapealert: d.tapealert, health: d.health,
    })));
  },

  // /tapes/list 聚合形状（信封同后端：{tapes, slots, ledger}）
  async tapeList(): Promise<ApiResponse> {
    await sleep(80);
    refreshLib();
    const tapes: any[] = SLOTS.filter((s) => s.barcode).map((s) => ({
      barcode: s.barcode, sn: null, media_type: 'LTO',
      generation: s.media_type?.replace('LTO', '') ?? '',
      slot: s.slot, drive: null, changer: 'sg1', dte: null, source_slot: null,
      status: 'Available' as const, media_state: 'appendable', registered: true,
      write_protect: false, health: 'Good',
      mount_count: Math.floor(Math.random() * 50),
      capacity_bytes: 1224438927360, used_bytes: Math.floor(Math.random() * 5e10),
    }));
    DRIVES.filter((d) => d.loaded_tape).forEach((d) => tapes.unshift({
      barcode: d.loaded_tape!, sn: 'T5KVFD2NT4', media_type: 'LTO', generation: '9',
      slot: null, drive: d.nst, changer: 'sg1', dte: d.index, source_slot: d.index + 1,
      status: 'Loaded' as const, media_state: 'appendable', registered: true,
      write_protect: false, health: 'Good',
      mount_count: 3, capacity_bytes: 1224438927360, used_bytes: 145715200,
    }));
    return ok({ count: tapes.length, tapes,
      slots: { total: SLOTS.length, occupied: SLOTS.filter((s) => s.barcode).length },
      ledger: { source: 'tape_media', merged: true, error: null } });
  },

  async driveDetail(nst: string): Promise<ApiResponse> {
    await sleep(80);
    const d = DRIVES.find((x) => x.nst === nst || x.sg === nst);
    if (!d) return fail('DEVICE_NOT_FOUND', `Tape drive ${nst} not found`);
    return ok(d);
  },

  // v1.2 参数（与后端同构 mock）：load 推荐 barcode(磁带条码，检查必在槽)+drive_sn(带机SN，检查存在/空)；
  // 兼容 tape_position/slot/drive_position/drive。响应 checks.* 回显前置检查。
  async load(changer: string, p: { barcode?: string; drive_sn?: string; slot?: number; drive?: number; tape_position?: string; drive_position?: string }): Promise<ApiResponse> {
    await sleep(1500);
    const r = rid();
    const cmdOf = (s: number, d: number) => `mtx -f /dev/${changer} load ${s} ${d}`;
    if (!SAFETY.allow_device_operation) { audit(r, 'LOAD', cmdOf(p.slot ?? 0, p.drive ?? 0), 'LEVEL_2', 1); op({ library: changer, tape: '-', drive: String(p.drive ?? 0), operation: 'Mount', risk: 'LEVEL_2' }, 'FAIL', 0, r); return fail('WRITE_NOT_ALLOWED', 'Device operations disabled by safety policy'); }
    // ① 带机：drive_sn(SN→带机) 优先 > drive_position > 旧 drive
    let d = null as any; let driveMethod = 'raw_element'; let snSerial: string | null = null;
    if (p.drive_sn) {
      d = DRIVES.find((x) => x.serial.toLowerCase() === String(p.drive_sn).toLowerCase());
      if (!d) return fail('DRIVE_NOT_FOUND', `带机 SN ${p.drive_sn} 不存在；已知：${DRIVES.map((x) => x.serial).join(',')}（见 GET /drives/list）`);
      snSerial = d.serial; driveMethod = 'drive_sn';
    } else {
      const dp = String(p.drive_position ?? '').toLowerCase().replace(/\//g, '');
      if (p.drive_position) {
        const mm = dp.match(/^(?:nst|st|sg)(\d+)$/);
        const md = dp.match(/^(?:dte|element)[-:]?(\d+)$/);
        const mn = dp.match(/^drive-?(\d+)$/);
        if (mm) { d = DRIVES.find((x) => x.nst === `nst${mm[1]}` || x.sg === `sg${mm[1]}`); }
        else if (md) { d = DRIVES.find((x) => x.index === Number(md[1])); }
        else if (mn) { d = DRIVES.find((x) => x.index === Number(mn[1]) - 1); }
        if (!d) return fail('DRIVE_NOT_FOUND', `无法解释带机位置参数: ${p.drive_position}`);
        driveMethod = dp.startsWith('nst') || dp.startsWith('st') || dp.startsWith('sg') ? 'device_name' : 'dte_label';
      } else if (p.drive != null) {
        d = DRIVES.find((x) => x.index === p.drive);
      } else return fail('INVALID_REQUEST', '需提供 drive_sn（推荐）/ drive_position / drive 定位带机');
    }
    if (!d) return fail('INVALID_DRIVE', '带机未找到');
    // ② 磁带：barcode（检查必在槽）优先 > tape_position > 旧 slot
    let s: any = null; let slotN: number | null = p.slot ?? null; let tapeMethod = 'slot';
    if (p.barcode) {
      s = SLOTS.find((x) => x.barcode === p.barcode);
      if (!s) {
        const inDrv = DRIVES.find((x) => x.loaded_tape === p.barcode);
        if (inDrv) return fail('MEDIA_IN_DRIVE', `磁带 ${p.barcode} 已在带机 ${inDrv.nst}（需先 unload）`);
        return fail('MEDIA_NOT_FOUND', `磁带 ${p.barcode} 不在槽位中`);
      }
      slotN = s.slot; tapeMethod = 'barcode_lookup';
    } else if (p.tape_position) {
      const m = String(p.tape_position).match(/(?:s(?:lot)?[-:]?|)(\d+)/i);
      if (!m) return fail('INVALID_REQUEST', `无法解析 tape_position: ${p.tape_position}`);
      slotN = Number(m[1]); tapeMethod = 'tape_position';
      s = SLOTS.find((x) => x.slot === slotN);
    } else if (slotN != null) {
      s = SLOTS.find((x) => x.slot === slotN);
    } else return fail('INVALID_REQUEST', '需提供 barcode（推荐）/ tape_position / slot 定位磁带');
    if (!s) return fail('INVALID_SLOT', `Slot ${slotN} not found`);
    if (!s.barcode) return fail('SLOT_EMPTY', `槽位 S${String(slotN).padStart(3, '0')} 为空，无带可装`);
    if (d.loaded_tape) return fail('MEDIA_ALREADY_LOADED', `Drive ${d.nst} already loaded with ${d.loaded_tape}`);
    const barcode = s.barcode;
    d.loaded_tape = s.barcode; d.status = 'LOADED';
    s.barcode = null; s.media_type = null; s.status = 'Empty';
    refreshLib();
    audit(r, 'LOAD', cmdOf(slotN!, d.index), 'LEVEL_2');
    op({ library: changer, tape: d.loaded_tape, drive: d.nst, operation: 'Mount', risk: 'LEVEL_2' }, 'PASS', 23, r);
    return ok({ slot: slotN, drive: d.index, barcode,
      checks: {
        tape: { barcode, method: tapeMethod, position: `S${String(slotN).padStart(3, '0')}`, element: slotN, state: 'in_slot' },
        drive: { serial: snSerial, nst: d.nst, dte: d.index, occupied_before: false, state: 'ready', probe: 'ok' },
      },
      resolved: { tape: `S${String(slotN).padStart(3, '0')}`, tape_method: tapeMethod,
        drive: `DTE${d.index}`, drive_method: driveMethod, mtx_command: cmdOf(slotN!, d.index), verified_by_status: true },
    }, 'LOAD_SUCCESS', `Loaded ${barcode} into ${d.nst}`, r);
  },

  // v1.2：unload 推荐 barcode(检查必在带机)+slot(检查存在且空)；缺槽自动回原槽/首个空槽
  async unload(changer: string, p: { barcode?: string; drive_sn?: string; slot?: number; drive?: number; tape_position?: string; drive_position?: string }): Promise<ApiResponse> {
    await sleep(1500);
    const r = rid();
    if (!SAFETY.allow_device_operation) return fail('WRITE_NOT_ALLOWED', 'Device operations disabled by safety policy');
    // 带机：barcode 在机自动定位 > drive_position > 旧 drive
    let d = null as any;
    if (p.barcode) {
      d = DRIVES.find((x) => x.loaded_tape === p.barcode);
      if (!d) {
        const inSlot = SLOTS.find((x) => x.barcode === p.barcode);
        if (inSlot) return fail('MEDIA_NOT_IN_DRIVE', `磁带 ${p.barcode} 在槽位 S${String(inSlot.slot).padStart(3, '0')}，不在任何带机，无需 unload`);
        return fail('MEDIA_NOT_FOUND', `磁带 ${p.barcode} 不在带库中`);
      }
    }
    if (!d && p.drive_position) {
      const dp = String(p.drive_position).toLowerCase().replace(/\//g, '');
      const mm = dp.match(/^(?:nst|st|sg)(\d+)$/); const md = dp.match(/^(?:dte|element)[-:]?(\d+)$/); const mn = dp.match(/^drive-?(\d+)$/);
      if (mm) d = DRIVES.find((x) => x.nst === `nst${mm[1]}` || x.sg === `sg${mm[1]}`);
      else if (md) d = DRIVES.find((x) => x.index === Number(md[1]));
      else if (mn) d = DRIVES.find((x) => x.index === Number(mn[1]) - 1);
    }
    if (!d && p.drive != null) d = DRIVES.find((x) => x.index === p.drive);
    if (!d) return fail('INVALID_REQUEST', '需提供 barcode（推荐）或 drive/drive_position 定位待卸磁带');
    if (!d.loaded_tape) return fail('DRIVE_EMPTY', `带机 ${d.nst} 为空，无带可卸`);
    // 目标槽：slot > tape_position > 首个空槽
    let s: any = null; let slotN: number | null = null; let targetMethod = 'slot';
    if (p.slot != null) { slotN = p.slot; s = SLOTS.find((x) => x.slot === slotN); }
    else if (p.tape_position) {
      const m = String(p.tape_position).match(/(?:s(?:lot)?[-:]?|)(\d+)/i);
      if (m) { slotN = Number(m[1]); s = SLOTS.find((x) => x.slot === slotN); targetMethod = 'tape_position'; }
    }
    if (p.slot != null || p.tape_position) {
      if (!s) return fail('SLOT_NOT_FOUND', `目标槽 ${slotN} 不存在`);
      if (s.barcode) return fail('SLOT_OCCUPIED', `目标槽 S${String(slotN).padStart(3, '0')} 已被 ${s.barcode} 占用`);
    } else {
      s = SLOTS.find((x) => !x.barcode);
      if (!s) return fail('NO_EMPTY_SLOT', '带库已满，无空槽可卸带');
      slotN = s.slot; targetMethod = 'first_empty';
    }
    const tape = d.loaded_tape;
    s.barcode = tape; s.media_type = 'LTO9'; s.status = 'Occupied';
    d.loaded_tape = null; d.status = 'EMPTY';
    refreshLib();
    audit(r, 'UNLOAD', `mtx -f /dev/${changer} unload ${slotN} ${d.index}`, 'LEVEL_2');
    op({ library: changer, tape, drive: d.nst, operation: 'Unmount', risk: 'LEVEL_2' }, 'PASS', 21, r);
    return ok({ slot: slotN, drive: d.index, barcode: tape,
      checks: {
        tape: { barcode: tape, state: 'in_drive', dte: d.index, method: p.barcode ? 'barcode_holder' : 'drive_lookup' },
        slot: { position: `S${String(slotN).padStart(3, '0')}`, element: slotN, method: targetMethod, state: 'empty' },
      },
      resolved: { drive: `DTE${d.index}`, drive_method: p.barcode ? 'barcode_holder' : 'device_name',
        target: `S${String(slotN).padStart(3, '0')}`, target_method: targetMethod,
        mtx_command: `mtx -f /dev/${changer} unload ${slotN} ${d.index}`, verified_by_status: true },
    }, 'UNLOAD_SUCCESS', `Unloaded ${tape} to slot ${slotN}`, r);
  },

  // v1.2 槽位聚合清单（与后端 /libraries/{changer}/slots/list 同构）
  async slotsList(changer: string, q: { refresh?: boolean; occupied_only?: boolean; barcode?: string; limit?: number; offset?: number } = {}): Promise<ApiResponse> {
    await sleep(80);
    const r = rid();
    refreshLib();
    const wantBc = (q.barcode || '').trim().toUpperCase();
    let rows = SLOTS.map((s) => {
      const row: any = { element: s.element, position: `S${String(s.slot).padStart(3, '0')}`,
        occupied: !!s.barcode, import_export: false, barcode: s.barcode };
      if (s.barcode) row.media = { registered: true, state: 'appendable',
        capacity_bytes: 1224438927360, used_bytes: 145715200, block_records: 14, mount_count: 1, bytes_written: 145715200 };
      return row;
    });
    if (q.occupied_only) rows = rows.filter((x) => x.occupied);
    if (wantBc) rows = rows.filter((x) => (x.barcode || '').toUpperCase() === wantBc);
    const total = rows.length;
    if (q.offset) rows = rows.slice(q.offset);
    if (q.limit) rows = rows.slice(0, q.limit);
    const drives = DRIVES.map((x) => ({ drive: x.index, occupied: !!x.loaded_tape, barcode: x.loaded_tape, source_slot: null }));
    return ok({ changer,
      summary: { slots_total: SLOTS.length, occupied: SLOTS.filter((x) => x.barcode).length,
        with_barcode: SLOTS.filter((x) => x.barcode).length, import_export: 0,
        loaded_drives: drives.filter((x) => x.occupied).length, returned: rows.length, total_filtered: total },
      slots: rows, drives,
      ledger: { source: 'tape_media', merged: true, error: null } }, 'OK', 'ok', r);
  },

  async rewind(nst: string): Promise<ApiResponse> {
    await sleep(600); const r = rid();
    audit(r, 'REWIND', `mt -f /dev/${nst} rewind`, 'LEVEL_2');
    return ok({ nst }, 'REWIND_SUCCESS', 'Rewound', r);
  },

  async runTest(kind: TestKind, drive: string, sizeMb: number, tape?: string, barcodeInput?: string): Promise<ApiResponse> {
    const r = rid();
    if ((kind === 'write' || kind === 'write-verify' || kind === 'full') && !SAFETY.allow_write) {
      op({ library: LIB.changer, tape: tape || '-', drive, operation: kind, risk: 'LEVEL_3' }, 'FAIL', 0, r);
      return fail('WRITE_NOT_ALLOWED', 'Write operations disabled by safety policy');
    }
    if ((kind === 'write' || kind === 'write-verify' || kind === 'full') && tape && tape !== barcodeInput) {
      return fail('TEST_MEDIA_REQUIRED', `Barcode mismatch: you must type the exact test tape barcode (${tape})`);
    }
    await sleep(200);
    const sess = startSession(kind, drive, tape, sizeMb, r);
    audit(r, kind.toUpperCase(), `tape test ${kind} on ${drive} size=${sizeMb}MB`, kind === 'read' ? 'LEVEL_1' : 'LEVEL_3');
    return ok({ session_id: sess.session_id, status: sess.status }, 'TEST_STARTED', 'Test session started', r);
  },

  async getSession(sid: string): Promise<ApiResponse> {
    tickSessions();
    const s = SESSIONS[sid];
    if (!s) return fail('NOT_FOUND', `Session ${sid} not found`);
    return ok(s);
  },

  async listSessions(): Promise<ApiResponse> { tickSessions(); return ok(Object.values(SESSIONS).slice().reverse()); },

  async operations(): Promise<ApiResponse> { await sleep(50); return ok(OPERATIONS); },

  async auditList(): Promise<ApiResponse> { await sleep(50); return ok(AUDIT.slice(0, 100)); },

  async command(cid_: string): Promise<ApiResponse> {
    const c = AUDIT.find((x) => x.command_id === cid_);
    if (!c) return fail('NOT_FOUND', `Command ${cid_} not found`);
    return ok(c);
  },
};
