> 2026-09-22 同步入库注：线上部署已演进至 v1.4.0（新增 LTFS 双格式 ltfs_* 配置键与 HATest），本手册为 v1.2.4 配置体系实测基线（2026-09-20），v1.3+ 增量见企微智能文档「Tape_API raw+LTFS 双格式改造实施文档」。

> 适用软件：磁带归档网关（tape-library-api `/api/v1/archive/*`，版本 v1.2.4，2026-09-20 上线）
> 部署机：172.16.12.186（后端 127.0.0.1:8001，nginx :8080）
> 本手册所有回包均为 2026-09-20 22:11 于 186 实测原始输出（超长截断，留档见文末）

## 1. 配置体系：三层优先级

归档网关的参数解析按以下优先级逐键生效（v1.2.4 起）：

| 层 | 载体 | 说明 |
| --- | --- | --- |
| ① 文件层 | `/home/tape_api/gateway-config.json` | 由 gw-config API 写入；`$GATEWAY_CONFIG_FILE` 可改路径；**删除该文件即回到纯 env 行为**；文件损坏自动逐键回退，不阻塞启动 |
| ② 环境变量层 | `GATEWAY_*`（start-gw.sh 从 `/home/tape_api/gw.env` 注入） | 生产现状即这一层（文件层为空） |
| ③ 内置默认 | 代码默认值 | 上两层都没给的键走默认 |

逐键溯源：`GET /api/v1/archive/config` 回包 `sources`（每键 `file/env/default`）与 `file_keys`。

**语义要点**：自 v1.2.4 起 `/archive` 路由**无条件挂载**——网关未运行（PG 不可达 / enabled=false）时，其余 /archive 端点回 503 `GATEWAY_UNAVAILABLE`，但 gw-config 三端点仍可用，可**在启动网关前完成预配置**；改参数不再依赖重启整个 uvicorn 进程。

## 2. 配置项一览（17 键）

当前生产值 = 2026-09-20 22:11 `GET /archive/gw-config` 实测 `live`（来源列为 `sources` 字段）。

| 键 | 含义 | 当前生产值 | 来源 |
| --- | --- | --- | --- |
| enabled | 网关总开关（false 时 apply 保持停止） | true | env |
| cache_dir | 缓存根目录 | /home/tape_api/archive-cache | env |
| db_dsn | PG 元数据库（库 `tapegw`） | 127.0.0.1:5432/tapegw | env |
| small_file_mb | 大小文件分界，>该值直写磁带 | 64 | default |
| container_target_mb | 小文件容器封箱目标大小 | 1024 | default |
| container_flush_s | 容器首个文件滞留超时封箱（秒） | 120 | default |
| container_max_files | 单容器文件数上限 | 4000 | default |
| cache_quota_gb | 缓存容量配额（GB） | 200 | default |
| watermarks_pct | LRU 双水位 [low,high] | [70,85] | default |
| drive | 默认带机设备 | /dev/nst1 | env |
| changer | 默认带库机械手设备 | /dev/sg1 | env |
| dte_map | DTE→带机设备映射 | {"0":"/dev/nst0","2":"/dev/nst1"} | env |
| auto_load | 自动装卸带开关 | true | env |
| trust_drive | 手动锚定带机介质条码（绕过机器人）；空串=显式清除回自动模式 | null（自动模式） | default |
| verify_write | 落带写校验开关 | false | default |
| max_attempts | 设备命令重试次数 | 3 | default |
| redis_enabled | Redis 缓存启用开关 | false | env |

## 3. 配置 API（gw-config 三端点）

### 3.1 GET /api/v1/archive/gw-config [L1]

全貌 = 运行实例 `live` + `file_layer` + `candidate_after_restart` + `pending_diff`（逐项 live → after_restart 对比）+ `restart_required`；网关未运行也可查。

```bash
curl -s http://127.0.0.1:8001/api/v1/archive/gw-config
```

实测（2026-09-20 22:11，REQ-20260920-221126-8775A4，截断）：

```json
{"success":true,"code":"OK","data":{"running":true,
 "live":{"enabled":true,"cache_dir":"/home/tape_api/archive-cache","db_dsn":"127.0.0.1:5432/tapegw",
  "small_file_mb":64,"container_target_mb":1024,"container_flush_s":120,"container_max_files":4000,
  "cache_quota_gb":200,"watermarks_pct":[70,85],"drive":"/dev/nst1","changer":"/dev/sg1",
  "dte_map":{"0":"/dev/nst0","2":"/dev/nst1"},"auto_load":true,"trust_drive":null,
  "verify_write":false,"max_attempts":3,"redis_enabled":false,
  "config_file":"/home/tape_api/gateway-config.json","file_keys":[],
  "sources":{"enabled":"env","cache_dir":"env","db_dsn":"env","small_file_mb":"default", "...":"..."}},
 "file_layer":{},"restart_required":false,"pending_diff":[]}}
```

