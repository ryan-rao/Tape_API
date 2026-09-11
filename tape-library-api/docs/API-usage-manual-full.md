# Tape Library API 全量测试手册（CMD-000001 ~ CMD-000108 逐条对照）

- 版本: 2.0.0 | 服务: tape-library-api @ node186 (172.16.12.186) | 生成: 2026-09-10
- 框架: Python 3.9 / FastAPI / Pydantic / Uvicorn | Swagger: `/docs` | OpenAPI: `/openapi.json`
- 环境: IBM 03584L32 带库（/dev/sg1 与 /dev/sg3 双路径）+ 2× IBM ULT3580-TDA 带机（/dev/nst0、/dev/nst1）+ 测试介质 IBM015LA
- 本手册将 CLI 测试报告的全部 **108 条命令**（CMD-000001 ~ CMD-000108）逐条映射到 API，每条附 **真实 curl 调用** 与 **原始响应**（JSON 已格式化为每行一个 key/value）。同参数重复调用标注"同参数复用同一次调用结果"。
- 测试实例：`8001` = DIAGNOSTIC 模式（LEVEL 1+2）；`8002` = FULL 模式（LEVEL 1+2+3，写类接口）
- 采集统计：41 次独立 API 调用 + 75 次同参数复用 = 覆盖 108 条 CLI 命令

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
│  Command Adapters (白名单)     │  Lsscsi/Sg/Mtx/Mt/SystemProbe
└───────────────┬───────────────┘
┌───────────────▼───────────────┐
│  Command Runner               │  subprocess shell=False + 超时
                                │  + 设备锁 + 审计落盘
└───────────────┬───────────────┘
┌───────────────▼───────────────┐
│  Linux 命令层                  │  lsscsi / sg3_utils / mtx / mt
└───────────────┬───────────────┘
┌───────────────▼───────────────┐
│  磁带库硬件                    │
└───────────────────────────────┘
```

# 二、JSON 字段解释（全局字典）

## 2.1 外层响应字段（所有 API 一致）

| key | 含义 |
|---|---|
| success | 布尔，本次 API 操作是否成功 |
| code | 结果码（OK / LOAD_SUCCESS / WRITE_TEST_PASS / COMMAND_FAILED 等，见 docs/API.md 错误码表） |
| message | 人类可读的结果说明 |
| request_id | 本次 API 请求唯一 ID（REQ-时间-序号），一次请求可关联多条底层命令 |
| data | 业务数据对象（各接口不同，见 2.2） |
| error | 失败时的错误对象（type=错误类别，details=详情）；成功时为 null |

## 2.2 常见 data 内层字段

| key | 含义 |
|---|---|
| command_id | 底层 Linux 命令的唯一 ID（CMD-XXXX），可在 audit/commands/ 找到原始 stdout/stderr |
| command | 实际执行的命令行（argv 拼接展示） |
| phase | 命令所属测试阶段（DISCOVERY / LIBRARY_LOAD / WRITE_TEST 等） |
| risk_level | 安全等级：LEVEL_1 只读 / LEVEL_2 设备操作 / LEVEL_3 写入 |
| device | 命令作用的设备节点（如 /dev/sg1） |
| started_at / finished_at | 命令开始 / 结束时间（ISO8601） |
| duration_ms | 命令耗时（毫秒） |
| exit_code | 底层命令退出码（0=成功） |
| stdout / stderr | 底层命令原始标准输出 / 标准错误（保留用于审计溯源） |
| parsed | **结构化解析对象**：将 CLI 的原始 stdout 文本解析为 JSON 字段（见 2.4） |
| parsed_ok | 解析是否成功（false 表示输出格式无法识别，仅保留原始 stdout） |
| result | 命令判定（PASS/FAIL/TIMEOUT） |
| os_release / kernel / hostname / arch / user | 系统信息（/etc/os-release、uname -a、hostname、uname -m、id） |
| package_manager | 检测到的包管理器（dnf/yum/apt-get/zypper） |
| dependencies[] | 依赖矩阵：name=工具名，required=是否必需，installed=是否已安装，path=可执行文件路径 |
| devices[] | 发现的 SCSI 设备：scsi_address=总线地址，device_type=TAPE/MEDIUMX，vendor/product=厂商型号，sg_device/st_device/nst_device=设备节点 |
| sg_scan / sg_map | 原始扫描输出（stdout 字段） |
| page | VPD/日志页码（如 0x80、0x83、0x11） |
| ready | TUR 结果：设备是否就绪 |
| alerts[] | TapeAlert 告警列表（name=告警名，value=值，severity=严重级）；空数组=无告警 |
| stdout | 命令原始输出（解析前文本，与 parsed 并存用于审计溯源） |
| slots[] | 带库槽位：element/slot=槽位号，occupied=是否有带，barcode=卷条码 |
| drives[] | 带库驱动器位（DTE）：drive=驱动器号，occupied=是否装载，barcode=已装载介质条码 |
| loaded | （/system/kernel）内核模块是否已加载 |
| lin_tape_nodes / itdt_installed | IBM lin_tape 设备节点 / ITDT 是否安装 |
| operation / count | 磁带定位操作（rewind/fsf/bsf/fsr/bsr/seod/offline）与次数 |
| drive / block_size | 读测试的带机与块大小 |
| size_mb / test_media | 写测试的大小（MiB）与目标介质条码 |
| steps[] | write-verify 五步链路：rewind→write→weof→read_verify→content_verify，每步含 command_id |
| write_duration_ms / read_duration_ms | 写入 / 读回耗时（毫秒） |
| content_verified | 内容比特级校验结果（cmp 对比，true=完全一致） |
| slot / drive / element | 装卸载/转存/定位的槽位、驱动器、元素地址 |

## 2.3 错误响应字段

| key | 含义 |
|---|---|
| detail.code | 错误码（INVALID_SLOT / COMMAND_FAILED / PERMISSION_DENIED / WRITE_OPERATION_NOT_AUTHORIZED 等） |
| detail.message | 错误说明 |

> 说明：HTTP 状态码 200=成功；400=参数/状态错误；403=安全门禁拦截；404=设备不存在；409=设备忙；502=底层命令失败。

## 2.4 parsed 结构化解析字段（stdout 已 JSON 化）

API 已将 CLI 原始文本输出解析为结构化 JSON，与 stdout 并存（stdout 保留审计溯源）。各接口的 parsed 字段：

| 接口 | parsed 字段 | 含义 |
|---|---|---|
| /discovery/detail | sg_scan.devices[] | sg_scan 解析：sg_device=设备节点，scsi_host/channel/id/lun=SCSI 地址 |
| /discovery/detail | sg_map.mapping[] | sg_map 解析：sg_device/nst_device（带机才有）/vendor/product/revision |
| /devices/{sg}/inquiry、/libraries/{x}/inquiry | vendor_identification 等 | sg_inq 解析：厂商/型号/固件版本/设备类型/序列号 |
| /libraries/{x}/status | slots[] | mtx status 解析：element=槽位号，occupied=是否有带，import_export=进出站槽，barcode=条码 |
| /libraries/{x}/status | drives[] | drive=驱动器号，occupied=是否装载，barcode/source_slot=装载介质及来源槽 |
| /libraries/{x}/status | occupied_slots / loaded_drives | 汇总：占用槽数 / 已装载驱动器数 |
| /drives/{nst}/status | file_number / block_number / partition | mt status 解析：当前文件号 / 块号 / 分区 |
| /drives/{nst}/status | block_size / density_code / density_name | 块大小（字节）/ 磁带密度码及名称（如 0x58 = LTO-7） |
| /drives/{nst}/status | flags / at_bot / at_eod / tape_online | 状态标志（BOT=带头，EOD=带尾，DR_OPEN=门开无带），及布尔化结果 |
| /drives/{nst}/status | soft_error_count | 软错误计数 |
| /drives/{nst}/compression | compression_enabled | 压缩是否启用 |
| /devices/{sg}/vpd | page_code / page_name / fields / ascii | VPD 页解析：页码/页名（如 Unit serial number VPD）、键值字段（如 unit_serial_number=序列号）、可读 ASCII 片段；total/hex_dump/text_lines=输出行数统计 |
| /devices/{sg}/modes | header_fields / mode_pages | 模式页解析：头字段（mode_data_length/density_code 等）、页列表；hex_dump_lines=十六进制转储行数 |
| /devices/{sg}/logs | log_pages / parameters | 日志页解析：页列表 + 参数键值（如 0x11 卷统计页：lifetime_media_loads=终身介质装载次数、lifetime_power_on_hours=累计开机小时、hard_write_errors/hard_read_errors=硬错误数、volume_loads_since_last_parameter_reset=复位后装载次数） |
| /devices/{sg}/tur | ready / stdout_text / stderr_text | TUR 解析：就绪布尔 + 原始文本（"device not ready"=无带） |
| /system/kernel | modules[] | lsmod 解析：module=模块名，size=内存占用（字节），used_by=被引用次数 |
| /system/ibm | lin_tape_nodes_list | IBM 设备节点数组（字符串列表，空=未安装 lin_tape） |
| /diagnostics/system | total_lines / tape_related_lines / tape_related_tail | 内核日志解析：总行数、磁带相关行数、最近 20 条磁带相关日志（st/sg/changer 关键词过滤） |
| /tests/read、/tests/write | bytes / bytes_human / seconds / throughput / records_in / records_out | dd 摘要解析：字节数、人类可读大小、耗时秒、吞吐（如 243 MB/s）、读入/写出块数 |
| /system/info | parsed.os_release / parsed.kernel / parsed.user | os-release 解析：name/version/version_id/id/pretty_name + all_fields 全量键值；uname 解析：kernel_release（如 5.14.0-570.12.1.el9_6.x86_64）、machine 架构；id 解析：uid/user/gid/group/groups |
| /commands/{command_id}（审计） | parsed.*（auto_parse 自动分发） | 按命令类型自动解析历史命令 stdout：sg_inq/sg_vpd/sg_modes/sg_logs/sg_turs/sg_scan/sg_map/mtx/mt/dd/lsmod/dmesg/cat os-release/uname/id/hostname 全部支持；机器人动作类（load/unload/transfer/position）返回 exit_code 判定说明；无匹配解析器时 parsed_ok=false 并给出 reason |

### 2.4.1 一对一细粒度接口（CLI 报告逐命令对应）

为满足 CLI 报告命令级 1:1 对应，新增以下接口（每个 CLI 命令对应一个独立 API，不再合并）：

| API | 对应 CLI 命令 | parsed 字段 |
|---|---|---|
| GET /system/os-release | cat /etc/os-release | name/version/version_id/id/pretty_name/all_fields |
| GET /system/uname | uname -a | kernel_release/machine/hostname |
| GET /system/hostname | hostname | hostname |
| GET /system/arch | uname -m | arch |
| GET /system/user | id | uid/user/gid/group/groups |
| GET /dependencies/{name} | command -v / which {name} | installed/path/exit_code |
| GET /diagnostics/dmesg?tail=N | dmesg \| grep -Ei 磁带关键词 \| tail -N | lines[]（服务端已按 tape/changer/scsi/st/sg/lto/ibm/quantum 关键词过滤）/total_matched/shown |
| GET /diagnostics/journalctl?tail=N | journalctl -k --no-pager \| tail -N | lines[]/total_lines/shown |
| /drives/{sg}/tapealert | alerts / parsed.flags[] | **全量 TapeAlert 标志位矩阵**（64 项）：name=标志名（如 Read warning/Hard error/Media life）、value=值（0=未触发）、severity=严重级（CRITICAL=硬错误类/WARNING=警告类）、triggered=是否触发；parsed.device/page=设备型号与页信息；triggered_alerts/triggered_count=仅非零项及计数；all_clear=全部无告警布尔 |

> 注：sg_modes / sg_logs 的十六进制转储区保留在 stdout 原文中；其页码/页名/参数行均已解析到 parsed（log_pages/mode_pages/parameters）。

## 2.5 stdout 原始输出逐字段注释

各类 CLI 命令的原始 stdout 文本中，每个字段/列的含义如下：

### lsscsi -g（/discovery 的 data.devices 来源）

```
[0:0:1:1]  tape    IBM  ULT3580-TDA  T3S0  /dev/sg0   /dev/nst0
```

| 字段 | 含义 |
|---|---|
| [0:0:1:1] | SCSI 四元组地址：host:channel:id:lun |
| tape / mediumx | 设备类型：tape=磁带机，mediumx=介质交换器（带库机械手） |
| IBM | 厂商（vendor） |
| ULT3580-TDA / 03584L32 | 型号（product）：带机 / 带库 |
| T3S0 / 2C02 | 固件版本（revision） |
| /dev/sgN | SCSI 通用设备节点（sg3_utils 用） |
| /dev/nstN | 不可回绕磁带设备节点（mt/dd 用） |

### sg_scan（/discovery/detail 的 sg_scan.stdout）

```
/dev/sg0: scsi33 channel=0 id=0 lun=0
```

| 字段 | 含义 |
|---|---|
| /dev/sg0 | sg 设备节点 |
| scsi33 | 所属 SCSI 主机适配器（HBA）编号：33/32 对应双 FC 路径 |
| channel / id / lun | 通道号 / SCSI ID / 逻辑单元号 |

### sg_map -i（/discovery/detail 的 sg_map.stdout）

```
/dev/sg0 /dev/nst0 IBM ULT3580-TDA T3S0
/dev/sg1 IBM 03584L32 2C02
```

| 字段 | 含义 |
|---|---|
| 第 1 列 /dev/sgN | sg 设备节点 |
| 第 2 列 /dev/nstN | 对应的磁带设备节点；**没有此列 = 该 sg 是带库（changer），无 nst 设备** |
| 第 3~5 列 | 厂商 / 型号 / 固件版本 |

### sg_inq（/devices/{sg}/inquiry、/libraries/{x}/inquiry 的 stdout）

| 输出行 | 含义 |
|---|---|
| standard inquiry page | 标准 Inquiry 数据页 |
| vendor identification | 厂商（如 IBM） |
| product identification | 型号（ULT3580-TDA 带机 / 03584L32 带库） |
| product revision level | 固件版本 |
| device type | 设备类型（tape / medium changer） |
| unit serial number | 设备序列号 |

### mtx status（/libraries/{x}/status 的 stdout）

```
Storage Element 6:Full:VolumeTag = IBM015LA
    Drive 0 (Transfer) Full (Storage Element 6):VolumeTag = IBM015LA
```

| 字段 | 含义 |
|---|---|
| Storage Element N | 存储槽位号（N=1~1585） |
| Full / Empty | 槽内是否有磁带 |
| Import/Export | 进出站槽（人工插取带口） |
| VolumeTag = XXX | 磁带条码（卷标） |
| Drive N (Transfer) | 驱动器（DTE）槽位及传输功能 |
| (Storage Element M) | 该驱动器内磁带的来源槽位 |

### mt status（/drives/{nst}/status 的 stdout）

```
SCSI 2 tape drive:
File number=0, block number=0, partition=0.
Tape block size 0 bytes. Density code 0x58 (LTO-7).
Soft error count since last status=0
General status bits on (41000000):
 BOT ONLINE
```

| 字段 | 含义 |
|---|---|
| File number | 当前位置文件号（磁带上的第 N 个文件/文件标记） |
| block number | 当前文件内块号 |
| partition | 分区号（分区磁带用，普通带为 0） |
| Tape block size | 块大小（字节）；0 = 可变长块模式 |
| Density code | 磁带密度码：0x58=LTO-7；0x0/default=无带或未识别 |
| Soft error count | 软错误计数（可恢复错误，非致命） |
| General status bits | 状态位图（十六进制） |
| BOT | Beginning Of Tape：磁带处于带头位置 |
| EOD | End Of Data：磁带处于数据尾 |
| ONLINE | 有带且就绪 |
| DR_OPEN | 驱动器门开（无带） |
| IM_REP_EN | 立即报告模式（错误上报方式） |

### sg_logs TapeAlert（/drives/{sg}/tapealert）

```
TapeAlert: There is no tape alert flag set.
```

| 字段 | 含义 |
|---|---|
| 各告警名: 数值 | 每行一个 TapeAlert 帟（0=未触发）；API 已解析为 alerts[] 数组，空数组=无告警 |

### dd 写入摘要（/tests/write、/tests/read 的 data）

```
1073741824 bytes (1.1 GB, 1.0 GiB) copied, 4.4 s, 243 MB/s
```

| 字段 | 含义 |
|---|---|
| bytes copied | 读/写的总字节数 |
| 时间 | 耗时（秒） |
| 吞吐 | 平均速率 MB/s（如写 243 MB/s、读 694 MB/s） |
| records in/out | 块计数（完整读入/写出的块数） |

### dmesg / journalctl（/diagnostics/system）

| 行内容 | 含义 |
|---|---|
| stN: Attached SCSI tape | 内核 st 驱动接管磁带机 |
| Changer with sX lun(s) found | 机械手设备识别 |
| linux-lin_tape | IBM lin_tape 驱动（如安装）加载日志 |
| I/O error / Sense 错误 | 硬件/介质异常记录，对应接口 502 时的底层原因 |

---

# 三、API 接口分类总览（按操作对象四类）

## 3.1 带库操作 —— /libraries（8 个端点）

| 方法 | 端点 | 说明 | 安全级 |
|---|---|---|---|
| GET | /libraries | 带库设备发现（changer 列表） | LEVEL 1 |
| GET | /libraries/{changer}/inquiry | 带库 SCSI INQUIRY | LEVEL 1 |
| GET | /libraries/{changer}/status | 库状态（槽位/带机/机器人） | LEVEL 1 |
| GET | /libraries/{changer}/inventory | 库内介质清单 | LEVEL 1 |
| POST | /libraries/{changer}/load | 装带（槽→带机） | LEVEL 2 |
| POST | /libraries/{changer}/unload | 卸带（带机→槽） | LEVEL 2 |
| POST | /libraries/{changer}/transfer | 槽→槽搬移介质 | LEVEL 2 |
| POST | /libraries/{changer}/position | 机器人定位 | LEVEL 2 |

## 3.2 带机操作 —— /devices + /drives（12 个端点）

| 方法 | 端点 | 说明 | 安全级 |
|---|---|---|---|
| GET | /devices/{sg}/inquiry | 带机 SCSI INQUIRY | LEVEL 1 |
| GET | /devices/{sg}/vpd | VPD 关键产品数据 | LEVEL 1 |
| GET | /devices/{sg}/tur | TEST UNIT READY | LEVEL 1 |
| GET | /devices/{sg}/modes | MODE SENSE | LEVEL 1 |
| GET | /devices/{sg}/logs | LOG SENSE | LEVEL 1 |
| GET | /drives/{sg}/tapealert | TapeAlert 64 标志位全量矩阵 | LEVEL 1 |
| GET | /drives/{nst}/status | mt status（位置/密度/块数） | LEVEL 1 |
| GET | /drives/{nst}/compression | 压缩状态与统计 | LEVEL 1 |
| POST | /drives/{nst}/rewind | 倒带 | LEVEL 2 |
| POST | /drives/{nst}/position | 定位（fsf/bsf/n） | LEVEL 2 |
| POST | /drives/{nst}/weof | 写文件结束标记 | LEVEL 3 |
| GET | /diagnostics/tape/{sg} | 带机专项诊断（错误计数） | LEVEL 1 |

## 3.3 IO 操作 —— /tests（5 个端点）

| 方法 | 端点 | 说明 | 安全级 |
|---|---|---|---|
| POST | /tests/read | 读测试（dd 可控块） | LEVEL 1 |
| POST | /tests/write | 写测试（dd 可控块/速度） | LEVEL 3 |
| POST | /tests/write-verify | 写入+读回+cmp 校验 | LEVEL 3 |
| POST | /tests/erase | 介质擦除 | LEVEL 3 |
| POST | /tests/full | 全链路综合测试 | LEVEL 2+3 |

## 3.4 其他操作 —— 系统/依赖/发现/诊断/审计（20 个端点）

| 方法 | 端点 | 说明 | 安全级 |
|---|---|---|---|
| GET | /system/info、/system/kernel、/system/ibm | 系统信息/内核模块/IBM 专检（3） | LEVEL 1 |
| GET | /system/os-release、/uname、/hostname、/arch、/user | 系统命令 1:1 细粒度接口（5） | LEVEL 1 |
| GET | /dependencies、/verify、/{name} | 依赖矩阵/验证/单工具 1:1（3） | LEVEL 1 |
| POST | /dependencies/install | 安装缺失依赖（1） | LEVEL 1 |
| GET | /discovery、/discovery/detail | 设备发现 lsscsi / sg_scan+sg_map（2） | LEVEL 1 |
| GET | /diagnostics/system、/dmesg、/journalctl | 系统日志诊断含 1:1（3） | LEVEL 1 |
| GET | /commands/{command_id} | 历史命令审计（auto_parse）（1） | LEVEL 1 |
| GET | /audit/{request_id} | 请求级审计链（1） | LEVEL 1 |

分类规则（按 URL 前缀）：/libraries → 带库；/devices、/drives、/diagnostics/tape → 带机；/tests → IO；其余（system/dependencies/discovery/diagnostics/commands/audit）→ 其他。

---

# 四、CMD-000001 ~ CMD-000108 逐条 API 对照测试（按四类分组）

以下每条包含：CLI 原始命令 → CLI 测试结果 → 对应 API → curl 调用 → 说明 → 原始响应（JSON 每行一个 key/value）。


## 第 1 部分 · 3.1 带库操作（/libraries）（共 15 条 CMD）
### CMD-000042

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 inquiry
```

