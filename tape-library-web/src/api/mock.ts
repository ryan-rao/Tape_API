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

  async driveDetail(nst: string): Promise<ApiResponse> {
    await sleep(80);
    const d = DRIVES.find((x) => x.nst === nst || x.sg === nst);
    if (!d) return fail('DEVICE_NOT_FOUND', `Tape drive ${nst} not found`);
    return ok(d);
  },

  async load(changer: string, slot: number, driveIdx: number): Promise<ApiResponse> {
    await sleep(1500);
    const r = rid();
    if (!SAFETY.allow_device_operation) { audit(r, 'LOAD', `mtx -f /dev/${changer} load ${slot} ${driveIdx}`, 'LEVEL_2', 1); op({ library: changer, tape: '-', drive: String(driveIdx), operation: 'Mount', risk: 'LEVEL_2' }, 'FAIL', 0, r); return fail('WRITE_NOT_ALLOWED', 'Device operations disabled by safety policy'); }
    const s = SLOTS.find((x) => x.slot === slot);
    const d = DRIVES.find((x) => x.index === driveIdx);
    if (!s) { audit(r, 'LOAD', `mtx -f /dev/${changer} load ${slot} ${driveIdx}`, 'LEVEL_2', 1); return fail('INVALID_SLOT', `Slot ${slot} not found`); }
    if (!d) return fail('INVALID_DRIVE', `Drive ${driveIdx} not found`);
    if (!s.barcode) return fail('MEDIA_NOT_FOUND', `Slot ${slot} is empty`);
    if (d.loaded_tape) return fail('MEDIA_ALREADY_LOADED', `Drive ${d.nst} already loaded with ${d.loaded_tape}`);
    d.loaded_tape = s.barcode; d.status = 'LOADED';
    s.barcode = null; s.media_type = null; s.status = 'Empty';
    refreshLib();
    audit(r, 'LOAD', `mtx -f /dev/${changer} load ${slot} ${driveIdx}`, 'LEVEL_2');
    op({ library: changer, tape: d.loaded_tape, drive: d.nst, operation: 'Mount', risk: 'LEVEL_2' }, 'PASS', 23, r);
    return ok({ drive: d.nst, tape: d.loaded_tape }, 'LOAD_SUCCESS', `Loaded ${d.loaded_tape} into ${d.nst}`, r);
  },

  async unload(changer: string, slot: number, driveIdx: number): Promise<ApiResponse> {
    await sleep(1500);
    const r = rid();
    if (!SAFETY.allow_device_operation) return fail('WRITE_NOT_ALLOWED', 'Device operations disabled by safety policy');
    const s = SLOTS.find((x) => x.slot === slot);
    const d = DRIVES.find((x) => x.index === driveIdx);
    if (!d || !s) return fail('INVALID_DRIVE', 'Invalid drive or slot');
    if (!d.loaded_tape) return fail('MEDIA_NOT_FOUND', `Drive ${d.nst} is empty`);
    if (s.barcode) return fail('INVALID_SLOT', `Slot ${slot} already occupied`);
    s.barcode = d.loaded_tape; s.media_type = 'LTO9'; s.status = 'Occupied';
    const tape = d.loaded_tape;
    d.loaded_tape = null; d.status = 'EMPTY';
    refreshLib();
    audit(r, 'UNLOAD', `mtx -f /dev/${changer} unload ${slot} ${driveIdx}`, 'LEVEL_2');
    op({ library: changer, tape, drive: d.nst, operation: 'Unmount', risk: 'LEVEL_2' }, 'PASS', 21, r);
    return ok({ slot, tape }, 'UNLOAD_SUCCESS', `Unloaded ${tape} to slot ${slot}`, r);
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
