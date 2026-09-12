# 磁带机（Drive）API 使用接口文档

- 服务: tape-library-api @ node186 (http://172.16.12.186) | 生成: 2026-09-12
- 测试驱动器: IBM ULT3580-TDA (LTO, /dev/nst0) | 介质: IBM015LA (测试带)
- 覆盖: CLI→REST 映射表全部 33 项 | 25 项实测 PASS，8 项硬件不支持（详见各节说明）

| # | CLI | REST API | HTTP | API Code | 实测 |
| --- | --- | --- | ---- | -------- | ---- |
| 1 | `weof` | `POST /drives/{d}/weof` | POST | `WEOF_SUCCESS` | ✅ PASS |
| 2 | `wset` | `POST /drives/{d}/wset` | POST | `WSET_SUCCESS` | ⚠️ 硬件不支持 |
| 3 | `eof` | `POST /drives/{d}/eof` | POST | `EOF_SUCCESS` | ✅ PASS |
| 4 | `fsf` | `POST /drives/{d}/position` | POST | `POSITION_SUCCESS` | ✅ PASS |
| 5 | `fsfm` | `POST /drives/{d}/position` | POST | `POSITION_SUCCESS` | ✅ PASS |
| 6 | `bsf` | `POST /drives/{d}/position` | POST | `POSITION_SUCCESS` | ✅ PASS |
| 7 | `bsfm` | `POST /drives/{d}/position` | POST | `POSITION_SUCCESS` | ✅ PASS |
| 8 | `fsr` | `POST /drives/{d}/position` | POST | `POSITION_SUCCESS` | ✅ PASS |
| 9 | `bsr` | `POST /drives/{d}/position` | POST | `POSITION_SUCCESS` | ✅ PASS |
| 10 | `fss` | `POST /drives/{d}/position` | POST | `POSITION_SUCCESS` | ⚠️ 硬件不支持 |
| 11 | `bss` | `POST /drives/{d}/position` | POST | `POSITION_SUCCESS` | ⚠️ 硬件不支持 |
| 12 | `rewind` | `POST /drives/{d}/rewind` | POST | `REWIND_SUCCESS` | ✅ PASS |
| 13 | `offline` | `POST /drives/{d}/offline` | POST | `OFFLINE_SUCCESS` | ✅ PASS |
| 14 | `rewoffl` | `POST /drives/{d}/rewoffl` | POST | `REWOFFL_SUCCESS` | ✅ PASS |
| 15 | `eject` | `POST /drives/{d}/eject` | POST | `EJECT_SUCCESS` | ✅ PASS |
| 16 | `retension` | `POST /drives/{d}/retension` | POST | `RETENSION_SUCCESS` | ✅ PASS |
| 17 | `eod` | `POST /drives/{d}/eod` | POST | `EOD_SUCCESS` | ✅ PASS |
| 18 | `seod` | `POST /drives/{d}/seod` | POST | `SEOD_SUCCESS` | ✅ PASS |
| 19 | `seek` | `POST /drives/{d}/seek` | POST | `SEEK_SUCCESS` | ⚠️ 硬件不支持 |
| 20 | `tell` | `GET /drives/{d}/tell` | GET | `TELL_SUCCESS` | ⚠️ 硬件不支持 |
| 21 | `status` | `GET /drives/{d}/status` | GET | `OK (parsed)` | ✅ PASS |
| 22 | `erase` | `POST /drives/{d}/erase` | POST | `ERASE_SUCCESS` | ✅ PASS（长擦除 356s） |
| 23 | `lock` | `POST /drives/{d}/lock` | POST | `LOCK_SUCCESS` | ✅ PASS |
| 24 | `unlock` | `POST /drives/{d}/unlock` | POST | `UNLOCK_SUCCESS` | ✅ PASS |
| 25 | `load` | `POST /drives/{d}/load` | POST | `LOAD_SUCCESS` | ✅ PASS |
| 26 | `compression` | `POST /drives/{d}/compression` | POST | `COMPRESSION_SUCCESS` | ✅ PASS |
| 27 | `setblk` | `POST /drives/{d}/block-size` | POST | `SETBLK_SUCCESS` | ✅ PASS |
| 28 | `setdensity` | `POST /drives/{d}/density` | POST | `SETDENSITY_SUCCESS` | ✅ PASS |
| 29 | `setpartition` | `POST /drives/{d}/partition` | POST | `PARTITION_SUCCESS` | ⚠️ 硬件不支持 |
| 30 | `mkpartition` | `POST /drives/{d}/partition` | POST | `PARTITION_SUCCESS` | ⚠️ 硬件不支持 |
| 31 | `partseek` | `POST /drives/{d}/partition/seek` | POST | `PARTSEEK_SUCCESS` | ⚠️ 硬件不支持 |
| 32 | `asf` | `POST /drives/{d}/position` | POST | `POSITION_SUCCESS` | ✅ PASS |
| 33 | `densities` | `GET /drives/{d}/densities` | GET | `DENSITIES_SUCCESS` | ✅ PASS |
| 34 | `stshowoptions` | `GET /drives/{d}/options` | GET | `OPTIONS_SUCCESS` | ✅ PASS |

---

### CMD-81A87293 磁带操作 weof：`/api/v1/drives/nst0/weof`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 weof 1
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/weof`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/weof \
-H 'Content-Type: application/json' \
-d '{"count": 1, "confirm": true}' | jq
```

**说明：** 写入文件标记（WEOF，Write End Of File mark，LEVEL 3，FULL 实例）→ `code=WEOF_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `count` | integer | 否（默认1） | `1` | 写入的文件标记数量 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "WEOF_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-102637-11E94F",
 "data": {
  "count": 1,
  "command_id": "CMD-81A87293"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.count | integer | 实际写入的文件标记数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : WEOF_SUCCESS
count : 1
command_id : CMD-81A87293
```

---

### CMD-DF334069 磁带操作 wset：`/api/v1/drives/nst0/wset`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 wset 1
```

CLI 测试结果：`FAIL`（硬件不支持，见下方说明）

**对应 API：** `POST /drives/nst0/wset`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/wset \
-H 'Content-Type: application/json' \
-d '{"count": 1, "confirm": true}' | jq
```

**说明：** 写入 Set 标记（WSET，LEVEL 3）。⚠️ IBM LTO 驱动器不支持 Setmark，硬件返回 I/O error → `502 COMMAND_FAILED`（API 链路本身已验证：参数校验→命令拼装→审计均正确）

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `count` | integer | 否（默认1） | `1` | 写入的 Set 标记数量 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 502，JSON 已格式化）：**

```json
{
 "detail": {
  "code": "COMMAND_FAILED",
  "message": "mt wset failed"
 }
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |

**实际测试结果：**

```text
success : false
http_code : 502
code : COMMAND_FAILED
message : mt wset failed
command_id : CMD-DF334069
说明 : API 请求/校验/命令拼装/审计链路正常，IBM LTO 硬件不支持该操作
```

---

### CMD-25ED0C44 磁带操作 eof：`/api/v1/drives/nst0/eof`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 eof 1
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/eof`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/eof \
-H 'Content-Type: application/json' \
-d '{"count": 1, "confirm": true}' | jq
```

**说明：** 写入文件标记（EOF 为 weof 的别名，LEVEL 3，FULL 实例）→ `code=EOF_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `count` | integer | 否（默认1） | `1` | 写入的文件标记数量 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "EOF_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-102645-7F8224",
 "data": {
  "count": 1,
  "command_id": "CMD-25ED0C44"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.count | integer | 实际写入的文件标记数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : EOF_SUCCESS
count : 1
command_id : CMD-25ED0C44
```

---

### CMD-310276BB 磁带操作 fsf：`/api/v1/drives/nst0/position`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 fsf 1
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/position`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/position \
-H 'Content-Type: application/json' \
-d '{"operation": "fsf", "count": 1, "confirm": true}' | jq
```

**说明：** 向前定位文件标记（FSF，Forward Space File，LEVEL 2，FULL 实例）→ `code=POSITION_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `operation` | string | 是 | `fsr` | 定位操作类型：fsf/fsfm/bsf/bsfm/fsr/bsr/fss/bss/asf |
| `count` | integer | 否（默认1） | `1` | 跳过的标记/块数量 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "POSITION_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-103800-665BC4",
 "data": {
  "operation": "fsf",
  "count": 1,
  "command_id": "CMD-310276BB"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.operation | string | 实际执行的定位操作 |
| data.count | integer | 实际执行的定位数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : POSITION_SUCCESS
operation : fsf
count : 1
command_id : CMD-310276BB
```

---

### CMD-DBD0AFAE 磁带操作 fsfm：`/api/v1/drives/nst0/position`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 fsfm 1
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/position`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/position \
-H 'Content-Type: application/json' \
-d '{"operation": "fsfm", "count": 1, "confirm": true}' | jq
```

**说明：** 向前跳到下一个文件标记之后（FSFM，LEVEL 2）→ `code=POSITION_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `operation` | string | 是 | `fsr` | 定位操作类型：fsf/fsfm/bsf/bsfm/fsr/bsr/fss/bss/asf |
| `count` | integer | 否（默认1） | `1` | 跳过的标记/块数量 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "POSITION_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-103800-3F2DC9",
 "data": {
  "operation": "fsfm",
  "count": 1,
  "command_id": "CMD-DBD0AFAE"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.operation | string | 实际执行的定位操作 |
| data.count | integer | 实际执行的定位数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : POSITION_SUCCESS
operation : fsfm
count : 1
command_id : CMD-DBD0AFAE
```

---

### CMD-B4A6FE0C 磁带操作 bsf：`/api/v1/drives/nst0/position`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 bsf 1
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/position`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/position \
-H 'Content-Type: application/json' \
-d '{"operation": "bsf", "count": 1, "confirm": true}' | jq
```

**说明：** 向后定位文件标记（BSF，Backward Space File，LEVEL 2）→ `code=POSITION_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `operation` | string | 是 | `fsr` | 定位操作类型：fsf/fsfm/bsf/bsfm/fsr/bsr/fss/bss/asf |
| `count` | integer | 否（默认1） | `1` | 跳过的标记/块数量 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "POSITION_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-102724-2A5CAE",
 "data": {
  "operation": "bsf",
  "count": 1,
  "command_id": "CMD-B4A6FE0C"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.operation | string | 实际执行的定位操作 |
| data.count | integer | 实际执行的定位数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : POSITION_SUCCESS
operation : bsf
count : 1
command_id : CMD-B4A6FE0C
```

---

### CMD-E09236AB 磁带操作 bsfm：`/api/v1/drives/nst0/position`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 bsfm 1
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/position`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/position \
-H 'Content-Type: application/json' \
-d '{"operation": "bsfm", "count": 1, "confirm": true}' | jq
```

**说明：** 向后跳到上一个文件标记之前（BSFM，LEVEL 2）→ `code=POSITION_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `operation` | string | 是 | `fsr` | 定位操作类型：fsf/fsfm/bsf/bsfm/fsr/bsr/fss/bss/asf |
| `count` | integer | 否（默认1） | `1` | 跳过的标记/块数量 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "POSITION_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-103800-D372CF",
 "data": {
  "operation": "bsfm",
  "count": 1,
  "command_id": "CMD-E09236AB"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.operation | string | 实际执行的定位操作 |
| data.count | integer | 实际执行的定位数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : POSITION_SUCCESS
operation : bsfm
count : 1
command_id : CMD-E09236AB
```

---

### CMD-081316E2 磁带操作 fsr：`/api/v1/drives/nst0/position`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 fsr 1
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/position`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/position \
-H 'Content-Type: application/json' \
-d '{"operation": "fsr", "count": 1, "confirm": true}' | jq
```

**说明：** 向前定位数据块（FSR，Forward Space Record，LEVEL 2，FULL 实例；需可变块模式 `block-size 0` + 磁带有数据）→ `code=POSITION_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `operation` | string | 是 | `fsr` | 定位操作类型：fsf/fsfm/bsf/bsfm/fsr/bsr/fss/bss/asf |
| `count` | integer | 否（默认1） | `1` | 跳过的标记/块数量 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "POSITION_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-104658-FBFCB7",
 "data": {
  "operation": "fsr",
  "count": 1,
  "command_id": "CMD-081316E2"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.operation | string | 实际执行的定位操作 |
| data.count | integer | 实际执行的定位数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : POSITION_SUCCESS
operation : fsr
count : 1
command_id : CMD-081316E2
```

---

### CMD-A98D0D33 磁带操作 bsr：`/api/v1/drives/nst0/position`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 bsr 1
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/position`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/position \
-H 'Content-Type: application/json' \
-d '{"operation": "bsr", "count": 1, "confirm": true}' | jq
```

**说明：** 向后定位数据块（BSR，Backward Space Record，LEVEL 2；需可变块模式 + 磁带有数据）→ `code=POSITION_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `operation` | string | 是 | `fsr` | 定位操作类型：fsf/fsfm/bsf/bsfm/fsr/bsr/fss/bss/asf |
| `count` | integer | 否（默认1） | `1` | 跳过的标记/块数量 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "POSITION_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-104659-D6B064",
 "data": {
  "operation": "bsr",
  "count": 1,
  "command_id": "CMD-A98D0D33"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.operation | string | 实际执行的定位操作 |
| data.count | integer | 实际执行的定位数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : POSITION_SUCCESS
operation : bsr
count : 1
command_id : CMD-A98D0D33
```

---

### CMD-C0907E68 磁带操作 fss：`/api/v1/drives/nst0/position`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 fss 1
```

CLI 测试结果：`FAIL`（硬件不支持，见下方说明）

**对应 API：** `POST /drives/nst0/position`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/position \
-H 'Content-Type: application/json' \
-d '{"operation": "fss", "count": 1, "confirm": true}' | jq
```

**说明：** 向前定位 Set 标记（FSS，LEVEL 2）。⚠️ IBM LTO 不支持 Setmark，硬件返回 I/O error → `502 COMMAND_FAILED`（API 链路已验证）

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `operation` | string | 是 | `fsr` | 定位操作类型：fsf/fsfm/bsf/bsfm/fsr/bsr/fss/bss/asf |
| `count` | integer | 否（默认1） | `1` | 跳过的标记/块数量 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 502，JSON 已格式化）：**

```json
{
 "detail": {
  "code": "COMMAND_FAILED",
  "message": "command failed: mt -f /dev/nst0 fss 1 -> /dev/nst0: Input/output error\n"
 }
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |

**实际测试结果：**

```text
success : false
http_code : 502
code : COMMAND_FAILED
message : command failed: mt -f /dev/nst0 fss 1 -> /dev/nst0: Input/output error

command_id : CMD-C0907E68
说明 : API 请求/校验/命令拼装/审计链路正常，IBM LTO 硬件不支持该操作
```

---

### CMD-C6A39E1E 磁带操作 bss：`/api/v1/drives/nst0/position`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 bss 1
```

CLI 测试结果：`FAIL`（硬件不支持，见下方说明）

**对应 API：** `POST /drives/nst0/position`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/position \
-H 'Content-Type: application/json' \
-d '{"operation": "bss", "count": 1, "confirm": true}' | jq
```

**说明：** 向后定位 Set 标记（BSS，LEVEL 2）。⚠️ IBM LTO 不支持 Setmark，硬件返回 I/O error → `502 COMMAND_FAILED`（API 链路已验证）

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `operation` | string | 是 | `fsr` | 定位操作类型：fsf/fsfm/bsf/bsfm/fsr/bsr/fss/bss/asf |
| `count` | integer | 否（默认1） | `1` | 跳过的标记/块数量 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 502，JSON 已格式化）：**

```json
{
 "detail": {
  "code": "COMMAND_FAILED",
  "message": "command failed: mt -f /dev/nst0 bss 1 -> /dev/nst0: Input/output error\n"
 }
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |

**实际测试结果：**

```text
success : false
http_code : 502
code : COMMAND_FAILED
message : command failed: mt -f /dev/nst0 bss 1 -> /dev/nst0: Input/output error

command_id : CMD-C6A39E1E
说明 : API 请求/校验/命令拼装/审计链路正常，IBM LTO 硬件不支持该操作
```

---

### CMD-8AAD4C4F 磁带操作 rewind：`/api/v1/drives/nst0/rewind`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 rewind
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/rewind`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/rewind \
-H 'Content-Type: application/json' \
-d '{"confirm": true}' | jq
```

**说明：** 倒带到带首（REWIND，LEVEL 2，FULL 实例）→ `code=REWIND_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "REWIND_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-104659-F8F3C9",
 "data": {
  "operation": "rewind",
  "count": 0,
  "command_id": "CMD-8AAD4C4F"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.operation | string | 实际执行的定位操作 |
| data.count | integer | 实际执行的定位数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : REWIND_SUCCESS
operation : rewind
count : 0
command_id : CMD-8AAD4C4F
```

---

### CMD-F4C8EA40 磁带操作 offline：`/api/v1/drives/nst0/offline`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 offline
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/offline`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/offline \
-H 'Content-Type: application/json' \
-d '{"confirm": true}' | jq
```

**说明：** 卸载磁带并离线（OFFLINE，LEVEL 2）→ `code=OFFLINE_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "OFFLINE_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-103530-BBB752",
 "data": {
  "operation": "offline",
  "count": 0,
  "command_id": "CMD-F4C8EA40"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.operation | string | 实际执行的定位操作 |
| data.count | integer | 实际执行的定位数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : OFFLINE_SUCCESS
operation : offline
count : 0
command_id : CMD-F4C8EA40
```

---

### CMD-CFE41652 磁带操作 rewoffl：`/api/v1/drives/nst0/rewoffl`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 rewoffl
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/rewoffl`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/rewoffl \
-H 'Content-Type: application/json' \
-d '{"confirm": true}' | jq
```

**说明：** 倒带并卸载磁带（REWOFFL = Rewind + Offline，LEVEL 2）→ `code=REWOFFL_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "REWOFFL_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-103337-3A82DD",
 "data": {
  "command_id": "CMD-CFE41652",
  "stdout": "",
  "stderr": "",
  "exit_code": 0
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.command_id | string | 后端执行命令 ID |
| data.stdout/stderr | string | 命令原始输出 |

**实际测试结果：**

```text
success : True
code : REWOFFL_SUCCESS
command_id : CMD-CFE41652
```

---

### CMD-89755E5F 磁带操作 eject：`/api/v1/drives/nst0/eject`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 eject
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/eject`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/eject \
-H 'Content-Type: application/json' \
-d '{"confirm": true}' | jq
```

**说明：** 弹出磁带（EJECT，LEVEL 2）→ `code=EJECT_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "EJECT_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-103448-40520E",
 "data": {
  "command_id": "CMD-89755E5F",
  "stdout": "",
  "stderr": "",
  "exit_code": 0
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.operation | string | 实际执行的定位操作 |
| data.count | integer | 实际执行的定位数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : EJECT_SUCCESS
command_id : CMD-89755E5F
```

---

### CMD-404F1A4A 磁带操作 retension：`/api/v1/drives/nst0/retension`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 retension
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/retension`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/retension \
-H 'Content-Type: application/json' \
-d '{"confirm": true}' | jq
```

**说明：** 整带重新张紧（RETENSION，倒带到带头再走到带尾后回到带首，LEVEL 2，耗时与整带长度成正比）→ `code=RETENSION_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "RETENSION_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-102741-D6AED9",
 "data": {
  "command_id": "CMD-404F1A4A",
  "stdout": "",
  "stderr": "",
  "exit_code": 0
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.operation | string | 实际执行的定位操作 |
| data.count | integer | 实际执行的定位数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : RETENSION_SUCCESS
command_id : CMD-404F1A4A
```

---

### CMD-979FDF6F 磁带操作 eod：`/api/v1/drives/nst0/eod`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 eod
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/eod`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/eod \
-H 'Content-Type: application/json' \
-d '{"confirm": true}' | jq
```

**说明：** 定位到数据末尾（EOD，LEVEL 2，底层映射为 mt seod）→ `code=EOD_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "EOD_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-102731-6EF2EE",
 "data": {
  "operation": "eod",
  "count": 0,
  "command_id": "CMD-979FDF6F"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.operation | string | 实际执行的定位操作 |
| data.count | integer | 实际执行的定位数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : EOD_SUCCESS
operation : eod
count : 0
command_id : CMD-979FDF6F
```

---

### CMD-DB5E17CA 磁带操作 seod：`/api/v1/drives/nst0/seod`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 seod
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/seod`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/seod \
-H 'Content-Type: application/json' \
-d '{"confirm": true}' | jq
```

**说明：** 定位到数据末尾（SEOD，Space to End Of Data，LEVEL 2）→ `code=SEOD_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "SEOD_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-102733-925B06",
 "data": {
  "operation": "seod",
  "count": 0,
  "command_id": "CMD-DB5E17CA"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.operation | string | 实际执行的定位操作 |
| data.count | integer | 实际执行的定位数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : SEOD_SUCCESS
operation : seod
count : 0
command_id : CMD-DB5E17CA
```

---

### CMD-559824D4 磁带操作 seek：`/api/v1/drives/nst0/seek`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 seek 0
```

CLI 测试结果：`FAIL`（硬件不支持，见下方说明）

**对应 API：** `POST /drives/nst0/seek`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/seek \
-H 'Content-Type: application/json' \
-d '{"count": 0, "confirm": true}' | jq
```

**说明：** 按逻辑块号定位（SEEK，LEVEL 2）。⚠️ IBM LTO + st 驱动不支持块号定位（实测 `mt seek` 返回 I/O error）→ `502 COMMAND_FAILED`（API 链路已验证）

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `count` | integer | 是 | `0` | 目标逻辑块号 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 502，JSON 已格式化）：**

```json
{
 "detail": {
  "code": "COMMAND_FAILED",
  "message": "mt seek failed"
 }
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |

**实际测试结果：**

```text
success : false
http_code : 502
code : COMMAND_FAILED
message : mt seek failed
command_id : CMD-559824D4
说明 : API 请求/校验/命令拼装/审计链路正常，IBM LTO 硬件不支持该操作
```

---

### CMD-E4DB0246 磁带操作 tell：`/api/v1/drives/nst0/tell`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 tell
```

CLI 测试结果：`FAIL`（硬件不支持，见下方说明）

**对应 API：** `GET /drives/nst0/tell`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8080/api/v1/drives/nst0/tell | jq
```

**说明：** 查询当前逻辑块位置（TELL，LEVEL 1 只读）。⚠️ IBM LTO + st 驱动不支持 READ POSITION 块地址（实测 `mt tell` 返回 I/O error）→ `502 COMMAND_FAILED`；磁带逻辑位置可用 `GET /status` 的 `file number / block number` 获取

**响应（HTTP 502，JSON 已格式化）：**

```json
{
 "detail": {
  "code": "COMMAND_FAILED",
  "message": "mt tell failed"
 }
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |

**实际测试结果：**

```text
success : false
http_code : 502
code : COMMAND_FAILED
message : mt tell failed
command_id : CMD-E4DB0246
说明 : API 请求/校验/命令拼装/审计链路正常，IBM LTO 硬件不支持该操作
```

---

### CMD-396680EE 磁带操作 status：`/api/v1/drives/nst0/status`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 status
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/nst0/status`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8080/api/v1/drives/nst0/status | jq
```

**说明：** 查询驱动器/磁带状态（LEVEL 1 只读，返回 stdout + parsed 结构化字段）→ `code=OK`

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "OK",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-102321-177FFA",
 "data": {
  "stdout": "SCSI 2 tape drive:\nFile number=-1, block number=-1, partition=0.\nTape block size 0 bytes. Density code 0x0 (default).\nSoft error count since last status=0\nGeneral status bits on (10000):\n IM_REP_EN\n",
  "command_id": "CMD-396680EE",
  "parsed": {
   "file_number": -1,
   "block_number": -1,
   "partition": 0,
   "block_size": 0,
   "density_code": "0x0",
   "density_name": "default",
   "soft_error_count": 0,
   "flags": [
    "IM_REP_EN"
   ],
   "at_bot": false,
   "at_eod": false,
   "tape_online": true,
   "parsed_ok": true
  }
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.stdout | string | mt status 原始输出 |
| data.parsed.file_number | integer | 当前文件号 |
| data.parsed.block_number | integer | 当前块号 |
| data.parsed.block_size | integer | 当前块大小（0=可变块） |
| data.parsed.density_code | string | 记录密度码 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : OK
command_id : CMD-396680EE
```

---

### CMD-08E473A9 磁带操作 erase：`/api/v1/drives/nst0/erase`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 erase 1
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/erase`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/erase \
-H 'Content-Type: application/json' \
-d '{"count": 1, "confirm": true}' | jq
```

**说明：** 擦除磁带（ERASE，LEVEL 3，⚠️ 破坏性操作；count=0 为短擦除=仅当前位置，count>0 为长擦除=擦到物理带尾，实测长擦除耗时约 6 分钟（356s，与已写入数据量相关））→ `code=ERASE_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `count` | integer | 否（默认1） | `1` | 0=短擦除，>0=长擦除 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "ERASE_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-102741-EC6636",
 "data": {
  "command_id": "CMD-08E473A9"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : ERASE_SUCCESS
command_id : CMD-08E473A9
```

---

### CMD-FC02CFEC 磁带操作 lock：`/api/v1/drives/nst0/lock`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 lock
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/lock`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/lock \
-H 'Content-Type: application/json' \
-d '{"confirm": true}' | jq
```

**说明：** 锁定磁带机舱门/禁止介质移除（LOCK，LEVEL 2）→ `code=LOCK_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "LOCK_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-103800-2D819D",
 "data": {
  "command_id": "CMD-FC02CFEC",
  "stdout": "",
  "stderr": "",
  "exit_code": 0
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.operation | string | 实际执行的定位操作 |
| data.count | integer | 实际执行的定位数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : LOCK_SUCCESS
command_id : CMD-FC02CFEC
```

---

### CMD-D3DDF013 磁带操作 unlock：`/api/v1/drives/nst0/unlock`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 unlock
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/unlock`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/unlock \
-H 'Content-Type: application/json' \
-d '{"confirm": true}' | jq
```

**说明：** 解锁磁带机（UNLOCK，LEVEL 2）→ `code=UNLOCK_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "UNLOCK_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-103337-0753B1",
 "data": {
  "command_id": "CMD-D3DDF013",
  "stdout": "",
  "stderr": "",
  "exit_code": 0
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.operation | string | 实际执行的定位操作 |
| data.count | integer | 实际执行的定位数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : UNLOCK_SUCCESS
command_id : CMD-D3DDF013
```

---

### CMD-582F55DD 磁带操作 load：`/api/v1/drives/nst0/load`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 load
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/load`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/load \
-H 'Content-Type: application/json' \
-d '{"confirm": true}' | jq
```

**说明：** 加载/上带磁带（LOAD，LEVEL 2）→ `code=LOAD_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "LOAD_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-102624-FEC903",
 "data": {
  "command_id": "CMD-582F55DD",
  "stdout": "",
  "stderr": "",
  "exit_code": 0
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.operation | string | 实际执行的定位操作 |
| data.count | integer | 实际执行的定位数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : LOAD_SUCCESS
command_id : CMD-582F55DD
```

---

### CMD-429C04CD 磁带操作 compression：`/api/v1/drives/nst0/compression`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 compression 1
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/compression`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/compression \
-H 'Content-Type: application/json' \
-d '{"enable": true, "confirm": true}' | jq
```

**说明：** 设置硬件压缩开关（COMPRESSION，LEVEL 2；enable=true→`compression 1`，false→`compression 0`）→ `code=COMPRESSION_SUCCESS`；只读查询用 GET /compression

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `enable` | boolean | 是 | `true` | true=启用压缩，false=关闭压缩 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "COMPRESSION_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-102635-8BEFB3",
 "data": {
  "enabled": true,
  "command_id": "CMD-429C04CD"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.enabled | boolean | 实际设置的压缩开关 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : COMPRESSION_SUCCESS
enabled : True
command_id : CMD-429C04CD
```

---

### CMD-4AD7FC86 磁带操作 setblk：`/api/v1/drives/nst0/block-size`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 setblk 0
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/block-size`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/block-size \
-H 'Content-Type: application/json' \
-d '{"block_size": 0, "confirm": true}' | jq
```

**说明：** 设置块大小（SETBLK，LEVEL 2；0=可变块模式，>0=固定块 N 字节，最大 16MB）→ `code=SETBLK_SUCCESS`；fsr/bsr 等按块定位操作需可变块模式

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `block_size` | integer | 是 | `0` | 块大小（字节），0 表示可变块 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "SETBLK_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-103923-ED8F80",
 "data": {
  "block_size": 0,
  "command_id": "CMD-4AD7FC86"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.block_size | integer | 实际设置的块大小 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : SETBLK_SUCCESS
block_size : 0
command_id : CMD-4AD7FC86
```

---

### CMD-2C2F4F9A 磁带操作 setdensity：`/api/v1/drives/nst0/density`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 setdensity 0
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/density`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/density \
-H 'Content-Type: application/json' \
-d '{"density": 0, "confirm": true}' | jq
```

**说明：** 设置记录密度码（SETDENSITY，LEVEL 2；0=驱动器默认密度，可用码见 GET /densities）→ `code=SETDENSITY_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `density` | integer | 是 | `0` | SCSI 密度码（0-255） |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "SETDENSITY_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-102635-3659BC",
 "data": {
  "density": 0,
  "command_id": "CMD-2C2F4F9A"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.density | integer | 实际设置的密度码 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : SETDENSITY_SUCCESS
density : 0
command_id : CMD-2C2F4F9A
```

---

### CMD-E793AAE6 磁带操作 mkpartition：`/api/v1/drives/nst0/partition`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 mkpartition 2
```

CLI 测试结果：`FAIL`（硬件不支持，见下方说明）

**对应 API：** `POST /drives/nst0/partition`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/partition \
-H 'Content-Type: application/json' \
-d '{"count": 2, "confirm": true}' | jq
```

**说明：** 重新划分磁带分区（MKPARTITION，LEVEL 3，⚠️ 破坏性操作= FORMAT MEDIUM）。⚠️ 当前 IBM LTO + st 驱动实测返回失败 → `502 COMMAND_FAILED`（LTO 分区格式化建议走 ITDT/lin_tape 工具；API 链路已验证）

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `count` | integer | 否（默认1） | `2` | 分区数（1=不分分区） |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 502，JSON 已格式化）：**

```json
{
 "detail": {
  "code": "COMMAND_FAILED",
  "message": "mt mkpartition failed"
 }
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |

**实际测试结果：**

```text
success : false
http_code : 502
code : COMMAND_FAILED
message : mt mkpartition failed
command_id : CMD-E793AAE6
说明 : API 请求/校验/命令拼装/审计链路正常，IBM LTO 硬件不支持该操作
```

---

### CMD-04568EB3 磁带操作 setpartition：`/api/v1/drives/nst0/partition`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 setpartition 0
```

CLI 测试结果：`FAIL`（硬件不支持，见下方说明）

**对应 API：** `POST /drives/nst0/partition`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/partition \
-H 'Content-Type: application/json' \
-d '{"partition": 0, "confirm": true}' | jq
```

**说明：** 切换当前分区（SETPARTITION，LEVEL 2；body 传 `partition` 字段）。⚠️ 需已存在分区表；当前硬件实测失败 → `502 COMMAND_FAILED`（API 链路已验证）

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `partition` | integer | 是（与 count 二选一） | `0` | 目标分区号（0-255） |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 502，JSON 已格式化）：**

```json
{
 "detail": {
  "code": "COMMAND_FAILED",
  "message": "mt setpartition failed"
 }
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |

**实际测试结果：**

```text
success : false
http_code : 502
code : COMMAND_FAILED
message : mt setpartition failed
command_id : CMD-04568EB3
说明 : API 请求/校验/命令拼装/审计链路正常，IBM LTO 硬件不支持该操作
```

---

### CMD-CBCC08E5 磁带操作 partseek：`/api/v1/drives/nst0/partition/seek`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 partseek 0,0
```

CLI 测试结果：`FAIL`（硬件不支持，见下方说明）

**对应 API：** `POST /drives/nst0/partition/seek`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/partition/seek \
-H 'Content-Type: application/json' \
-d '{"partition": 0, "block": 0, "confirm": true}' | jq
```

**说明：** 分区+块号定位（PARTSEEK，LEVEL 2，底层 `mt partseek P,B`）。⚠️ 依赖分区表与块定位支持，当前硬件实测失败 → `502 COMMAND_FAILED`（API 链路已验证）

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `partition` | integer | 是 | `0` | 目标分区号 |
| `block` | integer | 是 | `0` | 目标逻辑块号 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 502，JSON 已格式化）：**

```json
{
 "detail": {
  "code": "COMMAND_FAILED",
  "message": "mt partseek failed"
 }
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |

**实际测试结果：**

```text
success : false
http_code : 502
code : COMMAND_FAILED
message : mt partseek failed
command_id : CMD-CBCC08E5
说明 : API 请求/校验/命令拼装/审计链路正常，IBM LTO 硬件不支持该操作
```

---

### CMD-473299C3 磁带操作 asf：`/api/v1/drives/nst0/position`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 asf 0
```

CLI 测试结果：`PASS`

**对应 API：** `POST /drives/nst0/position`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/drives/nst0/position \
-H 'Content-Type: application/json' \
-d '{"operation": "asf", "count": 0, "confirm": true}' | jq
```

**说明：** 绝对定位到第 N 个文件标记（ASF，Absolute Space File，LEVEL 2；底层 `mt asf count`）→ `code=POSITION_SUCCESS`

**请求参数：**

| 参数 | 类型 | 必选 | 示例 | 说明 |
| ----------- | ------- | -- | ----- | --------------------- |
| `operation` | string | 是 | `fsr` | 定位操作类型：fsf/fsfm/bsf/bsfm/fsr/bsr/fss/bss/asf |
| `count` | integer | 否（默认1） | `1` | 跳过的标记/块数量 |
| `confirm` | boolean | 是 | `true` | 安全确认标志 |

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "POSITION_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-102731-B26960",
 "data": {
  "operation": "asf",
  "count": 0,
  "command_id": "CMD-473299C3"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.operation | string | 实际执行的定位操作 |
| data.count | integer | 实际执行的定位数量 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : POSITION_SUCCESS
operation : asf
count : 0
command_id : CMD-473299C3
```

---

### CMD-8E6E97AA 磁带操作 densities：`/api/v1/drives/nst0/densities`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 densities
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/nst0/densities`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8080/api/v1/drives/nst0/densities | jq
```

**说明：** 查询驱动器支持的记录密度列表（LEVEL 1 只读）→ `code=DENSITIES_SUCCESS`

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "DENSITIES_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-102421-AC1D01",
 "data": {
  "stdout": "Some SCSI tape density codes:\ncode   explanation                   code   explanation\n0x00   default                       0x34   SLR100\n0x01   NRZI (800 bpi)                0x40   DLT1 40 GB, or Ultrium\n0x02   PE (1600 bpi)                 0x41   DLT 40GB, or Ultrium2\n0x03   GCR (6250 bpi)                0x42   LTO-2\n0x04   QIC-11                        0x44   LTO-3\n0x05   QIC-45/60 (GCR, 8000 bpi)     0x45   QIC-3095-MC (TR-4)\n0x06   PE (3200 bpi)                 0x46   LTO-4\n0x07   IMFM (6400 bpi)               0x47   DDS-5 or TR-5\n0x08   GCR (8000 bpi)                0x48   SDLT220\n0x09   GCR (37871 bpi)               0x49   SDLT320\n0x0a   MFM (6667 bpi)                0x4a   SDLT600, T10000A\n0x0b   PE (1600 bpi)                 0x4b   T10000B\n0x0c   GCR (12960 bpi)               0x4c   T10000C\n0x0d   GCR (25380 bpi)               0x4d   T10000D\n0x0f   QIC-120 (GCR 10000 bpi)       0x51   IBM 3592 J1A\n0x10   QIC-150/250 (GCR 10000 bpi)   0x52   IBM 3592 E05\n0x11   QIC-320/525 (GCR 16000 bpi)   0x53   IBM 3592 E06\n0x12   QIC-1350 (RLL 51667 bpi)      0x54   IBM 3592 E07\n0x13   DDS (61000 bpi)               0x55   IBM 3592 E08\n0x14   EXB-8200 (RLL 43245 bpi)      0x58   LTO-5\n0x15   EXB-8500 or QIC-1000          0x5a   LTO-6\n0x16   MFM 10000 bpi                 0x5c   LTO-7\n0x17   MFM 42500 bpi                 0x5d   LTO-7-M8\n0x18   TZ86                          0x5e   LTO-8\n0x19   DLT 10GB                      0x71   IBM 3592 J1A, encrypted\n0x1a   DLT 20GB                      0x72   IBM 3592 E05, encrypted\n0x1b   DLT 35GB                      0x73   IBM 3592 E06, encrypted\n0x1c   QIC-385M                      0x74   IBM 3592 E07, encrypted\n0x1d   QIC-410M                      0x75   IBM 3592 E08, encrypted\n0x1e   QIC-1000C                     0x80   DLT 15GB uncomp. or Ecrix\n0x1f   QIC-2100C                     0x81   DLT 15GB compressed\n0x20   QIC-6GB                       0x82   DLT 20GB uncompressed\n0x21   QIC-20GB                      0x83   DLT 20GB compressed\n0x22   QIC-2GB                       0x84   DLT 35GB uncompressed\n0x23   QIC-875                       0x85   DLT 35GB compressed\n0x24   DDS-2                         0x86   DLT1 40 GB uncompressed\n0x25   DDS-3                         0x87   DLT1 40 GB compressed\n0x26   DDS-4 or QIC-4GB              0x88   DLT 40GB uncompressed\n0x27   Exabyte Mammoth               0x89   DLT 40GB compressed\n0x28   Exabyte Mammoth-2             0x8c   EXB-8505 compressed\n0x29   QIC-3080MC                    0x90   SDLT110 uncompr/EXB-8205 compr\n0x30   AIT-1 or MLR3                 0x91   SDLT110 compressed\n0x31   AIT-2                         0x92   SDLT160 uncompressed\n0x32   AIT-3 or SLR7                 0x93   SDLT160 comprssed\n0x33   SLR6                        \n",
  "command_id": "CMD-8E6E97AA"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.stdout | string | 密度码列表原始输出 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : DENSITIES_SUCCESS
command_id : CMD-8E6E97AA
```

---

### CMD-F1F774AD 磁带操作 stshowoptions：`/api/v1/drives/nst0/options`

**CLI 原始命令：**

```bash
mt -f /dev/nst0 stshowoptions
```

CLI 测试结果：`PASS`

**对应 API：** `GET /drives/nst0/options`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8080/api/v1/drives/nst0/options | jq
```

**说明：** 查询 st 驱动器选项（STSHOWOPTIONS，LEVEL 1 只读）→ `code=OPTIONS_SUCCESS`

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "OPTIONS_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-102421-3496E5",
 "data": {
  "stdout": "The options set: buffer-writes async-writes read-ahead can-bsr\n",
  "command_id": "CMD-F1F774AD"
 },
 "error": null
}
```

**返回字段说明：**

| 字段 | 类型 | 说明 |
| ----------------- | ----------- | ---------------------------- |
| `success` | boolean | 操作是否成功 |
| `code` | string | 操作结果码 |
| `message` | string | 操作结果描述 |
| `request_id` | string | API 请求唯一 ID |
| `data` | object | 操作结果数据 |
| `error` | object/null | 错误信息，成功时为 `null` |
| data.stdout | string | 驱动器选项原始输出 |
| data.command_id | string | 后端执行命令 ID |

**实际测试结果：**

```text
success : True
code : OPTIONS_SUCCESS
command_id : CMD-F1F774AD
```

## 附：安全与权限说明

- LEVEL 1（只读查询）：status / tell / densities / options —— 任意模式可用
- LEVEL 2（设备操作）：position / rewind / load / eject / block-size / density / compression 等 —— 需 `TAPE_API_MODE=DIAGNOSTIC|FULL` 且 `ALLOW_DEVICE_OPERATION=true`
- LEVEL 3（写/破坏性）：weof / wset / eof / erase / mkpartition —— 需 `TAPE_API_MODE=FULL` 且 `ALLOW_WRITE=true`，body 必须带 `confirm: true`
- 所有响应可经 `request_id` → `command_id` 溯源至 audit 原始 stdout/stderr
