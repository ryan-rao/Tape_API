// 自动生成：scripts/gen_catalog.py <- openapi.json（勿手改；重新生成即可）
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AnyObj = Record<string, any>;

export interface EndpointParam {
  name: string;
  in: 'path' | 'query';
  required?: boolean;
  default?: unknown;
}

export interface Endpoint {
  id: string;
  group: string;
  method: 'GET' | 'POST' | 'DELETE',
  path: string;
  summary: string;
  level: 'L1' | 'L2' | 'L3' | '-';
  isAsync?: boolean;
  hidden?: boolean;
  params: EndpointParam[];
  hasBody?: boolean;
  bodyDefault?: string | null;
}

export const GROUPS: { key: string; label: string }[] = [
  { key: "Meta", label: "Meta 元信息" },
  { key: "System", label: "System 系统" },
  { key: "Dependencies", label: "Deps 依赖" },
  { key: "Discovery", label: "Discovery 设备发现" },
  { key: "SCSI", label: "SCSI 诊断" },
  { key: "Library", label: "Library 带库" },
  { key: "Inventory", label: "Inventory 清单" },
  { key: "Drive", label: "Drive 带机" },
  { key: "Diagnostics", label: "Diag 诊断" },
  { key: "Tests", label: "Tests 读写测试" },
  { key: "Jobs", label: "Jobs 任务" },
  { key: "Audit", label: "Audit 审计" },
  { key: "Archive", label: "Archive 归档网关" },
];

