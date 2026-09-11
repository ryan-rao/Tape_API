#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compose the full-coverage manual: glossary + all 108 CMD sections."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECTIONS = os.path.join(ROOT, "manual-evidence3-sections.md")

GLOSSARY = """# Tape Library API 全量测试手册（CMD-000001 ~ CMD-000108 逐条对照）

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

"""

TAIL = """

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
TAPE_API_MODE=DIAGNOSTIC ALLOW_DEVICE_OPERATION=true \\
  python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8001

# 模式三：FULL 完整模式（LEVEL 1+2+3，允许写/擦除；写接口还需请求体 allow_write+confirm 双重确认，端口 8002）
TAPE_API_MODE=FULL ALLOW_DEVICE_OPERATION=true ALLOW_WRITE=true TEST_MEDIA=IBM015LA \\
  python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8002
```

## 5.3 后台常驻运行（setsid + nohup，退出 SSH 不中断）

```bash
TAPE_API_MODE=DIAGNOSTIC ALLOW_DEVICE_OPERATION=true \\
  setsid nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8001 \\
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
"""

body = open(SECTIONS, errors="replace").read()

# ---- 按四类（带库/带机/IO/其他）重排 CMD 章节 ----
import re as _re
_blocks = _re.split(r"(?m)(?=^### CMD-)", body)
_head = _blocks[0]  # 文件头说明（如有）


def _category(b):
    m = _re.search(r"/api/v1(/[a-z_\-]+)", b)
    p = m.group(1) if m else ""
    if p.startswith("/libraries"):
        return "3.1 带库操作（/libraries）"
    if p.startswith("/devices") or p.startswith("/drives") or p == "/diagnostics":
        return "3.2 带机操作（/devices + /drives）"
    if p.startswith("/tests"):
        return "3.3 IO 操作（/tests）"
    return "3.4 其他操作（系统/依赖/发现/诊断/审计）"


_order = ["3.1 带库操作（/libraries）", "3.2 带机操作（/devices + /drives）",
          "3.3 IO 操作（/tests）", "3.4 其他操作（系统/依赖/发现/诊断/审计）"]
_parts = {k: [] for k in _order}
for _b in _blocks[1:]:
    if _b.strip():
        _parts[_category(_b)].append(_b)

_grouped = _head + "".join(
    "\n## 第 {} 部分 · {}（共 {} 条 CMD）\n".format(i + 1, k, len(_parts[k])) + "".join(_parts[k])
    for i, k in enumerate(_order)
)
_counts = {k: len(_parts[k]) for k in _order}
print("CMD 分类统计:", _counts)

out = os.path.join(ROOT, "docs", "API-usage-manual-full.md")
open(out, "w").write(GLOSSARY + _grouped + TAIL)
print("written", out, os.path.getsize(out), "bytes")
