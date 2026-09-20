# Tape Library API 完整使用手册

- 版本: 1.1.0 | 服务: tape-library-api @ node186 (172.16.12.186) | 更新: 2026-09-10 17:30
- 框架: Python 3.9 / FastAPI / Pydantic / Uvicorn | Swagger: `/docs` | OpenAPI: `/openapi.json`
- 测试环境: IBM 03584L32 带库 (/dev/sg1, /dev/sg3 双路径) + 2× IBM ULT3580-TDA 带机 (/dev/nst0, /dev/nst1)，测试介质 IBM015LA
- 本手册覆盖 CLI 命令行测试报告（108 条命令）涉及的全部操作能力；所有测试结果均为**真实硬件调用**的原始返回（超长输出截断标注），采集时间 2026-09-10 17:12–17:30

---

# 一、API 架构

```
┌───────────────────────────────┐
│  REST API (FastAPI)           │  统一 JSON 响应 + request_id
└───────────────┬───────────────┘
┌───────────────▼───────────────┐
│  Service Layer                │  System/Dependency/Discovery/Device/
                                │  Library/Drive/Diagnostic/Test
└───────────────┬───────────────┘
┌───────────────▼───────────────┐
│  Command Adapters (白名单)     │  Lsscsi/Sg/Mtx/Mt/SystemProbe — 仅构造 argv
└───────────────┬───────────────┘
┌───────────────▼───────────────┐
│  Command Runner               │  subprocess shell=False + 超时 + 设备锁 + 审计
└───────────────┬───────────────┘
┌───────────────▼───────────────┐
│  Linux 命令层                  │  lsscsi / sg3_utils / mtx / mt
└───────────────┬───────────────┘
┌───────────────▼───────────────┐
│  磁带库硬件 + 审计落盘          │  audit/commands/CMD-*/ 原始 stdout/stderr
└───────────────────────────────┘
```

**安全模型**：LEVEL 1（只读，默认开放）→ LEVEL 2（设备操作，需 `TAPE_API_MODE=DIAGNOSTIC|FULL` + `ALLOW_DEVICE_OPERATION=true`）→ LEVEL 3（写/擦除，需 `FULL` + `ALLOW_WRITE=true` + 请求体 `allow_write:true` + `confirm:true` + `test_media`）。

**统一响应**：`{success, code, message, request_id, data, error}`；每条底层命令生成 `command_id`，原始输出永久落盘，可通过 `GET /api/v1/commands/{command_id}` 与 `GET /api/v1/audit/{request_id}` 溯源。

---

# 二、CLI 测试 ↔ API 完整对照表

| CLI 测试命令 (测试报告章节) | 对应 API | 风险级 | 手册章节 |
|---|---|---|---|
| `cat /etc/os-release` / `uname` / `hostname` / `id` | GET /system/info | L1 | 3.1 |
| `lsmod`（st/sg/ch/lin_tape） | GET /system/kernel | L1 | 3.2 |
| `ls /dev/IBMtape*` / `command -v itdt` | GET /system/ibm | L1 | 3.3 |
| `which` 依赖检查 | GET /dependencies | L1 | 3.4 |
| `dnf install` | POST /dependencies/install | L2 | — |
| `lsscsi -g` | GET /discovery | L1 | 3.5 |
| `sg_scan` / `sg_map -i` | GET /discovery/detail | L1 | 3.6 |
| `sg_inq /dev/sgX` | GET /devices/{sg}/inquiry | L1 | 3.7 |
| `sg_vpd -p 0x80/0x83` | GET /devices/{sg}/vpd?page= | L1 | — |
| `sg_turs` | GET /devices/{sg}/tur | L1 | — |
| `sg_modes -a` | GET /devices/{sg}/modes | L1 | 3.8 |
| `sg_logs -a` | GET /devices/{sg}/logs | L1 | 3.9 |
| `sg_logs -p 0x11`（卷统计） | GET /devices/{sg}/logs?page=0x11 | L1 | 3.9 |
| `sg_logs -p 0x2e`（TapeAlert） | GET /drives/{sg}/tapealert | L1 | 4.2 |
| `mtx inquiry` | GET /libraries/{changer}/inquiry | L1 | 4.1 |
| `mtx status` | GET /libraries/{changer}/status | L1 | 4.3 |
| `mtx status`（结构化槽位） | GET /libraries/{changer}/inventory | L1 | 4.4 |
| `mtx load S D` | POST /libraries/{changer}/load | L2 | 4.5 |
| `mtx unload S D` | POST /libraries/{changer}/unload | L2 | 4.6 |
| `mtx transfer S D` | POST /libraries/{changer}/transfer | L2 | — |
| `mtx position E` | POST /libraries/{changer}/position | L2 | — |
| `mt status` | GET /drives/{nst}/status | L1 | 5.1 |
| `mt rewind` | POST /drives/{nst}/position {rewind} / /rewind | L2 | 5.3 |
| `mt fsf / bsf / fsr / bsr / seod / offline` | POST /drives/{nst}/position | L2 | 5.4 |
| `mt compression` | GET /drives/{nst}/compression | L1 | 5.5 |
| `mt weof` | POST /drives/{nst}/weof | L3 | 6.3 |
| `mt erase` | POST /tests/erase | L3 | — |
| `dd if=/dev/nstX of=/dev/null`（读） | POST /tests/read | L2 | 6.1 |
| `dd if=/dev/zero of=/dev/nstX`（写） | POST /tests/write | L3 | 6.2 |
| 写+weof+读回+`cmp` 校验全流程 | POST /tests/write-verify | L3 | 6.4 |
| `dmesg` / `journalctl -k` | GET /diagnostics/system | L1 | — |
| sg_inq+vpd+tur+tapealert 综合 | GET /diagnostics/tape/{sg} | L1 | 5.6 |
| 全链路只读测试 | POST /tests/full | L1 | — |
| 审计溯源 | GET /commands/{id}、GET /audit/{request_id} | L1 | 7 |

---

# 三、基础与发现 API

## 3.1 系统信息 `GET /api/v1/system/info`

