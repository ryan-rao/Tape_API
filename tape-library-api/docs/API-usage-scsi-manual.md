# SCSI 通用设备 API 文档：/api/v1/scsi/{device}/...

> 实例：http://172.16.12.186:8080（nginx→8001，FULL 模式）或直连 http://172.16.12.186:8001
> 测试设备：/dev/sg0（IBM ULT3580-TDA LTO5 磁带机）、/dev/sg1（更换器）｜测试时间：2026-09-12 17:52
> 设备参数支持 `/scsi/sg4/...` 简写或 `/scsi//dev/sg4/...` 全路径；5 个查询接口为 LEVEL 1，reset 为 LEVEL 2

---

### CMD-F58B63EF SCSI查询-标准查询: /api/v1/scsi/sg0/inquiry

**CLI 原始命令：**

```bash
sg_inq /dev/sg0
```

CLI 测试结果：`PASS`

**对应 API：** `GET /scsi/{device}/inquiry`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/scsi/sg0/inquiry | jq
```
**API 参数：** device（路径参数，sg 设备名）

**说明：** SCSI 标准 INQUIRY（厂商/型号/序列号等，LEVEL 1 只读）→ code=INQUIRY_SUCCESS，data.parsed 含结构化字段

**响应（HTTP 200，JSON 已格式化，stdout 节选）：**

```json
{
 "success": true,
 "code": "INQUIRY_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-175227-D03728",
 "data": {
  "device": "/dev/sg0",
  "stdout": "standard INQUIRY:\n  PQual=0  PDT=1  RMB=1 ...\n Vendor identification: IBM\n Product identification: ULT3580-TDA\n Product revision level: T3S0\n Unit serial number: 607B811E08",
  "command_id": "CMD-F58B63EF",
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

---

### CMD-A2208C51 SCSI查询-重要产品数据: /api/v1/scsi/sg0/vpd

**CLI 原始命令：**

```bash
sg_vpd -p 0x80 /dev/sg0
```

CLI 测试结果：`PASS`

**对应 API：** `GET /scsi/{device}/vpd?page=0x80`

**curl 调用：**

```bash
curl -s "http://172.16.12.186:8001/api/v1/scsi/sg0/vpd?page=0x80" | jq
```
**API 参数：**
* page: VPD 页码，0x80（序列号，默认）或 0x83（设备标识）

**说明：** 查询 VPD 重要产品数据页（LEVEL 1 只读）→ code=VPD_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "VPD_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-175227-D29323",
 "data": {
  "device": "/dev/sg0",
  "page": "0x80",
  "stdout": "Unit serial number VPD page:\n  Unit serial number: 607B811E08",
  "command_id": "CMD-A2208C51",
  "parsed": {
   "page_name": "Unit serial number VPD",
   "fields": {"unit_serial_number": "607B811E08"},
   "parsed_ok": true
  }
 },
 "error": null
}
```

---

### CMD-5A8CB079 SCSI查询-日志页: /api/v1/scsi/sg0/logs

**CLI 原始命令：**

```bash
sg_logs /dev/sg0
```

CLI 测试结果：`PASS`

**对应 API：** `GET /scsi/{device}/logs`（可选 `?page=0xNN` 查指定页）

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/scsi/sg0/logs | jq
```
**API 参数：** page 可选（十六进制页码如 0x2e，省略返回支持的日志页列表）

**说明：** 查询 SCSI 日志页（LEVEL 1 只读）→ code=LOGS_SUCCESS

**响应（HTTP 200，JSON 已格式化，stdout 节选）：**

```json
{
 "success": true,
 "code": "LOGS_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-175218-133202",
 "data": {
  "device": "/dev/sg0",
  "stdout": "    IBM       ULT3580-TDA       T3S0\nSupported log pages  [0x0]:\n    0x00        Supported log pages [sp]\n    0x02        Write error [we]\n    0x03        Read error [re]\n    0x06        Non medium [nm]\n    0x0c        Sequential access device [sad]\n    0x11        DT Device status [dtds]\n    0x12        Tape alert response [ta]...",
  "command_id": "CMD-5A8CB079"
 },
 "error": null
}
```

---

### CMD-FB51236F SCSI查询-磁带告警: /api/v1/scsi/sg0/tapealert

**CLI 原始命令：**

```bash
sg_logs -p 0x2e /dev/sg0
```

CLI 测试结果：`PASS`（64 项 TapeAlert 全部为 0，无告警）

**对应 API：** `GET /scsi/{device}/tapealert`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/scsi/sg0/tapealert | jq
```
**API 参数：** 无

**说明：** 查询 TapeAlert（0x2e）日志页：读/写告警、硬错误、介质寿命、清洗请求、温度/电压等（LEVEL 1 只读）→ code=TAPEALERT_SUCCESS

**响应（HTTP 200，JSON 已格式化，stdout 节选）：**

```json
{
 "success": true,
 "code": "TAPEALERT_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-175243-1A9E31",
 "data": {
  "device": "/dev/sg0",
  "stdout": "    IBM       ULT3580-TDA       T3S0\nTape alert page (ssc-3) [0x2e]\n  Read warning: 0\n  Write warning: 0\n  Hard error: 0\n  Media: 0\n  Read failure: 0\n  Write failure: 0\n  Media life: 0\n  ...\n  Predictive failure: 0\n  Diagnostics required: 0",
  "command_id": "CMD-FB51236F"
 },
 "error": null
}
```

---

### CMD-814EF041 SCSI查询-持久保留: /api/v1/scsi/sg0/persist

**CLI 原始命令：**

```bash
sg_persist /dev/sg0
```

CLI 测试结果：`PASS`（PR generation=0x10，无注册保留键）

**对应 API：** `GET /scsi/{device}/persist`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8001/api/v1/scsi/sg0/persist | jq
```
**API 参数：** 无

**说明：** 查询 SCSI 持久保留状态（LEVEL 1 只读）→ code=PERSIST_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "PERSIST_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-175243-7714A5",
 "data": {
  "device": "/dev/sg0",
  "stdout": "  IBM       ULT3580-TDA       T3S0\n  Peripheral device type: tape\n  PR generation=0x10, there are NO registered reservation keys",
  "command_id": "CMD-814EF041"
 },
 "error": null
}
```

---

### CMD-2B9B57BE SCSI操作-设备复位: /api/v1/scsi/sg0/reset

**CLI 原始命令：**

```bash
sg_reset -d /dev/sg0
```

CLI 测试结果：`PASS`（复位后驱动器状态正常）

**对应 API：** `POST /scsi/{device}/reset`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/scsi/sg0/reset -H 'Content-Type: application/json' -d '{"confirm": true}'
```
**API 参数：** confirm 必须为 true

