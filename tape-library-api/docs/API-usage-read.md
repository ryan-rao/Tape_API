# 磁带读取 API 文档：POST /api/v1/read

> 实例：http://172.16.12.186:8080（nginx→8001，FULL 模式）或直连 http://172.16.12.186:8001
> 测试驱动器：/dev/nst0（IBM ULT3580-TDA LTO5，对应库 DTE2，磁带 IBM015LA）｜测试时间：2026-09-12 17:33

---

### CMD-D65CE206 磁带读取-读带出到文件: /api/v1/read

**CLI 原始命令：**

```bash
dd if=/dev/nst0 of=/root/f2 bs=1M
```

CLI 测试结果：`PASS`（读取 8 MiB 到 /root/f2，与写入数据一致）

**对应 API：** `POST /read`（原 `/tests/read` 仍可用，等价别名；结果码统一为 READ_SUCCESS）

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8001/api/v1/read -H 'Content-Type: application/json' -d '{"drive": "/dev/nst1", "block_size": "1M", "file": "/root/f2", "confirm": true}'
```
**API 参数：**
* drive: 磁带机设备（/dev/nst0、/dev/nst1 或 nst0 简写）
* block_size: dd 块大小，支持 1M/512K/64k 等（默认 1M）
* file: 读取数据保存的目标文件，必须是绝对路径；省略时数据丢弃到 /dev/null（纯读测速）
* confirm: 必须为 true（安全确认）
* timeout: 可选，秒（默认 3600）

**说明：** 从磁带当前位置读取数据写入指定文件（LEVEL 2，需设备锁空闲）→ code=READ_SUCCESS。data.parsed 为 dd 统计（字节数/耗时/吞吐），data.file 为实际输出文件。⚠️ 实测注意：①空白/长擦除后的磁带在 BOT 直接读取会返回 I/O error（先写入数据再读）；②读取前若刚写完，需先 rewind 回到 BOT。

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "READ_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-173328-D87618",
 "data": {
  "drive": "/dev/nst0",
  "duration_ms": 31,
  "command_id": "CMD-D65CE206",
  "parsed": {
   "bytes": 8388608,
   "bytes_human": "8.4 MB, 8.0 MiB",
   "seconds": 0.0185055,
   "throughput": "453 MB/s",
   "records_in": 8,
   "records_out": 8,
   "parsed_ok": true
  },
  "file": "/root/f2"
 },
 "error": null
}
```

**验证：** `ls -la /root/f2` → `-rw-r--r-- 1 root root 8388608`（8 MiB，与写入量一致）

**配合接口（本次测试链路）：**
1. `POST /tests/write` {"drive":"/dev/nst0","test_media":"IBM015LA","size_mb":8,"allow_write":true,"confirm":true} → WRITE_TEST_PASS（先写入 8 MiB 数据，REQ-20260912-173317-207ADF）
2. `POST /drives/nst0/rewind` → REWIND_SUCCESS（回到 BOT，REQ-20260912-173320-8CA533）
3. `POST /read`（本文档）→ READ_SUCCESS

**安全校验（file 参数）：** 绝对路径、拒绝 `..`/特殊字符/写入 /dev，违规返回 400 INVALID_PATH