export const CATALOG: Endpoint[] = [
  {
    id: "get", group: "Meta", method: 'GET', path: "/",
    summary: "Root", level: "-",
    params: [],
  },
  {
    id: "get-api-v1-safety", group: "Meta", method: 'GET', path: "/api/v1/safety",
    summary: "Safety", level: "-",
    params: [],
  },
  {
    id: "get-api-v1-system-arch", group: "System", method: 'GET', path: "/api/v1/system/arch",
    summary: "System Arch", level: "-",
    params: [],
  },
  {
    id: "get-api-v1-system-hostname", group: "System", method: 'GET', path: "/api/v1/system/hostname",
    summary: "System Hostname", level: "-",
    params: [],
  },
  {
    id: "get-api-v1-system-ibm", group: "System", method: 'GET', path: "/api/v1/system/ibm",
    summary: "System Ibm", level: "-",
    params: [],
  },
  {
    id: "get-api-v1-system-info", group: "System", method: 'GET', path: "/api/v1/system/info",
    summary: "System Info", level: "-",
    params: [],
  },
  {
    id: "get-api-v1-system-kernel", group: "System", method: 'GET', path: "/api/v1/system/kernel",
    summary: "System Kernel", level: "-",
    params: [],
  },
  {
    id: "get-api-v1-system-os-release", group: "System", method: 'GET', path: "/api/v1/system/os-release",
    summary: "System Os Release", level: "-",
    params: [],
  },
  {
    id: "get-api-v1-system-uname", group: "System", method: 'GET', path: "/api/v1/system/uname",
    summary: "System Uname", level: "-",
    params: [],
  },
  {
    id: "get-api-v1-system-user", group: "System", method: 'GET', path: "/api/v1/system/user",
    summary: "System User", level: "-",
    params: [],
  },
  {
    id: "get-api-v1-dependencies", group: "Dependencies", method: 'GET', path: "/api/v1/dependencies",
    summary: "Dependencies", level: "-",
    params: [],
  },
  {
    id: "post-api-v1-dependencies-install", group: "Dependencies", method: 'POST', path: "/api/v1/dependencies/install",
    summary: "Dependencies Install", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [],
  },
  {
    id: "get-api-v1-dependencies-verify", group: "Dependencies", method: 'GET', path: "/api/v1/dependencies/verify",
    summary: "Dependencies Verify", level: "-",
    params: [],
  },
  {
    id: "get-api-v1-dependencies-name", group: "Dependencies", method: 'GET', path: "/api/v1/dependencies/{name}",
    summary: "Dependency Check One", level: "-",
    params: [{"name": "name", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-discovery", group: "Discovery", method: 'GET', path: "/api/v1/discovery",
    summary: "Discovery", level: "-",
    params: [],
  },
  {
    id: "get-api-v1-discovery-detail", group: "Discovery", method: 'GET', path: "/api/v1/discovery/detail",
    summary: "Discovery Detail", level: "-",
    params: [],
  },
  {
    id: "get-api-v1-devices-sg-device-inquiry", group: "SCSI", method: 'GET', path: "/api/v1/devices/{sg_device}/inquiry",
    summary: "Device Inquiry", level: "-",
    params: [{"name": "sg_device", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-devices-sg-device-logs", group: "SCSI", method: 'GET', path: "/api/v1/devices/{sg_device}/logs",
    summary: "Device Logs", level: "-",
    params: [{"name": "sg_device", "in": "path", "required": true, "default": null}, {"name": "page", "in": "query", "required": false, "default": null}],
  },
  {
    id: "get-api-v1-devices-sg-device-modes", group: "SCSI", method: 'GET', path: "/api/v1/devices/{sg_device}/modes",
    summary: "Device Modes", level: "-",
    params: [{"name": "sg_device", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-devices-sg-device-tur", group: "SCSI", method: 'GET', path: "/api/v1/devices/{sg_device}/tur",
    summary: "Device Tur", level: "-",
    params: [{"name": "sg_device", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-devices-sg-device-vpd", group: "SCSI", method: 'GET', path: "/api/v1/devices/{sg_device}/vpd",
    summary: "Device Vpd", level: "-",
    params: [{"name": "sg_device", "in": "path", "required": true, "default": null}, {"name": "page", "in": "query", "required": false, "default": "0x80"}],
  },
  {
    id: "get-api-v1-scsi-device-inquiry", group: "SCSI", method: 'GET', path: "/api/v1/scsi/{device}/inquiry",
    summary: "Scsi Inquiry", level: "-",
    params: [{"name": "device", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-scsi-device-logs", group: "SCSI", method: 'GET', path: "/api/v1/scsi/{device}/logs",
    summary: "Scsi Logs", level: "-",
    params: [{"name": "device", "in": "path", "required": true, "default": null}, {"name": "page", "in": "query", "required": false, "default": null}],
  },
  {
    id: "get-api-v1-scsi-device-persist", group: "SCSI", method: 'GET', path: "/api/v1/scsi/{device}/persist",
    summary: "Scsi Persist", level: "-",
    params: [{"name": "device", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-scsi-device-reset", group: "SCSI", method: 'POST', path: "/api/v1/scsi/{device}/reset",
    summary: "Scsi Reset", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "device", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-scsi-device-tapealert", group: "SCSI", method: 'GET', path: "/api/v1/scsi/{device}/tapealert",
    summary: "Scsi Tapealert", level: "-",
    params: [{"name": "device", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-scsi-device-vpd", group: "SCSI", method: 'GET', path: "/api/v1/scsi/{device}/vpd",
    summary: "Scsi Vpd", level: "-",
    params: [{"name": "device", "in": "path", "required": true, "default": null}, {"name": "page", "in": "query", "required": false, "default": "0x80"}],
  },
  {
    id: "get-api-v1-libraries", group: "Library", method: 'GET', path: "/api/v1/libraries",
    summary: "Libraries", level: "-",
    params: [],
  },
  {
    id: "post-api-v1-libraries-changer-exchange", group: "Library", method: 'POST', path: "/api/v1/libraries/{changer}/exchange",
    summary: "Library Exchange", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "changer", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-libraries-changer-inquiry", group: "Library", method: 'GET', path: "/api/v1/libraries/{changer}/inquiry",
    summary: "Library Inquiry", level: "-",
    params: [{"name": "changer", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-libraries-changer-inventory", group: "Library", method: 'GET', path: "/api/v1/libraries/{changer}/inventory",
    summary: "Library Inventory", level: "-",
    params: [{"name": "changer", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-libraries-changer-load", group: "Library", method: 'POST', path: "/api/v1/libraries/{changer}/load",
    summary: "装带：barcode+drive_sn(带机序列号)，动作前双状态检查", level: "L2",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true, \"barcode\": \"IBM006LA\", \"drive_sn\": \"607B811E03\"}",
    params: [{"name": "changer", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-libraries-changer-robot-first", group: "Library", method: 'POST', path: "/api/v1/libraries/{changer}/robot/first",
    summary: "Library Robot First", level: "-",
    isAsync: true,
    params: [{"name": "changer", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-libraries-changer-robot-last", group: "Library", method: 'POST', path: "/api/v1/libraries/{changer}/robot/last",
    summary: "Library Robot Last", level: "-",
    isAsync: true,
    params: [{"name": "changer", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-libraries-changer-robot-next", group: "Library", method: 'POST', path: "/api/v1/libraries/{changer}/robot/next",
    summary: "Library Robot Next", level: "-",
    isAsync: true,
    params: [{"name": "changer", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-libraries-changer-robot-position", group: "Library", method: 'POST', path: "/api/v1/libraries/{changer}/robot/position",
    summary: "Library Robot Position", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "changer", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-libraries-changer-status", group: "Library", method: 'GET', path: "/api/v1/libraries/{changer}/status",
    summary: "Library Status", level: "-",
    params: [{"name": "changer", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-libraries-changer-transfer", group: "Library", method: 'POST', path: "/api/v1/libraries/{changer}/transfer",
    summary: "Library Transfer", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "changer", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-libraries-changer-unload", group: "Library", method: 'POST', path: "/api/v1/libraries/{changer}/unload",
    summary: "卸带：barcode+slot(目标槽)，动作前状态检查", level: "L2",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true, \"barcode\": \"IBM015LA\", \"slot\": 7}",
    params: [{"name": "changer", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-drives-list", group: "Inventory", method: 'GET', path: "/api/v1/drives/list",
    summary: "Drives List", level: "-",
    params: [{"name": "refresh", "in": "query", "required": false, "default": false}],
  },
  {
    id: "get-api-v1-libraries-changer-slots-list", group: "Inventory", method: 'GET', path: "/api/v1/libraries/{changer}/slots/list",
    summary: "槽位清单：位置/占用/条码+介质台账(过滤分页)", level: "-",
    params: [{"name": "changer", "in": "path", "required": true, "default": null}, {"name": "refresh", "in": "query", "required": false, "default": false}, {"name": "occupied_only", "in": "query", "required": false, "default": false}, {"name": "barcode", "in": "query", "required": false, "default": null}, {"name": "limit", "in": "query", "required": false, "default": 0}, {"name": "offset", "in": "query", "required": false, "default": 0}],
  },
  {
    id: "get-api-v1-tapes-list", group: "Inventory", method: 'GET', path: "/api/v1/tapes/list",
    summary: "Tapes List", level: "-",
    params: [{"name": "refresh", "in": "query", "required": false, "default": false}],
  },
  {
    id: "post-api-v1-drives-drive-block-size", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/block-size",
    summary: "Drive Block Size", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-compression", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/compression",
    summary: "Drive Compression Set", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-drives-drive-densities", group: "Drive", method: 'GET', path: "/api/v1/drives/{drive}/densities",
    summary: "Drive Densities", level: "-",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-density", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/density",
    summary: "Drive Density", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-eject", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/eject",
    summary: "Drive Eject", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-eod", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/eod",
    summary: "Drive Eod", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-eof", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/eof",
    summary: "Drive Eof", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true, \"count\": 1}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-erase", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/erase",
    summary: "Drive Erase", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true, \"count\": 1}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-load", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/load",
    summary: "Drive Load", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-lock", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/lock",
    summary: "Drive Lock", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-offline", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/offline",
    summary: "Drive Offline", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-drives-drive-options", group: "Drive", method: 'GET', path: "/api/v1/drives/{drive}/options",
    summary: "Drive Options", level: "-",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-partition", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/partition",
    summary: "Drive Partition", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-partition-seek", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/partition/seek",
    summary: "Drive Partition Seek", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-position", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/position",
    summary: "Drive Position", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true, \"count\": 1}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-retension", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/retension",
    summary: "Drive Retension", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-rewind", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/rewind",
    summary: "Drive Rewind", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-rewoffl", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/rewoffl",
    summary: "Drive Rewoffl", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-seek", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/seek",
    summary: "Drive Seek", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true, \"count\": 1}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-seod", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/seod",
    summary: "Drive Seod", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-drives-drive-status", group: "Drive", method: 'GET', path: "/api/v1/drives/{drive}/status",
    summary: "Drive Status", level: "-",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-drives-drive-tell", group: "Drive", method: 'GET', path: "/api/v1/drives/{drive}/tell",
    summary: "Drive Tell", level: "-",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-unlock", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/unlock",
    summary: "Drive Unlock", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-weof", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/weof",
    summary: "Drive Weof", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true, \"count\": 1}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-drives-drive-wset", group: "Drive", method: 'POST', path: "/api/v1/drives/{drive}/wset",
    summary: "Drive Wset", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true, \"count\": 1}",
    params: [{"name": "drive", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-diagnostics-dmesg", group: "Diagnostics", method: 'GET', path: "/api/v1/diagnostics/dmesg",
    summary: "Diag Dmesg", level: "-",
    params: [{"name": "tail", "in": "query", "required": false, "default": 100}],
  },
  {
    id: "get-api-v1-diagnostics-journalctl", group: "Diagnostics", method: 'GET', path: "/api/v1/diagnostics/journalctl",
    summary: "Diag Journalctl", level: "-",
    params: [{"name": "tail", "in": "query", "required": false, "default": 100}],
  },
  {
    id: "get-api-v1-diagnostics-system", group: "Diagnostics", method: 'GET', path: "/api/v1/diagnostics/system",
    summary: "Diag System", level: "-",
    params: [],
  },
  {
    id: "get-api-v1-diagnostics-tape-sg-device", group: "Diagnostics", method: 'GET', path: "/api/v1/diagnostics/tape/{sg_device}",
    summary: "Diag Tape", level: "-",
    params: [{"name": "sg_device", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-drives-sg-device-tapealert", group: "Diagnostics", method: 'GET', path: "/api/v1/drives/{sg_device}/tapealert",
    summary: "Drive Tapealert", level: "-",
    params: [{"name": "sg_device", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-read", group: "Tests", method: 'POST', path: "/api/v1/read",
    summary: "Api Read", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true, \"block_size\": \"1M\", \"file\": \"\", \"timeout\": 3600}",
    params: [],
  },
  {
    id: "post-api-v1-tests-erase", group: "Tests", method: 'POST', path: "/api/v1/tests/erase",
    summary: "Tests Erase", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true, \"allow_write\": true}",
    params: [],
  },
  {
    id: "post-api-v1-tests-full", group: "Tests", method: 'POST', path: "/api/v1/tests/full",
    summary: "Tests Full", level: "-",
    isAsync: true,
    params: [],
  },
  {
    id: "post-api-v1-tests-write-verify", group: "Tests", method: 'POST', path: "/api/v1/tests/write-verify",
    summary: "Tests Write Verify", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true, \"test_media\": \"\", \"size_mb\": 256, \"allow_write\": true, \"timeout\": 7200}",
    params: [],
  },
  {
    id: "post-api-v1-write", group: "Tests", method: 'POST', path: "/api/v1/write",
    summary: "Api Write", level: "-",
    isAsync: true, hasBody: true, bodyDefault: "{\"confirm\": true, \"media\": \"\", \"test_media\": \"\", \"file\": \"\", \"size_mb\": 1024, \"allow_write\": true, \"timeout\": 7200}",
    params: [],
  },
  {
    id: "get-api-v1-jobs", group: "Jobs", method: 'GET', path: "/api/v1/jobs",
    summary: "Jobs List", level: "-",
    params: [{"name": "status", "in": "query", "required": false, "default": null}, {"name": "limit", "in": "query", "required": false, "default": 50}, {"name": "offset", "in": "query", "required": false, "default": 0}],
  },
  {
    id: "get-api-v1-jobs-job-id", group: "Jobs", method: 'GET', path: "/api/v1/jobs/{job_id}",
    summary: "Jobs Get", level: "-",
    params: [{"name": "job_id", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-jobs-job-id-cancel", group: "Jobs", method: 'POST', path: "/api/v1/jobs/{job_id}/cancel",
    summary: "Jobs Cancel", level: "-",
    params: [{"name": "job_id", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-jobs-job-id-progress", group: "Jobs", method: 'GET', path: "/api/v1/jobs/{job_id}/progress",
    summary: "Jobs Progress", level: "-",
    params: [{"name": "job_id", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-jobs-job-id-result", group: "Jobs", method: 'GET', path: "/api/v1/jobs/{job_id}/result",
    summary: "Jobs Result", level: "-",
    params: [{"name": "job_id", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-audit-request-id", group: "Audit", method: 'GET', path: "/api/v1/audit/{request_id}",
    summary: "Get Audit", level: "-",
    params: [{"name": "request_id", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-commands-command-id", group: "Audit", method: 'GET', path: "/api/v1/commands/{command_id}",
    summary: "Get Command", level: "-",
    params: [{"name": "command_id", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-archive-cache", group: "Archive", method: 'GET', path: "/api/v1/archive/cache",
    summary: "缓存明细(递归分目录)", level: "-",
    params: [{"name": "kind", "in": "query", "required": false, "default": null}, {"name": "dirty", "in": "query", "required": false, "default": null}, {"name": "limit", "in": "query", "required": false, "default": 200}, {"name": "offset", "in": "query", "required": false, "default": 0}],
  },
  {
    id: "get-api-v1-archive-config", group: "Archive", method: 'GET', path: "/api/v1/archive/config",
    summary: "Gw Config", level: "-",
    params: [],
  },
  {
    id: "get-api-v1-archive-containers", group: "Archive", method: 'GET', path: "/api/v1/archive/containers",
    summary: "Gw Containers", level: "-",
    params: [{"name": "state", "in": "query", "required": false, "default": null}, {"name": "limit", "in": "query", "required": false, "default": 50}],
  },
  {
    id: "get-api-v1-archive-containers-container-id", group: "Archive", method: 'GET', path: "/api/v1/archive/containers/{container_id}",
    summary: "Gw Container Get", level: "-",
    params: [{"name": "container_id", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-archive-containers-container-id-retry", group: "Archive", method: 'POST', path: "/api/v1/archive/containers/{container_id}/retry",
    summary: "Gw Container Retry", level: "L2",
    params: [{"name": "container_id", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-archive-containers-container-id-seal", group: "Archive", method: 'POST', path: "/api/v1/archive/containers/{container_id}/seal",
    summary: "Gw Container Seal", level: "L2",
    params: [{"name": "container_id", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-archive-evict", group: "Archive", method: 'POST', path: "/api/v1/archive/evict",
    summary: "Gw Evict", level: "L2",
    params: [],
  },
  {
    id: "get-api-v1-archive-files", group: "Archive", method: 'GET', path: "/api/v1/archive/files",
    summary: "② 文件列表查询(name/state过滤)", level: "-",
    params: [{"name": "name", "in": "query", "required": false, "default": null}, {"name": "state", "in": "query", "required": false, "default": null}, {"name": "limit", "in": "query", "required": false, "default": 50}, {"name": "offset", "in": "query", "required": false, "default": 0}],
  },
  {
    id: "get-api-v1-archive-files-file-id", group: "Archive", method: 'GET', path: "/api/v1/archive/files/{file_id}",
    summary: "② 文件详情(位置/磁带/容器)", level: "-",
    params: [{"name": "file_id", "in": "path", "required": true, "default": null}],
  },
  {
    id: "post-api-v1-archive-files-file-id-archive", group: "Archive", method: 'POST', path: "/api/v1/archive/files/{file_id}/archive",
    summary: "③ 手动归档(封箱→落带)", level: "L2",
    params: [{"name": "file_id", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-archive-files-file-id-download", group: "Archive", method: 'GET', path: "/api/v1/archive/files/{file_id}/download",
    summary: "⑤ 下载文件流(二进制落盘)", level: "-",
    params: [{"name": "file_id", "in": "path", "required": true, "default": null}, {"name": "full_container", "in": "query", "required": false, "default": false}, {"name": "dir", "in": "query", "required": false, "default": null}],
  },
  {
    id: "post-api-v1-archive-files-file-id-recall", group: "Archive", method: 'POST', path: "/api/v1/archive/files/{file_id}/recall",
    summary: "④ 召回(热同步/冷202异步, dir=)", level: "L2",
    params: [{"name": "file_id", "in": "path", "required": true, "default": null}, {"name": "dir", "in": "query", "required": false, "default": null}],
  },
  {
    id: "get-api-v1-archive-gw-config", group: "Archive", method: 'GET', path: "/api/v1/archive/gw-config",
    summary: "读取 config：运行值/文件层/重启后预览+pending_diff(网关未运行也可查)", level: "L1",
    params: [],
  },
  {
    id: "post-api-v1-archive-gw-config", group: "Archive", method: 'POST', path: "/api/v1/archive/gw-config",
    summary: "设置 config：存 gateway-config.json(文件层>env，confirm 必需)，apply=true 写后立即重启生效", level: "L2",
    hasBody: true, bodyDefault: "{\"confirm\": true, \"apply\": false, \"small_file_mb\": 64, \"container_target_mb\": 1024, \"cache_quota_gb\": 200, \"watermarks_pct\": [70, 85], \"drive\": \"/dev/nst1\", \"changer\": \"/dev/sg1\", \"dte_map\": {\"0\": \"/dev/nst0\", \"2\": \"/dev/nst1\"}, \"auto_load\": true}",
    params: [],
  },
  {
    id: "post-api-v1-archive-gw-config-apply", group: "Archive", method: 'POST', path: "/api/v1/archive/gw-config/apply",
    summary: "按已存 gw-config 原地重启网关(有 running job 则 409)", level: "L2",
    hasBody: true, bodyDefault: "{\"confirm\": true}",
    params: [],
  },
  {
    id: "get-api-v1-archive-media", group: "Archive", method: 'GET', path: "/api/v1/archive/media",
    summary: "Gw Media", level: "L1",
    params: [],
  },
  {
    id: "post-api-v1-archive-media", group: "Archive", method: 'POST', path: "/api/v1/archive/media",
    summary: "Gw Media Register(双格式登记 v1.3)", level: "L2",
    hasBody: true, bodyDefault: "{\"barcode\": \"\", \"state\": \"appendable\", \"format\": \"raw\"}",
    params: [],
  },
  {
    id: "post-api-v1-archive-media-barcode-format", group: "Archive", method: 'POST', path: "/api/v1/archive/media/{barcode}/format",
    summary: "介质格式化(mkltfs→LTFS,销毁性,L3+confirm+force)", level: "L3",
    hasBody: true, bodyDefault: "{\"format\": \"ltfs\", \"confirm\": true, \"force\": true}",
    params: [{"name": "barcode", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-archive-ltfs-status", group: "Archive", method: 'GET', path: "/api/v1/archive/ltfs/status",
    summary: "LTFS 栈与会话健康(设备/挂载/租约, v1.3)", level: "L1",
    params: [],
  },
  {
    id: "post-api-v1-archive-ltfs-barcode-check", group: "Archive", method: 'POST', path: "/api/v1/archive/ltfs/{barcode}/check",
    summary: "ltfsck 一致性检查(会装载介质, v1.3)", level: "L2",
    params: [{"name": "barcode", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-archive-hatest-script", group: "Archive", method: 'GET', path: "/api/v1/archive/hatest/script",
    summary: "HATest 默认压测脚本模板 (v1.4)", level: "L1",
    params: [],
  },
  {
    id: "post-api-v1-archive-hatest-start", group: "Archive", method: 'POST', path: "/api/v1/archive/hatest/start",
    summary: "启动 HATest 压测(L3+confirm, setsid 脱离网关, v1.4)", level: "L3",
    hasBody: true, bodyDefault: "{\"params\": {\"api\": \"http://127.0.0.1:8001/api/v1\", \"rounds\": 2, \"big_mb\": 64, \"small_mb\": 1, \"fill\": 0}, \"confirm\": true}",
    params: [],
  },
  {
    id: "get-api-v1-archive-hatest-status", group: "Archive", method: 'GET', path: "/api/v1/archive/hatest/status",
    summary: "HATest 运行态/汇总/图表序列 (v1.4)", level: "L1",
    params: [],
  },
  {
    id: "get-api-v1-archive-hatest-log", group: "Archive", method: 'GET', path: "/api/v1/archive/hatest/log",
    summary: "HATest 原始输出(offset 增量, v1.4)", level: "L1",
    params: [{"name": "offset", "in": "query", "required": false, "default": 0}, {"name": "limit", "in": "query", "required": false, "default": 65536}],
  },
  {
    id: "post-api-v1-archive-hatest-stop", group: "Archive", method: 'POST', path: "/api/v1/archive/hatest/stop",
    summary: "停止 HATest(kill 进程组, v1.4)", level: "L3",
    params: [],
  },
  {
    id: "delete-api-v1-archive-files-file-id", group: "Archive", method: 'DELETE', path: "/api/v1/archive/files/{file_id}",
    summary: "删除文件记录(元数据级,磁带空间保留, v1.4)", level: "L2",
    params: [{"name": "file_id", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-archive-metrics", group: "Archive", method: 'GET', path: "/api/v1/archive/metrics",
    summary: "Gw Metrics", level: "-",
    params: [],
  },
  {
    id: "post-api-v1-archive-selfheal", group: "Archive", method: 'POST', path: "/api/v1/archive/selfheal",
    summary: "Gw Selfheal", level: "L2",
    params: [],
  },
  {
    id: "get-api-v1-archive-stats", group: "Archive", method: 'GET', path: "/api/v1/archive/stats",
    summary: "Gw Stats", level: "-",
    params: [],
  },
  {
    id: "get-api-v1-archive-tasks", group: "Archive", method: 'GET', path: "/api/v1/archive/tasks",
    summary: "后台任务列表(flusher/归档)", level: "-",
    params: [{"name": "kind", "in": "query", "required": false, "default": null}, {"name": "state", "in": "query", "required": false, "default": null}, {"name": "limit", "in": "query", "required": false, "default": 50}],
  },
  {
    id: "get-api-v1-archive-tasks-task-id", group: "Archive", method: 'GET', path: "/api/v1/archive/tasks/{task_id}",
    summary: "Gw Task Get", level: "-",
    params: [{"name": "task_id", "in": "path", "required": true, "default": null}],
  },
  {
    id: "get-api-v1-archive-tree", group: "Archive", method: 'GET', path: "/api/v1/archive/tree",
    summary: "缓存目录树(含封箱虚拟节点)", level: "-",
    params: [],
  },
  {
    id: "post-api-v1-archive-upload", group: "Archive", method: 'POST', path: "/api/v1/archive/upload",
    summary: "① 上传到指定目录(dir=)", level: "L2",
    hasBody: true,
    params: [{"name": "dir", "in": "query", "required": false, "default": null}],
  },
];

export const PATH_DEFAULTS: Record<string, string> = {
  "changer": "sg1",
  "command_id": "",
  "container_id": "11c0f998-335d-4146-bdd0-e17572942d66",
  "device": "sg2",
  "drive": "",
  "file_id": "7192fa6a-e7b2-4200-bc3a-2f924d00aff5",
  "job_id": "",
  "name": "mt-st",
  "request_id": "",
  "sg_device": "",
  "task_id": "",
};