### GET http://127.0.0.1:8001/api/v1/system/info

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-171116-37E0A9","data":{"os_release":"NAME=\"Red Hat Enterprise Linux\"\nVERSION=\"9.6 (Plow)\"\nID=\"rhel\"\nID_LIKE=\"fedora\"\nVERSION_ID=\"9.6\"\nPLATFORM_ID=\"platform:el9\"\nPRETTY_NAME=\"Red Hat Enterprise Linux 9.6 (Plow)\"\nANSI_COLOR=\"0;31\"\nLOGO=\"fedora-logo-icon\"\nCPE_NAME=\"cpe:/o:redhat:enterprise_linux:9::baseos\"\nHOME_URL=\"https://www.redhat.com/\"\nDOCUMENTATION_URL=\"https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/9\"\nBUG_REPORT_URL=\"https://issues.redhat.com/\"\n\nREDHAT_BUGZILLA_PRODUCT=\"Red Hat Enterprise Linux 9\"\nREDHAT_BUGZILLA_PRODUCT_VERSION=9.6\nREDHAT_SUPPORT_PRODUCT=\"Red Hat Enterprise Linux\"\nREDHAT_SUPPORT_PRODUCT_VERSION=\"9.6\"","os_release_command_id":"CMD-84276EFD","kernel":"Linux node186 5.14.0-570.12.1.el9_6.x86_64 #1 SMP PREEMPT_DYNAMIC Fri Apr 4 10:41:31 EDT 2025 x86_64 x86_64 x86_64 GNU/Linux","kernel_command_id":"CMD-0B595BB6","hostname":"node186","hostname_command_id":"CMD-A9C9BB82","arch":"x86_64","arch_command_id":"CMD-3CB9BF0A","user":"uid=0(root) gid=0(root) groups=0(root) context=unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023","user_command_id":"CMD-E7A6198B"},"error":null}```


## 3.2 内核驱动检查 `GET /api/v1/system/kernel`（CLI: lsmod）

### GET http://127.0.0.1:8001/api/v1/system/kernel

Response:
```json
{"success":true,"code":"KERNEL_CHECKED","message":"Operation completed successfully","request_id":"REQ-20260910-172939-CF21AB","data":{"st":{"loaded":true,"stdout":"st                     77824  0","command_id":"CMD-957BF350"},"sg":{"loaded":true,"stdout":"sg                     53248  0","command_id":"CMD-F29E0245"},"ch":{"loaded":true,"stdout":"ch                     24576  0","command_id":"CMD-BD948F25"},"lin_tape":{"loaded":false,"stdout":"","command_id":"CMD-DE99C2BA"}},"error":null}```


## 3.3 IBM 检测 `GET /api/v1/system/ibm`（CLI: /dev/IBMtape*、ITDT）

### GET http://127.0.0.1:8001/api/v1/system/ibm

Response:
```json
{"success":true,"code":"IBM_CHECKED","message":"Operation completed successfully","request_id":"REQ-20260910-172939-124D4E","data":{"lin_tape_nodes":"ls: cannot access '/dev/IBMtape*': No such file or directory\nls: cannot access '/dev/IBMchanger*': No such file or directory","itdt_installed":false,"commands":["CMD-DC77BCB3","CMD-9912B1AE"]},"error":null}```


## 3.4 依赖检查 `GET /api/v1/dependencies`

### GET http://127.0.0.1:8001/api/v1/dependencies

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-171116-912D32","data":{"package_manager":"dnf","dependencies":[{"name":"lsscsi","required":true,"installed":true,"path":"/usr/bin/lsscsi","command_id":"CMD-CA5AF4C3"},{"name":"sg_scan","required":true,"installed":true,"path":"/usr/bin/sg_scan","command_id":"CMD-BDD36594"},{"name":"sg_map","required":true,"installed":true,"path":"/usr/bin/sg_map","command_id":"CMD-A1E3F724"},{"name":"sg_inq","required":true,"installed":true,"path":"/usr/bin/sg_inq","command_id":"CMD-0240B5BF"},{"name":"sg_vpd","required":true,"installed":true,"path":"/usr/bin/sg_vpd","command_id":"CMD-C4FB7D0F"},{"name":"sg_turs","required":true,"installed":true,"path":"/usr/bin/sg_turs","command_id":"CMD-E4C15F6E"},{"name":"sg_modes","required":true,"installed":true,"path":"/usr/bin/sg_modes","command_id":"CMD-87BAC34F"},{"name":"sg_logs","required":true,"installed":true,"path":"/usr/bin/sg_logs","command_id":"CMD-C6606D13"},{"name":"mtx","required":true,"installed":true,"path":"/usr/sbin/mtx","command_id":"CMD-0F5B7153"},{"name":"mt","required":true,"installed":true,"path":"/usr/bin/mt","command_id":"CMD-DE074183"},{"name":"tar","required":true,"installed":true,"path":"/usr/bin/tar","command_id":"CMD-094B7A9B"},{"name":"jq","required":false,"installed":true,"path":"/usr/bin/jq","command_id":"CMD-29A896C8"},{"name":"python3","required":false,"installed":true,"path":"/usr/bin/python3","command_id":"CMD-EF9B8F28"},{"name":"gzip","required":false,"installed":true,"path":"/usr/bin/gzip","command_id":"CMD-77EEAF15"},{"name":"file","required":false,"installed":true,"path":"/usr/bin/file","command_id":"CMD-8A187ECD"},{"name":"udevadm","required":false,"installed":true,"path":"/usr/sbin/udevadm","command_id":"CMD-1BC4D5E6"}],"gate":"PASS"},"error":null}```


## 3.5 SCSI 发现 `GET /api/v1/discovery`（lsscsi -g）

### GET http://127.0.0.1:8001/api/v1/discovery

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-171116-8BC607","data":{"devices":[{"scsi_address":"32:0:0:0","device_type":"TAPE","vendor":"IBM","product":"ULT3580-TDA","sg_device":"/dev/sg2","st_device":"/dev/st1","nst_device":"/dev/nst1"},{"scsi_address":"32:0:0:1","device_type":"MEDIUMX","vendor":"IBM","product":"03584L32","sg_device":"/dev/sg3","st_device":null,"nst_device":null},{"scsi_address":"33:0:0:0","device_type":"TAPE","vendor":"IBM","product":"ULT3580-TDA","sg_device":"/dev/sg0","st_device":"/dev/st0","nst_device":"/dev/nst0"},{"scsi_address":"33:0:0:1","device_type":"MEDIUMX","vendor":"IBM","product":"03584L32","sg_device":"/dev/sg1","st_device":null,"nst_device":null},{"scsi_address":"N:0:6:1","device_type":"DISK","vendor":"SAMSUNG","product":"MZQL21T9HCJR-00A07__1","sg_device":null,"st_device":null,"nst_device":null},{"scsi_address":"N:1:6:1","device_type":"DISK","vendor":"SAMSUNG","product":"MZQL21T9HCJR-00A07__1","sg_device":null,"st_device":null,"nst_device":null},{"scsi_address":"N:2:6:1","device_type":"DISK","vendor":"SAMSUNG","product":"MZQL21T9HCJR-00A07__1","sg_device":null,"st_device":null,"nst_device":null},{"scsi_address":"N:3:6:1","device_type":"DISK","vendor":"SAMSUNG","product":"MZQL21T9HCJR-00A07__1","sg_device":null,"st_device":null,"nst_device":null},{"scsi_address":"N:4:6:1","device_type":"DISK","vendor":"SAMSUNG","product":"MZQL21T9HCJR-00A07__1","sg_device":null,"st_device":null,"nst_device":null},{"scsi_address":"N:5:6:1","device_type":"DISK","vendor":"SAMSUNG","product":"MZQL21T9HCJR-00A07__1","sg_device":null,"st_device":null,"nst_device":null},{"scsi_address":"N:6:6:1","device_type":"DISK","vendor":"SAMSUNG","product":"MZQL21T9HCJR-00A07__1","sg_device":null,"st_device":null,"nst_device":null},{"scsi_address":"N:7:6:1","device_type":"DISK","vendor":"SAMSUNG","product":"MZQL21T9HCJR-00A07__1","sg_device":null,"st_device":null,"nst_device":null},{"scsi_address":"N:8:6:1","device_type":"DISK","vendor":"SAMSUNG","product":"MZQL21T9HCJR-00A07__1","sg_device":null,"st_device":null,"nst_device":null},{"scsi_address":"N:9:6:1","device_type":"DISK","vendor":"SAMSUNG","product":"MZQL21T9HCJR-00A07__1","sg_device":null,"st_device":null,"nst_device":null},{"scsi_address":"N:10:6:1","device_type":"DISK","vendor":"SAMSUNG","product":"MZQL21T9HCJR-00A07__1","sg_device":null,"st_device":null,"nst_device":null},{"scsi_address":"N:11:6:1","device_type":"DISK","vendor":"SAMSUNG","product":"MZQL21T9HCJR-00A07__1","sg_device":null,"st_device":null,"nst_device":null},{"scsi_address":"N:12:6:1","device_type":"DISK","vendor":"SAMSUNG","product":"MZQL21T9HCJR-00A07__1","sg_device":null,"st_device":null,"nst_device":null},{"scsi_address":"N:13:6:1","device_type":"DISK","vendor":"SAMSUNG","product":"MZQL21T9HCJR-00A07__1","sg_device":null,"st_device":null,"nst_device":null}],"command_id":"CMD-43269258"},"error":null}```


## 3.6 扫描明细 `GET /api/v1/discovery/detail`（sg_scan + sg_map -i）

### GET http://127.0.0.1:8001/api/v1/discovery/detail

Response:
```json
{"success":true,"code":"SCAN_COMPLETED","message":"Operation completed successfully","request_id":"REQ-20260910-172939-98AECC","data":{"sg_scan":{"stdout":"/dev/sg0: scsi33 channel=0 id=0 lun=0\n/dev/sg1: scsi33 channel=0 id=0 lun=1\n/dev/sg2: scsi32 channel=0 id=0 lun=0\n/dev/sg3: scsi32 channel=0 id=0 lun=1\n","command_id":"CMD-75A0C982"},"sg_map":{"stdout":"/dev/sg0  /dev/nst0  IBM       ULT3580-TDA       T3S0\n/dev/sg1  IBM       03584L32          2C02\n/dev/sg2  /dev/nst1  IBM       ULT3580-TDA       T3S0\n/dev/sg3  IBM       03584L32          2C02\n","command_id":"CMD-2E1B791B"}},"error":null}```


## 3.7 设备 Inquiry `GET /api/v1/devices/sg2/inquiry` 与 VPD/TUR

### GET http://127.0.0.1:8001/api/v1/devices/sg2/inquiry

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-173215-721FB7","data":{"stdout":"standard INQUIRY:\n  PQual=0  PDT=1  RMB=1  LU_CONG=0  hot_pluggable=0  version=0x06  [SPC-4]\n  [AERC=0]  [TrmTsk=0]  NormACA=0  HiSUP=1  Resp_data_format=2\n  SCCS=0  ACC=0  TPGS=0  3PC=0  Protect=1  [BQue=0]\n  EncServ=0  MultiP=1 (VS=0)  [MChngr=0]  [ACKREQQ=0]  Addr16=0\n  [RelAdr=0]  WBus16=0  Sync=0  [Linked=0]  [TranDis=0]  CmdQue=1\n  [SPI: Clocking=0x0  QAS=0  IUS=0]\n    length=70 (0x46)   Peripheral device type: tape\n Vendor identification: IBM     \n Product identification: ULT3580-TDA     \n Product revision level: T3S0\n Unit serial number: 607B811E03\n","command_id":"CMD-54AA9C63"},"error":null}```


