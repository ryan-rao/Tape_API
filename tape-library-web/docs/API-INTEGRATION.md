# API 集成说明

## 原则

- **API FIRST**：GUI 不执行 shell、不访问 /dev、不猜测设备
- 集成基于真实 `/openapi.json`（45 端点）实测适配，未实现的后缀自动降级为审计页说明

## 客户端（src/api/client.ts）

- mock/real 双模式：`VITE_API_MODE` 分发到 `mockApi` 或 axios
- 统一错误归一化：HTTP 401/403/404/409/422/500/503/504 → `{success:false, code, message}`
- 网络异常 → `AGENT_UNAVAILABLE`
- `friendlyError()` 将 13 类错误码映射为中文友好提示

## 端点映射表

| GUI 用途 | Mock 方法 | Real 端点 | 风险 |
|---|---|---|---|
| 安全策略 | mockApi.safety | GET /safety | L1 |
| 系统信息 | mockApi.systemInfo | GET /system/info | L1 |
| 带库列表 | mockApi.listLibraries | GET /libraries | L1 |
| 库状态+槽位 | mockApi.libraryStatus | GET /libraries/{c}/status | L1 |
| 介质清单 | mockApi.libraryInventory | GET /libraries/{c}/inventory | L1 |
| 带机列表 | mockApi.listDrives | GET /discovery | L1 |
| 带机详情 | mockApi.driveDetail | GET /drives/{nst}/status | L1 |
| 装带 | mockApi.load | POST /libraries/{c}/load `{slot,drive,confirm}` | L2 |
| 卸带 | mockApi.unload | POST /libraries/{c}/unload `{slot,drive,confirm}` | L2 |
| 倒带 | mockApi.rewind | POST /drives/{nst}/rewind `{confirm}` | L2 |
| 读测试 | mockApi.runTest(read) | POST /tests/read `{nst_device,size_mb,block_size}` | L1 |
| 写校验测试 | mockApi.runTest(write/write-verify/full) | POST /tests/write-verify `{drive,test_media,size_mb,allow_write,confirm}` | L3 |
| 会话轮询 | mockApi.getSession | mock 专用（real 为同步结果，无会话端点） | - |
| 历史命令 | mockApi.command | GET /commands/{command_id} | L1 |

## Real 模式差异

真实 API 的测试接口为**同步执行**（返回最终结果 + command_id），无 `/test-sessions` 轮询端点。client 处理策略：

- mock 模式：1s 轮询推进进度条
- real 模式：直接展示同步返回的 parsed dd 摘要（bytes/throughput/records），审计详情经 `/commands/{id}` 查询

写类请求体字段与 API 严格一致：`drive` 用 `/dev/nstX` 路径、`test_media` 必须等于服务端 `TEST_MEDIA`、`allow_write+confirm` 双 true。
