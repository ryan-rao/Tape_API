# 磁带写入 API 文档：POST /api/v1/write

> 实例：http://172.16.12.186:8080（nginx→8001，FULL 模式）或直连 http://172.16.12.186:8001
> 测试驱动器：/dev/nst0（IBM ULT3580-TDA LTO5，对应库 DTE2，磁带 IBM015LA）｜测试时间：2026-09-12 17:46

---

### CMD-B04AD96E 磁带写入-写文件到磁带: /api/v1/write

**CLI 原始命令：**

```bash
dd if=/root/f1 of=/dev/nst0 bs=1M conv=notrunc
```

CLI 测试结果：`PASS`（写入 4 MiB 到磁带，读回 md5 校验一致）

**对应 API：** `POST /write`（指定 file 参数时写入该文件内容；不指定 file 时写入 size_mb 的零数据，见下节）

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/write -H 'Content-Type: application/json' -d '{"drive": "/dev/nst0", "media": "IBM015LA", "file": "/root/f1", "size_mb": 8, "allow_write": true, "confirm": true}'
```
**API 参数：**
* drive: 磁带机设备（/dev/nst0、nst0 简写均可）
* media: 目标磁带条码（如 IBM015LA）
* file: 要写入磁带的源文件，必须是绝对路径且存在（此模式下写入整个文件，size_mb 被忽略）
* size_mb: 零数据模式的写入量（MiB，默认 1024；指定 file 时忽略）
* allow_write: 必须为 true（双重授权：请求体 + 服务端 ALLOW_WRITE=true）
* confirm: 必须为 true（安全确认）
* timeout: 可选，秒（默认 7200）

**说明：** 把指定文件内容写入磁带当前位置（LEVEL 3，dd if=<file> of=drive）→ code=WRITE_SUCCESS。data.file 回显源文件，data.parsed 为 dd 统计。安全校验：file 必须绝对路径、拒 ..//dev//proc//sys、文件必须存在（否则 400 INVALID_PATH / 404 FILE_NOT_FOUND）。验证链路：f1(4MiB 随机数据) → 写带 → rewind → read 到 /root/f3 → **md5 一致**（650567dab179e62d772beff90551eae6）

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "WRITE_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-174607-9827A4",
 "data": {
  "drive": "/dev/nst0",
  "duration_ms": 7935,
  "command_id": "CMD-B04AD96E",
  "parsed": {
   "bytes": 4194304,
   "bytes_human": "4.2 MB, 4.0 MiB",
   "seconds": 7.92854,
   "throughput": "529 kB/s",
   "records_in": 4,
   "records_out": 4,
   "parsed_ok": true
  },
  "file": "/root/f1"
 },
 "error": null
}
```

---

### CMD-AB619994 磁带写入-写零数据测速: /api/v1/write（无 file 参数）

**CLI 原始命令：**

```bash
dd if=/dev/zero of=/dev/nst0 bs=1M count=8
```

CLI 测试结果：`PASS`（写入 8 MiB，校验与读回一致）

**对应 API：** `POST /write`（零数据模式；原 `/tests/write` 仍可用，等价别名；结果码统一为 WRITE_SUCCESS；参数 `test_media` 改名为 `media`，旧名兼容）

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/write -H 'Content-Type: application/json' -d '{"drive": "/dev/nst0", "media": "IBM015LA", "size_mb": 8, "allow_write": true, "confirm": true}'
```
**API 参数：**
* drive: 磁带机设备（/dev/nst0、nst0 简写均可）
* media: 目标磁带条码（如 IBM015LA，即环境 TEST_MEDIA 指定的测试介质）
* size_mb: 写入数据量（MiB，默认 1024）
* allow_write: 必须为 true（双重授权：请求体 + 服务端 ALLOW_WRITE=true 环境变量）
* confirm: 必须为 true（安全确认）
* timeout: 可选，秒（默认 7200）

**说明：** 从磁带当前位置写入指定容量的测试数据（LEVEL 3 写操作，需设备锁空闲）→ code=WRITE_SUCCESS。data.parsed 为 dd 统计（字节数/耗时/吞吐）。⚠️ 依赖磁带当前位置：建议先 rewind 再写；写入后读取需先 rewind 回 BOT。

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "WRITE_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-174046-CCBADE",
 "data": {
  "drive": "/dev/nst0",
  "size_mb": 8,
  "duration_ms": 25456,
  "command_id": "CMD-AB619994",
  "parsed": {
   "bytes": 8388608,
   "bytes_human": "8.4 MB, 8.0 MiB",
   "seconds": 25.4489,
   "throughput": "330 kB/s",
   "records_in": 8,
   "records_out": 8,
   "parsed_ok": true
  }
 },
 "error": null
}
```

**旧路径兼容验证：** `POST /tests/write {"test_media":"IBM015LA",...}` → 同样返回 WRITE_SUCCESS（REQ-20260912-174111-022CFD）

**配合接口（写→读完整链路）：**
1. `POST /drives/nst0/rewind` → REWIND_SUCCESS（回到 BOT）
2. `POST /write`（本文档）→ WRITE_SUCCESS
3. `POST /drives/nst0/rewind` → REWIND_SUCCESS
4. `POST /read {"drive":"/dev/nst0","block_size":"1M","file":"/root/f2","confirm":true}` → READ_SUCCESS（详见 API-usage-read.md）

**安全模型：** LEVEL 3 双重授权——缺 allow_write 返回 403 WRITE_OPERATION_NOT_AUTHORIZED；缺 media 返回 400 MISSING_PARAMETER