VPD 0x83：

### GET http://127.0.0.1:8001/api/v1/devices/sg2/vpd?page=0x83

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-173215-8FB1F4","data":{"page":"0x83","stdout":"Device Identification VPD page:\n  Addressed logical unit:\n    designator type: T10 vendor identification,  code set: ASCII\n      vendor id: IBM     \n      vendor specific: ULT3580-TDA     607B811E03\n    designator type: NAA,  code set: Binary\n      0x500507607b811e03\n  Target port:\n    designator type: Relative target port,  code set: Binary\n     transport: Fibre Channel Protocol for SCSI (FCP-5)\n      Relative target port: 0x1\n    designator type: NAA,  code set: Binary\n     transport: Fibre Channel Protocol for SCSI (FCP-5)\n      0x500507607b411e03\n","command_id":"CMD-96997514"},"error":null}```


TUR：

### GET http://127.0.0.1:8001/api/v1/devices/sg2/tur

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-173216-FC57E2","data":{"ready":false,"stdout":"device not ready\nCompleted 1 Test Unit Ready commands with 1 errors\n","stderr":"","command_id":"CMD-9D6B5BF9"},"error":null}```


## 3.8 模式页 `GET /api/v1/devices/sg2/modes`（sg_modes -a）

### GET http://127.0.0.1:8001/api/v1/devices/sg2/modes

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-172939-4BBA7D","data":{"stdout":"    IBM       ULT3580-TDA       T3S0   peripheral_type: tape [0x1]\nMode parameter header from MODE SENSE(10):\n  Mode data length=223, medium type=0x00, specific param=0x10, longlba=0\n  Block descriptor length=8\n> General mode parameter block descriptors:\n   Density code=0x0\n 00     00 00 00 00 00 00 00 00\n\n>> Read-Write error recovery, page_control: current\n 00     01 0a 28 ff 00 00 00 00  ff 00 00 00\n>> Disconnect-Reconnect, page_control: current\n 00     02 0e 00 00 00 00 00 00  00 00 00 00 00 00 00 00\n>> Control, page_control: current\n 00     0a 0a 00 01 00 00 00 00  ff ff 00 00\n>> Data Compression, page_control: current\n 00     0f 0e c0 80 00 00 00 ff  00 00 00 ff 00 00 00 00\n>> Device configuration, page_control: current\n 00     90 0e 00 00 00 00 01 2c  40 00 10 00 00 00 01 90\n>> Medium Partition [1], page_control: current\n 00     11 0e 03 00 3c 03 18 00  00 00 00 00 00 00 00 00\n>> LU control, page_control: current\n 00     18 06 00 00 00 00 00 00\n>> Port control, page_control: current\n 00     19 06 00 00 00 00 03 fa\n>> Power condition, page_control: current\n 00     9a 26 00 08 00 00 00 00  00 00 00 00 00 00 00 00\n 10     00 00 2e e0 00 00 00 00  00 00 00 00 00 00 00 00\n 20     00 00 00 00 00 00 00 00\n>> Informational exceptions control (tape version), page_control: current\n 00     1c 0a 08 04 00 00 00 00  00 00 00 00\n>> Medium configuration, page_control: current\n 00     1d 1e 00 00 01 02 00 00  00 00 00 00 00 00 00 00\n 10     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00\n>> page_code: 0x2f, page_control: current\n 00     af 08 00 01 00 01 00 00  00 01\n>> page_code: 0x30, page_control: current\n 00     30 07 01 02 03 20 40 42  43\n","command_id":"CMD-A9CEF782"},"error":null}```


## 3.9 日志页 `GET /api/v1/devices/sg2/logs` 与 `?page=0x11`（sg_logs）

全页（sg_logs -a）：