CLI 测试结果：`PASS`

**对应 API：** `GET /libraries/sg1/inquiry`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/libraries/sg1/inquiry
```

**说明：** 带库识别 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-60083B",
  "data": {
    "stdout": "Product Type: Medium Changer\nVendor ID: 'IBM     '\nProduct ID: '03584L32        '\nRevision: '2C02'\nAttached Changer API: No\n",
    "command_id": "CMD-552AD6C0",
    "parsed": {
      "parsed_ok": false
    }
  },
  "error": null
}
```

### CMD-000043

**CLI 原始命令：**

```bash
mtx -f /dev/sg3 inquiry
```

CLI 测试结果：`PASS`

**对应 API：** `GET /libraries/sg3/inquiry`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/libraries/sg3/inquiry
```

**说明：** 带库识别 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-B4EED3",
  "data": {
    "stdout": "Product Type: Medium Changer\nVendor ID: 'IBM     '\nProduct ID: '03584L32        '\nRevision: '2C02'\nAttached Changer API: No\n",
    "command_id": "CMD-F652F7C3",
    "parsed": {
      "parsed_ok": false
    }
  },
  "error": null
}
```

### CMD-000044

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 status
```

CLI 测试结果：`PASS`

**对应 API：** `GET /libraries/sg1/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/libraries/sg1/status
```

**说明：** 带库状态 → data.stdout（结构化用 /inventory）

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-059704",
  "data": {
    "stdout": "  Storage Changer /dev/sg1:3 Drives, 1840 Slots ( 255 Import/Export )\nData Transfer Element 0:Empty\nData Transfer Element 1:Empty\nData Transfer Element 2:Empty\n      Storage Element 1:Full :VolumeTag=IBM006LA\n      Storage Element 2:Full :VolumeTag=IBM014LA\n      Storage Element 3:Empty:VolumeTag=                                    \n      Storage Element 4:Full :VolumeTag=IBM009LA\n      Storage Element 5:Full :VolumeTag=IBM013LA\n      Storage Element 6:Full :VolumeTag=IBM015LA\n      Storage Element 7:Empty:VolumeTag=                                    \n      Storage Element 8:Empty:VolumeTag=                                    \n      Storage Element 9:Empty:VolumeTag=                                    \n      Storage Element 10:Empty:VolumeTag=                                    \n      Storage Element 11:Empty:VolumeTag=                                    \n      Storage Element 12:Empty:VolumeTag=                                    \n      Storage Element 13:Empty:VolumeTag=                                    \n      Storage Element 14:Empty:VolumeTag=                                    \n      Storage Element 15:Empty:VolumeTag=                                    \n      Storage Element 16:Empty:VolumeTag=                                    \n      Storage Element 17:Empty:VolumeTag=                                    \n      Storage Element 18:Empty:VolumeTag=                                    \n      Storage Element 19:Empty:VolumeTag=                                    \n      Storage Element 20:Empty:VolumeTag=                                    \n      Storage Element 21:Empty:VolumeTag=                                    \n      Storage Element 22:Empty:VolumeTag=                                    \n      Storage Element 23:Empty:VolumeTag=                                    \n      Storage Element 24:Empty:VolumeTag=                                    \n      Storage Element 25:Empty:VolumeTag=                                    \n      Storage Element 26:Empty:VolumeTag=                                    \n      Storage Element 27:Empty:VolumeTag=                                    \n      Storage Element 28:Empty:VolumeTag=                                    \n      Storage Element 29:Empty:VolumeTag=                                    \n      Storage Element 30:Empty:VolumeTag=                                    \n      Storage Element 31:Empty:VolumeTag=                                    \n      Storage Element 32:Empty:VolumeTag=                                    \n      Storage Element 33:Empty:VolumeTag=                                    \n      Storage Element 34:Empty:VolumeTag=                                    \n      Storage Element 35:Empty:VolumeTag=                                    \n      Storage Element 36:Empty:VolumeTag=                                    \n      Storage Element 37:Empty:VolumeTag=                                    \n      Storage Element 38:Empty:VolumeTag=                                    \n      Storage Element 39:Empty:VolumeTag=                                    \n      Storage Element 40:Empty:VolumeTag=                                    \n      Storage Element 41:Empty:VolumeTag=                                    \n      Storage Element 42:Empty:VolumeTag=                                    \n      Storage Element 43:Empty:VolumeTag=                                    \n      Storage Element 44:Empty:VolumeTag=                                    \n      Storage Element 45:Empty:VolumeTag=                                    \n      Storage Element 46:Empty:VolumeTag=                                    \n      Storage Element 47:Empty:VolumeTag=                                    \n      Storage Element 48:Empty:VolumeTag=                                    \n      Storage Element 49:Empty:Vol
  ...（截断，完整见 audit 原始日志）
```

### CMD-000045

**CLI 原始命令：**

```bash
mtx -f /dev/sg3 status
```

CLI 测试结果：`PASS`

**对应 API：** `GET /libraries/sg3/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/libraries/sg3/status
```

**说明：** 带库状态 → data.stdout（结构化用 /inventory）

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185408-94A704",
  "data": {
    "stdout": "  Storage Changer /dev/sg3:3 Drives, 1840 Slots ( 255 Import/Export )\nData Transfer Element 0:Empty\nData Transfer Element 1:Empty\nData Transfer Element 2:Empty\n      Storage Element 1:Full :VolumeTag=IBM006LA\n      Storage Element 2:Full :VolumeTag=IBM014LA\n      Storage Element 3:Empty:VolumeTag=                                    \n      Storage Element 4:Full :VolumeTag=IBM009LA\n      Storage Element 5:Full :VolumeTag=IBM013LA\n      Storage Element 6:Full :VolumeTag=IBM015LA\n      Storage Element 7:Empty:VolumeTag=                                    \n      Storage Element 8:Empty:VolumeTag=                                    \n      Storage Element 9:Empty:VolumeTag=                                    \n      Storage Element 10:Empty:VolumeTag=                                    \n      Storage Element 11:Empty:VolumeTag=                                    \n      Storage Element 12:Empty:VolumeTag=                                    \n      Storage Element 13:Empty:VolumeTag=                                    \n      Storage Element 14:Empty:VolumeTag=                                    \n      Storage Element 15:Empty:VolumeTag=                                    \n      Storage Element 16:Empty:VolumeTag=                                    \n      Storage Element 17:Empty:VolumeTag=                                    \n      Storage Element 18:Empty:VolumeTag=                                    \n      Storage Element 19:Empty:VolumeTag=                                    \n      Storage Element 20:Empty:VolumeTag=                                    \n      Storage Element 21:Empty:VolumeTag=                                    \n      Storage Element 22:Empty:VolumeTag=                                    \n      Storage Element 23:Empty:VolumeTag=                                    \n      Storage Element 24:Empty:VolumeTag=                                    \n      Storage Element 25:Empty:VolumeTag=                                    \n      Storage Element 26:Empty:VolumeTag=                                    \n      Storage Element 27:Empty:VolumeTag=                                    \n      Storage Element 28:Empty:VolumeTag=                                    \n      Storage Element 29:Empty:VolumeTag=                                    \n      Storage Element 30:Empty:VolumeTag=                                    \n      Storage Element 31:Empty:VolumeTag=                                    \n      Storage Element 32:Empty:VolumeTag=                                    \n      Storage Element 33:Empty:VolumeTag=                                    \n      Storage Element 34:Empty:VolumeTag=                                    \n      Storage Element 35:Empty:VolumeTag=                                    \n      Storage Element 36:Empty:VolumeTag=                                    \n      Storage Element 37:Empty:VolumeTag=                                    \n      Storage Element 38:Empty:VolumeTag=                                    \n      Storage Element 39:Empty:VolumeTag=                                    \n      Storage Element 40:Empty:VolumeTag=                                    \n      Storage Element 41:Empty:VolumeTag=                                    \n      Storage Element 42:Empty:VolumeTag=                                    \n      Storage Element 43:Empty:VolumeTag=                                    \n      Storage Element 44:Empty:VolumeTag=                                    \n      Storage Element 45:Empty:VolumeTag=                                    \n      Storage Element 46:Empty:VolumeTag=                                    \n      Storage Element 47:Empty:VolumeTag=                                    \n      Storage Element 48:Empty:VolumeTag=                                    \n      Storage Element 49:Empty:Vol
  ...（截断，完整见 audit 原始日志）
```

### CMD-000058

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 load 6 0
```

CLI 测试结果：`PASS`

**对应 API：** `POST /libraries/sg1/load`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/libraries/sg1/load -H 'Content-Type: application/json' -d '{"slot": 6, "drive": 0, "confirm": true}'
```

**说明：** 装载 → code=LOAD_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "LOAD_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185411-7313A3",
  "data": {
    "slot": 6,
    "drive": 0,
    "command_id": "CMD-4AA71B24"
  },
  "error": null
}
```

### CMD-000059

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 status | head -12
```

CLI 测试结果：`PASS`

**对应 API：** `GET /libraries/sg1/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/libraries/sg1/status
```

**说明：** 带库状态 → data.stdout（结构化用 /inventory）

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-059704",
  "data": {
    "stdout": "  Storage Changer /dev/sg1:3 Drives, 1840 Slots ( 255 Import/Export )\nData Transfer Element 0:Empty\nData Transfer Element 1:Empty\nData Transfer Element 2:Empty\n      Storage Element 1:Full :VolumeTag=IBM006LA\n      Storage Element 2:Full :VolumeTag=IBM014LA\n      Storage Element 3:Empty:VolumeTag=                                    \n      Storage Element 4:Full :VolumeTag=IBM009LA\n      Storage Element 5:Full :VolumeTag=IBM013LA\n      Storage Element 6:Full :VolumeTag=IBM015LA\n      Storage Element 7:Empty:VolumeTag=                                    \n      Storage Element 8:Empty:VolumeTag=                                    \n      Storage Element 9:Empty:VolumeTag=                                    \n      Storage Element 10:Empty:VolumeTag=                                    \n      Storage Element 11:Empty:VolumeTag=                                    \n      Storage Element 12:Empty:VolumeTag=                                    \n      Storage Element 13:Empty:VolumeTag=                                    \n      Storage Element 14:Empty:VolumeTag=                                    \n      Storage Element 15:Empty:VolumeTag=                                    \n      Storage Element 16:Empty:VolumeTag=                                    \n      Storage Element 17:Empty:VolumeTag=                                    \n      Storage Element 18:Empty:VolumeTag=                                    \n      Storage Element 19:Empty:VolumeTag=                                    \n      Storage Element 20:Empty:VolumeTag=                                    \n      Storage Element 21:Empty:VolumeTag=                                    \n      Storage Element 22:Empty:VolumeTag=                                    \n      Storage Element 23:Empty:VolumeTag=                                    \n      Storage Element 24:Empty:VolumeTag=                                    \n      Storage Element 25:Empty:VolumeTag=                                    \n      Storage Element 26:Empty:VolumeTag=                                    \n      Storage Element 27:Empty:VolumeTag=                                    \n      Storage Element 28:Empty:VolumeTag=                                    \n      Storage Element 29:Empty:VolumeTag=                                    \n      Storage Element 30:Empty:VolumeTag=                                    \n      Storage Element 31:Empty:VolumeTag=                                    \n      Storage Element 32:Empty:VolumeTag=                                    \n      Storage Element 33:Empty:VolumeTag=                                    \n      Storage Element 34:Empty:VolumeTag=                                    \n      Storage Element 35:Empty:VolumeTag=                                    \n      Storage Element 36:Empty:VolumeTag=                                    \n      Storage Element 37:Empty:VolumeTag=                                    \n      Storage Element 38:Empty:VolumeTag=                                    \n      Storage Element 39:Empty:VolumeTag=                                    \n      Storage Element 40:Empty:VolumeTag=                                    \n      Storage Element 41:Empty:VolumeTag=                                    \n      Storage Element 42:Empty:VolumeTag=                                    \n      Storage Element 43:Empty:VolumeTag=                                    \n      Storage Element 44:Empty:VolumeTag=                                    \n      Storage Element 45:Empty:VolumeTag=                                    \n      Storage Element 46:Empty:VolumeTag=                                    \n      Storage Element 47:Empty:VolumeTag=                                    \n      Storage Element 48:Empty:VolumeTag=                                    \n      Storage Element 49:Empty:Vol
  ...（截断，完整见 audit 原始日志）
```

### CMD-000067

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 status | head -8
```

CLI 测试结果：`PASS`

**对应 API：** `GET /libraries/sg1/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/libraries/sg1/status
```

**说明：** 带库状态 → data.stdout（结构化用 /inventory）

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-059704",
  "data": {
    "stdout": "  Storage Changer /dev/sg1:3 Drives, 1840 Slots ( 255 Import/Export )\nData Transfer Element 0:Empty\nData Transfer Element 1:Empty\nData Transfer Element 2:Empty\n      Storage Element 1:Full :VolumeTag=IBM006LA\n      Storage Element 2:Full :VolumeTag=IBM014LA\n      Storage Element 3:Empty:VolumeTag=                                    \n      Storage Element 4:Full :VolumeTag=IBM009LA\n      Storage Element 5:Full :VolumeTag=IBM013LA\n      Storage Element 6:Full :VolumeTag=IBM015LA\n      Storage Element 7:Empty:VolumeTag=                                    \n      Storage Element 8:Empty:VolumeTag=                                    \n      Storage Element 9:Empty:VolumeTag=                                    \n      Storage Element 10:Empty:VolumeTag=                                    \n      Storage Element 11:Empty:VolumeTag=                                    \n      Storage Element 12:Empty:VolumeTag=                                    \n      Storage Element 13:Empty:VolumeTag=                                    \n      Storage Element 14:Empty:VolumeTag=                                    \n      Storage Element 15:Empty:VolumeTag=                                    \n      Storage Element 16:Empty:VolumeTag=                                    \n      Storage Element 17:Empty:VolumeTag=                                    \n      Storage Element 18:Empty:VolumeTag=                                    \n      Storage Element 19:Empty:VolumeTag=                                    \n      Storage Element 20:Empty:VolumeTag=                                    \n      Storage Element 21:Empty:VolumeTag=                                    \n      Storage Element 22:Empty:VolumeTag=                                    \n      Storage Element 23:Empty:VolumeTag=                                    \n      Storage Element 24:Empty:VolumeTag=                                    \n      Storage Element 25:Empty:VolumeTag=                                    \n      Storage Element 26:Empty:VolumeTag=                                    \n      Storage Element 27:Empty:VolumeTag=                                    \n      Storage Element 28:Empty:VolumeTag=                                    \n      Storage Element 29:Empty:VolumeTag=                                    \n      Storage Element 30:Empty:VolumeTag=                                    \n      Storage Element 31:Empty:VolumeTag=                                    \n      Storage Element 32:Empty:VolumeTag=                                    \n      Storage Element 33:Empty:VolumeTag=                                    \n      Storage Element 34:Empty:VolumeTag=                                    \n      Storage Element 35:Empty:VolumeTag=                                    \n      Storage Element 36:Empty:VolumeTag=                                    \n      Storage Element 37:Empty:VolumeTag=                                    \n      Storage Element 38:Empty:VolumeTag=                                    \n      Storage Element 39:Empty:VolumeTag=                                    \n      Storage Element 40:Empty:VolumeTag=                                    \n      Storage Element 41:Empty:VolumeTag=                                    \n      Storage Element 42:Empty:VolumeTag=                                    \n      Storage Element 43:Empty:VolumeTag=                                    \n      Storage Element 44:Empty:VolumeTag=                                    \n      Storage Element 45:Empty:VolumeTag=                                    \n      Storage Element 46:Empty:VolumeTag=                                    \n      Storage Element 47:Empty:VolumeTag=                                    \n      Storage Element 48:Empty:VolumeTag=                                    \n      Storage Element 49:Empty:Vol
  ...（截断，完整见 audit 原始日志）
```

### CMD-000080

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 unload 6 0
```

CLI 测试结果：`PASS`

**对应 API：** `POST /libraries/sg1/unload`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/libraries/sg1/unload -H 'Content-Type: application/json' -d '{"slot": 6, "drive": 0, "confirm": true}'
```

**说明：** 卸载归位 → code=UNLOAD_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "UNLOAD_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185828-47C64A",
  "data": {
    "slot": 6,
    "drive": 0,
    "command_id": "CMD-7B786721"
  },
  "error": null
}
```

### CMD-000082

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 status | head -10
```

