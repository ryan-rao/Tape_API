# Tape Library Web GUI 测试报告

- Frontend Version: tape-library-web 1.0.0（React 18 + Vite 5 + TS 5.6 + AntD 5 + ECharts 5）
- API Mode: mock（真实 API 集成层已按 openapi.json 适配，端点见 docs/API-INTEGRATION.md）
- API Base URL: http://172.16.12.186:8001（real 模式用）

## 规模统计

- 总页面: 9（Dashboard / Libraries / LibraryDetail / Drives / DriveDetail / Tapes / TestCenter / Operations / Audit）
- 总组件: 11（RiskTag / Chart / ConfirmOperation / ConfirmDestructive / SlotGrid / SlotDetailModal / DeviceTree / TestProgressView + 布局）
- API 端点对接: 13 个方法（mock/real 双实现）
- 测试用例: 27（单元 16 + E2E 11）

## 单元测试（vitest）—— 16/16 通过

| 分组 | 用例 | 结果 |
|---|---|---|
| Mock 带库状态 | 列出带库 / 库状态含槽位带机 / 库存清单 | 3 PASS |
| Mount/Unmount 状态机 | 正常装载 / 重复装载拒绝 / 空槽拒绝 / 正常卸载 / 空机卸载拒绝 / 无效槽位拒绝 | 6 PASS |
| 写测试安全控制 | Barcode 不匹配拒绝 / 读测试会话推进 PASS / 未知会话 NOT_FOUND | 3 PASS |
| 审计链 | 操作产生 CMD/REQ ID 审计记录 | 1 PASS |
| 错误码映射 | DEVICE_NOT_FOUND / WRITE_NOT_ALLOWED / 未知错误回退 | 3 PASS |

## E2E 测试（Playwright + Chromium 1134）—— 11/11 通过

| # | 用例 | 结果 |
|---|---|---|
| 01 | 打开 Dashboard 显示统计卡片 | PASS |
| 02 | 查看 Library 列表 | PASS |
| 03 | 进入 Library Detail 槽位可视化 | PASS |
| 04 | 点击 Slot 弹出详情 | PASS |
| 05 | 查看带机列表与详情 | PASS |
| 06 | 查看 Tape Inventory | PASS |
| 07 | Test Center 执行 Mount（确认框→物理移动→PASS） | PASS |
| 08 | Unmount 归位（切换操作类型→确认→PASS） | PASS |
| 09 | Read Test 产生会话并轮询进度 | PASS |
| 10 | Write Test 错误 Barcode 禁止授权（正确 Barcode 解锁） | PASS |
| 11 | Operation History 与 Audit 页 | PASS |

## 安全测试

- LEVEL_2 Mount/Unmount 均需确认弹窗，无单击直执行路径 ✓
- LEVEL_3 Write：错误 Barcode 时 Authorize 按钮保持 disabled（E2E 10 验证）✓
- TEST_MEDIA 校验：后端 mockApi.runTest 双重校验 Barcode（单元测试验证）✓
- Safety Policy 禁用时按钮灰显 + 后端仍会二次校验 ✓
- 前端零 shell / 零 /dev 访问（代码审计确认）✓

## 汇总

```
Mock Tests:    16 passed / 0 failed
E2E Tests:     11 passed / 0 failed
Real API Tests: 集成层已适配（同步测试接口；生产部署后可切 real 模式回归）
Safety Tests:  4/4
Skipped:       0
```

报告产物：test-results/e2e-report/index.html（HTML）、test-results/e2e-summary.json
