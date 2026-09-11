# Tape_API — 磁带库管理系统

IBM TS3500 系列（03584L32 机械手 + ULT3580-TDA LTO 带机）磁带库的统一管理平台：**FastAPI 后端 + React Web 前端**，通过封装 SCSI 工具链（mtx / mt / sg_utils）实现带库、带机、磁带的 REST 化管理与深度诊断。

- Web 界面：`http://172.16.12.186:8080`
- API 服务：`http://172.16.12.186:8080/api/v1`（nginx → uvicorn 127.0.0.1:8001）

---

## 1. 项目架构

```
┌────────────────────────────────────────────────────────────┐
│  浏览器                                                     │
│  React + AntD + ECharts (tape-library-web, nginx :8080)     │
└────────────────────────┬───────────────────────────────────┘
                         │ HTTP /api/v1
┌────────────────────────▼───────────────────────────────────┐
│  FastAPI 后端 (tape-library-api, uvicorn :8001)             │
│                                                            │
│  routes.py ──► services.py ──► adapters.py（命令组装+白名单）│
│      │             │                        │               │
│      │             │                   runner.py（执行/锁/审计）│
│      │             │                        │               │
│  security/policy.py │                  mtx / mt / sg_modes   │
│  （LEVEL_1/2/3     │                  / sg_logs / sg_inq …  │
│   风险分级鉴权）    │                        │               │
│      │             ▼                        ▼               │
│  audit/       parsers.py            Linux SCSI 子系统        │
│  （命令审计）  （结构化解析）         sg / st / sch 设备       │
└────────────────────────────────────────────────────────────┘
                         │ FC (Emulex LPe12000)
              ┌──────────┴──────────┐
              │ host32              │ host33
              │ 32:0:0:0 ULT3580-TDA│ 33:0:0:0 ULT3580-TDA
              │ 32:0:0:1 03584L32   │ 33:0:0:1 03584L32
              └─────────────────────┘
```

### 分层说明

| 层 | 文件 | 职责 |
|---|---|---|
| 路由层 | `app/api/routes.py` | REST 端点、参数校验、统一响应信封 |
| 业务层 | `app/services/services.py` | Drive / Library / Diagnostic / Discovery 服务，预检与聚合 |
| 命令层 | `app/commands/adapters.py` | mtx/mt/sg_* 命令行组装，设备名与操作白名单校验 |
| 执行层 | `app/commands/runner.py` | subprocess 执行、超时、设备锁、命令审计记录 |
| 解析层 | `app/commands/parsers.py` | MODE SENSE / LOG SENSE / mtx status / mt status / dmesg / lsscsi 结构化为 JSON |
| 安全层 | `app/security/policy.py` | 三级风险控制（见下） |
| 审计层 | `app/audit/` | 每条底层命令的记录（command_id 可追溯） |

### 安全分级

| 级别 | 允许的操作 | 启用条件（环境变量） |
|---|---|---|
| LEVEL_1 | 只读：状态、诊断、日志、发现 | 默认 |
| LEVEL_2 | 设备控制：装载/卸出、定位、rewind | `TAPE_API_MODE=DIAGNOSTIC|FULL` + `ALLOW_DEVICE_OPERATION=true` |
| LEVEL_3 | 写操作：weof、erase | `TAPE_API_MODE=FULL` + `ALLOW_WRITE=true` |

另有 `confirm: true` 二次确认机制，写类操作必须显式携带。

---

## 2. API 使用

所有响应统一信封：

```json
{
  "success": true, "code": "POSITION_SUCCESS",
  "message": "Operation completed successfully",
  "request_id": "REQ-20260911-205229-EE5520",
  "data": { "...": "..." },
  "error": null
}
```

错误时 `success:false`，`code` 为错误码（`NO_MEDIUM` / `COMMAND_FAILED` / `INVALID_OPERATION` / `PERMISSION_DENIED` 等），`detail.error_detail` 携带底层命令的完整 stdout/stderr/exit_code 与 command_id。

### 主要端点

**设备发现与拓扑**
```bash
curl -s http://172.16.12.186:8080/api/v1/discovery/map | jq
# 三种粒度：
#   matrix   — sg↔st/ch↔SCSI地址↔类型↔型号↔固件 六列映射表
#   hba_tree — 按 FC HBA 分组的树形拓扑（host→target→设备）
#   devices  — 每设备全量明细（序列号/ANSI/PDT/PCI/块限制 25+ 字段）
```