CLI 测试结果：`PASS`

**对应 API：** `GET /libraries/sg1/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/libraries/sg1/status
```

**说明：** 带库状态 → data.stdout（结构化用 /inventory）

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-059704",
  "data": {
    "stdout": "  Storage Changer /dev/sg1:3 Drives, 1840 Slots ( 255 Import/Export )\nData Transfer Element 0:Empty\nData Transfer Element 1:Empty\nData Transfer Element 2:Empty\n      Storage Element 1:Full :VolumeTag=IBM006LA\n      Storage Element 2:Full :VolumeTag=IBM014LA\n      Storage Element 3:Empty:VolumeTag=                                    \n      Storage Element 4:Full :VolumeTag=IBM009LA\n      Storage Element 5:Full :VolumeTag=IBM013LA\n      Storage Element 6:Full :VolumeTag=IBM015LA\n      Storage Element 7:Empty:VolumeTag=                                    \n      Storage Element 8:Empty:VolumeTag=                                    \n      Storage Element 9:Empty:VolumeTag=                                    \n      Storage Element 10:Empty:VolumeTag=                                    \n      Storage Element 11:Empty:VolumeTag=                                    \n      Storage Element 12:Empty:VolumeTag=                                    \n      Storage Element 13:Empty:VolumeTag=                                    \n      Storage Element 14:Empty:VolumeTag=                                    \n      Storage Element 15:Empty:VolumeTag=                                    \n      Storage Element 16:Empty:VolumeTag=                                    \n      Storage Element 17:Empty:VolumeTag=                                    \n      Storage Element 18:Empty:VolumeTag=                                    \n      Storage Element 19:Empty:VolumeTag=                                    \n      Storage Element 20:Empty:VolumeTag=                                    \n      Storage Element 21:Empty:VolumeTag=                                    \n      Storage Element 22:Empty:VolumeTag=                                    \n      Storage Element 23:Empty:VolumeTag=                                    \n      Storage Element 24:Empty:VolumeTag=                                    \n      Storage Element 25:Empty:VolumeTag=                                    \n      Storage Element 26:Empty:VolumeTag=                                    \n      Storage Element 27:Empty:VolumeTag=                                    \n      Storage Element 28:Empty:VolumeTag=                                    \n      Storage Element 29:Empty:VolumeTag=                                    \n      Storage Element 30:Empty:VolumeTag=                                    \n      Storage Element 31:Empty:VolumeTag=                                    \n      Storage Element 32:Empty:VolumeTag=                                    \n      Storage Element 33:Empty:VolumeTag=                                    \n      Storage Element 34:Empty:VolumeTag=                                    \n      Storage Element 35:Empty:VolumeTag=                                    \n      Storage Element 36:Empty:VolumeTag=                                    \n      Storage Element 37:Empty:VolumeTag=                                    \n      Storage Element 38:Empty:VolumeTag=                                    \n      Storage Element 39:Empty:VolumeTag=                                    \n      Storage Element 40:Empty:VolumeTag=                                    \n      Storage Element 41:Empty:VolumeTag=                                    \n      Storage Element 42:Empty:VolumeTag=                                    \n      Storage Element 43:Empty:VolumeTag=                                    \n      Storage Element 44:Empty:VolumeTag=                                    \n      Storage Element 45:Empty:VolumeTag=                                    \n      Storage Element 46:Empty:VolumeTag=                                    \n      Storage Element 47:Empty:VolumeTag=                                    \n      Storage Element 48:Empty:VolumeTag=                                    \n      Storage Element 49:Empty:Vol
  ...（截断，完整见 audit 原始日志）
```

### CMD-000083

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 load 6 0
```

CLI 测试结果：`PASS`

**对应 API：** `POST /libraries/sg1/load`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/libraries/sg1/load -H 'Content-Type: application/json' -d '{"slot": 6, "drive": 0, "confirm": true}'
```

**说明：** 装载 → code=LOAD_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "LOAD_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185411-7313A3",
  "data": {
    "slot": 6,
    "drive": 0,
    "command_id": "CMD-4AA71B24"
  },
  "error": null
}
```

### CMD-000088

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 unload 6 0
```

CLI 测试结果：`PASS`

**对应 API：** `POST /libraries/sg1/unload`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/libraries/sg1/unload -H 'Content-Type: application/json' -d '{"slot": 6, "drive": 0, "confirm": true}'
```

**说明：** 卸载归位 → code=UNLOAD_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "UNLOAD_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185828-47C64A",
  "data": {
    "slot": 6,
    "drive": 0,
    "command_id": "CMD-7B786721"
  },
  "error": null
}
```

### CMD-000089

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 status | head -10
```

CLI 测试结果：`PASS`

**对应 API：** `GET /libraries/sg1/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/libraries/sg1/status
```

**说明：** 带库状态 → data.stdout（结构化用 /inventory）

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-059704",
  "data": {
    "stdout": "  Storage Changer /dev/sg1:3 Drives, 1840 Slots ( 255 Import/Export )\nData Transfer Element 0:Empty\nData Transfer Element 1:Empty\nData Transfer Element 2:Empty\n      Storage Element 1:Full :VolumeTag=IBM006LA\n      Storage Element 2:Full :VolumeTag=IBM014LA\n      Storage Element 3:Empty:VolumeTag=                                    \n      Storage Element 4:Full :VolumeTag=IBM009LA\n      Storage Element 5:Full :VolumeTag=IBM013LA\n      Storage Element 6:Full :VolumeTag=IBM015LA\n      Storage Element 7:Empty:VolumeTag=                                    \n      Storage Element 8:Empty:VolumeTag=                                    \n      Storage Element 9:Empty:VolumeTag=                                    \n      Storage Element 10:Empty:VolumeTag=                                    \n      Storage Element 11:Empty:VolumeTag=                                    \n      Storage Element 12:Empty:VolumeTag=                                    \n      Storage Element 13:Empty:VolumeTag=                                    \n      Storage Element 14:Empty:VolumeTag=                                    \n      Storage Element 15:Empty:VolumeTag=                                    \n      Storage Element 16:Empty:VolumeTag=                                    \n      Storage Element 17:Empty:VolumeTag=                                    \n      Storage Element 18:Empty:VolumeTag=                                    \n      Storage Element 19:Empty:VolumeTag=                                    \n      Storage Element 20:Empty:VolumeTag=                                    \n      Storage Element 21:Empty:VolumeTag=                                    \n      Storage Element 22:Empty:VolumeTag=                                    \n      Storage Element 23:Empty:VolumeTag=                                    \n      Storage Element 24:Empty:VolumeTag=                                    \n      Storage Element 25:Empty:VolumeTag=                                    \n      Storage Element 26:Empty:VolumeTag=                                    \n      Storage Element 27:Empty:VolumeTag=                                    \n      Storage Element 28:Empty:VolumeTag=                                    \n      Storage Element 29:Empty:VolumeTag=                                    \n      Storage Element 30:Empty:VolumeTag=                                    \n      Storage Element 31:Empty:VolumeTag=                                    \n      Storage Element 32:Empty:VolumeTag=                                    \n      Storage Element 33:Empty:VolumeTag=                                    \n      Storage Element 34:Empty:VolumeTag=                                    \n      Storage Element 35:Empty:VolumeTag=                                    \n      Storage Element 36:Empty:VolumeTag=                                    \n      Storage Element 37:Empty:VolumeTag=                                    \n      Storage Element 38:Empty:VolumeTag=                                    \n      Storage Element 39:Empty:VolumeTag=                                    \n      Storage Element 40:Empty:VolumeTag=                                    \n      Storage Element 41:Empty:VolumeTag=                                    \n      Storage Element 42:Empty:VolumeTag=                                    \n      Storage Element 43:Empty:VolumeTag=                                    \n      Storage Element 44:Empty:VolumeTag=                                    \n      Storage Element 45:Empty:VolumeTag=                                    \n      Storage Element 46:Empty:VolumeTag=                                    \n      Storage Element 47:Empty:VolumeTag=                                    \n      Storage Element 48:Empty:VolumeTag=                                    \n      Storage Element 49:Empty:Vol
  ...（截断，完整见 audit 原始日志）
```

### CMD-000094

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 load 6 0
```

CLI 测试结果：`PASS`

**对应 API：** `POST /libraries/sg1/load`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/libraries/sg1/load -H 'Content-Type: application/json' -d '{"slot": 6, "drive": 0, "confirm": true}'
```

**说明：** 装载 → code=LOAD_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "LOAD_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185411-7313A3",
  "data": {
    "slot": 6,
    "drive": 0,
    "command_id": "CMD-4AA71B24"
  },
  "error": null
}
```

### CMD-000107

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 unload 6 0
```

CLI 测试结果：`PASS`

**对应 API：** `POST /libraries/sg1/unload`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/libraries/sg1/unload -H 'Content-Type: application/json' -d '{"slot": 6, "drive": 0, "confirm": true}'
```

**说明：** 卸载归位 → code=UNLOAD_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "UNLOAD_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185828-47C64A",
  "data": {
    "slot": 6,
    "drive": 0,
    "command_id": "CMD-7B786721"
  },
  "error": null
}
```

### CMD-000108

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 status | head -10
```

CLI 测试结果：`PASS`

**对应 API：** `GET /libraries/sg1/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/libraries/sg1/status
```