（当前文件层为空 `{}`，全部键走 env/default，`gateway-config.json` 不存在。）

### 3.2 POST /api/v1/archive/gw-config [L2，confirm=true 必需]

保存参数到文件层。键集与 `GET /archive/config` 的 summary 同形（即上表 17 键白名单，未知键 400 `INVALID_GW_CONFIG`）。

服务端校验（全部实测过负向用例）：
- 设备路径过 normalize_device 白名单——`/dev/hax;rm -rf /` 类注入直接 400
- `watermarks_pct` 必须 0 < low < high < 100
- `small_file_mb ≤ container_target_mb`
- `db_dsn` 短形式 `"host:port/db"` 自动补全为完整 DSN
- `trust_drive` 传空串 = 显式清除（回自动装载模式）
- 缺 `confirm:true` → 400

```bash
# 示例：调小文件阈值并立即生效（v1.2.4 上线 E2E 第 6/8 步实测链路）
curl -s -X POST http://127.0.0.1:8001/api/v1/archive/gw-config \
  -H 'Content-Type: application/json' \
  -d '{"config":{"small_file_mb":32,"watermarks_pct":[60,80],"cache_quota_gb":150},"confirm":true,"apply":true}'
```

回包关键字段：`saved` / `applied` / `restart_required`。`apply=true` 时写文件后立即原地重启生效。

### 3.3 POST /api/v1/archive/gw-config/apply [L2，confirm=true 必需]

按已保存配置**原地重启 worker**（shutdown 旧实例 → 重读 GatewayConfig → 新 GatewayManager，四 worker 线程重建）。

- 有运行中 job → 409 `GW_JOBS_RUNNING` 拒绝（勿当故障）
- 文件层 `enabled=false` → 保持停止并回报原因
- 只重启 worker，**不重读 Python 代码**——改过代码仍走全进程重启（见 §4）

## 4. 环境变量层与启动脚本

生产启动链：`/home/tape_api/start-gw.sh` 逐行回放 `/home/tape_api/gw.env` 后拉起 uvicorn。当前网关相关变量集（实测于 2026-09-20）：

```bash
GATEWAY_ENABLED=true
GATEWAY_DB_DSN=postgresql://postgres@127.0.0.1:5432/tapegw   # PG trust 免密，无密码成分
GATEWAY_CACHE_DIR=/home/tape_api/archive-cache
GATEWAY_CHANGER=/dev/sg1
GATEWAY_DRIVE=/dev/nst1
GATEWAY_DTE_MAP={"0":"/dev/nst0","2":"/dev/nst1"}
GATEWAY_AUTO_LOAD=true                       # 不设 GATEWAY_TRUST_DRIVE = 自动模式
TAPE_API_MODE=FULL
ALLOW_DEVICE_OPERATION=true
ALLOW_WRITE=true
TEST_MEDIA=IBM015LA
```

手工重启套路（部署新代码后）：

```bash
# 1) 先抓活进程全量 env 原样复用，勿按关键字过滤重建（漏 ALLOW_* 会 PERMISSION_DENIED）
tr '\0' '\n' < /proc/<pid>/environ > /home/tape_api/gw.env
# 2) 防自匹配杀旧进程，再走固定脚本（setsid 常驻）
pkill -f 'uvicorn app[.]main:app'
bash /home/tape_api/start-gw.sh
```

## 5. 常见排查

| 症状 | 处置 |
| --- | --- |
| 改了参数不生效 | `GET gw-config` 看 `file_layer`/`sources`——文件层单键会**盖过** gw.env 同名键；要回 env 基线就删文件层对应键或整文件删除后 apply |
| apply 后行为没变 | 确认是否改的是 Python 代码——apply 只重启 worker 不重读代码，需 §4 全进程重启 |
| /archive 端点全 503 | 网关未运行（PG 不可达 / enabled=false），属设计行为；gw-config 仍可用，改好配置 apply 拉起 |
| apply 回 409 | 有 running job，等终态再 apply |
| 机器人 Not Ready 长时间 | 盘点瞬态非故障；紧急绕过可设 trust_drive 锚定当前带，但要自动换带就别设 |

回归脚本：`tape-library-api-app/tmp_deploy/test_gwconfig.sh`（14 步含五连负向校验）。

## 6. 原始回包留档

- 本手册 §3.1/§4 实测：186 `:/tmp/cfgm_gwconfig.json`、`/tmp/cfgm_config.json`、`/tmp/cfgm_stats.json`（REQ-20260920-221126-*，2026-09-20 22:11）
- v1.2.4 上线 14 步 E2E：186 `:/tmp/gwc*.json`（原始 JSON，含 pending_diff→apply 全链）