**带机状态与诊断**
```bash
# 聚合状态（sg_inq + mt status + 压缩 + TapeAlert）
curl -s .../api/v1/drives/nst1/summary | jq

# MODE SENSE：全量 / 单页 / 精华版
curl -s .../api/v1/drives/sg2/modes            | jq   # 全部模式页（字节级解析）
curl -s ".../api/v1/drives/sg2/modes?page=0x0f" | jq  # 仅压缩页
curl -s .../api/v1/drives/sg2/modes/sum        | jq   # 压缩/分区/块描述符精华

# LOG SENSE：全量 / 单页 / 精华版
curl -s .../api/v1/drives/sg2/logsense        | jq   # 25 个日志页结构化
curl -s ".../api/v1/drives/sg2/logsense?page=0x17" | jq
curl -s .../api/v1/drives/sg2/logsense/sum    | jq   # 寿命/错误/容量/TapeAlert

# 内核日志设备映射
curl -s .../api/v1/diagnostics/dmesg | jq '.data.device_map'
```

**磁带定位（17 个 mt 操作统一入口）**
```bash
curl -s -X POST .../api/v1/drives/nst1/position \
  -H 'Content-Type: application/json' \
  -d '{"operation": "fsf", "count": 2, "confirm": true}'

# operation 可选：
#   介质：  eject / offline / rewoffl / load
#   定位：  rewind / seod / eod / eom / fsf / fsfm / bsf / bsfm
#           fsr / bsr / fss / bss / asf / seek / tell
# count 缺省 1（seek/asf 为目标位置参数）
```

**写文件标记**
```bash
curl -s -X POST .../api/v1/drives/nst1/weof \
  -H 'Content-Type: application/json' -d '{"count": 1, "confirm": true}'
# 返回 data.position_after（写后回读 file/block/partition/flags）
```

**命令审计**
```bash
curl -s .../api/v1/commands | jq    # 底层命令执行历史（command_id 追溯）
```

行为要点：
- 空仓预检：无介质时 eject/offline 幂等成功，其余操作快速返回 `NO_MEDIUM`（避免 mt 在空仓上内核挂死）
- `tell` 在 ULT3580 上设备不支持（I/O error），查位置请用 `GET /drives/{nst}/status`

---

## 3. Web Demo 应用

React 19 + Ant Design 5 + ECharts 单页应用，10 个页面：

| 页面 | 功能 |
|---|---|
| Dashboard | 集群总览：库/带机/磁带健康度、容量图表 |
| Libraries / LibraryDetail | 库与槽位矩阵（SlotGrid），磁带进出可视化 |
| Drives / DriveDetail | 带机详情：状态、压缩、模式页、日志精华 |
| Tapes | 磁带清单（条码/容量/位置） |
| Operations | 命令操作台（装载/定位/卸出，二次确认对话框） |
| TestCenter | 测试中心：Mount/Unmount 全流程自动化验证 |
| Audit | 命令审计追溯 |
| ApiLogs | API 调用日志查看 |

组件库：DeviceTree（HBA 拓扑树）、SlotGrid（槽位网格）、ConfirmDialog（风险确认）、RiskTag（LEVEL 分级标签）、TestProgress（测试进度）。

---

## 4. 安装部署

### 依赖

- Linux + SCSI 子统（`sg` / `st` / `ch` 驱动），FC HBA（本文环境 Emulex LPe12000，lpfc 驱动）
- 工具链：`mtx`、`mt-st`、`sg3-utils`、`lsscsi`
- Python 3.9+（后端）、Node 18+（前端构建）

```bash
# RHEL/Rocky 示例
dnf install -y mtx mt-st sg3_utils lsscsi python3 python3-pip
```

### 后端

```bash
cd tape-library-api
pip install -r requirements.txt

# 启动（模式见安全分级表）
TAPE_API_MODE=FULL ALLOW_DEVICE_OPERATION=true ALLOW_WRITE=true \
  python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

### 前端

```bash
cd tape-library-web
npm install
npm run build          # 产出 dist/

# 方式一：nginx 直接服务 dist/ 并反代 /api → 8001（推荐）
# 方式二：docker compose up（附 Dockerfile）
```

nginx 关键配置（`tape-library-web/nginx.conf`）：

```nginx
location /api/ { proxy_pass http://127.0.0.1:8001/api/; }
location /     { root /home/tape_api/tape-library-web/dist; try_files $uri /index.html; }
```

### 验证

```bash
curl -s http://localhost:8080/api/v1/discovery/map | jq '.data.matrix'
curl -s http://localhost:8080/api/v1/drives/nst1/status | jq '.data.parsed'
```

### 测试

```bash
cd tape-library-api && python3 -m pytest        # 后端单测
cd tape-library-web && npx playwright test      # 前端 e2e
```

---

## 5. 目录结构

```
tape-library-api/          # FastAPI 后端
  app/api/routes.py        #   路由
  app/services/            #   业务服务
  app/commands/            #   命令组装/执行/解析
  app/security/            #   风险分级
  app/audit/               #   审计
  docs/                    #   API 文档与使用手册
  tests/                   #   pytest

tape-library-web/          # React 前端
  src/pages/               #   10 个页面
  src/components/          #   通用组件
  src/api/                 #   接口封装
  tests/e2e/               #   Playwright
  nginx.conf               #   部署配置
```