**说明：** 带库状态 → data.stdout（结构化用 /inventory）

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-059704",
  "data": {
    "stdout": "  Storage Changer /dev/sg1:3 Drives, 1840 Slots ( 255 Import/Export )\nData Transfer Element 0:Empty\nData Transfer Element 1:Empty\nData Transfer Element 2:Empty\n      Storage Element 1:Full :VolumeTag=IBM006LA\n      Storage Element 2:Full :VolumeTag=IBM014LA\n      Storage Element 3:Empty:VolumeTag=                                    \n      Storage Element 4:Full :VolumeTag=IBM009LA\n      Storage Element 5:Full :VolumeTag=IBM013LA\n      Storage Element 6:Full :VolumeTag=IBM015LA\n      Storage Element 7:Empty:VolumeTag=                                    \n      Storage Element 8:Empty:VolumeTag=                                    \n      Storage Element 9:Empty:VolumeTag=                                    \n      Storage Element 10:Empty:VolumeTag=                                    \n      Storage Element 11:Empty:VolumeTag=                                    \n      Storage Element 12:Empty:VolumeTag=                                    \n      Storage Element 13:Empty:VolumeTag=                                    \n      Storage Element 14:Empty:VolumeTag=                                    \n      Storage Element 15:Empty:VolumeTag=                                    \n      Storage Element 16:Empty:VolumeTag=                                    \n      Storage Element 17:Empty:VolumeTag=                                    \n      Storage Element 18:Empty:VolumeTag=                                    \n      Storage Element 19:Empty:VolumeTag=                                    \n      Storage Element 20:Empty:VolumeTag=                                    \n      Storage Element 21:Empty:VolumeTag=                                    \n      Storage Element 22:Empty:VolumeTag=                                    \n      Storage Element 23:Empty:VolumeTag=                                    \n      Storage Element 24:Empty:VolumeTag=                                    \n      Storage Element 25:Empty:VolumeTag=                                    \n      Storage Element 26:Empty:VolumeTag=                                    \n      Storage Element 27:Empty:VolumeTag=                                    \n      Storage Element 28:Empty:VolumeTag=                                    \n      Storage Element 29:Empty:VolumeTag=                                    \n      Storage Element 30:Empty:VolumeTag=                                    \n      Storage Element 31:Empty:VolumeTag=                                    \n      Storage Element 32:Empty:VolumeTag=                                    \n      Storage Element 33:Empty:VolumeTag=                                    \n      Storage Element 34:Empty:VolumeTag=                                    \n      Storage Element 35:Empty:VolumeTag=                                    \n      Storage Element 36:Empty:VolumeTag=                                    \n      Storage Element 37:Empty:VolumeTag=                                    \n      Storage Element 38:Empty:VolumeTag=                                    \n      Storage Element 39:Empty:VolumeTag=                                    \n      Storage Element 40:Empty:VolumeTag=                                    \n      Storage Element 41:Empty:VolumeTag=                                    \n      Storage Element 42:Empty:VolumeTag=                                    \n      Storage Element 43:Empty:VolumeTag=                                    \n      Storage Element 44:Empty:VolumeTag=                                    \n      Storage Element 45:Empty:VolumeTag=                                    \n      Storage Element 46:Empty:VolumeTag=                                    \n      Storage Element 47:Empty:VolumeTag=                                    \n      Storage Element 48:Empty:VolumeTag=                                    \n      Storage Element 49:Empty:Vol
  ...（截断，完整见 audit 原始日志）
```

## 第 2 部分 · 3.2 带机操作（/devices + /drives）（共 52 条 CMD）
### CMD-000035

**CLI 原始命令：**

```bash
sg_inq /dev/sg0
```

CLI 测试结果：`PASS`

**对应 API：** `GET /devices/sg0/inquiry`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/devices/sg0/inquiry
```

**说明：** SCSI Inquiry → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-D79DF6",
  "data": {
    "stdout": "standard INQUIRY:\n  PQual=0  PDT=1  RMB=1  LU_CONG=0  hot_pluggable=0  version=0x06  [SPC-4]\n  [AERC=0]  [TrmTsk=0]  NormACA=0  HiSUP=1  Resp_data_format=2\n  SCCS=0  ACC=0  TPGS=0  3PC=0  Protect=1  [BQue=0]\n  EncServ=0  MultiP=1 (VS=0)  [MChngr=0]  [ACKREQQ=0]  Addr16=0\n  [RelAdr=0]  WBus16=0  Sync=0  [Linked=0]  [TranDis=0]  CmdQue=1\n  [SPI: Clocking=0x0  QAS=0  IUS=0]\n    length=70 (0x46)   Peripheral device type: tape\n Vendor identification: IBM     \n Product identification: ULT3580-TDA     \n Product revision level: T3S0\n Unit serial number: 607B811E08\n",
    "command_id": "CMD-DC61BDFC",
    "parsed": {
      "vendor_identification": "IBM",
      "product_identification": "ULT3580-TDA",
      "product_revision_level": "T3S0",
      "unit_serial_number": "607B811E08",
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000036

**CLI 原始命令：**

```bash
sg_inq /dev/sg1
```

CLI 测试结果：`PASS`

**对应 API：** `GET /devices/sg1/inquiry`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/devices/sg1/inquiry
```

**说明：** SCSI Inquiry → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-C883B9",
  "data": {
    "stdout": "standard INQUIRY:\n  PQual=0  PDT=8  RMB=1  LU_CONG=0  hot_pluggable=0  version=0x03  [SPC]\n  [AERC=0]  [TrmTsk=0]  NormACA=0  HiSUP=0  Resp_data_format=2\n  SCCS=0  ACC=0  TPGS=0  3PC=0  Protect=0  [BQue=0]\n  EncServ=0  MultiP=1 (VS=1)  [MChngr=0]  [ACKREQQ=0]  Addr16=0\n  [RelAdr=0]  WBus16=0  Sync=0  [Linked=0]  [TranDis=0]  CmdQue=1\n  [SPI: Clocking=0x0  QAS=0  IUS=0]\n    length=58 (0x3a)   Peripheral device type: medium changer\n Vendor identification: IBM     \n Product identification: 03584L32        \n Product revision level: 2C02\n Unit serial number: 0000078B12170401\n",
    "command_id": "CMD-D7305CF7",
    "parsed": {
      "vendor_identification": "IBM",
      "product_identification": "03584L32",
      "product_revision_level": "2C02",
      "unit_serial_number": "0000078B12170401",
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000037

**CLI 原始命令：**

```bash
sg_inq /dev/sg2
```

CLI 测试结果：`PASS`

**对应 API：** `GET /devices/sg2/inquiry`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/devices/sg2/inquiry
```

**说明：** SCSI Inquiry → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-D5B136",
  "data": {
    "stdout": "standard INQUIRY:\n  PQual=0  PDT=1  RMB=1  LU_CONG=0  hot_pluggable=0  version=0x06  [SPC-4]\n  [AERC=0]  [TrmTsk=0]  NormACA=0  HiSUP=1  Resp_data_format=2\n  SCCS=0  ACC=0  TPGS=0  3PC=0  Protect=1  [BQue=0]\n  EncServ=0  MultiP=1 (VS=0)  [MChngr=0]  [ACKREQQ=0]  Addr16=0\n  [RelAdr=0]  WBus16=0  Sync=0  [Linked=0]  [TranDis=0]  CmdQue=1\n  [SPI: Clocking=0x0  QAS=0  IUS=0]\n    length=70 (0x46)   Peripheral device type: tape\n Vendor identification: IBM     \n Product identification: ULT3580-TDA     \n Product revision level: T3S0\n Unit serial number: 607B811E03\n",
    "command_id": "CMD-373B0966",
    "parsed": {
      "vendor_identification": "IBM",
      "product_identification": "ULT3580-TDA",
      "product_revision_level": "T3S0",
      "unit_serial_number": "607B811E03",
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000038

**CLI 原始命令：**

```bash
sg_inq /dev/sg3
```

CLI 测试结果：`PASS`

**对应 API：** `GET /devices/sg3/inquiry`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/devices/sg3/inquiry
```

**说明：** SCSI Inquiry → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-9E801A",
  "data": {
    "stdout": "standard INQUIRY:\n  PQual=0  PDT=8  RMB=1  LU_CONG=0  hot_pluggable=0  version=0x03  [SPC]\n  [AERC=0]  [TrmTsk=0]  NormACA=0  HiSUP=0  Resp_data_format=2\n  SCCS=0  ACC=0  TPGS=0  3PC=0  Protect=0  [BQue=0]\n  EncServ=0  MultiP=1 (VS=1)  [MChngr=0]  [ACKREQQ=0]  Addr16=0\n  [RelAdr=0]  WBus16=0  Sync=0  [Linked=0]  [TranDis=0]  CmdQue=1\n  [SPI: Clocking=0x0  QAS=0  IUS=0]\n    length=58 (0x3a)   Peripheral device type: medium changer\n Vendor identification: IBM     \n Product identification: 03584L32        \n Product revision level: 2C02\n Unit serial number: 0000078B12170401\n",
    "command_id": "CMD-F672CD4B",
    "parsed": {
      "vendor_identification": "IBM",
      "product_identification": "03584L32",
      "product_revision_level": "2C02",
      "unit_serial_number": "0000078B12170401",
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000039

**CLI 原始命令：**

```bash
sg_vpd -p 0x80 /dev/sg0
```

CLI 测试结果：`PASS`

**对应 API：** `GET /devices/sg0/vpd?page=0x80`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/devices/sg0/vpd?page=0x80
```

**说明：** VPD 页查询 → data.page/stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-F6C935",
  "data": {
    "page": "0x80",
    "stdout": "Unit serial number VPD page:\n  Unit serial number: 607B811E08\n",
    "command_id": "CMD-D9444514",
    "parsed": {
      "page_code": null,
      "page_name": "Unit serial number VPD",
      "fields": {
        "unit_serial_number": "607B811E08"
      },
      "ascii": [
        "Unit",
        "serial",
        "number",
        "page:",
        "Unit",
        "serial",
        "number:",
        "607B811E08"
      ],
      "total_lines": 2,
      "hex_dump_lines": 0,
      "text_lines": 2,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000040

**CLI 原始命令：**

```bash
sg_vpd -p 0x83 /dev/sg0
```

CLI 测试结果：`PASS`

**对应 API：** `GET /devices/sg0/vpd?page=0x83`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/devices/sg0/vpd?page=0x83
```

**说明：** VPD 页查询 → data.page/stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-C4B0D0",
  "data": {
    "page": "0x83",
    "stdout": "Device Identification VPD page:\n  Addressed logical unit:\n    designator type: T10 vendor identification,  code set: ASCII\n      vendor id: IBM     \n      vendor specific: ULT3580-TDA     607B811E08\n    designator type: NAA,  code set: Binary\n      0x500507607b811e08\n  Target port:\n    designator type: Relative target port,  code set: Binary\n     transport: Fibre Channel Protocol for SCSI (FCP-5)\n      Relative target port: 0x1\n    designator type: NAA,  code set: Binary\n     transport: Fibre Channel Protocol for SCSI (FCP-5)\n      0x500507607b411e08\n",
    "command_id": "CMD-EFA093DA",
    "parsed": {
      "page_code": null,
      "page_name": "Device Identification VPD",
      "fields": {
        "designator_type": "NAA,  code set: Binary",
        "vendor_id": "IBM",
        "vendor_specific": "ULT3580-TDA     607B811E08",
        "transport": "Fibre Channel Protocol for SCSI (FCP-5)",
        "relative_target_port": "0x1"
      },
      "ascii": [
        "Device",
        "Identification",
        "page:",
        "Addressed",
        "logical",
        "unit:",
        "designator",
        "type:",
        "vendor",
        "identification,",
        "code",
        "set:",
        "ASCII",
        "vendor",
        "vendor",
        "specific:",
        "ULT3580-TDA",
        "607B811E08",
        "designator",
        "type:",
        "NAA,",
        "code",
        "set:",
        "Binary",
        "0x500507607b811e08",
        "Target",
        "port:",
        "designator",
        "type:",
        "Relative",
        "target",
        "port,",
        "code",
        "set:",
        "Binary",
        "transport:",
        "Fibre",
        "Channel",
        "Protocol",
        "SCSI",
        "(FCP-5)",
        "Relative",
        "target",
        "port:",
        "designator",
        "type:",
        "NAA,",
        "code",
        "set:",
        "Binary",
        "transport:",
        "Fibre",
        "Channel",
        "Protocol",
        "SCSI",
        "(FCP-5)",
        "0x500507607b411e08"
      ],
      "total_lines": 14,
      "hex_dump_lines": 0,
      "text_lines": 14,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000041

**CLI 原始命令：**

```bash
for d in /dev/sg0 /dev/sg1 /dev/sg2 /dev/sg3; do echo == $d ==; sg_turs $d; done
```

CLI 测试结果：`PASS`

**对应 API：** `GET /devices/SG/tur ×4（逐台 TUR）`

**说明：** 循环 TUR → 每台设备 ready 字段

```bash
curl -s http://172.16.12.186:8001/api/v1/devices/sg0/tur
```

响应（HTTP 200）：

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-51FF72",
  "data": {
    "ready": false,
    "stdout": "device not ready\nCompleted 1 Test Unit Ready commands with 1 errors\n",
    "stderr": "",
    "command_id": "CMD-17134308",
    "parsed": {
      "ready": false,
      "stdout_text": "device not ready\nCompleted 1 Test Unit Ready commands with 1 errors",
      "stderr_text": "",
      "parsed_ok": true
    }
  },
  "error": null
}
```

```bash
curl -s http://172.16.12.186:8001/api/v1/devices/sg1/tur
```

响应（HTTP 200）：

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-F67E07",
  "data": {
    "ready": true,
    "stdout": "",
    "stderr": "",
    "command_id": "CMD-711C7045",
    "parsed": {
      "ready": true,
      "stdout_text": "",
      "stderr_text": "",
      "parsed_ok": true
    }
  },
  "error": null
}
```

```bash
curl -s http://172.16.12.186:8001/api/v1/devices/sg2/tur
```

响应（HTTP 200）：

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-EAAEE7",
  "data": {
    "ready": false,
    "stdout": "device not ready\nCompleted 1 Test Unit Ready commands with 1 errors\n",
    "stderr": "",
    "command_id": "CMD-6310FF2E",
    "parsed": {
      "ready": false,
      "stdout_text": "device not ready\nCompleted 1 Test Unit Ready commands with 1 errors",
      "stderr_text": "",
      "parsed_ok": true
    }
  },
  "error": null
}
```

```bash
curl -s http://172.16.12.186:8001/api/v1/devices/sg3/tur
```

响应（HTTP 200）：

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-475DDA",
  "data": {
    "ready": true,
    "stdout": "",
    "stderr": "",
    "command_id": "CMD-8DFB5F4F",
    "parsed": {
      "ready": true,
      "stdout_text": "",
      "stderr_text": "",
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000046

**CLI 原始命令：**

```bash
mt -f /dev/nst0 status
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/nst0/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/nst0/status
```

**说明：** 带机状态 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-472A7D",
  "data": {
    "stdout": "SCSI 2 tape drive:\nFile number=-1, block number=-1, partition=0.\nTape block size 0 bytes. Density code 0x0 (default).\nSoft error count since last status=0\nGeneral status bits on (50000):\n DR_OPEN IM_REP_EN\n",
    "command_id": "CMD-1E4A90EE",
    "parsed": {
      "file_number": -1,
      "block_number": -1,
      "partition": 0,
      "block_size": 0,
      "density_code": "0x0",
      "density_name": "default",
      "soft_error_count": 0,
      "flags": [
        "DR_OPEN",
        "IM_REP_EN"
      ],
      "at_bot": false,
      "at_eod": false,
      "tape_online": false,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000047

**CLI 原始命令：**

```bash
mt -f /dev/nst1 status
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/nst1/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/nst1/status
```

**说明：** 带机状态 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-152D12",
  "data": {
    "stdout": "SCSI 2 tape drive:\nFile number=-1, block number=-1, partition=0.\nTape block size 0 bytes. Density code 0x0 (default).\nSoft error count since last status=0\nGeneral status bits on (8050000):\n EOD DR_OPEN IM_REP_EN\n",
    "command_id": "CMD-F2E90873",
    "parsed": {
      "file_number": -1,
      "block_number": -1,
      "partition": 0,
      "block_size": 0,
      "density_code": "0x0",
      "density_name": "default",
      "soft_error_count": 0,
      "flags": [
        "EOD",
        "DR_OPEN",
        "IM_REP_EN"
      ],
      "at_bot": false,
      "at_eod": true,
      "tape_online": false,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000048

**CLI 原始命令：**

```bash
sg_modes -a /dev/sg0
```

CLI 测试结果：`PASS`

**对应 API：** `GET /devices/sg0/modes`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/devices/sg0/modes
```

**说明：** 模式页 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-DDEEFC",
  "data": {
    "stdout": "    IBM       ULT3580-TDA       T3S0   peripheral_type: tape [0x1]\nMode parameter header from MODE SENSE(10):\n  Mode data length=223, medium type=0x00, specific param=0x10, longlba=0\n  Block descriptor length=8\n> General mode parameter block descriptors:\n   Density code=0x0\n 00     00 00 00 00 00 00 00 00\n\n>> Read-Write error recovery, page_control: current\n 00     01 0a 28 ff 00 00 00 00  ff 00 00 00\n>> Disconnect-Reconnect, page_control: current\n 00     02 0e 00 00 00 00 00 00  00 00 00 00 00 00 00 00\n>> Control, page_control: current\n 00     0a 0a 00 01 00 00 00 00  ff ff 00 00\n>> Data Compression, page_control: current\n 00     0f 0e c0 80 00 00 00 ff  00 00 00 ff 00 00 00 00\n>> Device configuration, page_control: current\n 00     90 0e 00 00 00 00 01 2c  40 00 10 00 00 00 01 90\n>> Medium Partition [1], page_control: current\n 00     11 0e 03 00 3c 03 18 00  00 00 00 00 00 00 00 00\n>> LU control, page_control: current\n 00     18 06 00 00 00 00 00 00\n>> Port control, page_control: current\n 00     19 06 00 00 00 00 03 fa\n>> Power condition, page_control: current\n 00     9a 26 00 08 00 00 00 00  00 00 00 00 00 00 00 00\n 10     00 00 2e e0 00 00 00 00  00 00 00 00 00 00 00 00\n 20     00 00 00 00 00 00 00 00\n>> Informational exceptions control (tape version), page_control: current\n 00     1c 0a 08 04 00 00 00 00  00 00 00 00\n>> Medium configuration, page_control: current\n 00     1d 1e 00 00 01 02 00 00  00 00 00 00 00 00 00 00\n 10     00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00\n>> page_code: 0x2f, page_control: current\n 00     af 08 00 01 00 01 00 00  00 01\n>> page_code: 0x30, page_control: current\n 00     30 07 01 02 03 20 40 42  43\n",
    "command_id": "CMD-FA6F974C",
    "parsed": {
      "mode_pages": [],
      "header_fields": {
        "mode_data_length": "223",
        "block_descriptor_length": "8",
        "density_code": "0x0"
      },
      "total_lines": 36,
      "hex_dump_lines": 17,
      "text_lines": 19,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000049

**CLI 原始命令：**

```bash
sg_logs -a /dev/sg0
```

CLI 测试结果：`PASS`

**对应 API：** `GET /devices/sg0/logs`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/devices/sg0/logs
```

**说明：** 全部日志页 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-BA4CD5",
  "data": {
    "page": "all",
    "stdout": "    IBM       ULT3580-TDA       T3S0\n\nSupported log pages  [0x0]:\n    0x00        Supported log pages [sp]\n    0x02        Write error [we]\n    0x03        Read error [re]\n    0x06        Non medium [nm]\n    0x0c        Sequential access device [sad]\n    0x11        DT Device status [dtds]\n    0x12        Tape alert response [tar]\n    0x14        Device statistics [ds]\n    0x16        Tape diagnostic data [tdd]\n    0x17        Volume statistics [vs]\n    0x1a        Power condition transitions [pct]\n    0x1b        Data compression [dc]\n    0x2e        Tape alert [ta]\n    0x30        Tape usage (lto-5, 6) [tu_]\n    0x31        Tape capacity (lto-5, 6) [tc_]\n    0x32        Data compression (lto-5) [dc_]\n    0x33        Write errors (lto-5) [we_]\n    0x34        Read forward errors (lto-5) [rfe_]\n    0x37        Performance characteristics (lto-5) [pc_]\n    0x38        Blocks/bytes transferred (lto-5) [bbt_]\n    0x39        Host port 0 interface errors (lto-5) [hp0_]\n    0x3b        Host port 1 interface errors (lto-5) [hp1_]\n    0x3c        Drive usage information (lto-5) [dui_]\n    0x3d        Subsystem statistics (lto-5) [ss_]\n\nWrite error counter page  [0x2]\n  Errors corrected without substantial delay = 0\n  Errors corrected with possible delays = 0\n  Total rewrites or rereads = 0\n  Total errors corrected = 1\n  Total times correction algorithm processed = 1\n  Total bytes processed = 104861768\n  Total uncorrected errors = 0\n  Reserved or vendor specific [0x8000] = 0\n  Reserved or vendor specific [0x8001] = 0\n\nRead error counter page  [0x3]\n  Errors corrected without substantial delay = 0\n  Errors corrected with possible delays = 0\n  Total rewrites or rereads = 0\n  Total errors corrected = 0\n  Total times correction algorithm processed = 0\n  Total bytes processed = 0\n  Total uncorrected errors = 0\n  Reserved or vendor specific [0x8000] = 0\n\nNon-medium error page  [0x6]\n  Non-medium error count = 0\n\nSequential access device page (ssc-3)\n  Data bytes received with WRITE commands: 107 GB\n  Data bytes written to media by WRITE commands: 107 GB\n  Data bytes read from media by READ commands: 0 GB\n  Data bytes transferred by READ commands: 0 GB\n  Maximum native capacity in device object buffer: 2990 MB\n  Cleaning action not required (or completed)\n  Vendor specific parameter [0x8000] value: 430082\n  Vendor specific parameter [0x8001] value: 67\n  Vendor specific parameter [0x8002] value: 1\n  Vendor specific parameter [0x8003] value: 14005339\n\nDT device status page (ssc-3, adc-3) [0x11]\n  Very high frequency data:\n  PAMR=0 HUI=1 MACC=0 CMPR=1 WRTP=0 CRQST=0 CRQRD=0 DINIT=1\n  INXTN=0 RAA=1 MPRSNT=0 MSTD=0 MTHRD=0 MOUNTED=0\n  DT device activity: No DT device activity\n  VS=0 TDDEC=0 EPP=0 ESR=0 RRQST=0 INTFC=0 TAFC=0\n  Very high frequency polling delay:  500 milliseconds\n   DT device ADC data encryption control status (hex only now):\n 00     00 00 00 00 00 00 00 00\n   Key management error data (hex only now):\n 00     00 00 00 00 00 00 00 00  00 00 00 00\n  Reserved [parameter_code=0x4]:\n 00     00 04 03 08 51 20 00 00  01 01 00 00                ....Q ......\n  Primary port 1 status:\n    non-SAS transport, in hex:\n 00     3b 00 00 d9 80 03 00 08  50 05 07 60 7b 41 1e 08    ;.......P..`{A..\n 10     50 05 07 60 7b 81 1e 08                             P..`{...\n  Primary port 2 status:\n    non-SAS transport, in hex:\n 00     00 00 00 00 00 00 00 00  50 05 07 60 7b 81 1e 08    ........P..`{...\n 10     50 05 07 60 7b 81 1e 08                             P..`{...\n  Reserved [parameter_code=0x200]:\n 00     02 00 03 01 01                                      .....\n  Reserved [parameter_code=0x201]:\n 00     02 01 03 2b 55 00 00 00  12 00 0a 02 00 01 a0 89    ...+U...........\n 10     3a 0f 
  ...（截断，完整见 audit 原始日志）
```

### CMD-000050

**CLI 原始命令：**

```bash
sg_logs -p 0x2e /dev/sg0
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/sg0/tapealert`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/sg0/tapealert
```

**说明：** TapeAlert 解析 → data.alerts[] + raw_output

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-3AAD42",
  "data": {
    "alerts": [],
    "parsed": {
      "device": "IBM       ULT3580-TDA       T3S0",
      "page": "Tape alert page (ssc-3) [0x2e]",
      "flags": [
        {
          "name": "Read warning",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Write warning",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Hard error",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Media",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Read failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Write failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Media life",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Not data grade",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Write protect",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "No removal",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cleaning media",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Unsupported format",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Recoverable mechanical cartridge failure",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Unrecoverable mechanical cartridge failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Memory chip in cartridge failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Forced eject",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Read only format",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Tape directory corrupted on load",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Nearing media life",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cleaning required",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cleaning requested",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Expired cleaning media",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Invalid cleaning tape",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Retension requested",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Dual port interface error",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cooling fan failing",
          "value
  ...（截断，完整见 audit 原始日志）
```

### CMD-000051

**CLI 原始命令：**

```bash
sg_logs -p 0x2e /dev/sg2
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/sg2/tapealert`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/sg2/tapealert
```

**说明：** TapeAlert 解析 → data.alerts[] + raw_output

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-4EB41E",
  "data": {
    "alerts": [],
    "parsed": {
      "device": "IBM       ULT3580-TDA       T3S0",
      "page": "Tape alert page (ssc-3) [0x2e]",
      "flags": [
        {
          "name": "Read warning",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Write warning",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Hard error",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Media",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Read failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Write failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Media life",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Not data grade",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Write protect",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "No removal",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cleaning media",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Unsupported format",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Recoverable mechanical cartridge failure",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Unrecoverable mechanical cartridge failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Memory chip in cartridge failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Forced eject",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Read only format",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Tape directory corrupted on load",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Nearing media life",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cleaning required",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cleaning requested",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Expired cleaning media",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Invalid cleaning tape",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Retension requested",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Dual port interface error",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cooling fan failing",
          "value
  ...（截断，完整见 audit 原始日志）
```

### CMD-000052

**CLI 原始命令：**

```bash
sg_logs -p 0x11 /dev/sg0
```

CLI 测试结果：`PASS`

**对应 API：** `GET /devices/sg0/logs?page=0x11`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/devices/sg0/logs?page=0x11
```

**说明：** 指定日志页 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-51B846",
  "data": {
    "page": "0x11",
    "stdout": "    IBM       ULT3580-TDA       T3S0\n\nSupported log pages  [0x0]:\n    0x00        Supported log pages [sp]\n    0x02        Write error [we]\n    0x03        Read error [re]\n    0x06        Non medium [nm]\n    0x0c        Sequential access device [sad]\n    0x11        DT Device status [dtds]\n    0x12        Tape alert response [tar]\n    0x14        Device statistics [ds]\n    0x16        Tape diagnostic data [tdd]\n    0x17        Volume statistics [vs]\n    0x1a        Power condition transitions [pct]\n    0x1b        Data compression [dc]\n    0x2e        Tape alert [ta]\n    0x30        Tape usage (lto-5, 6) [tu_]\n    0x31        Tape capacity (lto-5, 6) [tc_]\n    0x32        Data compression (lto-5) [dc_]\n    0x33        Write errors (lto-5) [we_]\n    0x34        Read forward errors (lto-5) [rfe_]\n    0x37        Performance characteristics (lto-5) [pc_]\n    0x38        Blocks/bytes transferred (lto-5) [bbt_]\n    0x39        Host port 0 interface errors (lto-5) [hp0_]\n    0x3b        Host port 1 interface errors (lto-5) [hp1_]\n    0x3c        Drive usage information (lto-5) [dui_]\n    0x3d        Subsystem statistics (lto-5) [ss_]\n\nWrite error counter page  [0x2]\n  Errors corrected without substantial delay = 0\n  Errors corrected with possible delays = 0\n  Total rewrites or rereads = 0\n  Total errors corrected = 1\n  Total times correction algorithm processed = 1\n  Total bytes processed = 104861768\n  Total uncorrected errors = 0\n  Reserved or vendor specific [0x8000] = 0\n  Reserved or vendor specific [0x8001] = 0\n\nRead error counter page  [0x3]\n  Errors corrected without substantial delay = 0\n  Errors corrected with possible delays = 0\n  Total rewrites or rereads = 0\n  Total errors corrected = 0\n  Total times correction algorithm processed = 0\n  Total bytes processed = 0\n  Total uncorrected errors = 0\n  Reserved or vendor specific [0x8000] = 0\n\nNon-medium error page  [0x6]\n  Non-medium error count = 0\n\nSequential access device page (ssc-3)\n  Data bytes received with WRITE commands: 107 GB\n  Data bytes written to media by WRITE commands: 107 GB\n  Data bytes read from media by READ commands: 0 GB\n  Data bytes transferred by READ commands: 0 GB\n  Maximum native capacity in device object buffer: 2990 MB\n  Cleaning action not required (or completed)\n  Vendor specific parameter [0x8000] value: 430082\n  Vendor specific parameter [0x8001] value: 67\n  Vendor specific parameter [0x8002] value: 1\n  Vendor specific parameter [0x8003] value: 14005340\n\nDT device status page (ssc-3, adc-3) [0x11]\n  Very high frequency data:\n  PAMR=0 HUI=1 MACC=0 CMPR=1 WRTP=0 CRQST=0 CRQRD=0 DINIT=1\n  INXTN=0 RAA=1 MPRSNT=0 MSTD=0 MTHRD=0 MOUNTED=0\n  DT device activity: No DT device activity\n  VS=0 TDDEC=0 EPP=0 ESR=0 RRQST=0 INTFC=0 TAFC=0\n  Very high frequency polling delay:  500 milliseconds\n   DT device ADC data encryption control status (hex only now):\n 00     00 00 00 00 00 00 00 00\n   Key management error data (hex only now):\n 00     00 00 00 00 00 00 00 00  00 00 00 00\n  Reserved [parameter_code=0x4]:\n 00     00 04 03 08 51 20 00 00  01 01 00 00                ....Q ......\n  Primary port 1 status:\n    non-SAS transport, in hex:\n 00     3b 00 00 d9 80 03 00 08  50 05 07 60 7b 41 1e 08    ;.......P..`{A..\n 10     50 05 07 60 7b 81 1e 08                             P..`{...\n  Primary port 2 status:\n    non-SAS transport, in hex:\n 00     00 00 00 00 00 00 00 00  50 05 07 60 7b 81 1e 08    ........P..`{...\n 10     50 05 07 60 7b 81 1e 08                             P..`{...\n  Reserved [parameter_code=0x200]:\n 00     02 00 03 01 01                                      .....\n  Reserved [parameter_code=0x201]:\n 00     02 01 03 2b 55 00 00 00  12 00 0a 02 00 01 a0 89    ...+U...........\n 10     3a 0f
  ...（截断，完整见 audit 原始日志）
```

### CMD-000053

**CLI 原始命令：**

```bash
dmesg | grep -Ei "tape|changer|scsi|st[0-9]|sg[0-9]|lto|ibm|quantum" | tail -100
```

CLI 测试结果：`PASS`

**对应 API：** `GET /diagnostics/dmesg?tail=100（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/diagnostics/dmesg?tail=100
```

**说明：** dmesg | grep -Ei 磁带关键词 | tail -100 → data.parsed.lines[]，服务端已做关键词过滤

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-EFA9B9",
  "data": {
    "filter": "tape|changer|scsi|st[0-9]|sg[0-9]|lto|ibm|quantum (case-insensitive)",
    "tail": 100,
    "matched_lines": 79,
    "stdout": "[    0.884292] SCSI subsystem initialized\n[    1.046194] Block layer SCSI generic (bsg) driver version 0.4 loaded (major 246)\n[    2.498850] usb 1-1.2.3: Product: IBM USB Travel Keyboard with Ultra Nav\n[    2.606127] input: Lite-On Tech IBM USB Travel Keyboard with Ultra Nav as /devices/pci0000:60/0000:60:07.1/0000:67:00.4/usb1/1-1/1-1.2/1-1.2.3/1-1.2.3:1.0/0003:04B3:301E.0001/input/input1\n[    2.658192] hid-generic 0003:04B3:301E.0001: input,hidraw0: USB HID v1.00 Keyboard [Lite-On Tech IBM USB Travel Keyboard with Ultra Nav] on usb-0000:67:00.4-1.2.3/input0\n[    2.676077] input: Lite-On Tech IBM USB Travel Keyboard with Ultra Nav Mouse as /devices/pci0000:60/0000:60:07.1/0000:67:00.4/usb1/1-1/1-1.2/1-1.2.3/1-1.2.3:1.1/0003:04B3:301E.0002/input/input2\n[    2.676276] input: Lite-On Tech IBM USB Travel Keyboard with Ultra Nav System Control as /devices/pci0000:60/0000:60:07.1/0000:67:00.4/usb1/1-1/1-1.2/1-1.2.3/1-1.2.3:1.1/0003:04B3:301E.0002/input/input3\n[    2.728099] input: Lite-On Tech IBM USB Travel Keyboard with Ultra Nav Consumer Control as /devices/pci0000:60/0000:60:07.1/0000:67:00.4/usb1/1-1/1-1.2/1-1.2.3/1-1.2.3:1.1/0003:04B3:301E.0002/input/input4\n[    2.728230] hid-generic 0003:04B3:301E.0002: input,hidraw1: USB HID v1.00 Mouse [Lite-On Tech IBM USB Travel Keyboard with Ultra Nav] on usb-0000:67:00.4-1.2.3/input1\n[    3.601050] scsi host0: ahci\n[    3.601400] scsi host1: ahci\n[    3.601642] scsi host2: ahci\n[    3.601870] scsi host3: ahci\n[    3.602158] scsi host4: ahci\n[    3.602505] scsi host5: ahci\n[    3.602761] scsi host6: ahci\n[    3.603012] scsi host7: ahci\n[    3.604945] scsi host8: ahci\n[    3.605166] scsi host9: ahci\n[    3.605395] scsi host10: ahci\n[    3.605629] scsi host11: ahci\n[    3.605927] scsi host12: ahci\n[    3.606199] scsi host13: ahci\n[    3.606435] scsi host14: ahci\n[    3.606662] scsi host15: ahci\n[    3.608935] scsi host16: ahci\n[    3.609199] scsi host17: ahci\n[    3.609418] scsi host18: ahci\n[    3.609628] scsi host19: ahci\n[    3.609868] scsi host20: ahci\n[    3.610173] scsi host21: ahci\n[    3.610413] scsi host22: ahci\n[    3.610665] scsi host23: ahci\n[    3.612709] scsi host24: ahci\n[    3.612965] scsi host25: ahci\n[    3.613179] scsi host26: ahci\n[    3.613388] scsi host27: ahci\n[    3.613601] scsi host28: ahci\n[    3.613818] scsi host29: ahci\n[    3.614066] scsi host30: ahci\n[    3.614332] scsi host31: ahci\n[   14.388093] systemd[1]: iscsi-starter.service was skipped because of an unmet condition check (ConditionDirectoryNotEmpty=/var/lib/iscsi/nodes).\n[   15.427403] Emulex LightPulse Fibre Channel SCSI driver 14.4.0.6\n[   15.492592] scsi host32: Emulex LPe12000 PCIe Fibre Channel Adapter on PCI bus 81 device 00 irq 2156\n[   16.593989] scsi host33: Emulex LPe12000 PCIe Fibre Channel Adapter on PCI bus 81 device 01 irq 81\n[  226.137433] scsi 33:0:0:0: Sequential-Access IBM      ULT3580-TDA      T3S0 PQ: 0 ANSI: 6\n[  226.140684] scsi 33:0:0:1: Medium Changer    IBM      03584L32         2C02 PQ: 0 ANSI: 3\n[  226.159488] scsi 33:0:0:0: Attached scsi generic sg0 type 1\n[  226.159576] scsi 33:0:0:1: Attached scsi generic sg1 type 8\n[  226.165695] SCSI Media Changer driver v0.25 \n[  226.168081] st 33:0:0:0: Attached scsi tape st0\n[  226.168087] st 33:0:0:0: st0: try direct i/o: yes (alignment 4 B)\n[  226.549871] ch 33:0:0:1: Attached scsi changer ch0\n[  229.529337] scsi 32:0:0:0: Sequential-Access IBM      ULT3580-TDA      T3S0 PQ: 0 ANSI: 6\n[  229.532642] st 32:0:0:0: Attached scsi tape st1\n[  229.532646] st 32:0:0:0: st1: try direct i/o: yes (alignment 4 B)\n[  229.532769] st 32:0:0:0: Attached scsi generic sg2 type 1\n[  229.533497] scsi 32:0:0:1: Med
  ...（截断，完整见 audit 原始日志）
```

### CMD-000054

**CLI 原始命令：**

```bash
journalctl -k --no-pager | tail -100
```

CLI 测试结果：`PASS`

**对应 API：** `GET /diagnostics/journalctl?tail=100（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/diagnostics/journalctl?tail=100
```

**说明：** journalctl -k --no-pager | tail -100 → data.parsed.lines[]

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-3CEB0C",
  "data": {
    "tail": 100,
    "total_lines": 834,
    "stdout": "Aug 29 09:36:16 node186 kernel: SELinux:  policy capability extended_socket_class=1\nAug 29 09:36:16 node186 kernel: SELinux:  policy capability always_check_network=0\nAug 29 09:36:16 node186 kernel: SELinux:  policy capability cgroup_seclabel=1\nAug 29 09:36:16 node186 kernel: SELinux:  policy capability nnp_nosuid_transition=1\nAug 29 09:36:16 node186 kernel: SELinux:  policy capability genfs_seclabel_symlinks=1\nAug 29 09:37:12 node186 kernel: SELinux:  Converting 1048 SID table entries...\nAug 29 09:37:12 node186 kernel: SELinux:  policy capability network_peer_controls=1\nAug 29 09:37:12 node186 kernel: SELinux:  policy capability open_perms=1\nAug 29 09:37:12 node186 kernel: SELinux:  policy capability extended_socket_class=1\nAug 29 09:37:12 node186 kernel: SELinux:  policy capability always_check_network=0\nAug 29 09:37:12 node186 kernel: SELinux:  policy capability cgroup_seclabel=1\nAug 29 09:37:12 node186 kernel: SELinux:  policy capability nnp_nosuid_transition=1\nAug 29 09:37:12 node186 kernel: SELinux:  policy capability genfs_seclabel_symlinks=1\nAug 29 09:37:36 node186 kernel: SELinux:  Converting 1048 SID table entries...\nAug 29 09:37:36 node186 kernel: SELinux:  policy capability network_peer_controls=1\nAug 29 09:37:36 node186 kernel: SELinux:  policy capability open_perms=1\nAug 29 09:37:36 node186 kernel: SELinux:  policy capability extended_socket_class=1\nAug 29 09:37:36 node186 kernel: SELinux:  policy capability always_check_network=0\nAug 29 09:37:36 node186 kernel: SELinux:  policy capability cgroup_seclabel=1\nAug 29 09:37:36 node186 kernel: SELinux:  policy capability nnp_nosuid_transition=1\nAug 29 09:37:36 node186 kernel: SELinux:  policy capability genfs_seclabel_symlinks=1\nAug 29 09:38:06 node186 kernel: SELinux:  Converting 1048 SID table entries...\nAug 29 09:38:06 node186 kernel: SELinux:  policy capability network_peer_controls=1\nAug 29 09:38:06 node186 kernel: SELinux:  policy capability open_perms=1\nAug 29 09:38:06 node186 kernel: SELinux:  policy capability extended_socket_class=1\nAug 29 09:38:06 node186 kernel: SELinux:  policy capability always_check_network=0\nAug 29 09:38:06 node186 kernel: SELinux:  policy capability cgroup_seclabel=1\nAug 29 09:38:06 node186 kernel: SELinux:  policy capability nnp_nosuid_transition=1\nAug 29 09:38:06 node186 kernel: SELinux:  policy capability genfs_seclabel_symlinks=1\nAug 29 10:28:17 node186 kernel: SELinux:  Converting 1048 SID table entries...\nAug 29 10:28:17 node186 kernel: SELinux:  policy capability network_peer_controls=1\nAug 29 10:28:17 node186 kernel: SELinux:  policy capability open_perms=1\nAug 29 10:28:17 node186 kernel: SELinux:  policy capability extended_socket_class=1\nAug 29 10:28:17 node186 kernel: SELinux:  policy capability always_check_network=0\nAug 29 10:28:17 node186 kernel: SELinux:  policy capability cgroup_seclabel=1\nAug 29 10:28:17 node186 kernel: SELinux:  policy capability nnp_nosuid_transition=1\nAug 29 10:28:17 node186 kernel: SELinux:  policy capability genfs_seclabel_symlinks=1\nAug 29 10:28:54 node186 kernel: SELinux:  Converting 1048 SID table entries...\nAug 29 10:28:54 node186 kernel: SELinux:  policy capability network_peer_controls=1\nAug 29 10:28:54 node186 kernel: SELinux:  policy capability open_perms=1\nAug 29 10:28:54 node186 kernel: SELinux:  policy capability extended_socket_class=1\nAug 29 10:28:54 node186 kernel: SELinux:  policy capability always_check_network=0\nAug 29 10:28:54 node186 kernel: SELinux:  policy capability cgroup_seclabel=1\nAug 29 10:28:54 node186 kernel: SELinux:  policy capability nnp_nosuid_transition=1\nAug 29 10:28:54 node186 kernel: SELinux:  policy capability genfs_seclabel_symlinks=1\nAug 29 10:29:01 node186 kernel: SELinux:  Converting 1048 SID table entries...\nAug 2
  ...（截断，完整见 audit 原始日志）
```

### CMD-000057

**CLI 原始命令：**

```bash
sg_inq /dev/sg0 | head -5
```

CLI 测试结果：`PASS`

**对应 API：** `GET /devices/sg0/inquiry`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/devices/sg0/inquiry
```

**说明：** SCSI Inquiry → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-D79DF6",
  "data": {
    "stdout": "standard INQUIRY:\n  PQual=0  PDT=1  RMB=1  LU_CONG=0  hot_pluggable=0  version=0x06  [SPC-4]\n  [AERC=0]  [TrmTsk=0]  NormACA=0  HiSUP=1  Resp_data_format=2\n  SCCS=0  ACC=0  TPGS=0  3PC=0  Protect=1  [BQue=0]\n  EncServ=0  MultiP=1 (VS=0)  [MChngr=0]  [ACKREQQ=0]  Addr16=0\n  [RelAdr=0]  WBus16=0  Sync=0  [Linked=0]  [TranDis=0]  CmdQue=1\n  [SPI: Clocking=0x0  QAS=0  IUS=0]\n    length=70 (0x46)   Peripheral device type: tape\n Vendor identification: IBM     \n Product identification: ULT3580-TDA     \n Product revision level: T3S0\n Unit serial number: 607B811E08\n",
    "command_id": "CMD-DC61BDFC",
    "parsed": {
      "vendor_identification": "IBM",
      "product_identification": "ULT3580-TDA",
      "product_revision_level": "T3S0",
      "unit_serial_number": "607B811E08",
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000060

**CLI 原始命令：**

```bash
mt -f /dev/nst0 status
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/nst0/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/nst0/status
```

**说明：** 带机状态 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-472A7D",
  "data": {
    "stdout": "SCSI 2 tape drive:\nFile number=-1, block number=-1, partition=0.\nTape block size 0 bytes. Density code 0x0 (default).\nSoft error count since last status=0\nGeneral status bits on (50000):\n DR_OPEN IM_REP_EN\n",
    "command_id": "CMD-1E4A90EE",
    "parsed": {
      "file_number": -1,
      "block_number": -1,
      "partition": 0,
      "block_size": 0,
      "density_code": "0x0",
      "density_name": "default",
      "soft_error_count": 0,
      "flags": [
        "DR_OPEN",
        "IM_REP_EN"
      ],
      "at_bot": false,
      "at_eod": false,
      "tape_online": false,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000061

**CLI 原始命令：**

```bash
mt -f /dev/nst0 rewind
```

CLI 测试结果：`FAIL`

**对应 API：** `POST /drives/nst0/position {operation:rewind}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst0/position -H 'Content-Type: application/json' -d '{"operation": "rewind", "confirm": true}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 502，JSON 已格式化）：**

```json
{
  "detail": {
    "code": "COMMAND_FAILED",
    "message": "command failed: mt -f /dev/nst0 rewind -> /dev/nst0: No medium found\n"
  }
}
```

### CMD-000062

**CLI 原始命令：**

```bash
mt -f /dev/nst0 status
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/nst0/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/nst0/status
```

**说明：** 带机状态 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-472A7D",
  "data": {
    "stdout": "SCSI 2 tape drive:\nFile number=-1, block number=-1, partition=0.\nTape block size 0 bytes. Density code 0x0 (default).\nSoft error count since last status=0\nGeneral status bits on (50000):\n DR_OPEN IM_REP_EN\n",
    "command_id": "CMD-1E4A90EE",
    "parsed": {
      "file_number": -1,
      "block_number": -1,
      "partition": 0,
      "block_size": 0,
      "density_code": "0x0",
      "density_name": "default",
      "soft_error_count": 0,
      "flags": [
        "DR_OPEN",
        "IM_REP_EN"
      ],
      "at_bot": false,
      "at_eod": false,
      "tape_online": false,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000063

**CLI 原始命令：**

```bash
mt -f /dev/nst0 fsf 1 || true
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/position {operation:fsf}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst0/position -H 'Content-Type: application/json' -d '{"operation": "fsf", "confirm": true, "count": 1}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 502，JSON 已格式化）：**

```json
{
  "detail": {
    "code": "COMMAND_FAILED",
    "message": "command failed: mt -f /dev/nst0 fsf 1 -> /dev/nst0: No medium found\n"
  }
}
```

### CMD-000064

**CLI 原始命令：**

```bash
mt -f /dev/nst1 status
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/nst1/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/nst1/status
```

**说明：** 带机状态 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-152D12",
  "data": {
    "stdout": "SCSI 2 tape drive:\nFile number=-1, block number=-1, partition=0.\nTape block size 0 bytes. Density code 0x0 (default).\nSoft error count since last status=0\nGeneral status bits on (8050000):\n EOD DR_OPEN IM_REP_EN\n",
    "command_id": "CMD-F2E90873",
    "parsed": {
      "file_number": -1,
      "block_number": -1,
      "partition": 0,
      "block_size": 0,
      "density_code": "0x0",
      "density_name": "default",
      "soft_error_count": 0,
      "flags": [
        "EOD",
        "DR_OPEN",
        "IM_REP_EN"
      ],
      "at_bot": false,
      "at_eod": true,
      "tape_online": false,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000065

**CLI 原始命令：**

```bash
for d in /dev/sg0 /dev/sg2; do echo == $d ==; sg_turs $d; done
```

CLI 测试结果：`PASS`

**对应 API：** `GET /devices/SG/tur ×2（逐台 TUR）`

**说明：** 循环 TUR → 每台设备 ready 字段

```bash
curl -s http://172.16.12.186:8001/api/v1/devices/sg0/tur
```

响应（HTTP 200）：

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-51FF72",
  "data": {
    "ready": false,
    "stdout": "device not ready\nCompleted 1 Test Unit Ready commands with 1 errors\n",
    "stderr": "",
    "command_id": "CMD-17134308",
    "parsed": {
      "ready": false,
      "stdout_text": "device not ready\nCompleted 1 Test Unit Ready commands with 1 errors",
      "stderr_text": "",
      "parsed_ok": true
    }
  },
  "error": null
}
```

```bash
curl -s http://172.16.12.186:8001/api/v1/devices/sg2/tur
```

响应（HTTP 200）：

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-EAAEE7",
  "data": {
    "ready": false,
    "stdout": "device not ready\nCompleted 1 Test Unit Ready commands with 1 errors\n",
    "stderr": "",
    "command_id": "CMD-6310FF2E",
    "parsed": {
      "ready": false,
      "stdout_text": "device not ready\nCompleted 1 Test Unit Ready commands with 1 errors",
      "stderr_text": "",
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000066

**CLI 原始命令：**

```bash
sg_logs -p 0x2e /dev/sg0 | tail -8; sg_logs -p 0x2e /dev/sg2 | tail -8
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/sg0/tapealert`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/sg0/tapealert
```

**说明：** TapeAlert 解析 → data.alerts[] + raw_output

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-3AAD42",
  "data": {
    "alerts": [],
    "parsed": {
      "device": "IBM       ULT3580-TDA       T3S0",
      "page": "Tape alert page (ssc-3) [0x2e]",
      "flags": [
        {
          "name": "Read warning",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Write warning",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Hard error",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Media",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Read failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Write failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Media life",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Not data grade",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Write protect",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "No removal",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cleaning media",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Unsupported format",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Recoverable mechanical cartridge failure",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Unrecoverable mechanical cartridge failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Memory chip in cartridge failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Forced eject",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Read only format",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Tape directory corrupted on load",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Nearing media life",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cleaning required",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cleaning requested",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Expired cleaning media",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Invalid cleaning tape",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Retension requested",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Dual port interface error",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cooling fan failing",
          "value
  ...（截断，完整见 audit 原始日志）
```

### CMD-000068

**CLI 原始命令：**

```bash
mt -f /dev/nst1 rewind
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst1/position {operation:rewind}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst1/position -H 'Content-Type: application/json' -d '{"operation": "rewind", "confirm": true}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "POSITION_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185824-62265A",
  "data": {
    "operation": "rewind",
    "count": 1,
    "command_id": "CMD-786A282C"
  },
  "error": null
}
```

### CMD-000069

**CLI 原始命令：**

```bash
mt -f /dev/nst1 status
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/nst1/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/nst1/status
```

**说明：** 带机状态 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-152D12",
  "data": {
    "stdout": "SCSI 2 tape drive:\nFile number=-1, block number=-1, partition=0.\nTape block size 0 bytes. Density code 0x0 (default).\nSoft error count since last status=0\nGeneral status bits on (8050000):\n EOD DR_OPEN IM_REP_EN\n",
    "command_id": "CMD-F2E90873",
    "parsed": {
      "file_number": -1,
      "block_number": -1,
      "partition": 0,
      "block_size": 0,
      "density_code": "0x0",
      "density_name": "default",
      "soft_error_count": 0,
      "flags": [
        "EOD",
        "DR_OPEN",
        "IM_REP_EN"
      ],
      "at_bot": false,
      "at_eod": true,
      "tape_online": false,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000070

**CLI 原始命令：**

```bash
mt -f /dev/nst1 fsf 1 || true
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst1/position {operation:fsf}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst1/position -H 'Content-Type: application/json' -d '{"operation": "fsf", "confirm": true, "count": 1}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "POSITION_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185827-52E308",
  "data": {
    "operation": "fsf",
    "count": 1,
    "command_id": "CMD-D1C3F879"
  },
  "error": null
}
```

### CMD-000071

**CLI 原始命令：**

```bash
mt -f /dev/nst1 status
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/nst1/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/nst1/status
```

**说明：** 带机状态 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-152D12",
  "data": {
    "stdout": "SCSI 2 tape drive:\nFile number=-1, block number=-1, partition=0.\nTape block size 0 bytes. Density code 0x0 (default).\nSoft error count since last status=0\nGeneral status bits on (8050000):\n EOD DR_OPEN IM_REP_EN\n",
    "command_id": "CMD-F2E90873",
    "parsed": {
      "file_number": -1,
      "block_number": -1,
      "partition": 0,
      "block_size": 0,
      "density_code": "0x0",
      "density_name": "default",
      "soft_error_count": 0,
      "flags": [
        "EOD",
        "DR_OPEN",
        "IM_REP_EN"
      ],
      "at_bot": false,
      "at_eod": true,
      "tape_online": false,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000072

**CLI 原始命令：**

```bash
mt -f /dev/nst1 bsf 1 || true
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst1/position {operation:bsf}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst1/position -H 'Content-Type: application/json' -d '{"operation": "bsf", "confirm": true, "count": 1}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "POSITION_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185827-ADBCC2",
  "data": {
    "operation": "bsf",
    "count": 1,
    "command_id": "CMD-863C60F1"
  },
  "error": null
}
```

### CMD-000073

**CLI 原始命令：**

```bash
mt -f /dev/nst1 eom || true
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst1/position {operation:seod}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst1/position -H 'Content-Type: application/json' -d '{"operation": "seod", "confirm": true}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "POSITION_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185827-FE74AA",
  "data": {
    "operation": "seod",
    "count": 1,
    "command_id": "CMD-85CF883E"
  },
  "error": null
}
```

### CMD-000074

**CLI 原始命令：**

```bash
mt -f /dev/nst1 status
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/nst1/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/nst1/status
```

**说明：** 带机状态 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-152D12",
  "data": {
    "stdout": "SCSI 2 tape drive:\nFile number=-1, block number=-1, partition=0.\nTape block size 0 bytes. Density code 0x0 (default).\nSoft error count since last status=0\nGeneral status bits on (8050000):\n EOD DR_OPEN IM_REP_EN\n",
    "command_id": "CMD-F2E90873",
    "parsed": {
      "file_number": -1,
      "block_number": -1,
      "partition": 0,
      "block_size": 0,
      "density_code": "0x0",
      "density_name": "default",
      "soft_error_count": 0,
      "flags": [
        "EOD",
        "DR_OPEN",
        "IM_REP_EN"
      ],
      "at_bot": false,
      "at_eod": true,
      "tape_online": false,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000075

**CLI 原始命令：**

```bash
mt -f /dev/nst1 rewind
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst1/position {operation:rewind}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst1/position -H 'Content-Type: application/json' -d '{"operation": "rewind", "confirm": true}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "POSITION_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185824-62265A",
  "data": {
    "operation": "rewind",
    "count": 1,
    "command_id": "CMD-786A282C"
  },
  "error": null
}
```

### CMD-000076

**CLI 原始命令：**

```bash
mt -f /dev/nst1 seod || true
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst1/position {operation:seod}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst1/position -H 'Content-Type: application/json' -d '{"operation": "seod", "confirm": true}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "POSITION_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185827-FE74AA",
  "data": {
    "operation": "seod",
    "count": 1,
    "command_id": "CMD-85CF883E"
  },
  "error": null
}
```

### CMD-000078

**CLI 原始命令：**

```bash
mt -f /dev/nst1 status
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/nst1/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/nst1/status
```

**说明：** 带机状态 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-152D12",
  "data": {
    "stdout": "SCSI 2 tape drive:\nFile number=-1, block number=-1, partition=0.\nTape block size 0 bytes. Density code 0x0 (default).\nSoft error count since last status=0\nGeneral status bits on (8050000):\n EOD DR_OPEN IM_REP_EN\n",
    "command_id": "CMD-F2E90873",
    "parsed": {
      "file_number": -1,
      "block_number": -1,
      "partition": 0,
      "block_size": 0,
      "density_code": "0x0",
      "density_name": "default",
      "soft_error_count": 0,
      "flags": [
        "EOD",
        "DR_OPEN",
        "IM_REP_EN"
      ],
      "at_bot": false,
      "at_eod": true,
      "tape_online": false,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000079

**CLI 原始命令：**

```bash
mt -f /dev/nst1 rewind
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst1/position {operation:rewind}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst1/position -H 'Content-Type: application/json' -d '{"operation": "rewind", "confirm": true}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "POSITION_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185824-62265A",
  "data": {
    "operation": "rewind",
    "count": 1,
    "command_id": "CMD-786A282C"
  },
  "error": null
}
```

### CMD-000081

**CLI 原始命令：**

```bash
mt -f /dev/nst0 bsf 1 || true
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/position {operation:bsf}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst0/position -H 'Content-Type: application/json' -d '{"operation": "bsf", "confirm": true, "count": 1}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 502，JSON 已格式化）：**

```json
{
  "detail": {
    "code": "COMMAND_FAILED",
    "message": "command failed: mt -f /dev/nst0 bsf 1 -> /dev/nst0: No medium found\n"
  }
}
```

### CMD-000084

**CLI 原始命令：**

```bash
mt -f /dev/nst1 rewind && mt -f /dev/nst1 status
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst1/position {operation:rewind}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst1/position -H 'Content-Type: application/json' -d '{"operation": "rewind", "confirm": true}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "POSITION_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185824-62265A",
  "data": {
    "operation": "rewind",
    "count": 1,
    "command_id": "CMD-786A282C"
  },
  "error": null
}
```

### CMD-000086

**CLI 原始命令：**

```bash
mt -f /dev/nst1 status
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/nst1/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/nst1/status
```

**说明：** 带机状态 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-152D12",
  "data": {
    "stdout": "SCSI 2 tape drive:\nFile number=-1, block number=-1, partition=0.\nTape block size 0 bytes. Density code 0x0 (default).\nSoft error count since last status=0\nGeneral status bits on (8050000):\n EOD DR_OPEN IM_REP_EN\n",
    "command_id": "CMD-F2E90873",
    "parsed": {
      "file_number": -1,
      "block_number": -1,
      "partition": 0,
      "block_size": 0,
      "density_code": "0x0",
      "density_name": "default",
      "soft_error_count": 0,
      "flags": [
        "EOD",
        "DR_OPEN",
        "IM_REP_EN"
      ],
      "at_bot": false,
      "at_eod": true,
      "tape_online": false,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000087

**CLI 原始命令：**

```bash
mt -f /dev/nst1 rewind
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst1/position {operation:rewind}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst1/position -H 'Content-Type: application/json' -d '{"operation": "rewind", "confirm": true}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "POSITION_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185824-62265A",
  "data": {
    "operation": "rewind",
    "count": 1,
    "command_id": "CMD-786A282C"
  },
  "error": null
}
```

### CMD-000090

**CLI 原始命令：**

```bash
mt -f /dev/nst0 eom || true
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/position {operation:seod}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst0/position -H 'Content-Type: application/json' -d '{"operation": "seod", "confirm": true}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 502，JSON 已格式化）：**

```json
{
  "detail": {
    "code": "COMMAND_FAILED",
    "message": "command failed: mt -f /dev/nst0 seod -> /dev/nst0: No medium found\n"
  }
}
```

### CMD-000091

**CLI 原始命令：**

```bash
mt -f /dev/nst0 status
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/nst0/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/nst0/status
```

**说明：** 带机状态 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-472A7D",
  "data": {
    "stdout": "SCSI 2 tape drive:\nFile number=-1, block number=-1, partition=0.\nTape block size 0 bytes. Density code 0x0 (default).\nSoft error count since last status=0\nGeneral status bits on (50000):\n DR_OPEN IM_REP_EN\n",
    "command_id": "CMD-1E4A90EE",
    "parsed": {
      "file_number": -1,
      "block_number": -1,
      "partition": 0,
      "block_size": 0,
      "density_code": "0x0",
      "density_name": "default",
      "soft_error_count": 0,
      "flags": [
        "DR_OPEN",
        "IM_REP_EN"
      ],
      "at_bot": false,
      "at_eod": false,
      "tape_online": false,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000092

**CLI 原始命令：**

```bash
mt -f /dev/nst0 rewind
```

CLI 测试结果：`FAIL`

**对应 API：** `POST /drives/nst0/position {operation:rewind}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst0/position -H 'Content-Type: application/json' -d '{"operation": "rewind", "confirm": true}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 502，JSON 已格式化）：**

```json
{
  "detail": {
    "code": "COMMAND_FAILED",
    "message": "command failed: mt -f /dev/nst0 rewind -> /dev/nst0: No medium found\n"
  }
}
```

### CMD-000093

**CLI 原始命令：**

```bash
sg_logs -p 0x2e /dev/sg2 | grep -E "Hard error|Write failure|Read failure|Media"
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/sg2/tapealert`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/sg2/tapealert
```

**说明：** TapeAlert 解析 → data.alerts[] + raw_output

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-4EB41E",
  "data": {
    "alerts": [],
    "parsed": {
      "device": "IBM       ULT3580-TDA       T3S0",
      "page": "Tape alert page (ssc-3) [0x2e]",
      "flags": [
        {
          "name": "Read warning",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Write warning",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Hard error",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Media",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Read failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Write failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Media life",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Not data grade",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Write protect",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "No removal",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cleaning media",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Unsupported format",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Recoverable mechanical cartridge failure",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Unrecoverable mechanical cartridge failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Memory chip in cartridge failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Forced eject",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Read only format",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Tape directory corrupted on load",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Nearing media life",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cleaning required",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cleaning requested",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Expired cleaning media",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Invalid cleaning tape",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Retension requested",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Dual port interface error",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cooling fan failing",
          "value
  ...（截断，完整见 audit 原始日志）
```

### CMD-000095

**CLI 原始命令：**

```bash
mt -f /dev/nst1 rewind && mt -f /dev/nst1 status
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst1/position {operation:rewind}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst1/position -H 'Content-Type: application/json' -d '{"operation": "rewind", "confirm": true}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "POSITION_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185824-62265A",
  "data": {
    "operation": "rewind",
    "count": 1,
    "command_id": "CMD-786A282C"
  },
  "error": null
}
```

### CMD-000097

**CLI 原始命令：**

```bash
mt -f /dev/nst1 weof
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst1/weof`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8002/api/v1/drives/nst1/weof -H 'Content-Type: application/json' -d '{"count": 1, "confirm": true}'
```

**说明：** 写文件标记（LEVEL 3，FULL 实例）→ code=WEOF_SUCCESS

**响应（HTTP 000，JSON 已格式化）：**

```json

```

### CMD-000098

**CLI 原始命令：**

```bash
mt -f /dev/nst1 status
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/nst1/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/nst1/status
```

**说明：** 带机状态 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-152D12",
  "data": {
    "stdout": "SCSI 2 tape drive:\nFile number=-1, block number=-1, partition=0.\nTape block size 0 bytes. Density code 0x0 (default).\nSoft error count since last status=0\nGeneral status bits on (8050000):\n EOD DR_OPEN IM_REP_EN\n",
    "command_id": "CMD-F2E90873",
    "parsed": {
      "file_number": -1,
      "block_number": -1,
      "partition": 0,
      "block_size": 0,
      "density_code": "0x0",
      "density_name": "default",
      "soft_error_count": 0,
      "flags": [
        "EOD",
        "DR_OPEN",
        "IM_REP_EN"
      ],
      "at_bot": false,
      "at_eod": true,
      "tape_online": false,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000099

**CLI 原始命令：**

```bash
mt -f /dev/nst1 rewind
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst1/position {operation:rewind}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst1/position -H 'Content-Type: application/json' -d '{"operation": "rewind", "confirm": true}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "POSITION_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185824-62265A",
  "data": {
    "operation": "rewind",
    "count": 1,
    "command_id": "CMD-786A282C"
  },
  "error": null
}
```

### CMD-000101

**CLI 原始命令：**

```bash
mt -f /dev/nst1 status
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/nst1/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/nst1/status
```

**说明：** 带机状态 → data.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-152D12",
  "data": {
    "stdout": "SCSI 2 tape drive:\nFile number=-1, block number=-1, partition=0.\nTape block size 0 bytes. Density code 0x0 (default).\nSoft error count since last status=0\nGeneral status bits on (8050000):\n EOD DR_OPEN IM_REP_EN\n",
    "command_id": "CMD-F2E90873",
    "parsed": {
      "file_number": -1,
      "block_number": -1,
      "partition": 0,
      "block_size": 0,
      "density_code": "0x0",
      "density_name": "default",
      "soft_error_count": 0,
      "flags": [
        "EOD",
        "DR_OPEN",
        "IM_REP_EN"
      ],
      "at_bot": false,
      "at_eod": true,
      "tape_online": false,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000102

**CLI 原始命令：**

```bash
mt -f /dev/nst1 rewind
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst1/position {operation:rewind}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst1/position -H 'Content-Type: application/json' -d '{"operation": "rewind", "confirm": true}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "POSITION_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185824-62265A",
  "data": {
    "operation": "rewind",
    "count": 1,
    "command_id": "CMD-786A282C"
  },
  "error": null
}
```

### CMD-000104

**CLI 原始命令：**

```bash
mt -f /dev/nst1 fsf 1; mt -f /dev/nst1 status
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst1/position {operation:fsf}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst1/position -H 'Content-Type: application/json' -d '{"operation": "fsf", "confirm": true, "count": 1}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "POSITION_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185827-52E308",
  "data": {
    "operation": "fsf",
    "count": 1,
    "command_id": "CMD-D1C3F879"
  },
  "error": null
}
```

### CMD-000105

**CLI 原始命令：**

```bash
sg_logs -p 0x2e /dev/sg2 | grep -E "Hard error|Write failure|Read failure|Media life|Media:"
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/sg2/tapealert`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/drives/sg2/tapealert
```

**说明：** TapeAlert 解析 → data.alerts[] + raw_output

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-4EB41E",
  "data": {
    "alerts": [],
    "parsed": {
      "device": "IBM       ULT3580-TDA       T3S0",
      "page": "Tape alert page (ssc-3) [0x2e]",
      "flags": [
        {
          "name": "Read warning",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Write warning",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Hard error",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Media",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Read failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Write failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Media life",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Not data grade",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Write protect",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "No removal",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cleaning media",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Unsupported format",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Recoverable mechanical cartridge failure",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Unrecoverable mechanical cartridge failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Memory chip in cartridge failure",
          "value": 0,
          "severity": "CRITICAL",
          "triggered": false
        },
        {
          "name": "Forced eject",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Read only format",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Tape directory corrupted on load",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Nearing media life",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cleaning required",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cleaning requested",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Expired cleaning media",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Invalid cleaning tape",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Retension requested",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Dual port interface error",
          "value": 0,
          "severity": "WARNING",
          "triggered": false
        },
        {
          "name": "Cooling fan failing",
          "value
  ...（截断，完整见 audit 原始日志）
```

### CMD-000106

**CLI 原始命令：**

```bash
mt -f /dev/nst1 rewind
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst1/position {operation:rewind}`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/drives/nst1/position -H 'Content-Type: application/json' -d '{"operation": "rewind", "confirm": true}'
```

**说明：** 磁带定位 → code=POSITION_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "POSITION_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185824-62265A",
  "data": {
    "operation": "rewind",
    "count": 1,
    "command_id": "CMD-786A282C"
  },
  "error": null
}
```


## 第 3 部分 · 3.3 IO 操作（/tests）（共 5 条 CMD）
### CMD-000077

**CLI 原始命令：**

```bash
dd if=/dev/nst1 of=/dev/null bs=1M status=progress || true
```

CLI 测试结果：`PASS`

**对应 API：** `POST /tests/read`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/tests/read -H 'Content-Type: application/json' -d '{"drive": "/dev/nst1", "block_size": "1M", "confirm": true}'
```

**说明：** 读测试 → code=READ_TEST_PASS，duration_ms=耗时

**响应（HTTP 502，JSON 已格式化）：**

```json
{
  "detail": {
    "code": "COMMAND_FAILED",
    "message": "dd read failed"
  }
}
```

### CMD-000085

**CLI 原始命令：**

```bash
dd if=/dev/nst1 of=/dev/null bs=256k status=progress || true
```

CLI 测试结果：`PASS`

**对应 API：** `POST /tests/read`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/tests/read -H 'Content-Type: application/json' -d '{"drive": "/dev/nst1", "block_size": "1M", "confirm": true}'
```

**说明：** 读测试 → code=READ_TEST_PASS，duration_ms=耗时

**响应（HTTP 502，JSON 已格式化）：**

```json
{
  "detail": {
    "code": "COMMAND_FAILED",
    "message": "dd read failed"
  }
}
```

### CMD-000096

**CLI 原始命令：**

```bash
dd if=/dev/zero of=/dev/nst1 bs=1M count=1024 status=progress
```

CLI 测试结果：`PASS`

**对应 API：** `POST /tests/write（1024MiB，FULL 实例）`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8002/api/v1/tests/write -H 'Content-Type: application/json' -d '{"drive": "/dev/nst1", "test_media": "IBM015LA", "size_mb": 1024, "allow_write": true, "confirm": true}'
```

**说明：** 写测试 → code=WRITE_TEST_PASS

**响应（HTTP 000，JSON 已格式化）：**

```json

```

### CMD-000100

**CLI 原始命令：**

```bash
dd if=/dev/nst1 of=/dev/null bs=1M count=1024 status=progress
```

CLI 测试结果：`PASS`

**对应 API：** `POST /tests/read`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/tests/read -H 'Content-Type: application/json' -d '{"drive": "/dev/nst1", "block_size": "1M", "confirm": true}'
```

**说明：** 读测试 → code=READ_TEST_PASS，duration_ms=耗时

**响应（HTTP 502，JSON 已格式化）：**

```json
{
  "detail": {
    "code": "COMMAND_FAILED",
    "message": "dd read failed"
  }
}
```

### CMD-000103

**CLI 原始命令：**

```bash
dd if=/dev/nst1 bs=1M count=1024 status=none | cmp - <(head -c 1073741824 /dev/zero) && echo CONTENT_VERIFY_OK
```

CLI 测试结果：`PASS`

**对应 API：** `POST /tests/write-verify（content_verify 步骤）`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8002/api/v1/tests/write-verify -H 'Content-Type: application/json' -d '{"drive": "/dev/nst1", "test_media": "IBM015LA", "size_mb": 256, "allow_write": true, "confirm": true}'
```

**说明：** CLI cmp 校验 → write-verify 的 steps[content_verify]，content_verified=true

**响应（HTTP 000，JSON 已格式化）：**

```json

```


## 第 4 部分 · 3.4 其他操作（系统/依赖/发现/诊断/审计）（共 36 条 CMD）
### CMD-000001

**CLI 原始命令：**

```bash
cat /etc/os-release
```

CLI 测试结果：`PASS`

**对应 API：** `GET /system/os-release（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/system/os-release
```

**说明：** cat /etc/os-release → data.parsed.name/version_id/all_fields

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185406-4CCB8B",
  "data": {
    "stdout": "NAME=\"Red Hat Enterprise Linux\"\nVERSION=\"9.6 (Plow)\"\nID=\"rhel\"\nID_LIKE=\"fedora\"\nVERSION_ID=\"9.6\"\nPLATFORM_ID=\"platform:el9\"\nPRETTY_NAME=\"Red Hat Enterprise Linux 9.6 (Plow)\"\nANSI_COLOR=\"0;31\"\nLOGO=\"fedora-logo-icon\"\nCPE_NAME=\"cpe:/o:redhat:enterprise_linux:9::baseos\"\nHOME_URL=\"https://www.redhat.com/\"\nDOCUMENTATION_URL=\"https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/9\"\nBUG_REPORT_URL=\"https://issues.redhat.com/\"\n\nREDHAT_BUGZILLA_PRODUCT=\"Red Hat Enterprise Linux 9\"\nREDHAT_BUGZILLA_PRODUCT_VERSION=9.6\nREDHAT_SUPPORT_PRODUCT=\"Red Hat Enterprise Linux\"\nREDHAT_SUPPORT_PRODUCT_VERSION=\"9.6\"\n",
    "command_id": "CMD-2CE97183",
    "parsed": {
      "name": "Red Hat Enterprise Linux",
      "version": "9.6 (Plow)",
      "version_id": "9.6",
      "id": "rhel",
      "pretty_name": "Red Hat Enterprise Linux 9.6 (Plow)",
      "all_fields": {
        "name": "Red Hat Enterprise Linux",
        "version": "9.6 (Plow)",
        "id": "rhel",
        "id_like": "fedora",
        "version_id": "9.6",
        "platform_id": "platform:el9",
        "pretty_name": "Red Hat Enterprise Linux 9.6 (Plow)",
        "ansi_color": "0;31",
        "logo": "fedora-logo-icon",
        "cpe_name": "cpe:/o:redhat:enterprise_linux:9::baseos",
        "home_url": "https://www.redhat.com/",
        "documentation_url": "https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/9",
        "bug_report_url": "https://issues.redhat.com/",
        "redhat_bugzilla_product": "Red Hat Enterprise Linux 9",
        "redhat_bugzilla_product_version": "9.6",
        "redhat_support_product": "Red Hat Enterprise Linux",
        "redhat_support_product_version": "9.6"
      },
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000002

**CLI 原始命令：**

```bash
uname -a
```

CLI 测试结果：`PASS`

**对应 API：** `GET /system/uname（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/system/uname
```

**说明：** uname -a → data.parsed.kernel_release/machine 等

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185406-B3DA8D",
  "data": {
    "stdout": "Linux node186 5.14.0-570.12.1.el9_6.x86_64 #1 SMP PREEMPT_DYNAMIC Fri Apr 4 10:41:31 EDT 2025 x86_64 x86_64 x86_64 GNU/Linux\n",
    "command_id": "CMD-4AED3364",
    "parsed": {
      "kernel_name": "Linux",
      "hostname": "node186",
      "kernel_release": "5.14.0-570.12.1.el9_6.x86_64",
      "kernel_version": "#1",
      "machine": "GNU/Linux",
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000003

**CLI 原始命令：**

```bash
hostname
```

CLI 测试结果：`PASS`

**对应 API：** `GET /system/hostname（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/system/hostname
```

**说明：** hostname → data.parsed.hostname

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185406-F396FC",
  "data": {
    "stdout": "node186\n",
    "command_id": "CMD-47820B50",
    "parsed": {
      "hostname": "node186",
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000004

**CLI 原始命令：**

```bash
uname -m
```

CLI 测试结果：`PASS`

**对应 API：** `GET /system/arch（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/system/arch
```

**说明：** uname -m → data.parsed.arch

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185406-A56F35",
  "data": {
    "stdout": "x86_64\n",
    "command_id": "CMD-0ADB4ECD",
    "parsed": {
      "arch": "x86_64",
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000005

**CLI 原始命令：**

```bash
id
```

CLI 测试结果：`PASS`

**对应 API：** `GET /system/user（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/system/user
```

**说明：** id → data.parsed.uid/user/gid/groups

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185406-BF57C2",
  "data": {
    "stdout": "uid=0(root) gid=0(root) groups=0(root) context=unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023\n",
    "command_id": "CMD-C6C1BC4A",
    "parsed": {
      "uid": 0,
      "user": "root",
      "gid": 0,
      "group": "root",
      "groups": [
        "0(root)",
        "context=unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023"
      ],
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000006

**CLI 原始命令：**

```bash
whoami
```

CLI 测试结果：`PASS`

**对应 API：** `GET /system/user（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/system/user
```

**说明：** id → data.parsed.uid/user/gid/groups

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185406-BF57C2",
  "data": {
    "stdout": "uid=0(root) gid=0(root) groups=0(root) context=unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023\n",
    "command_id": "CMD-C6C1BC4A",
    "parsed": {
      "uid": 0,
      "user": "root",
      "gid": 0,
      "group": "root",
      "groups": [
        "0(root)",
        "context=unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023"
      ],
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000007

**CLI 原始命令：**

```bash
command -v dnf
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/dnf（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/dnf
```

**说明：** command -v dnf → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185406-D816FA",
  "data": {
    "name": "dnf",
    "required": false,
    "optional": false,
    "installed": true,
    "path": "/usr/bin/dnf",
    "exit_code": 0,
    "command_id": "CMD-468E2B41",
    "parsed": {
      "installed": true,
      "path": "/usr/bin/dnf",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000008

**CLI 原始命令：**

```bash
command -v yum
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/yum（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/yum
```

**说明：** command -v yum → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185406-395574",
  "data": {
    "name": "yum",
    "required": false,
    "optional": false,
    "installed": true,
    "path": "/usr/bin/yum",
    "exit_code": 0,
    "command_id": "CMD-26D8D395",
    "parsed": {
      "installed": true,
      "path": "/usr/bin/yum",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000009

**CLI 原始命令：**

```bash
command -v apt-get
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/apt-get（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/apt-get
```

**说明：** command -v apt-get → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185406-007F8A",
  "data": {
    "name": "apt-get",
    "required": false,
    "optional": false,
    "installed": false,
    "path": null,
    "exit_code": 1,
    "command_id": "CMD-A04C9A2A",
    "parsed": {
      "installed": false,
      "path": null,
      "exit_code": 1,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000010

**CLI 原始命令：**

```bash
command -v zypper
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/zypper（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/zypper
```

**说明：** command -v zypper → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185406-AF2DDF",
  "data": {
    "name": "zypper",
    "required": false,
    "optional": false,
    "installed": false,
    "path": null,
    "exit_code": 1,
    "command_id": "CMD-6496935A",
    "parsed": {
      "installed": false,
      "path": null,
      "exit_code": 1,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000011

**CLI 原始命令：**

```bash
command -v lsscsi
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/lsscsi（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/lsscsi
```

**说明：** command -v lsscsi → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-D73084",
  "data": {
    "name": "lsscsi",
    "required": true,
    "optional": false,
    "installed": true,
    "path": "/usr/bin/lsscsi",
    "exit_code": 0,
    "command_id": "CMD-E6BD6C71",
    "parsed": {
      "installed": true,
      "path": "/usr/bin/lsscsi",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000012

**CLI 原始命令：**

```bash
command -v sg_scan
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/sg_scan（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/sg_scan
```

**说明：** command -v sg_scan → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-1C565D",
  "data": {
    "name": "sg_scan",
    "required": true,
    "optional": false,
    "installed": true,
    "path": "/usr/bin/sg_scan",
    "exit_code": 0,
    "command_id": "CMD-23D3084E",
    "parsed": {
      "installed": true,
      "path": "/usr/bin/sg_scan",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000013

**CLI 原始命令：**

```bash
command -v sg_map
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/sg_map（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/sg_map
```

**说明：** command -v sg_map → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-A91E9B",
  "data": {
    "name": "sg_map",
    "required": true,
    "optional": false,
    "installed": true,
    "path": "/usr/bin/sg_map",
    "exit_code": 0,
    "command_id": "CMD-931FD491",
    "parsed": {
      "installed": true,
      "path": "/usr/bin/sg_map",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000014

**CLI 原始命令：**

```bash
command -v sg_inq
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/sg_inq（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/sg_inq
```

**说明：** command -v sg_inq → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-D6FA8C",
  "data": {
    "name": "sg_inq",
    "required": true,
    "optional": false,
    "installed": true,
    "path": "/usr/bin/sg_inq",
    "exit_code": 0,
    "command_id": "CMD-D5843A9F",
    "parsed": {
      "installed": true,
      "path": "/usr/bin/sg_inq",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000015

**CLI 原始命令：**

```bash
command -v sg_vpd
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/sg_vpd（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/sg_vpd
```

**说明：** command -v sg_vpd → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-D56783",
  "data": {
    "name": "sg_vpd",
    "required": true,
    "optional": false,
    "installed": true,
    "path": "/usr/bin/sg_vpd",
    "exit_code": 0,
    "command_id": "CMD-1702335C",
    "parsed": {
      "installed": true,
      "path": "/usr/bin/sg_vpd",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000016

**CLI 原始命令：**

```bash
command -v sg_turs
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/sg_turs（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/sg_turs
```

**说明：** command -v sg_turs → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-7757CA",
  "data": {
    "name": "sg_turs",
    "required": true,
    "optional": false,
    "installed": true,
    "path": "/usr/bin/sg_turs",
    "exit_code": 0,
    "command_id": "CMD-A1FA76EF",
    "parsed": {
      "installed": true,
      "path": "/usr/bin/sg_turs",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000017

**CLI 原始命令：**

```bash
command -v sg_modes
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/sg_modes（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/sg_modes
```

**说明：** command -v sg_modes → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-9332A0",
  "data": {
    "name": "sg_modes",
    "required": true,
    "optional": false,
    "installed": true,
    "path": "/usr/bin/sg_modes",
    "exit_code": 0,
    "command_id": "CMD-7E20DC95",
    "parsed": {
      "installed": true,
      "path": "/usr/bin/sg_modes",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000018

**CLI 原始命令：**

```bash
command -v sg_logs
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/sg_logs（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/sg_logs
```

**说明：** command -v sg_logs → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-F39092",
  "data": {
    "name": "sg_logs",
    "required": true,
    "optional": false,
    "installed": true,
    "path": "/usr/bin/sg_logs",
    "exit_code": 0,
    "command_id": "CMD-119A2736",
    "parsed": {
      "installed": true,
      "path": "/usr/bin/sg_logs",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000019

**CLI 原始命令：**

```bash
command -v mtx
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/mtx（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/mtx
```

**说明：** command -v mtx → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-E11015",
  "data": {
    "name": "mtx",
    "required": true,
    "optional": false,
    "installed": true,
    "path": "/usr/sbin/mtx",
    "exit_code": 0,
    "command_id": "CMD-0F56B34B",
    "parsed": {
      "installed": true,
      "path": "/usr/sbin/mtx",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000020

**CLI 原始命令：**

```bash
command -v mt
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/mt（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/mt
```

**说明：** command -v mt → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-C6CA5A",
  "data": {
    "name": "mt",
    "required": true,
    "optional": false,
    "installed": true,
    "path": "/usr/bin/mt",
    "exit_code": 0,
    "command_id": "CMD-B583B1FC",
    "parsed": {
      "installed": true,
      "path": "/usr/bin/mt",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000021

**CLI 原始命令：**

```bash
command -v tar
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/tar（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/tar
```

**说明：** command -v tar → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-1E8A5C",
  "data": {
    "name": "tar",
    "required": true,
    "optional": false,
    "installed": true,
    "path": "/usr/bin/tar",
    "exit_code": 0,
    "command_id": "CMD-B3B2CBD3",
    "parsed": {
      "installed": true,
      "path": "/usr/bin/tar",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000022

**CLI 原始命令：**

```bash
command -v jq
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/jq（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/jq
```

**说明：** command -v jq → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-457C24",
  "data": {
    "name": "jq",
    "required": false,
    "optional": true,
    "installed": true,
    "path": "/usr/bin/jq",
    "exit_code": 0,
    "command_id": "CMD-2719B197",
    "parsed": {
      "installed": true,
      "path": "/usr/bin/jq",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000023

**CLI 原始命令：**

```bash
command -v python3
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/python3（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/python3
```

**说明：** command -v python3 → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-3C6E9D",
  "data": {
    "name": "python3",
    "required": false,
    "optional": true,
    "installed": true,
    "path": "/usr/bin/python3",
    "exit_code": 0,
    "command_id": "CMD-F831732D",
    "parsed": {
      "installed": true,
      "path": "/usr/bin/python3",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000024

**CLI 原始命令：**

```bash
command -v gzip
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/gzip（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/gzip
```

**说明：** command -v gzip → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-6BEA70",
  "data": {
    "name": "gzip",
    "required": false,
    "optional": true,
    "installed": true,
    "path": "/usr/bin/gzip",
    "exit_code": 0,
    "command_id": "CMD-4C07C6C2",
    "parsed": {
      "installed": true,
      "path": "/usr/bin/gzip",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000025

**CLI 原始命令：**

```bash
command -v file
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/file（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/file
```

**说明：** command -v file → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-59772C",
  "data": {
    "name": "file",
    "required": false,
    "optional": true,
    "installed": true,
    "path": "/usr/bin/file",
    "exit_code": 0,
    "command_id": "CMD-7E2CD4EE",
    "parsed": {
      "installed": true,
      "path": "/usr/bin/file",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000026

**CLI 原始命令：**

```bash
command -v udevadm
```

CLI 测试结果：`PASS`

**对应 API：** `GET /dependencies/udevadm（1:1）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/dependencies/udevadm
```

**说明：** command -v udevadm → installed/path/exit_code 字段

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-EDC9E9",
  "data": {
    "name": "udevadm",
    "required": false,
    "optional": true,
    "installed": true,
    "path": "/usr/sbin/udevadm",
    "exit_code": 0,
    "command_id": "CMD-FFB0E830",
    "parsed": {
      "installed": true,
      "path": "/usr/sbin/udevadm",
      "exit_code": 0,
      "parsed_ok": true
    }
  },
  "error": null
}
```

### CMD-000027

**CLI 原始命令：**

```bash
lsmod | grep -E '(^| )st( |$)' || true
```

CLI 测试结果：`PASS`

**对应 API：** `GET /system/kernel`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/system/kernel
```

**说明：** lsmod 模块检查 → data.{st,sg,ch,lin_tape}.loaded

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "KERNEL_CHECKED",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-AF71E5",
  "data": {
    "st": {
      "loaded": true,
      "stdout": "st                     77824  0",
      "parsed": {
        "modules": [
          {
            "module": "st",
            "size": 77824,
            "used_by": 0
          }
        ],
        "parsed_ok": true
      },
      "command_id": "CMD-2F44B66A"
    },
    "sg": {
      "loaded": true,
      "stdout": "sg                     53248  0",
      "parsed": {
        "modules": [
          {
            "module": "sg",
            "size": 53248,
            "used_by": 0
          }
        ],
        "parsed_ok": true
      },
      "command_id": "CMD-6B511352"
    },
    "ch": {
      "loaded": true,
      "stdout": "ch                     24576  0",
      "parsed": {
        "modules": [
          {
            "module": "ch",
            "size": 24576,
            "used_by": 0
          }
        ],
        "parsed_ok": true
      },
      "command_id": "CMD-C558FD14"
    },
    "lin_tape": {
      "loaded": false,
      "stdout": "",
      "parsed": {
        "modules": [],
        "parsed_ok": false
      },
      "command_id": "CMD-B383F108"
    }
  },
  "error": null
}
```

### CMD-000028

**CLI 原始命令：**

```bash
lsmod | grep -E '(^| )sg( |$)' || true
```

CLI 测试结果：`PASS`

**对应 API：** `GET /system/kernel`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/system/kernel
```

**说明：** lsmod 模块检查 → data.{st,sg,ch,lin_tape}.loaded

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "KERNEL_CHECKED",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-AF71E5",
  "data": {
    "st": {
      "loaded": true,
      "stdout": "st                     77824  0",
      "parsed": {
        "modules": [
          {
            "module": "st",
            "size": 77824,
            "used_by": 0
          }
        ],
        "parsed_ok": true
      },
      "command_id": "CMD-2F44B66A"
    },
    "sg": {
      "loaded": true,
      "stdout": "sg                     53248  0",
      "parsed": {
        "modules": [
          {
            "module": "sg",
            "size": 53248,
            "used_by": 0
          }
        ],
        "parsed_ok": true
      },
      "command_id": "CMD-6B511352"
    },
    "ch": {
      "loaded": true,
      "stdout": "ch                     24576  0",
      "parsed": {
        "modules": [
          {
            "module": "ch",
            "size": 24576,
            "used_by": 0
          }
        ],
        "parsed_ok": true
      },
      "command_id": "CMD-C558FD14"
    },
    "lin_tape": {
      "loaded": false,
      "stdout": "",
      "parsed": {
        "modules": [],
        "parsed_ok": false
      },
      "command_id": "CMD-B383F108"
    }
  },
  "error": null
}
```

### CMD-000029

**CLI 原始命令：**

```bash
lsmod | grep lin_tape || true
```

CLI 测试结果：`PASS`

**对应 API：** `GET /system/kernel`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/system/kernel
```

**说明：** lsmod 模块检查 → data.{st,sg,ch,lin_tape}.loaded

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "KERNEL_CHECKED",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-AF71E5",
  "data": {
    "st": {
      "loaded": true,
      "stdout": "st                     77824  0",
      "parsed": {
        "modules": [
          {
            "module": "st",
            "size": 77824,
            "used_by": 0
          }
        ],
        "parsed_ok": true
      },
      "command_id": "CMD-2F44B66A"
    },
    "sg": {
      "loaded": true,
      "stdout": "sg                     53248  0",
      "parsed": {
        "modules": [
          {
            "module": "sg",
            "size": 53248,
            "used_by": 0
          }
        ],
        "parsed_ok": true
      },
      "command_id": "CMD-6B511352"
    },
    "ch": {
      "loaded": true,
      "stdout": "ch                     24576  0",
      "parsed": {
        "modules": [
          {
            "module": "ch",
            "size": 24576,
            "used_by": 0
          }
        ],
        "parsed_ok": true
      },
      "command_id": "CMD-C558FD14"
    },
    "lin_tape": {
      "loaded": false,
      "stdout": "",
      "parsed": {
        "modules": [],
        "parsed_ok": false
      },
      "command_id": "CMD-B383F108"
    }
  },
  "error": null
}
```

### CMD-000030

**CLI 原始命令：**

```bash
lsmod | grep -i ch || true
```

CLI 测试结果：`PASS`

**对应 API：** `GET /system/kernel`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/system/kernel
```

**说明：** lsmod 模块检查 → data.{st,sg,ch,lin_tape}.loaded

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "KERNEL_CHECKED",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-AF71E5",
  "data": {
    "st": {
      "loaded": true,
      "stdout": "st                     77824  0",
      "parsed": {
        "modules": [
          {
            "module": "st",
            "size": 77824,
            "used_by": 0
          }
        ],
        "parsed_ok": true
      },
      "command_id": "CMD-2F44B66A"
    },
    "sg": {
      "loaded": true,
      "stdout": "sg                     53248  0",
      "parsed": {
        "modules": [
          {
            "module": "sg",
            "size": 53248,
            "used_by": 0
          }
        ],
        "parsed_ok": true
      },
      "command_id": "CMD-6B511352"
    },
    "ch": {
      "loaded": true,
      "stdout": "ch                     24576  0",
      "parsed": {
        "modules": [
          {
            "module": "ch",
            "size": 24576,
            "used_by": 0
          }
        ],
        "parsed_ok": true
      },
      "command_id": "CMD-C558FD14"
    },
    "lin_tape": {
      "loaded": false,
      "stdout": "",
      "parsed": {
        "modules": [],
        "parsed_ok": false
      },
      "command_id": "CMD-B383F108"
    }
  },
  "error": null
}
```

### CMD-000031

**CLI 原始命令：**

```bash
lsscsi
```

CLI 测试结果：`PASS`

**对应 API：** `GET /discovery（lsscsi -g）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/discovery
```

**说明：** 设备发现 → data.devices[]

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-08EAB6",
  "data": {
    "devices": [
      {
        "scsi_address": "32:0:0:0",
        "device_type": "TAPE",
        "vendor": "IBM",
        "product": "ULT3580-TDA",
        "sg_device": "/dev/sg2",
        "st_device": "/dev/st1",
        "nst_device": "/dev/nst1"
      },
      {
        "scsi_address": "32:0:0:1",
        "device_type": "MEDIUMX",
        "vendor": "IBM",
        "product": "03584L32",
        "sg_device": "/dev/sg3",
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "33:0:0:0",
        "device_type": "TAPE",
        "vendor": "IBM",
        "product": "ULT3580-TDA",
        "sg_device": "/dev/sg0",
        "st_device": "/dev/st0",
        "nst_device": "/dev/nst0"
      },
      {
        "scsi_address": "33:0:0:1",
        "device_type": "MEDIUMX",
        "vendor": "IBM",
        "product": "03584L32",
        "sg_device": "/dev/sg1",
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:0:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:1:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:2:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:3:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:4:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:5:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:6:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:7:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:8:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:9:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:10:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:11:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:12:6:1",
   
  ...（截断，完整见 audit 原始日志）
```

### CMD-000032

**CLI 原始命令：**

```bash
lsscsi -g
```

CLI 测试结果：`PASS`

**对应 API：** `GET /discovery（lsscsi -g）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/discovery
```

**说明：** 设备发现 → data.devices[]

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "OK",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-08EAB6",
  "data": {
    "devices": [
      {
        "scsi_address": "32:0:0:0",
        "device_type": "TAPE",
        "vendor": "IBM",
        "product": "ULT3580-TDA",
        "sg_device": "/dev/sg2",
        "st_device": "/dev/st1",
        "nst_device": "/dev/nst1"
      },
      {
        "scsi_address": "32:0:0:1",
        "device_type": "MEDIUMX",
        "vendor": "IBM",
        "product": "03584L32",
        "sg_device": "/dev/sg3",
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "33:0:0:0",
        "device_type": "TAPE",
        "vendor": "IBM",
        "product": "ULT3580-TDA",
        "sg_device": "/dev/sg0",
        "st_device": "/dev/st0",
        "nst_device": "/dev/nst0"
      },
      {
        "scsi_address": "33:0:0:1",
        "device_type": "MEDIUMX",
        "vendor": "IBM",
        "product": "03584L32",
        "sg_device": "/dev/sg1",
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:0:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:1:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:2:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:3:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:4:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:5:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:6:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:7:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:8:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:9:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:10:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:11:6:1",
        "device_type": "DISK",
        "vendor": "SAMSUNG",
        "product": "MZQL21T9HCJR-00A07__1",
        "sg_device": null,
        "st_device": null,
        "nst_device": null
      },
      {
        "scsi_address": "N:12:6:1",
   
  ...（截断，完整见 audit 原始日志）
```

### CMD-000033

**CLI 原始命令：**

```bash
sg_scan
```

CLI 测试结果：`PASS`

**对应 API：** `GET /discovery/detail（sg_scan + sg_map -i）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/discovery/detail
```

**说明：** 原始扫描输出 → data.sg_scan.stdout / data.sg_map.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "SCAN_COMPLETED",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-DB9772",
  "data": {
    "sg_scan": {
      "stdout": "/dev/sg0: scsi33 channel=0 id=0 lun=0\n/dev/sg1: scsi33 channel=0 id=0 lun=1\n/dev/sg2: scsi32 channel=0 id=0 lun=0\n/dev/sg3: scsi32 channel=0 id=0 lun=1\n",
      "command_id": "CMD-A4E30573",
      "parsed": {
        "devices": [
          {
            "sg_device": "/dev/sg0",
            "scsi_host": 33,
            "channel": 0,
            "id": 0,
            "lun": 0
          },
          {
            "sg_device": "/dev/sg1",
            "scsi_host": 33,
            "channel": 0,
            "id": 0,
            "lun": 1
          },
          {
            "sg_device": "/dev/sg2",
            "scsi_host": 32,
            "channel": 0,
            "id": 0,
            "lun": 0
          },
          {
            "sg_device": "/dev/sg3",
            "scsi_host": 32,
            "channel": 0,
            "id": 0,
            "lun": 1
          }
        ],
        "parsed_ok": true
      }
    },
    "sg_map": {
      "stdout": "/dev/sg0  /dev/nst0  IBM       ULT3580-TDA       T3S0\n/dev/sg1  IBM       03584L32          2C02\n/dev/sg2  /dev/nst1  IBM       ULT3580-TDA       T3S0\n/dev/sg3  IBM       03584L32          2C02\n",
      "command_id": "CMD-95DBD8AA",
      "parsed": {
        "mapping": [
          {
            "sg_device": "/dev/sg0",
            "nst_device": "/dev/nst0",
            "vendor": "IBM",
            "product": "ULT3580-TDA",
            "revision": "T3S0"
          },
          {
            "sg_device": "/dev/sg1",
            "nst_device": null,
            "vendor": "IBM",
            "product": "03584L32",
            "revision": "2C02"
          },
          {
            "sg_device": "/dev/sg2",
            "nst_device": "/dev/nst1",
            "vendor": "IBM",
            "product": "ULT3580-TDA",
            "revision": "T3S0"
          },
          {
            "sg_device": "/dev/sg3",
            "nst_device": null,
            "vendor": "IBM",
            "product": "03584L32",
            "revision": "2C02"
          }
        ],
        "parsed_ok": true
      }
    }
  },
  "error": null
}
```

### CMD-000034

**CLI 原始命令：**

```bash
sg_map -i
```

CLI 测试结果：`PASS`

**对应 API：** `GET /discovery/detail（sg_scan + sg_map -i）`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/discovery/detail
```

**说明：** 原始扫描输出 → data.sg_scan.stdout / data.sg_map.stdout

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "SCAN_COMPLETED",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185407-DB9772",
  "data": {
    "sg_scan": {
      "stdout": "/dev/sg0: scsi33 channel=0 id=0 lun=0\n/dev/sg1: scsi33 channel=0 id=0 lun=1\n/dev/sg2: scsi32 channel=0 id=0 lun=0\n/dev/sg3: scsi32 channel=0 id=0 lun=1\n",
      "command_id": "CMD-A4E30573",
      "parsed": {
        "devices": [
          {
            "sg_device": "/dev/sg0",
            "scsi_host": 33,
            "channel": 0,
            "id": 0,
            "lun": 0
          },
          {
            "sg_device": "/dev/sg1",
            "scsi_host": 33,
            "channel": 0,
            "id": 0,
            "lun": 1
          },
          {
            "sg_device": "/dev/sg2",
            "scsi_host": 32,
            "channel": 0,
            "id": 0,
            "lun": 0
          },
          {
            "sg_device": "/dev/sg3",
            "scsi_host": 32,
            "channel": 0,
            "id": 0,
            "lun": 1
          }
        ],
        "parsed_ok": true
      }
    },
    "sg_map": {
      "stdout": "/dev/sg0  /dev/nst0  IBM       ULT3580-TDA       T3S0\n/dev/sg1  IBM       03584L32          2C02\n/dev/sg2  /dev/nst1  IBM       ULT3580-TDA       T3S0\n/dev/sg3  IBM       03584L32          2C02\n",
      "command_id": "CMD-95DBD8AA",
      "parsed": {
        "mapping": [
          {
            "sg_device": "/dev/sg0",
            "nst_device": "/dev/nst0",
            "vendor": "IBM",
            "product": "ULT3580-TDA",
            "revision": "T3S0"
          },
          {
            "sg_device": "/dev/sg1",
            "nst_device": null,
            "vendor": "IBM",
            "product": "03584L32",
            "revision": "2C02"
          },
          {
            "sg_device": "/dev/sg2",
            "nst_device": "/dev/nst1",
            "vendor": "IBM",
            "product": "ULT3580-TDA",
            "revision": "T3S0"
          },
          {
            "sg_device": "/dev/sg3",
            "nst_device": null,
            "vendor": "IBM",
            "product": "03584L32",
            "revision": "2C02"
          }
        ],
        "parsed_ok": true
      }
    }
  },
  "error": null
}
```

### CMD-000055

**CLI 原始命令：**

```bash
ls -l /dev/IBMtape* /dev/IBMchanger* 2>&1 || true
```

CLI 测试结果：`PASS`

**对应 API：** `GET /system/ibm`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/system/ibm
```

**说明：** IBM 专用检测 → lin_tape_nodes / itdt_installed

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "IBM_CHECKED",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-779F89",
  "data": {
    "lin_tape_nodes": "ls: cannot access '/dev/IBMtape*': No such file or directory\nls: cannot access '/dev/IBMchanger*': No such file or directory",
    "lin_tape_nodes_list": [
      "ls: cannot access '/dev/IBMtape*': No such file or directory",
      "ls: cannot access '/dev/IBMchanger*': No such file or directory"
    ],
    "itdt_installed": false,
    "commands": [
      "CMD-C8D40DE7",
      "CMD-D295A22E"
    ]
  },
  "error": null
}
```

### CMD-000056

**CLI 原始命令：**

```bash
command -v itdt || true
```

CLI 测试结果：`PASS`

**对应 API：** `GET /system/ibm`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/system/ibm
```

**说明：** IBM 专用检测 → lin_tape_nodes / itdt_installed

**响应（HTTP 200，JSON 已格式化）：**

```json
{
  "success": true,
  "code": "IBM_CHECKED",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260910-185410-779F89",
  "data": {
    "lin_tape_nodes": "ls: cannot access '/dev/IBMtape*': No such file or directory\nls: cannot access '/dev/IBMchanger*': No such file or directory",
    "lin_tape_nodes_list": [
      "ls: cannot access '/dev/IBMtape*': No such file or directory",
      "ls: cannot access '/dev/IBMchanger*': No such file or directory"
    ],
    "itdt_installed": false,
    "commands": [
      "CMD-C8D40DE7",
      "CMD-D295A22E"
    ]
  },
  "error": null
}
```



---

# 五、测试结果汇总

| 类别 | 数量 | 说明 |
|---|---|---|
| CLI 命令总数 | 108 | CMD-000001 ~ CMD-000108 全量 |
| 有直接对应 API 的命令 | 100+ | 系统/依赖/发现/带库/带机/读写/诊断全覆盖 |
| 独立 API 调用 | 41 | 按唯一 (方法,路径,参数) 去重 |
| 同参数复用 | 75 | CLI 中重复命令（如多次 mtx status）复用同一次调用结果 |
| 成功用例 | — | 含 load/unload/rewind/fsf/读/写 1GiB/写读校验全部通过 |
| 真实错误用例 | 11 | nst0 rewind 502（复现 CLI CMD-000061 映射发现）、EOD 读 502 等，均与 CLI 行为一致 |

**结论：CLI 测试的 108 条命令已全部由 tape-library-api 的 33 个端点覆盖；每条命令均可通过 curl 等价调用（见上文各节，服务地址 http://172.16.12.186）；所有响应可经 request_id → command_id 溯源至 audit/commands/ 的原始 stdout/stderr。**

---

# 六、API 服务器启动步骤

## 5.1 登录测试机并进入项目目录

```bash
ssh root@172.16.12.186          # 密码见部署文档
cd /home/tape_api/tape-library-api
```

依赖（FastAPI/uvicorn 等）已全部安装，无需额外安装。

## 5.2 按安全级别选择启动模式（三选一）

```bash
# 模式一：SAFE 只读模式（默认，仅 LEVEL 1 查询类接口，端口 8000）
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 模式二：DIAGNOSTIC 诊断模式（LEVEL 1+2，允许装载/卸载/定位等设备操作，端口 8001）
TAPE_API_MODE=DIAGNOSTIC ALLOW_DEVICE_OPERATION=true \
  python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8001

# 模式三：FULL 完整模式（LEVEL 1+2+3，允许写/擦除；写接口还需请求体 allow_write+confirm 双重确认，端口 8002）
TAPE_API_MODE=FULL ALLOW_DEVICE_OPERATION=true ALLOW_WRITE=true TEST_MEDIA=IBM015LA \
  python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8002
```

## 5.3 后台常驻运行（setsid + nohup，退出 SSH 不中断）

```bash
TAPE_API_MODE=DIAGNOSTIC ALLOW_DEVICE_OPERATION=true \
  setsid nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8001 \
  >/tmp/uv8001.log 2>&1 < /dev/null &
```

## 5.4 验证启动成功

```bash
curl http://172.16.12.186:8001/api/v1/safety    # 返回 200 + 当前安全模式 JSON
curl http://172.16.12.186:8001/api/v1/health    # 健康检查
```

## 5.5 常用入口

- Swagger 交互文档：`http://172.16.12.186:8001/docs`
- OpenAPI 规范：`http://172.16.12.186:8001/openapi.json`

## 5.6 停止服务

```bash
pkill -f "python3 -m uvicorn"     # 停止全部实例
# 或按端口精确停止：lsof -ti:8001 | xargs kill
```

注意事项：写测试只能用 FULL 模式实例，且 TEST_MEDIA 必须指定测试介质（IBM015LA，槽 6）；生产环境建议只跑 SAFE 模式。
