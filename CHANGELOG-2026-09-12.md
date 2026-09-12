# 修改清单 2026-09-12

## tape-library-api（FastAPI 后端）

### 1. Drive 接口重命名/扩展（09-10~09-12，已含于既有提交基础上）
- `setblk`→`/block-size`、`setdensity`→`/density`、`tell` 等按映射表统一命名
- 新增 `/options`、`/partition`、`/partition/seek`、`/tapealert` 等
- 26 个 drive 接口与 CLI 映射表一致；手册 `docs/API-usage-drive-manual.md`（34 节，26 PASS / 8 硬件不支持）

### 2. Library robot 接口新增（当日）
- `POST /libraries/{id}/exchange`（EXCHANGE_SUCCESS）
- `POST /libraries/{id}/robot/position`（旧 `/position` 保留隐藏别名）
- `POST /libraries/{id}/robot/first|next|last`（FIRST/NEXT/LAST_SUCCESS）
- **`robot/last` 修复**：mtx 自带 last 因 IE 槽混编号误判末带位置；改为服务层仿真（解析 status → 过滤 IMPORT/EXPORT 槽 → 最大满槽精确 load）
- 文档 `docs/API-usage-library-robot-manual.md`

### 3. `/inventory` 语义修正
- 原：解析 mtx status 返回清单 → 现：真正执行 `mtx inventory`（INITIALIZE ELEMENT STATUS，LEVEL 2，GET）
- 原解析逻辑移入私有 `_status_inventory()`（load 内部仍用）；对外查清单用 `GET /status`

### 4. `/read` 接口改造
- 路径 `POST /tests/read` → `POST /read`（旧路径隐藏别名）
- 新增 `file` 参数：读取数据保存到指定文件（dd of=<file>）；省略时丢弃到 /dev/null
- 新增 `policy.validate_output_path`（绝对路径、拒 ..//dev）
- 结果码 READ_TEST_PASS → READ_SUCCESS；文档 `docs/API-usage-read.md`

### 5. `/write` 接口改造
- 路径 `POST /tests/write` → `POST /write`（旧路径隐藏别名）
- 参数 `test_media` → `media`（旧名兼容）
- 新增 `file` 参数：把指定文件内容写入磁带（dd if=<file> of=drive）；不指定时维持零数据测速模式
- 新增 `policy.validate_input_path`（拒 /dev /proc /sys、相对路径；文件不存在→FILE_NOT_FOUND）
- 结果码 WRITE_TEST_PASS → WRITE_SUCCESS；文档 `docs/API-usage-write.md`

### 6. SCSI 通用接口新增（6 个）
- `GET /scsi/{device}/inquiry`（sg_inq）、`/vpd`（sg_vpd -p 0x80|0x83）、`/logs`（sg_logs，可选 page）、`/tapealert`（sg_logs -p 0x2e）、`/persist`（sg_persist）— LEVEL 1
- `POST /scsi/{device}/reset`（sg_reset -d）— LEVEL 2 + confirm + 设备锁
- 文档 `docs/API-usage-scsi-manual.md`

### 7. 测试与部署
- mock 测试 108 个全过（新增 library robot / SCSI / read / write 用例）
- 部署 node186 8001/8002（FULL 模式），全部接口真机验证通过

## tape-library-web（React GUI）

- **client.ts 更新**：
  - 库存清单改走 `/status` 解析（避免误触发 `/inventory` 物理重扫）
  - 读测试改调 `POST /read`（drive/block_size:"1M"/confirm，修正旧 nst_device 参数错误）
  - FC 双路径去重：sg1/sg3 同一物理库，用 `/scsi/{dev}/inquiry` 序列号识别去重
- **构建部署**：`VITE_API_MODE=real`（同源 /api），dist 同步 node186（nginx 8080）
- **Playwright Chromium 回归**：10 个页面全部 REAL MODE 加载正常、无 JS 错误（截图 shots/）
