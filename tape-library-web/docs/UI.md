# UI 设计说明

## 风格

Enterprise Storage Management：高信息密度、专业、克制。基于 Ant Design 5 深色侧栏 + 浅色内容区，桌面优先（1920×1080 / 1440×900 / 1366×768）。

## 状态颜色规范（全局统一）

| 状态 | 颜色 |
|---|---|
| Healthy / Online / PASS | 绿 `#52c41a` |
| Warning | 橙 `#faad14` |
| Critical / Error / FAIL | 红 `#ff4d4f` |
| Offline / Unknown | 灰 `#8c8c8c` |
| Running | 蓝 `#1677ff` |

## 风险等级标识

- 🟢 LEVEL_1 READ ONLY：查询/诊断
- 🟡 LEVEL_2 DEVICE OPERATION：物理移动介质（弹窗确认）
- 🔴 LEVEL_3 DESTRUCTIVE：写/擦除（输入 Barcode 二次授权）

## 页面清单

| 页面 | 关键组件 | 自动刷新 |
|---|---|---|
| Dashboard | Statistic 卡片 ×4、ECharts 环形图 ×3、最近会话列表 | 10s + 手动 |
| Libraries | 表格（Vendor/Model/Serial/Status/Slots/Tapes） | 10s |
| Library Detail | SlotGrid（槽位可视化网格 + Tooltip + 详情弹窗）、DeviceTree、Tabs 六视图 | 10s |
| Drives | 表格（状态/装载/TapeAlert） | 5s |
| Drive Detail | Descriptions、诊断视图、Rewind 确认 | 5s |
| Tapes | 搜索 + 状态过滤 + 表格 | - |
| Test Center | Steps 七步、操作选择、ConfirmOperation/ConfirmDestructive、TestProgressView | 会话 1s |
| Operations | 操作历史表格（风险/状态/时长/REQ ID） | 10s |
| Audit | 命令审计表格 + 详情抽屉（stdout/stderr/parsed + JSON 下载） | 10s |

## 交互保护

1. 所有 LEVEL_2/3 操作必经确认弹窗，禁止单击直执行
2. ConfirmDestructive 的授权按钮在 Barcode 完全匹配前保持 disabled
3. Safety Policy 禁用时按钮灰显并提示 "Disabled by Safety Policy"（后端仍会再校验）
4. 所有页面处理 Loading / Empty / Error 三态，错误提供 Retry
