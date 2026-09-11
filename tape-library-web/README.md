# Tape Library Web GUI

统一的磁带库 Web 管理、状态监控、磁带管理、带机管理与读写测试界面。基于已开发的 **Tape Library REST API**（FastAPI），Web 端不直接接触任何 Linux 磁带设备（`/dev/sg*`、`/dev/st*`、`/dev/nst*`），全部操作经 REST API 完成。

## 1. Project Overview

- **目标**：为 Quantum / IBM / BDT / HPE / Dell / Oracle / Spectra 等磁带库提供统一 Web 管理界面
- **架构**：Browser → Web UI (React) → Tape Library REST API (FastAPI) → Linux 命令层 (lsscsi/sg3_utils/mtx/mt) → 磁带库硬件
- **模式**：`mock`（无硬件演示）/ `real`（连接真实 API）

## 2. Architecture

```
Browser ──HTTPS──> tape-library-web (React/Vite/AntD/ECharts, nginx)
                        │ REST API（唯一通道，禁止前端执行 shell / 访问 /dev）
                        ▼
                 Tape Library API (FastAPI, 8001 DIAGNOSTIC / 8002 FULL)
                        │ 白名单命令 + 三级安全 + 审计链
                        ▼
                 lsscsi / sg3_utils / mtx / mt → 磁带库硬件
```

## 3. Features

- 🟢 LEVEL_1 只读：发现 / INQUIRY / 状态 / 库存 / TapeAlert / 日志诊断
- 🟡 LEVEL_2 设备操作：Mount / Unmount / Transfer / Rewind / Position（弹窗确认）
- 🔴 LEVEL_3 破坏性：Write / Erase（必须输入 TEST_MEDIA Barcode 完全匹配才可执行）
- Safety Controller：按 API 返回的安全策略动态禁用按钮（后端二次校验）
- 槽位物理可视化（SlotGrid）、设备拓扑树（DeviceTree）
- 测试中心 7 步流程 + 1s 轮询实时进度（Throughput / Transferred / Errors / Elapsed）
- 操作历史 + 命令审计（stdout/stderr/parsed + 下载原始日志）
- Dashboard ECharts：库健康 / 带机状态 / 磁带状态分布

## 4. Screens

| 路由 | 页面 | 刷新 |
|---|---|---|
| `/` | Dashboard（统计卡片 + 3 图表 + 最近会话） | 10s |
| `/libraries` | Library Overview 表格 | 10s |
| `/libraries/:changer` | Library Detail（槽位可视化/Overview/Drives/Tapes/设备树/Events） | 10s |
| `/drives` | Drive Status 表格 | 5s |
| `/drives/:nst` | Drive Detail（含诊断/倒带） | 5s |
| `/tapes` | Tape Inventory（搜索 + 过滤） | - |
| `/tests` | Test Center（Mount/Unmount/Read/Write/Full） | 会话 1s |
| `/operations` | Operation History | 10s |
| `/audit` | Command/API Audit（详情抽屉 + 下载） | 10s |

## 5. API Integration

统一封装 `src/api/client.ts`：mock/real 双模式分发、错误归一化（HTTP 4xx/5xx → `success:false` + code）、友好错误文案映射（DEVICE_NOT_FOUND / WRITE_NOT_ALLOWED / TEST_MEDIA_REQUIRED 等 13 类）。

对接端点（基于真实 `/openapi.json` 适配，未猜测）：

```
GET  /api/v1/safety  /system/info  /libraries  /libraries/{c}/status  /libraries/{c}/inventory
GET  /api/v1/drives/{nst}/status  /discovery
POST /api/v1/libraries/{c}/load    {slot, drive, confirm}
POST /api/v1/libraries/{c}/unload  {slot, drive, confirm}
POST /api/v1/drives/{nst}/rewind   {confirm}
POST /api/v1/tests/read            {nst_device, size_mb, block_size}
POST /api/v1/tests/write-verify    {drive, test_media, size_mb, allow_write, confirm}
GET  /api/v1/commands/{command_id}
```

详见 `docs/API-INTEGRATION.md`。

## 6. Mock Mode

`VITE_API_MODE=mock`（默认）。`src/api/mock.ts` 内置完整模拟世界：

- IBM 03584L32 带库（12 槽 8 带）+ 2× ULT3580-TDA 带机
- Mount/Unload 真实状态机（占用检查 / 空槽错误 / 重复装载错误）
- 测试会话按吞吐推进进度，1s 轮询至 PASS
- 审计链与操作历史完整记录（CMD/REQ ID）

## 7. Real Hardware Mode

```bash
VITE_API_MODE=real VITE_API_BASE_URL=http://172.16.12.186:8001 npm run build
```

写类测试需连接 8002（FULL 模式）且 TEST_MEDIA 匹配。GUI 自身绝不连接 `/dev/*`。

## 8. Docker Deployment

```bash
docker build -t tape-library-web:1.0 .
docker run -d --name tape-library-web -p 8080:80 tape-library-web:1.0
# 浏览器打开 http://localhost:8080
```

`docker-compose.yml` 含 tape-api 服务位；nginx 反代 `/api/` → tape-api:8001。

## 9. Configuration

`.env`：

```
VITE_API_MODE=mock                          # mock | real
VITE_API_BASE_URL=http://172.16.12.186:8001 # real 模式 API 地址
```

## 10. Testing

```bash
npm test        # 单元测试（vitest）：Mock 状态机 / 安全控制 / 审计链 / 错误映射
npm run e2e     # E2E（Playwright）：10 条页面流程用例（需 npx playwright install chromium）
```

结果输出 `test-results/`（unit 由 vitest 输出；e2e html/json 报告）。

## 11. Security

- 前端零 shell、零 /dev 访问、零密码保存
- 所有操作带风险等级标签（LEVEL_1/2/3）
- LEVEL_2 弹窗确认；LEVEL_3 必须输入 TEST_MEDIA Barcode 完全匹配
- 按钮受 Safety Policy 动态禁用，**后端 API 仍会再次校验权限**（前端控制仅为 UX）

## 12. Troubleshooting

| 现象 | 处理 |
|---|---|
| API Unreachable | 检查 tape-api 服务与 VITE_API_BASE_URL |
| 按钮灰色 Disabled by Safety Policy | 当前模式禁止该操作（SAFE 只读 / DIAGNOSTIC 禁写） |
| Write 始终无法授权 | 输入的 Barcode 必须与 TEST_MEDIA 完全一致 |
| Mock 数据不刷新 | Mock 状态在浏览器内存，刷新页面重置 |
