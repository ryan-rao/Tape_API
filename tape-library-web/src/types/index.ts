// 全局类型定义 —— 与 Tape Library REST API 响应结构对齐
export interface ApiResponse<T = any> {
  success: boolean;
  code: string;
  message: string;
  request_id?: string;
  data?: T;
  error?: { type: string; details?: string } | null;
}

export type RiskLevel = 'LEVEL_1' | 'LEVEL_2' | 'LEVEL_3';
export type HealthStatus = 'Healthy' | 'Online' | 'Warning' | 'Critical' | 'Offline' | 'Running' | 'PASS' | 'FAIL' | 'Unknown';

export interface SafetyState {
  mode: 'SAFE' | 'DIAGNOSTIC' | 'FULL';
  allow_device_operation: boolean;
  allow_write: boolean;
  test_media?: string;
}

export interface LibraryInfo {
  changer: string;          // sg1
  vendor: string;
  model: string;
  serial: string;
  firmware: string;
  status: HealthStatus;
  drive_count: number;
  slot_count: number;
  occupied_slots: number;
  tape_count: number;
  loaded_drives: number;
  last_update: string;
}

export interface SlotInfo {
  element: number;          // 元素地址
  slot: number;             // 槽位号
  barcode: string | null;   // 有带为条码，空为 null
  media_type: string | null;// LTO8/LTO9...
  status: 'Occupied' | 'Empty';
}

export interface DriveInfo {
  index: number;            // 带机序号（load 用）
  sg: string;               // /dev/sg2
  nst: string;              // /dev/nst1
  vendor: string;
  model: string;
  serial: string;
  firmware: string;
  scsi_address: string;
  status: 'READY' | 'EMPTY' | 'LOADED' | 'OFFLINE' | 'ERROR' | 'UNKNOWN';
  loaded_tape: string | null;
  block_size: number;
  compression: boolean;
  temperature: number | null;
  tapealert: { triggered_count: number; all_clear: boolean };
  health: HealthStatus;
}

export interface TapeInfo {
  barcode: string;
  media_type: string;
  generation: string;
  slot: number | null;      // 在库槽位；null = 在带机
  drive: string | null;     // 在带机时的 nst 设备
  status: 'Available' | 'Loaded' | 'Error' | 'Unknown';
  write_protect: boolean;
  health: 'Good' | 'Warning' | 'Error' | 'Unknown';
  last_mount?: string;
  read_bytes?: number;
  write_bytes?: number;
  mount_count?: number;
  error_count?: number;
}

export type TestKind = 'read' | 'write' | 'write-verify' | 'full';
export type TestStatus = 'RUNNING' | 'PASS' | 'FAIL';

export interface TestSession {
  session_id: string;
  kind: TestKind;
  drive: string;
  tape?: string;
  size_mb: number;
  status: TestStatus;
  progress: number;         // 0-100
  transferred_mb: number;
  throughput_mbs: number;
  elapsed_s: number;
  errors: number;
  verify?: 'PASS' | 'FAIL' | null;
  started_at: string;
  finished_at?: string;
  request_id: string;
  commands: { command_id: string; command: string; exit_code: number; duration_ms: number }[];
}

export interface OperationRecord {
  time: string;
  user: string;
  library: string;
  tape: string;
  drive: string;
  operation: string;
  risk: RiskLevel;
  status: 'PASS' | 'FAIL';
  duration_s: number;
  request_id: string;
}

export interface AuditCommand {
  command_id: string;
  request_id: string;
  operation: string;
  command: string;
  risk: RiskLevel;
  exit_code: number;
  duration_ms: number;
  created_at: string;
  stdout: string;
  stderr: string;
  parsed?: any;
}