### GET http://127.0.0.1:8001/api/v1/devices/sg2/logs

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-173216-2FFC94","data":{"page":"all","stdout":"    IBM       ULT3580-TDA       T3S0\n\nSupported log pages  [0x0]:\n    0x00        Supported log pages [sp]\n    0x02        Write error [we]\n    0x03        Read error [re]\n    0x06        Non medium [nm]\n    0x0c        Sequential access device [sad]\n    0x11        DT Device status [dtds]\n    0x12        Tape alert response [tar]\n    0x14        Device statistics [ds]\n    0x16        Tape diagnostic data [tdd]\n    0x17        Volume statistics [vs]\n    0x1a        Power condition transitions [pct]\n    0x1b        Data compression [dc]\n    0x2e        Tape alert [ta]\n    0x30        Tape usage (lto-5, 6) [tu_]\n    0x31        Tape capacity (lto-5,
  ... (输出截断，完整结果见 audit/commands/ 原始日志)
```

指定卷统计页 0x11：

### GET http://127.0.0.1:8001/api/v1/devices/sg2/logs?page=0x11

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-172939-5FF89C","data":{"page":"0x11","stdout":"    IBM       ULT3580-TDA       T3S0\n\nSupported log pages  [0x0]:\n    0x00        Supported log pages [sp]\n    0x02        Write error [we]\n    0x03        Read error [re]\n    0x06        Non medium [nm]\n    0x0c        Sequential access device [sad]\n    0x11        DT Device status [dtds]\n    0x12        Tape alert response [tar]\n    0x14        Device statistics [ds]\n    0x16        Tape diagnostic data [tdd]\n    0x17        Volume statistics [vs]\n    0x1a        Power condition transitions [pct]\n    0x1b        Data compression [dc]\n    0x2e        Tape alert [ta]\n    0x30        Tape usage (lto-5, 6) [tu_]\n    0x31        Tape capacity (lto-5, 6) [tc_]\n    0x32        Data compression (lto-5) [dc_]\n    0x33        Write errors (lto-5) [we_]\n    0x34        Read forward errors (lto-5) [rfe_]\n    0x37        Performance characteristics (lto-5) [pc_]\n    0x38        Blocks/bytes transferred (lto-5) [bbt_]\n    0x39        Host port 0 interface errors (lto-5) [hp0_]\n    0x3b        Host port 1 interface errors (lto-5) [hp1_]\n    0x3c        Drive usage information (lto-5) [dui_]\n    0x3d        Subsystem statistics (lto-5) [ss_]\n\nWrite error counter page  [0x2]\n  Errors corrected without substantial delay = 0\n  Errors corrected with possible delays = 0\n  Total rewrites or rereads = 0\n  Total errors corrected = 0\n  Total times correction algorithm processed = 0\n  Total bytes processed = 262144\n  Total uncorrected errors = 0\n  Reserved or vendor specific [0x8000] = 0\n  Reserved or vendor specific [0x8001] = 0\n\nRead error counter page  [0x3]\n  Errors corrected without substantial delay = 0\n  Errors corrected with possible delays = 0\n  Total rewrites or rereads = 0\n  Total errors corrected = 0\n  Total times correction algorithm processed = 0\n  Total bytes processed = 0\n  Total uncorrected errors = 0\n  Reserved or vendor specific [0x8000] = 0\n\nNon-medium error page  [0x6]\n  Non-medium error count = 0\n\nSequential access device page (ssc-3)\n  Data bytes received with WRITE commands: 0 GB\n  Data bytes written to media by WRITE commands: 0 GB\n  Data bytes read from media by READ commands: 0 GB\n  Data bytes transferred by READ commands: 0 GB\n  Maximum native capacity in device object buffer: 3137 MB\n  Cleaning action not required (or completed)\n  Vendor specific parameter [0x8000] value: 1103719\n  Vendor specific parameter [0x8001] value: 95\n  Vendor specific parameter [0x8002] value: 1\n  Vendor specific parameter [0x8003] value: 14114704\n\nDT device status page (ssc-3, adc-3) [0x11]\n  Very high frequency data:\n  PAMR=0 HUI=0 MACC=0 CMPR=1 WRTP=0 CRQST=0 CRQRD=0 DINIT=1\n  INXTN=0 RAA=1 MPRSNT=0 MSTD=0 MTHRD=0 MOUNTED=0\n  DT device activity: No DT device activity\n  VS=0 TDDEC=0 EPP=0 ESR=0 RRQST=0 INTFC=0 TAFC=1\n  Very high frequency polling delay:  500 milliseconds\n   DT device ADC data encryption control status (hex only now):\n 00     00 00 00 00 00 00 00 00\n   Key management error data (hex only now):\n 00     00 00 00 00 00 00 00 00  00 00 00 00\n  Reserved [parameter_code=0x4]:\n 00     00 04 03 08 11 20 00 01  01 00 00 00                ..... ......\n  Primary port 1 status:\n    non-SAS transport, in hex:\n 00     3b 00 00 e1 80 03 00 04  50 05 07 60 7b 41 1e 03    ;.......P..`{A..\n 10     50 05 07 60 7b 81 1e 03                             P..`{...\n  Primary port 2 status:\n    non-SAS transport, in hex:\n 00     00 00 00 00 00 00 00 00  50 05 07 60 7b 81 1e 03    ........P..`{...\n 10     50 05 07 60 7b 81 1e 03                             P..`{...\n  Reserved [parameter_code=0x200]:\n 00     02 00 03 01 01                                      .....\n  Reserved [parameter_code=0x201]:\n 00     02 01 03 2b 01 00 00 00  1f 00 0a 02 00 01 a0 8a    ...+............\n 10     94 e2 50 00 00 00 01 00  00 00 00 00 00 00 00 10    ..P.............\n 20     00 00 90 fa 90 1e ac 00  00 00 00 00 00 00 00       ...............\n  Reserved [parameter_code=0x301]:\n 00     03 01 03 84 01 00 00 00  03 04 07 00 00 00 00 40    ...............@\n 10     40 04 68 06 ff 0c 00 00  02 00 0a 07 46 49 4e 49    @.h.........FINI\n 20     53 41 52 20 43 4f 52 50  2e 20 20 20 00 00 90 65    SAR CORP.   ...e\n 30     46 54 4c 46 38 35 33 32  50 35 50 43 56 20 20 20    FTLF8532P5PCV   \n 40     41 20 20 20 03 52 00 c3  08 3a 70 00 4e 44 53 44    A   .R...:p.NDSD\n 50     34 59 33 20 20 20 20 20  20 20 20 20 32 35 30 38    4Y3         2508\n 60     30 31 20 20 68 fa 08 95  00 00 00 00 00 00 00 00    01  h...........\n 70     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n 80     00 00 00 00 00 00 00 00                             ........\n  Reserved [parameter_code=0x302]:\n 00     03 02 03 84 01 00 00 00  03 04 07 00 00 00 00 40    ...............@\n 10     40 04 68 06 ff 0c 00 00  02 00 0a 07 46 49 4e 49    @.h.........FINI\n 20     53 41 52 20 43 4f 52 50  2e 20 20 20 00 00 90 65    SAR CORP.   ...e\n 30     46 54 4c 46 38 35 33 32  50 35 50 43 56 20 20 20    FTLF8532P5PCV   \n 40     41 20 20 20 03 52 00 c3  08 3a 70 00 4e 44 4d 47    A   .R...:p.NDMG\n 50     36 58 4c 20 20 20 20 20  20 20 20 20 32 35 30 37    6XL         2507\n 60     30 33 20 20 68 fa 08 ad  00 00 00 00 00 00 00 00    03  h...........\n 70     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n 80     00 00 00 00 00 00 00 00                             ........\n  Vendor specific [parameter_code=0x8000]:\n 00     80 00 43 08 20 20 20 20  20 20 20 20                ..C.        \n  Vendor specific [parameter_code=0x8001]:\n 00     80 01 43 04 14 45 00 00                             ..C..E..\n  Vendor specific [parameter_code=0x8100]:\n 00     81 00 43 28 00 01 02 00  00 00 00 00 ff ff ff ff    ..C(............\n 10     00 b8 b6 a5 00 00 00 00  00 00 00 00 00 00 00 00    ................\n 20     00 00 00 00 00 00 00 00  00 00 00 00                ............\n  Vendor specific [parameter_code=0x9101]:\n 00     91 01 43 04 00 00 00 00                             ..C.....\n  Vendor specific [parameter_code=0x9102]:\n 00     91 02 43 04 00 00 00 00                             ..C.....\n  Vendor specific [parameter_code=0xe000]:\n 00     e0 00 43 ff 00 00 00 00  00 00 00 00 00 00 00 00    ..C.............\n 10     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n 20     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n 30     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n 40     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n 50     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n 60     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n 70     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n 80     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n 90     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n a0     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n b0     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n c0     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n d0     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n e0     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n f0     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00    ................\n 100    00 00 00                                            ...\n\nTapeAlert response page (ssc-3, adc-3) [0x12]\n  Flag01h: 0  02h: 0  03h: 0  04h: 0  05h: 0  06h: 0  07h: 0  08h: 0\n  Flag09h: 0  0Ah: 0  0Bh: 0  0Ch: 0  0Dh: 0  0Eh: 0  0Fh: 0  10h: 0\n  Flag11h: 0  12h: 0  13h: 0  14h: 0  15h: 0  16h: 0  17h: 0  18h: 0\n  Flag19h: 0  1Ah: 0  1Bh: 0  1Ch: 0  1Dh: 0  1Eh: 0  1Fh: 0  20h: 0\n  Flag21h: 0  22h: 0  23h: 0  24h: 0  25h: 0  26h: 0  27h: 0  28h: 0\n  Flag29h: 0  2Ah: 0  2Bh: 0  2Ch: 0  2Dh: 0  2Eh: 0  2Fh: 0  30h: 0\n  Flag31h: 0  32h: 0  33h: 0  34h: 0  35h: 0  36h: 0  37h: 0  38h: 0\n  Flag39h: 0  3Ah: 0  3Bh: 0  3Ch: 0  3Dh: 0  3Eh: 0  3Fh: 0  40h: 0\n\nDevice statistics page (ssc-3 and adc)\n  Lifetime media loads: 95\n  Lifetime cleaning operations: 1\n  Lifetime power on hours: 3921\n  Lifetime media motion (head) hours: 5\n  Lifetime metres of tape processed: 87631\n  Lifetime media motion (head) hours when incompatible media last loaded: 0\n  Lifetime power on hours when last temperature condition occurred: 0\n  Lifetime power on hours when last power consumption condition occurred: 0\n  Media motion (head) hours since last successful cleaning operation: 2\n  Media motion (head) hours since 2nd to last successful cleaning: 5\n  Media motion (head) hours since 3rd to last successful cleaning: 5\n  Lifetime power on hours when last operator initiated forced reset\n    and/or emergency eject occurred: 0\n  Lifetime power cycles: 10\n  Volume loads since last parameter reset: 46\n  Hard write errors: 0\n  Hard read errors: 0\n  Duty cycle sample time (ms): 12105402840\n  Read duty cycle: 0\n  Write duty cycle: 0\n  Activity duty cycle: 0\n  Volume not present duty cycle: 44\n  Ready duty cycle: 47\n  Drive manufacturer's serial number: 0\n  Drive serial number: 0\n  Medium removal prevented: 0\n  Maximum recommended mechanism temperature exceeded: 0\n  Media motion (head) hours for each medium type:\n    Density code: 0x62, Medium type: 0xa8\n      Medium motion hours: 4\n    Density code: 0x62, Medium type: 0xac\n      Medium motion hours: 0\n    Density code: 0x63, Medium type: 0xa9\n      Medium motion hours: 2\n  Vendor specific parameter [0xf001], dump in hex:\n 00     1a                                                  .\n\nTape diagnostics data page (ssc-3) [0x16]\n  Parameter code: 0\n    Density code: 0x62\n    Medium type: 0xa8\n    Lifetime media motion hours: 1\n    Repeat: 0\n    Sense key: 0x3 [Medium Error]\n    Additional sense code: 0xc\n    Additional sense code qualifier: 0x0\n      [Additional sense: Write error]\n    Vendor specific code qualifier: 0x74212009\n    Product revision level: 1395868976\n    Hours since last clean: 1\n    Operation code: 0xa\n    Service action: 0x0\n    Medium id number (in hex):\n 00     54 34 50 4b 46 41 50 46  30 36 20 20 20 20 20 20    T4PKFAPF06      \n 10     20 20 20 20 20 20 20 20  20 20 20 20 20 20 20 20                    \n    Timestamp origin: 0x0\n    Timestamp:\n 00     00 00 00 35 de 14\n  Parameter code: 1\n    Density code: 0x0\n    Medium type: 0x0\n    Lifetime media motion hours: 0\n    Repeat: 0\n    Sense key: 0x0 [No Sense]\n    Additional sense code: 0x0\n    Additional sense code qualifier: 0x0\n    Vendor specific code qualifier: 0x0\n    Product revision level: 0\n    Hours since last clean: 0\n    Operation code: 0x0\n    Service action: 0x0\n    Medium id number is 32 bytes of zero\n    Timestamp origin: 0x0\n    Timestamp is all zeros:\n  Parameter code: 2\n    Density code: 0x0\n    Medium type: 0x0\n    Lifetime media motion hours: 0\n    Repeat: 0\n    Sense key: 0x0 [No Sense]\n    Additional sense code: 0x0\n    Additional sense code qualifier: 0x0\n    Vendor specific code qualifier: 0x0\n    Product revision level: 0\n    Hours since last clean: 0\n    Operation code: 0x0\n    Service action: 0x0\n    Medium id number is 32 bytes of zero\n    Timestamp origin: 0x0\n    Timestamp is all zeros:\n  Parameter code: 3\n    Density code: 0x0\n    Medium type: 0x0\n    Lifetime media motion hours: 0\n    Repeat: 0\n    Sense key: 0x0 [No Sense]\n    Additional sense code: 0x0\n    Additional sense code qualifier: 0x0\n    Vendor specific code qualifier: 0x0\n    Product revision level: 0\n    Hours since last clean: 0\n    Operation code: 0x0\n    Service action: 0x0\n    Medium id number is 32 bytes of zero\n    Timestamp origin: 0x0\n    Timestamp is all zeros:\n  Parameter code: 4\n    Density code: 0x0\n    Medium type: 0x0\n    Lifetime media motion hours: 0\n    Repeat: 0\n    Sense key: 0x0 [No Sense]\n    Additional sense code: 0x0\n    Additional sense code qualifier: 0x0\n    Vendor specific code qualifier: 0x0\n    Product revision level: 0\n    Hours since last clean: 0\n    Operation code: 0x0\n    Service action: 0x0\n    Medium id number is 32 bytes of zero\n    Timestamp origin: 0x0\n    Timestamp is all zeros:\n  Parameter code: 5\n    Density code: 0x0\n    Medium type: 0x0\n    Lifetime media motion hours: 0\n    Repeat: 0\n    Sense key: 0x0 [No Sense]\n    Additional sense code: 0x0\n    Additional sense code qualifier: 0x0\n    Vendor specific code qualifier: 0x0\n    Product revision level: 0\n    Hours since last clean: 0\n    Operation code: 0x0\n    Service action: 0x0\n    Medium id number is 32 bytes of zero\n    Timestamp origin: 0x0\n    Timestamp is all zeros:\n  Parameter code: 6\n    Density code: 0x0\n    Medium type: 0x0\n    Lifetime media motion hours: 0\n    Repeat: 0\n    Sense key: 0x0 [No Sense]\n    Additional sense code: 0x0\n    Additional sense code qualifier: 0x0\n    Vendor specific code qualifier: 0x0\n    Product revision level: 0\n    Hours since last clean: 0\n    Operation code: 0x0\n    Service action: 0x0\n    Medium id number is 32 bytes of zero\n    Timestamp origin: 0x0\n    Timestamp is all zeros:\n  Parameter code: 7\n    Density code: 0x0\n    Medium type: 0x0\n    Lifetime media motion hours: 0\n    Repeat: 0\n    Sense key: 0x0 [No Sense]\n    Additional sense code: 0x0\n    Additional sense code qualifier: 0x0\n    Vendor specific code qualifier: 0x0\n    Product revision level: 0\n    Hours since last clean: 0\n    Operation code: 0x0\n    Service action: 0x0\n    Medium id number is 32 bytes of zero\n    Timestamp origin: 0x0\n    Timestamp is all zeros:\n  Parameter code: 8\n    Density code: 0x0\n    Medium type: 0x0\n    Lifetime media motion hours: 0\n    Repeat: 0\n    Sense key: 0x0 [No Sense]\n    Additional sense code: 0x0\n    Additional sense code qualifier: 0x0\n    Vendor specific code qualifier: 0x0\n    Product revision level: 0\n    Hours since last clean: 0\n    Operation code: 0x0\n    Service action: 0x0\n    Medium id number is 32 bytes of zero\n    Timestamp origin: 0x0\n    Timestamp is all zeros:\n  Parameter code: 9\n    Density code: 0x0\n    Medium type: 0x0\n    Lifetime media motion hours: 0\n    Repeat: 0\n    Sense key: 0x0 [No Sense]\n    Additional sense code: 0x0\n    Additional sense code qualifier: 0x0\n    Vendor specific code qualifier: 0x0\n    Product revision level: 0\n    Hours since last clean: 0\n    Operation code: 0x0\n    Service action: 0x0\n    Medium id number is 32 bytes of zero\n    Timestamp origin: 0x0\n    Timestamp is all zeros:\n  Parameter code: 10\n    Density code: 0x0\n    Medium type: 0x0\n    Lifetime media motion hours: 0\n    Repeat: 0\n    Sense key: 0x0 [No Sense]\n    Additional sense code: 0x0\n    Additional sense code qualifier: 0x0\n    Vendor specific code qualifier: 0x0\n    Product revision level: 0\n    Hours since last clean: 0\n    Operation code: 0x0\n    Service action: 0x0\n    Medium id number is 32 bytes of zero\n    Timestamp origin: 0x0\n    Timestamp is all zeros:\n  Parameter code: 11\n    Density code: 0x0\n    Medium type: 0x0\n    Lifetime media motion hours: 0\n    Repeat: 0\n    Sense key: 0x0 [No Sense]\n    Additional sense code: 0x0\n    Additional sense code qualifier: 0x0\n    Vendor specific code qualifier: 0x0\n    Product revision level: 0\n    Hours since last clean: 0\n    Operation code: 0x0\n    Service action: 0x0\n    Medium id number is 32 bytes of zero\n    Timestamp origin: 0x0\n    Timestamp is all zeros:\n\nVolume statistics page (ssc-4), subpage=0\n  Page valid: 1\n  Thread count: 11\n  Total data sets written: 184726\n  Total write retries: 4\n  Total unrecovered write errors: 0\n  Total suspended writes: 2\n  Total fatal suspended writes: 0\n  Total data sets read: 57\n  Total read retries: 0\n  Total unrecovered read errors: 0\n  Last mount unrecovered write errors: 0\n  Last mount unrecovered read errors: 0\n  Last mount megabytes written: 9\n  Last mount megabytes read: 49\n  Lifetime megabytes written: 1811222\n  Lifetime megabytes read: 558\n  Last load write compression ratio: 8026\n  Last load read compression ratio: 0\n  Medium mount time: 73899\n  Medium ready time: 41258\n  Total native capacity [MB]: 27966101\n  Total used native capacity [MB]: 1418152\n  Reserved parameter code (0x18), payload in hex\n 00     01 ba 81 40                                         ...@\n  Reserved parameter code (0x19), payload in hex\n 00     63                                                  c\n  Volume serial number: T5KVFD2NT4                      \n  Tape lot identifier: *2282195\n  Volume barcode: IBM015LA\n  Volume manufacturer: IBM     \n  Volume license code: 0707\n  Volume personality: LTOLA62  \n  Write protect: 0\n  WORM: 0\n  Maximum recommended tape path temperature exceeded: 0\n  Beginning of medium passes: 135\n  Middle of medium passes: 37\n  Logical position of first encrypted logical object:\n    partition number: 0, partition record data counter: 0xffffffffffff\n    partition number: 1, partition record data counter: 0xffffffffffff\n  Logical position of first unencrypted logical object after first\n  encrypted logical object:\n    partition number: 0, partition record data counter: 0xffffffffffff\n    partition number: 1, partition record data counter: 0xffffffffffff\n  Native capacity partition(s) [MB]:\n    partition number: 0, partition record data counter: 127118\n    partition number: 1, partition record data counter: 27838983\n  Used native capacity partition(s) [MB]:\n    partition number: 0, partition record data counter: 39\n    partition number: 1, partition record data counter: 1418113\n  Remaining native capacity partition(s) [MB]:\n    partition number: 0, partition record data counter: 127074\n    partition number: 1, partition record data counter: 26439429\n\nPower condition transitions page  [0x1a]\n  Accumulated transitions to active = 18\n  Accumulated transitions to idle_c = 24\n\nData compression page  (ssc-4) [0x1b]\n  Read compression ratio x100: 0\n  Write compression ratio x100: 8026\n  Megabytes transferred to server: 0\n  Bytes transferred to server: 0\n  Megabytes read from tape: 0\n  Bytes read from tape: 4\n  Megabytes transferred from server: 268\n  Bytes transferred from server: 435456\n  Megabytes written to tape: 3\n  Bytes written to tape: 344392\n  Data compression enabled: 0x1\n\nTape alert page (ssc-3) [0x2e]\n  Read warning: 0\n  Write warning: 0\n  Hard error: 0\n  Media: 0\n  Read failure: 0\n  Write failure: 0\n  Media life: 0\n  Not data grade: 0\n  Write protect: 0\n  No removal: 0\n  Cleaning media: 0\n  Unsupported format: 0\n  Recoverable mechanical cartridge failure: 0\n  Unrecoverable mechanical cartridge failure: 0\n  Memory chip in cartridge failure: 0\n  Forced eject: 0\n  Read only format: 0\n  Tape directory corrupted on load: 0\n  Nearing media life: 0\n  Cleaning required: 0\n  Cleaning requested: 0\n  Expired cleaning media: 0\n  Invalid cleaning tape: 0\n  Retension requested: 0\n  Dual port interface error: 0\n  Cooling fan failing: 0\n  Power supply failure: 0\n  Power consumption: 0\n  Drive maintenance: 0\n  Hardware A: 0\n  Hardware B: 0\n  Interface: 0\n  Eject media: 0\n  Microcode update fail: 0\n  Drive humidity: 0\n  Drive temperature: 0\n  Drive voltage: 0\n  Predictive failure: 0\n  Diagnostics required: 0\n  Obsolete (28h): 0\n  Obsolete (29h): 0\n  Obsolete (2Ah): 0\n  Obsolete (2Bh): 0\n  Obsolete (2Ch): 0\n  Obsolete (2Dh): 0\n  Obsolete (2Eh): 0\n  Reserved (2Fh): 0\n  Reserved (30h): 0\n  Reserved (31h): 0\n  Lost statistics: 0\n  Tape directory invalid at unload: 0\n  Tape system area write failure: 0\n  Tape system area read failure: 0\n  No start of data: 0\n  Loading failure: 0\n  Unrecoverable unload failure: 0\n  Automation interface failure: 0\n  Firmware failure: 0\n  WORM medium - integrity check failed: 0\n  WORM medium - overwrite attempted: 0\n  Reserved parameter code 0x3d, flag: 0\n  Reserved parameter code 0x3e, flag: 0\n  Reserved parameter code 0x3f, flag: 0\n  Reserved parameter code 0x40, flag: 0\n\nTape usage page  (LTO-5 and LTO-6 specific) [0x30]\n  Thread count: 11\n  Total data sets written: 184726\n  Total write retries: 4\n  Total unrecovered write errors: 0\n  Total suspended writes: 2\n  Total fatal suspended writes: 0\n  Total data sets read: 57\n  Total read retries: 0\n  Total unrecovered read errors: 0\n  Total suspended reads: 0\n  Total fatal suspended reads: 0\n\nTape capacity page  (LTO-5 and LTO-6 specific) [0x31]\n  Main partition remaining capacity (in MiB): 121187\n  Alternate partition remaining capacity (in MiB): 25214604\n  Main partition maximum capacity (in MiB): 121229\n  Alternate partition maximum capacity (in MiB): 26549323\n\nData compression page  (LTO-5 specific) [0x32]\n  Read compression ratio x100: 0\n  Write compression ratio x100: 8026\n  Megabytes transferred to server: 0\n  Bytes transferred to server: 0\n  Megabytes read from tape: 0\n  Bytes read from tape: 4\n  Megabytes transferred from server: 268\n  Bytes transferred from server: 435456\n  Megabytes written to tape: 3\n  Bytes written to tape: 344392\n\nUnable to decode page = 0x33, here is hex:\n 00     33 00 00 6c 00 00 40 02  00 00 00 01 40 02 00 00\n 10     00 02 40 02 00 00 00 03  40 02 00 00 00 04 40 02\n 20     00 00 00 05 40 02 00 00  00 06 40 02 00 00 00 07\n 30     40 02 00 00 00 08 40 02  00 00 00 09 40 02 00 00\n 40     00 0a 40 02 00 00 00 0b  40 02 00 00 00 0c 40 02\n 50     00 00 00 0d 40 02 00 00  00 0e 40 02 00 00 00 0f\n 60     40 02 00 01 00 10 40 02  00 00 00 11 40 02 00 00\n\nUnable to decode page = 0x34, here is hex:\n 00     34 00 00 ba 00 00 40 02  00 05 00 01 40 02 00 00\n 10     00 02 40 02 00 00 00 03  40 02 00 00 00 04 40 02\n 20     00 00 00 05 40 02 00 00  00 06 40 02 00 00 00 07\n 30     40 02 00 00 00 08 40 02  00 00 00 09 40 02 00 00\n .....  [truncated after 64 of 190 bytes (use '-H' to see the rest)]\n\nUnable to decode page = 0x37, here is hex:\n 00     37 00 00 1e 00 00 60 01  23 00 01 60 01 08 00 10\n 10     60 01 80 00 11 60 01 80  00 12 60 01 00 00 1a 60\n 20     01 00\n\nUnable to decode page = 0x38, here is hex:\n 00     38 00 00 d0 00 00 40 08  00 00 00 00 00 00 01 00\n 10     00 01 40 08 00 00 00 00  00 04 00 00 00 02 40 08\n 20     00 00 00 00 00 00 00 00  00 03 40 08 00 00 00 00\n 30     00 00 00 00 00 04 40 04  00 00 00 02 00 05 40 06\n .....  [truncated after 64 of 212 bytes (use '-H' to see the rest)]\n\nUnable to decode page = 0x39, here is hex:\n 00     39 00 00 26 00 00 40 02  00 00 00 07 40 02 00 00\n 10     00 08 40 02 00 00 00 09  40 02 00 00 00 0a 40 02\n 20     00 00 00 10 40 04 00 00  00 00\n\nUnable to decode page = 0x3b, here is hex:\n 00     3b 00 00 26 00 00 40 02  00 00 00 07 40 02 00 00\n 10     00 08 40 02 00 00 00 09  40 02 00 00 00 0a 40 02\n 20     00 00 00 10 40 04 00 00  00 00\n\nUnable to decode page = 0x3c, here is hex:\n 00     3c 00 00 aa 00 01 40 08  00 00 00 00 00 04 91 ea\n 10     00 02 40 08 00 00 00 00  00 00 00 06 00 03 40 08\n 20     00 00 00 00 00 01 0c e3  00 04 40 08 00 00 00 00\n 30     00 03 5f 27 00 05 40 08  00 00 00 00 00 00 00 07\n .....  [truncated after 64 of 174 bytes (use '-H' to see the rest)]\n\nUnable to decode page = 0x3d, here is hex:\n 00     3d 00 01 20 00 20 40 04  00 00 00 0b 00 21 40 08\n 10     00 00 00 00 00 1b a3 16  00 22 40 08 00 00 00 00\n 20     00 00 02 2e 00 40 40 04  00 00 00 5f 00 41 40 08\n 30     00 00 00 00 00 2c ce e7  00 42 40 08 00 00 00 00\n .....  [truncated after 64 of 292 bytes (use '-H' to see the rest)]\n","command_id":"CMD-90D4F937"},"error":null}```


---

# 四、带库操作测试

## 4.1 带库列表与 Inquiry

### GET http://127.0.0.1:8001/api/v1/libraries

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-171116-FD4140","data":[{"scsi_address":"32:0:0:1","device_type":"MEDIUMX","vendor":"IBM","product":"03584L32","sg_device":"/dev/sg3","st_device":null,"nst_device":null},{"scsi_address":"33:0:0:1","device_type":"MEDIUMX","vendor":"IBM","product":"03584L32","sg_device":"/dev/sg1","st_device":null,"nst_device":null}],"error":null}```


### GET http://127.0.0.1:8001/api/v1/libraries/sg1/inquiry

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-171116-C58FC1","data":{"stdout":"Product Type: Medium Changer\nVendor ID: 'IBM     '\nProduct ID: '03584L32        '\nRevision: '2C02'\nAttached Changer API: No\n","command_id":"CMD-E095A75B"},"error":null}```


## 4.2 带库状态 `GET /api/v1/libraries/sg1/status`（mtx status）

### GET http://127.0.0.1:8001/api/v1/libraries/sg1/status

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-171116-FEFEE0","data":{"stdout":"  Storage Changer /dev/sg1:3 Drives,
  ... (输出截断，完整结果见 audit/commands/ 原始日志)
```

## 4.3 结构化 Inventory `GET /api/v1/libraries/sg1/inventory`

### GET http://127.0.0.1:8001/api/v1/libraries/sg1/inventory

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-171117-768D47","data":{"library":{"changer":"/dev/sg1"},"slots":[{"element":1,"slot":1,"occupied":true,"barcode":"IBM006LA"},{"element":2,"slot":2,"occupied":true,"barcode":"IBM014LA"},{"element":3,"slot":3,"occupied":false,"barcode":null},{"element":4,"slot":4,"occupied":true,"barcode":"IBM009LA"},{"element":5,"slot":5,"occupied":true,"barcode":"IBM013LA"},{"element":6,"slot":6,"occupied":true,"barcode":"IBM015LA"},{"element":7,"slot":7,"occupied":false,"barcode":null},{"element":8,"slot":8,"occupied":false,"barcode":null},{"element":9,"slot":9,"occupied":false,"barcode":null},{"element":10,"slot":10,"occupied":false,"barcode":null},{"element":11,"slot":11,"occupied":false,"barcode":null},{"element":12,"slot":12,"occupied":false,"barcode":null},{"element":13,"slot":13,"occupied":false,"barcode":null},{"element":14,"slot":14,"occupied":false,"barcode":null},{"element":15,"slot":15,"occupied":false,"barcode":null},{"element":16,"slot":16,"occupied":false,"barcode":null},{"element":17,"slot":17,"occupied":false,"barcode":null},{"element":18,"slot":18,"occupied":false,"barcode":null},{"element":19,"slot":19,"occupied":false,"barcode":null},{"element":20,"slot":20,"occupied":false,"barcode":null},{"element":21,"slot":21,"occupied":false,"barcode":null},{"element":22,"slot":22,"occupied":false,"barcode":null},{"element":23,"slot":23,"occupied":false,"barcode":null},{"element":24,"slot":24,"occupied":false,"barcode":null},{"element":25,"slot":25,"occupied":false,"barcode":null},{"element":26,"slot":26,"occupied":false,"barcode":null},{"element":27,"slot":27,"occupied":false,"barcode":null},{"element":28,"slot":28,"occupied":false,"barcode":null},{"element":29,"slot":29,"occupied":false,"barcode":null},{"element":30,"slot":30,"occupied":false,"barcode":null},{"element":31,"slot":31,"occupied":false,"barcode":null},{"element":32,"slot":32,"occupied":false,"barcode":null},{"element":33,"slot":33,"occupied":false,"barcode":null},{"element":34,"slot":34,"occupied":false,"barcode":null},
  ... (输出截断，完整结果见 audit/commands/ 原始日志)
```

## 4.4 装载磁带 `POST /api/v1/libraries/sg1/load`（LEVEL 2）

### POST http://127.0.0.1:8001/api/v1/libraries/sg1/load

Request:
```json
{"slot": 6, "drive": 0, "confirm": true}
```

Response:
```json
{"success":true,"code":"LOAD_SUCCESS","message":"Operation completed successfully","request_id":"REQ-20260910-171119-C8B784","data":{"slot":6,"drive":0,"command_id":"CMD-736D1B1F"},"error":null}```


装载后状态（DTE 0 = Full, IBM015LA）：

### GET http://127.0.0.1:8001/api/v1/libraries/sg1/status

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-171129-088036","data":{"stdout":"  Storage Changer /dev/sg1:3 Drives,
  ... (输出截断，完整结果见 audit/commands/ 原始日志)
```

## 4.5 卸载归位 `POST /api/v1/libraries/sg1/unload`

### POST http://127.0.0.1:8001/api/v1/libraries/sg1/unload

Request:
```json
{"slot": 6, "drive": 0, "confirm": true}
```

Response:
```json
{"success":true,"code":"UNLOAD_SUCCESS","message":"Operation completed successfully","request_id":"REQ-20260910-171130-601566","data":{"slot":6,"drive":0,"command_id":"CMD-0E331046"},"error":null}```


## 4.6 错误用例：非法槽位（INVALID_SLOT）

### POST http://127.0.0.1:8001/api/v1/libraries/sg1/load

Request:
```json
{"slot": -1, "drive": 0, "confirm": true}
```

Response:
```json
{"detail":{"code":"INVALID_SLOT","message":"INVALID_SLOT"}}```


## 4.7 错误用例：不存在的带库（sg9）

### POST http://127.0.0.1:8001/api/v1/libraries/sg9/load

Request:
```json
{"slot": 6, "drive": 0, "confirm": true}
```

Response:
```json
{"detail":{"code":"COMMAND_FAILED","message":"mtx load failed"}}```


---

# 五、带机操作测试

先装载测试带：

### POST http://127.0.0.1:8001/api/v1/libraries/sg1/load

Request:
```json
{"slot": 6, "drive": 0, "confirm": true}
```

Response:
```json
{"success":true,"code":"LOAD_SUCCESS","message":"Operation completed successfully","request_id":"REQ-20260910-171221-FAB005","data":{"slot":6,"drive":0,"command_id":"CMD-BE0A544D"},"error":null}```


## 5.1 带机状态 `GET /api/v1/drives/nst1/status`（mt status）

### GET http://127.0.0.1:8001/api/v1/drives/nst1/status

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-171230-9DDB9E","data":{"stdout":"SCSI 2 tape drive:\nFile number=-1, block number=-1, partition=0.\nTape block size 0 bytes. Density code 0x0 (default).\nSoft error count since last status=0\nGeneral status bits on (10000):\n IM_REP_EN\n","command_id":"CMD-F0CFD2CE"},"error":null}```


## 5.2 TapeAlert `GET /api/v1/drives/sg2/tapealert`（sg_logs -p 0x2e）

### GET http://127.0.0.1:8001/api/v1/drives/sg2/tapealert

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-171230-F0C15E","data":{"alerts":[],"raw_output":"    IBM       ULT3580-TDA       T3S0\nTape alert page (ssc-3) [0x2e]\n  Read warning: 0\n  Write warning: 0\n  Hard error: 0\n  Media: 0\n  Read failure: 0\n  Write failure: 0\n  Media life: 0\n  Not data grade: 0\n  Write protect: 0\n  No removal: 0\n  Cleaning media: 0\n  Unsupported format: 0\n  Recoverable mechanical cartridge failure: 0\n  Unrecoverable mechanical cartridge failure: 0\n  Memory chip in cartridge failure: 0\n  Forced eject: 0\n  Read only format: 0\n  Tape directory corrupted on load: 0\n  Nearing media life: 0\n  Cleaning required: 0\n  Cleaning requested: 0\n  Expired cleaning media: 0\n  Invalid cleaning tape: 0\n  Retension requested: 0\n  Dual port interface error: 0\n  Cooling fan failing: 0\n  Power supply failure: 0\n  Power consumption: 0\n  Drive maintenance: 0\n  Hardware A: 0\n  Hardware B: 0\n  Interface: 0\n  Eject media: 0\n  Microcode update fail: 0\n  Drive humidity: 0\n  Drive temperature: 0\n  Drive voltage: 0\n  Predictive failure: 0\n  Diagnostics required: 0\n  Obsolete (28h): 0\n  Obsolete (29h): 0\n  Obsolete (2Ah): 0\n  Obsolete (2Bh): 0\n  Obsolete (2Ch): 0\n  Obsolete (2Dh): 0\n  Obsolete (2Eh): 0\n  Reserved (2Fh): 0\n  Reserved (30h): 0\n  Reserved (31h): 0\n  Lost statistics: 0\n  Tape directory invalid at unload: 0\n  Tape system area write failure: 0\n  Tape system area read failure: 0\n  No start of data: 0\n  Loading failure: 0\n  Unrecoverable unload failure: 0\n  Automation interface failure: 0\n  Firmware failure: 0\n  WORM medium - integrity check failed: 0\n  WORM medium - overwrite attempted: 0\n  Reserved parameter code 0x3d, flag: 0\n  Reserved parameter code 0x3e, flag: 0\n  Reserved parameter code 0x3f, flag: 0\n  Reserved parameter code 0x40, flag: 0\n",
  ... (输出截断，完整结果见 audit/commands/ 原始日志)
```

## 5.3 磁带回绕 `POST /api/v1/drives/nst1/position {rewind}`

### POST http://127.0.0.1:8001/api/v1/drives/nst1/position

Request:
```json
{"operation": "rewind", "confirm": true}
```

Response:
```json
{"success":true,"code":"POSITION_SUCCESS","message":"Operation completed successfully","request_id":"REQ-20260910-171230-29B797","data":{"operation":"rewind","count":1,"command_id":"CMD-9B4F5C90"},"error":null}```


## 5.4 磁带定位 fsf `POST /api/v1/drives/nst1/position {fsf 1}`

### POST http://127.0.0.1:8001/api/v1/drives/nst1/position

Request:
```json
{"operation": "fsf", "count": 1, "confirm": true}
```

Response:
```json
{"success":true,"code":"POSITION_SUCCESS","message":"Operation completed successfully","request_id":"REQ-20260910-171243-37E425","data":{"operation":"fsf","count":1,"command_id":"CMD-8DED2803"},"error":null}```


## 5.5 压缩状态 `GET /api/v1/drives/nst1/compression`

### GET http://127.0.0.1:8001/api/v1/drives/nst1/compression

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-171250-77DE13","data":{"stdout":"","command_id":"CMD-C60903BE"},"error":null}```


## 5.6 错误用例：非法操作名（INVALID_OPERATION）

### POST http://127.0.0.1:8001/api/v1/drives/nst1/position

Request:
```json
{"operation": "format_c", "count": 1, "confirm": true}
```

Response:
```json
{"detail":{"code":"INVALID_OPERATION","message":"INVALID_OPERATION"}}```


## 5.7 综合诊断 `GET /api/v1/diagnostics/tape/sg2`

### GET http://127.0.0.1:8001/api/v1/diagnostics/tape/sg2

Response:
```json
{"success":true,"code":"OK","message":"Operation completed successfully","request_id":"REQ-20260910-171250-0E67E0","data":{"inquiry":{"stdout":"standard INQUIRY:\n  PQual=0  PDT=1  RMB=1  LU_CONG=0  hot_pluggable=0  version=0x06  [SPC-4]\n  [AERC=0]  [TrmTsk=0]  NormACA=0  HiSUP=1  Resp_data_format=2\n  SCCS=0  ACC=0  TPGS=0  3PC=0  Protect=1  [BQue=0]\n  EncServ=0  MultiP=1 (VS=0)  [MChngr=0]  [ACKREQQ=0]  Addr16=0\n  [RelAdr=0]  WBus16=0  Sync=0  [Linked=0]  [TranDis=0]  CmdQue=1\n  [SPI: Clocking=0x0  QAS=0  IUS=0]\n    length=70 (0x46)   Peripheral device type: tape\n Vendor identification: IBM     \n Product identification: ULT3580-TDA     \n Product revision level: T3S0\n Unit serial number: 607B811E03\n","command_id":"CMD-55E15978"},"vpd_0x80":{"page":"0x80","stdout":"Unit serial number VPD page:\n  Unit serial number: 607B811E03\n","command_id":"CMD-669898B9"},"tur":{"ready":true,"stdout":"","stderr":"","command_id":"CMD-56EEDAAB"},"tapealert":{"alerts":[],
  ... (输出截断，完整结果见 audit/commands/ 原始日志)
```

---

# 六、读写 IO 测试

> 读写在 FULL 模式实例（端口 8002）执行；写类接口要求请求体 `allow_write:true` + `test_media` + `confirm:true`。

## 6.1 读测试 `POST /api/v1/tests/read`（dd 读）

### POST http://127.0.0.1:8002/api/v1/tests/read

Request:
```json
{"drive": "/dev/nst1", "block_size": "1M", "confirm": true}
```

Response:
```json
{"success":true,"code":"READ_TEST_PASS","message":"Operation completed successfully","request_id":"REQ-20260910-171250-ABAEB7","data":{"drive":"/dev/nst1","duration_ms":1179,"command_id":"CMD-D5D61E9A"},"error":null}```


## 6.2 写测试 `POST /api/v1/tests/write`（dd 写 256MB，18.2s）

### POST http://127.0.0.1:8002/api/v1/tests/write

Request:
```json
{"drive": "/dev/nst1", "test_media": "IBM015LA", "size_mb": 256, "allow_write": true, "confirm": true}
```

Response:
```json
{"success":true,"code":"WRITE_TEST_PASS","message":"Operation completed successfully","request_id":"REQ-20260910-171251-634F33","data":{"drive":"/dev/nst1","size_mb":256,"duration_ms":18205,"command_id":"CMD-35DC8102"},"error":null}```


## 6.3 错误用例：未授权写文件标记（weof 被 FULL 门禁拦截）

### POST http://127.0.0.1:8001/api/v1/drives/nst1/weof

Request:
```json
{"count": 1, "confirm": true}
```

Response:
```json
{"detail":{"code":"WRITE_OPERATION_NOT_AUTHORIZED","message":"WRITE_OPERATION_NOT_AUTHORIZED"}}```


## 6.4 写后读回+内容校验 `POST /api/v1/tests/write-verify`（CLI: dd→weof→rewind→dd→cmp 全流程）

### POST http://127.0.0.1:8002/api/v1/tests/write-verify

Request:
```json
{"drive": "/dev/nst1", "test_media": "IBM015LA", "size_mb": 256, "allow_write": true, "confirm": true}
```

Response:
```json
{"success":true,"code":"WRITE_VERIFY_PASS","message":"Operation completed successfully","request_id":"REQ-20260910-172948-4B2CEA","data":{"drive":"/dev/nst1","media":"IBM015LA","size_mb":256,"write_duration_ms":8107,"read_duration_ms":395,"content_verified":true,"steps":[{"step":"rewind","command_id":"CMD-95C1856F"},{"step":"write","bytes":268435456,"duration_ms":8107,"command_id":"CMD-4CF67EFE"},{"step":"weof","command_id":"CMD-5C76342B"},{"step":"read_verify","duration_ms":395,"command_id":"CMD-D2DF66BC"},{"step":"content_verify","content_ok":true,"command_id":"CMD-57E95264"}]},"error":null}```


返回结构说明：`steps` 数组完整记录 5 步链路（rewind → write 256MB/8.1s → weof → read_verify 0.4s → content_verify CONTENT_VERIFY_OK），每步含 command_id 可溯源。

## 6.5 错误用例：未授权写测试（allow_write=false）

### POST http://127.0.0.1:8001/api/v1/tests/write

Request:
```json
{"drive": "/dev/nst1", "size_mb": 256, "allow_write": false, "confirm": true}
```

Response:
```json
{"detail":{"code":"WRITE_OPERATION_NOT_AUTHORIZED","message":"WRITE_OPERATION_NOT_AUTHORIZED"}}```


## 6.6 写后读回验证 `POST /api/v1/tests/read`

### POST http://127.0.0.1:8002/api/v1/tests/read

Request:
```json
{"drive": "/dev/nst1", "block_size": "1M", "confirm": true}
```

Response:
```json
{"success":true,"code":"READ_TEST_PASS","message":"Operation completed successfully","request_id":"REQ-20260910-171309-CAD602","data":{"drive":"/dev/nst1","duration_ms":8085,"command_id":"CMD-4A678722"},"error":null}```


## 6.7 测试后卸载归位 `POST /api/v1/libraries/sg1/unload`

### POST http://127.0.0.1:8001/api/v1/libraries/sg1/unload

Request:
```json
{"slot": 6, "drive": 0, "confirm": true}
```

Response:
```json
{"success":true,"code":"UNLOAD_SUCCESS","message":"Operation completed successfully","request_id":"REQ-20260910-171317-FA3414","data":{"slot":6,"drive":0,"command_id":"CMD-6A14D5AF"},"error":null}```


---

# 七、审计与溯源 API

```
GET /api/v1/commands/{command_id}   # 单条命令: command/stdout/stderr/exit_code/duration/result
GET /api/v1/audit/{request_id}      # 请求→命令链: 一次 API 调用的全部底层命令
```

任何响应中的 `command_id` 均可在测试机 `audit/commands/CMD-*/` 找到原始 stdout.txt / stderr.txt / command.json。

---

# 八、测试结果汇总

| 章节 | 用例 | 结果 |
|---|---|---|
| 基础与发现 | info / kernel / ibm / dependencies / discovery / detail / inquiry / modes / logs(全页+0x11) | 9/9 PASS |
| 带库操作 | libraries / inquiry / status / inventory / load / unload | 6/6 PASS |
| 带库错误用例 | INVALID_SLOT (slot=-1)、LIBRARY_NOT_FOUND (sg9) | 2/2 正确拦截 |
| 带机操作 | status / tapealert / rewind / fsf / compression / 综合诊断 | 6/6 PASS |
| 带机错误用例 | INVALID_OPERATION (format_c) | 1/1 正确拦截 |
| 读写 IO | read / write 256MB / write-verify 全流程（含 weof+读回+cmp）/ 写后读回 / 卸载 | 5/5 PASS |
| 读写错误用例 | WRITE_OPERATION_NOT_AUTHORIZED（weof 与 write 两处） | 2/2 正确拦截 |

**结论：31 个真实硬件用例全部符合预期（含 5 个安全拦截用例）；Mock 单元/API/安全测试 52/52 通过；所有响应可经 request_id → command_id 溯源至原始命令输出。**

# 九、服务启动与配置

```bash
# SAFE 模式（默认，只读）
uvicorn app.main:app --host 0.0.0.0 --port 8000

# DIAGNOSTIC 模式（允许 LEVEL 2 设备操作）
TAPE_API_MODE=DIAGNOSTIC ALLOW_DEVICE_OPERATION=true uvicorn app.main:app --port 8001

# FULL 模式（允许 LEVEL 3 写测试，需请求体双重授权）
TAPE_API_MODE=FULL ALLOW_DEVICE_OPERATION=true ALLOW_WRITE=true TEST_MEDIA=IBM015LA \
  uvicorn app.main:app --port 8002
```

环境变量完整清单见 `.env.example`；错误码表与安全说明见 `docs/API.md`。