**说明：** SCSI 设备复位（LEVEL 2，⚠️ 会中断该设备上的进行中 I/O；用于驱动器 D-state/挂死恢复）→ code=RESET_SUCCESS。复位后验证：mt status 正常

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "RESET_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-175218-DFEF30",
 "data": {
  "device": "/dev/sg0",
  "reset": "device",
  "command_id": "CMD-2B9B57BE"
 },
 "error": null
}
```

---

## 汇总表

| API | 方法 | 对应 OS 命令 | 结果码 | 实测 |
| --- | --- | --- | --- | --- |
| `/api/v1/scsi/{device}/inquiry` | GET | `sg_inq /dev/sg4` | INQUIRY_SUCCESS | ✅ |
| `/api/v1/scsi/{device}/vpd` | GET | `sg_vpd /dev/sg4` | VPD_SUCCESS | ✅ |
| `/api/v1/scsi/{device}/logs` | GET | `sg_logs /dev/sg4` | LOGS_SUCCESS | ✅ |
| `/api/v1/scsi/{device}/tapealert` | GET | `sg_logs -p 0x2e /dev/sg4` | TAPEALERT_SUCCESS | ✅ |
| `/api/v1/scsi/{device}/persist` | GET | `sg_persist /dev/sg4` | PERSIST_SUCCESS | ✅ |
| `/api/v1/scsi/{device}/reset` | POST | `sg_reset -d /dev/sg4` | RESET_SUCCESS | ✅ |
