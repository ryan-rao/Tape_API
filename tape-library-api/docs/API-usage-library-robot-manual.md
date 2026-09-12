# 磁带库新增 API 接口文档（robot 系列）

> 覆盖：robot/position、exchange、robot/first、robot/next、robot/last、inventory
> 实例：http://172.16.12.186:8080（FULL 模式）｜库设备：/dev/sg1｜测试时间：2026-09-12

---

### CMD-B956697E 带库操作-机械臂定位: /api/v1/libraries/sg1/robot/position

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 position 1
```

CLI 测试结果：`PASS`

**对应 API：** `POST /libraries/sg1/robot/position`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/libraries/sg1/robot/position -H 'Content-Type: application/json' -d '{"element": 1, "confirm": true}'
```
**API 参数：**
* element: 目标元素地址（Storage Element 编号）

**说明：** 机械臂定位到指定元素（POSITION，LEVEL 2）→ code=POSITION_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "POSITION_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-162449-355D8C",
 "data": {
  "element": 1,
  "command_id": "CMD-B956697E"
 },
 "error": null
}
```

---

### CMD-0576EDEF 带库操作-槽位互换: /api/v1/libraries/sg1/exchange

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 exchange 4 5
```

CLI 测试结果：`PASS`（实测槽 4↔5 磁带互换：IBM009LA/IBM013LA 交换后已再次 exchange 还原）

**对应 API：** `POST /libraries/sg1/exchange`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/libraries/sg1/exchange -H 'Content-Type: application/json' -d '{"source": 4, "destination": 5, "confirm": true}'
```
**API 参数：**
* source: 源 Storage Element 编号
* destination: 目标 Storage Element 编号

**说明：** 互换两个槽位的磁带（EXCHANGE，LEVEL 2，⚠️ 涉及机械臂实际动作）→ code=EXCHANGE_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "EXCHANGE_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-162719-C6CD33",
 "data": {
  "source": 4,
  "destination": 5,
  "command_id": "CMD-0576EDEF"
 },
 "error": null
}
```

---

### CMD-FA5E8662 带库操作-装载首盘磁带: /api/v1/libraries/sg1/robot/first

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 first
```

CLI 测试结果：`PASS`

**对应 API：** `POST /libraries/sg1/robot/first`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/libraries/sg1/robot/first
```
**API 参数：** 无（请求体可省略）

**说明：** 顺序装载第一盘磁带到驱动器 0（FIRST，⚠️ 非只读操作——mtx first/next/last 是"顺序上带"命令，会实际执行卸载/装载机械动作）→ code=FIRST_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "FIRST_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-162452-F704AC",
 "data": {
  "stdout": "Loading media from Storage Element 1 into drive 0...done\n",
  "command_id": "CMD-FA5E8662"
 },
 "error": null
}
```

---

### CMD-916577E1 带库操作-装载下一盘磁带: /api/v1/libraries/sg1/robot/next

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 next
```

CLI 测试结果：`PASS`

**对应 API：** `POST /libraries/sg1/robot/next`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/libraries/sg1/robot/next
```
**API 参数：** 无（请求体可省略）

**说明：** 卸下当前磁带并装载下一盘到驱动器 0（NEXT，⚠️ 会实际执行卸载+装载机械动作）→ code=NEXT_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "NEXT_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-162458-F813F4",
 "data": {
  "stdout": "Unloading drive 0 into Storage Element 1...done\nLoading media from Storage Element 2 into drive 0...done\n",
  "command_id": "CMD-916577E1"
 },
 "error": null
}
```

---

### CMD-1384F287 带库操作-装载末盘磁带: /api/v1/libraries/sg1/robot/last

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 last
```

CLI 测试结果：`PASS`（修复后。注：本库 IMPORT/EXPORT 槽与存储槽同段编号，mtx 自带 last 会误判末带位置，API 已改为服务层仿真实现：解析 status → 过滤 IE 槽 → 取最大编号满槽精确装载）

**对应 API：** `POST /libraries/sg1/robot/last`

**curl 调用：**

```bash
curl -s -X POST http://172.16.12.186:8080/api/v1/libraries/sg1/robot/last
```
**API 参数：** 无（请求体可省略）

**说明：** 装载最后一盘磁带到驱动器 0（LAST，⚠️ 会实际执行装载机械动作；IE 槽磁带不参与排序）→ code=LAST_SUCCESS

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "LAST_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-163405-9DD580",
 "data": {
  "slot": 5,
  "barcode": "IBM013LA",
  "drive": 0,
  "command_id": "CMD-1384F287"
 },
 "error": null
}
```

---

### CMD-67D18B0A 带库操作-盘点重扫: /api/v1/libraries/sg1/inventory

**CLI 原始命令：**

```bash
mtx -f /dev/sg1 inventory
```

CLI 测试结果：`PASS`

**对应 API：** `GET /libraries/sg1/inventory`

**curl 调用：**

```bash
curl -s http://172.16.12.186:8080/api/v1/libraries/sg1/inventory | jq
```
**API 参数：** 无

**说明：** 触发带库盘点重扫（INITIALIZE ELEMENT STATUS，LEVEL 2，机械臂会实际扫描槽位重新读条码；实测立即返回，部分库型为后台异步执行）→ code=INVENTORY_SUCCESS。注：查询槽位清单请用 `GET /status`（解析 mtx status 输出）

**响应（HTTP 200，JSON 已格式化）：**

```json
{
 "success": true,
 "code": "INVENTORY_SUCCESS",
 "message": "Operation completed successfully",
 "request_id": "REQ-20260912-165658-33B575",
 "data": {
  "changer": "/dev/sg1",
  "command_id": "CMD-67D18B0A"
 },
 "error": null
}
```

---

## 汇总表

| API | 方法 | 对应命令 | 结果码 | 实测 |
| --- | --- | --- | --- | --- |
| `/api/v1/libraries/{id}/robot/position` | POST | `mtx -f /dev/sg1 position 1` | POSITION_SUCCESS | ✅ |
| `/api/v1/libraries/{id}/exchange` | POST | `mtx -f /dev/sg1 exchange 4 5` | EXCHANGE_SUCCESS | ✅ |
| `/api/v1/libraries/{id}/robot/first` | POST | `mtx -f /dev/sg1 first` | FIRST_SUCCESS | ✅ |
| `/api/v1/libraries/{id}/robot/next` | POST | `mtx -f /dev/sg1 next` | NEXT_SUCCESS | ✅ |
| `/api/v1/libraries/{id}/robot/last` | POST | `mtx -f /dev/sg1 last` | LAST_SUCCESS | ✅（修复后） |
| `/api/v1/libraries/{id}/inventory` | GET | `mtx -f /dev/sg1 inventory` | INVENTORY_SUCCESS | ✅ |
