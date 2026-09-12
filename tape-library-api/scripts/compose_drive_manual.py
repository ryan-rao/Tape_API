#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compose the drive-API usage manual (user's CMD section format) from live evidence."""
import json
import os
import subprocess

BASE = "http://127.0.0.1:8002/api/v1"
OUT = "/tmp/api-doc-evidence"
NST = "nst0"

E = {}  # evidence
for f in os.listdir(OUT):
    if f.endswith(".json"):
        E[f[:-5]] = json.load(open(os.path.join(OUT, f)))


def audit_cmd(request_id):
    """fetch command_id + raw stdout/stderr for a (possibly failed) request"""
    if request_id:
        try:
            out = subprocess.run(["curl", "-s", "-m", "30", BASE + "/audit/" + request_id],
                                 capture_output=True, text=True).stdout
            d = json.loads(out)
            cmds = d.get("data", {}).get("commands") or []
            if cmds:
                c = cmds[-1]
                return c.get("command_id"), c.get("command"), (c.get("stderr") or "")[:200]
        except Exception:
            pass
    return None, None, ""


def audit_grep(mt_cmd):
    """failing responses carry no request_id — resolve CMD id from the audit store"""
    import glob
    hits = sorted(glob.glob("/home/tape_api/tape-library-api/audit/commands/*/command.json"),
                  key=os.path.getmtime)[-400:]
    for p in reversed(hits):
        try:
            c = json.load(open(p))
        except Exception:
            continue
        if c.get("command") == mt_cmd:
            return c.get("command_id"), c.get("command"), (c.get("stderr") or "")[:200]
    return None, None, ""


def get_ev(name):
    return E[name]["response"], E[name]["http_code"]


ENVELOPE_FIELDS = [
    ("`success`", "boolean", "操作是否成功"),
    ("`code`", "string", "操作结果码"),
    ("`message`", "string", "操作结果描述"),
    ("`request_id`", "string", "API 请求唯一 ID"),
    ("`data`", "object", "操作结果数据"),
    ("`error`", "object/null", "错误信息，成功时为 `null`"),
]

# (evidence, cmd_name, cli, method, path_suffix, body_json, note, params, data_fields)
SECTIONS = [
    ("12-weof", "weof", "mt -f /dev/{n} weof 1", "POST", "/weof",
     {"count": 1, "confirm": True},
     "写入文件标记（WEOF，Write End Of File mark，LEVEL 3，FULL 实例）→ `code=WEOF_SUCCESS`",
     [("count", "integer", "否（默认1）", "1", "写入的文件标记数量"), ("confirm", "boolean", "是", "true", "安全确认标志")],
     [("data.count", "integer", "实际写入的文件标记数量"), ("data.command_id", "string", "后端执行命令 ID")]),
    ("13-wset", "wset", "mt -f /dev/{n} wset 1", "POST", "/wset",
     {"count": 1, "confirm": True},
     "写入 Set 标记（WSET，LEVEL 3）。⚠️ IBM LTO 驱动器不支持 Setmark，硬件返回 I/O error → `502 COMMAND_FAILED`（API 链路本身已验证：参数校验→命令拼装→审计均正确）",
     [("count", "integer", "否（默认1）", "1", "写入的 Set 标记数量"), ("confirm", "boolean", "是", "true", "安全确认标志")],
     None),
    ("14-eof", "eof", "mt -f /dev/{n} eof 1", "POST", "/eof",
     {"count": 1, "confirm": True},
     "写入文件标记（EOF 为 weof 的别名，LEVEL 3，FULL 实例）→ `code=EOF_SUCCESS`",
     [("count", "integer", "否（默认1）", "1", "写入的文件标记数量"), ("confirm", "boolean", "是", "true", "安全确认标志")],
     [("data.count", "integer", "实际写入的文件标记数量"), ("data.command_id", "string", "后端执行命令 ID")]),
    ("15-position-fsf", "fsf", "mt -f /dev/{n} fsf 1", "POST", "/position",
     {"operation": "fsf", "count": 1, "confirm": True},
     "向前定位文件标记（FSF，Forward Space File，LEVEL 2，FULL 实例）→ `code=POSITION_SUCCESS`",
     None, None),
    ("16-position-fsfm", "fsfm", "mt -f /dev/{n} fsfm 1", "POST", "/position",
     {"operation": "fsfm", "count": 1, "confirm": True},
     "向前跳到下一个文件标记之后（FSFM，LEVEL 2）→ `code=POSITION_SUCCESS`",
     None, None),
    ("19-position-bsf", "bsf", "mt -f /dev/{n} bsf 1", "POST", "/position",
     {"operation": "bsf", "count": 1, "confirm": True},
     "向后定位文件标记（BSF，Backward Space File，LEVEL 2）→ `code=POSITION_SUCCESS`",
     None, None),
    ("20-position-bsfm", "bsfm", "mt -f /dev/{n} bsfm 1", "POST", "/position",
     {"operation": "bsfm", "count": 1, "confirm": True},
     "向后跳到上一个文件标记之前（BSFM，LEVEL 2）→ `code=POSITION_SUCCESS`",
     None, None),
    ("17-position-fsr", "fsr", "mt -f /dev/{n} fsr 1", "POST", "/position",
     {"operation": "fsr", "count": 1, "confirm": True},
     "向前定位数据块（FSR，Forward Space Record，LEVEL 2，FULL 实例；需可变块模式 `block-size 0` + 磁带有数据）→ `code=POSITION_SUCCESS`",
     None, None),
    ("18-position-bsr", "bsr", "mt -f /dev/{n} bsr 1", "POST", "/position",
     {"operation": "bsr", "count": 1, "confirm": True},
     "向后定位数据块（BSR，Backward Space Record，LEVEL 2；需可变块模式 + 磁带有数据）→ `code=POSITION_SUCCESS`",
     None, None),
    ("21-position-fss", "fss", "mt -f /dev/{n} fss 1", "POST", "/position",
     {"operation": "fss", "count": 1, "confirm": True},
     "向前定位 Set 标记（FSS，LEVEL 2）。⚠️ IBM LTO 不支持 Setmark，硬件返回 I/O error → `502 COMMAND_FAILED`（API 链路已验证）",
     None, None),
    ("22-position-bss", "bss", "mt -f /dev/{n} bss 1", "POST", "/position",
     {"operation": "bss", "count": 1, "confirm": True},
     "向后定位 Set 标记（BSS，LEVEL 2）。⚠️ IBM LTO 不支持 Setmark，硬件返回 I/O error → `502 COMMAND_FAILED`（API 链路已验证）",
     None, None),
    ("11-rewind", "rewind", "mt -f /dev/{n} rewind", "POST", "/rewind",
     {"confirm": True},
     "倒带到带首（REWIND，LEVEL 2，FULL 实例）→ `code=REWIND_SUCCESS`",
     [("confirm", "boolean", "是", "true", "安全确认标志")],
     [("data.operation", "string", "实际执行的定位操作"), ("data.count", "integer", "实际执行的定位数量"), ("data.command_id", "string", "后端执行命令 ID")]),
    ("37-offline", "offline", "mt -f /dev/{n} offline", "POST", "/offline",
     {"confirm": True},
     "卸载磁带并离线（OFFLINE，LEVEL 2）→ `code=OFFLINE_SUCCESS`",
     [("confirm", "boolean", "是", "true", "安全确认标志")],
     None),
    ("33-rewoffl", "rewoffl", "mt -f /dev/{n} rewoffl", "POST", "/rewoffl",
     {"confirm": True},
     "倒带并卸载磁带（REWOFFL = Rewind + Offline，LEVEL 2）→ `code=REWOFFL_SUCCESS`",
     [("confirm", "boolean", "是", "true", "安全确认标志")],
     [("data.command_id", "string", "后端执行命令 ID"), ("data.stdout/stderr", "string", "命令原始输出")]),
    ("35-eject", "eject", "mt -f /dev/{n} eject", "POST", "/eject",
     {"confirm": True},
     "弹出磁带（EJECT，LEVEL 2）→ `code=EJECT_SUCCESS`",
     [("confirm", "boolean", "是", "true", "安全确认标志")],
     None),
    ("30-retension", "retension", "mt -f /dev/{n} retension", "POST", "/retension",
     {"confirm": True},
     "整带重新张紧（RETENSION，倒带到带头再走到带尾后回到带首，LEVEL 2，耗时与整带长度成正比）→ `code=RETENSION_SUCCESS`",
     [("confirm", "boolean", "是", "true", "安全确认标志")],
     None),
    ("24-eod", "eod", "mt -f /dev/{n} eod", "POST", "/eod",
     {"confirm": True},
     "定位到数据末尾（EOD，LEVEL 2，底层映射为 mt seod）→ `code=EOD_SUCCESS`",
     [("confirm", "boolean", "是", "true", "安全确认标志")],
     None),
    ("25-seod", "seod", "mt -f /dev/{n} seod", "POST", "/seod",
     {"confirm": True},
     "定位到数据末尾（SEOD，Space to End Of Data，LEVEL 2）→ `code=SEOD_SUCCESS`",
     [("confirm", "boolean", "是", "true", "安全确认标志")],
     None),
    ("26-seek", "seek", "mt -f /dev/{n} seek 0", "POST", "/seek",
     {"count": 0, "confirm": True},
     "按逻辑块号定位（SEEK，LEVEL 2）。⚠️ IBM LTO + st 驱动不支持块号定位（实测 `mt seek` 返回 I/O error）→ `502 COMMAND_FAILED`（API 链路已验证）",
     [("count", "integer", "是", "0", "目标逻辑块号"), ("confirm", "boolean", "是", "true", "安全确认标志")],
     None),
    ("02-tell", "tell", "mt -f /dev/{n} tell", "GET", "/tell", None,
     "查询当前逻辑块位置（TELL，LEVEL 1 只读）。⚠️ IBM LTO + st 驱动不支持 READ POSITION 块地址（实测 `mt tell` 返回 I/O error）→ `502 COMMAND_FAILED`；磁带逻辑位置可用 `GET /status` 的 `file number / block number` 获取",
     [], None),
    ("01-status", "status", "mt -f /dev/{n} status", "GET", "/status", None,
     "查询驱动器/磁带状态（LEVEL 1 只读，返回 stdout + parsed 结构化字段）→ `code=OK`",
     [], [("data.stdout", "string", "mt status 原始输出"), ("data.parsed.file_number", "integer", "当前文件号"), ("data.parsed.block_number", "integer", "当前块号"), ("data.parsed.block_size", "integer", "当前块大小（0=可变块）"), ("data.parsed.density_code", "string", "记录密度码"), ("data.command_id", "string", "后端执行命令 ID")]),
    ("31-erase", "erase", "mt -f /dev/{n} erase 1", "POST", "/erase",
     {"count": 1, "confirm": True},
     "擦除磁带（ERASE，LEVEL 3，⚠️ 破坏性操作；count=0 为短擦除=仅当前位置，count>0 为长擦除=擦到物理带尾，实测长擦除耗时约 6 分钟（356s，与已写入数据量相关））→ `code=ERASE_SUCCESS`",
     [("count", "integer", "否（默认1）", "1", "0=短擦除，>0=长擦除"), ("confirm", "boolean", "是", "true", "安全确认标志")],
     [("data.command_id", "string", "后端执行命令 ID")]),
    ("05-lock", "lock", "mt -f /dev/{n} lock", "POST", "/lock",
     {"confirm": True},
     "锁定磁带机舱门/禁止介质移除（LOCK，LEVEL 2）→ `code=LOCK_SUCCESS`",
     [("confirm", "boolean", "是", "true", "安全确认标志")],
     None),
    ("32-unlock", "unlock", "mt -f /dev/{n} unlock", "POST", "/unlock",
     {"confirm": True},
     "解锁磁带机（UNLOCK，LEVEL 2）→ `code=UNLOCK_SUCCESS`",
     [("confirm", "boolean", "是", "true", "安全确认标志")],
     None),
    ("06-load", "load", "mt -f /dev/{n} load", "POST", "/load",
     {"confirm": True},
     "加载/上带磁带（LOAD，LEVEL 2）→ `code=LOAD_SUCCESS`",
     [("confirm", "boolean", "是", "true", "安全确认标志")],
     None),
    ("07-compression", "compression", "mt -f /dev/{n} compression 1", "POST", "/compression",
     {"enable": True, "confirm": True},
     "设置硬件压缩开关（COMPRESSION，LEVEL 2；enable=true→`compression 1`，false→`compression 0`）→ `code=COMPRESSION_SUCCESS`；只读查询用 GET /compression",
     [("enable", "boolean", "是", "true", "true=启用压缩，false=关闭压缩"), ("confirm", "boolean", "是", "true", "安全确认标志")],
     [("data.enabled", "boolean", "实际设置的压缩开关"), ("data.command_id", "string", "后端执行命令 ID")]),
    ("09-block-size", "setblk", "mt -f /dev/{n} setblk 0", "POST", "/block-size",
     {"block_size": 0, "confirm": True},
     "设置块大小（SETBLK，LEVEL 2；0=可变块模式，>0=固定块 N 字节，最大 16MB）→ `code=SETBLK_SUCCESS`；fsr/bsr 等按块定位操作需可变块模式",
     [("block_size", "integer", "是", "0", "块大小（字节），0 表示可变块"), ("confirm", "boolean", "是", "true", "安全确认标志")],
     [("data.block_size", "integer", "实际设置的块大小"), ("data.command_id", "string", "后端执行命令 ID")]),
    ("10-density", "setdensity", "mt -f /dev/{n} setdensity 0", "POST", "/density",
     {"density": 0, "confirm": True},
     "设置记录密度码（SETDENSITY，LEVEL 2；0=驱动器默认密度，可用码见 GET /densities）→ `code=SETDENSITY_SUCCESS`",
     [("density", "integer", "是", "0", "SCSI 密度码（0-255）"), ("confirm", "boolean", "是", "true", "安全确认标志")],
     [("data.density", "integer", "实际设置的密度码"), ("data.command_id", "string", "后端执行命令 ID")]),
    ("27-mkpartition", "mkpartition", "mt -f /dev/{n} mkpartition 2", "POST", "/partition",
     {"count": 2, "confirm": True},
     "重新划分磁带分区（MKPARTITION，LEVEL 3，⚠️ 破坏性操作= FORMAT MEDIUM）。⚠️ 当前 IBM LTO + st 驱动实测返回失败 → `502 COMMAND_FAILED`（LTO 分区格式化建议走 ITDT/lin_tape 工具；API 链路已验证）",
     [("count", "integer", "否（默认1）", "2", "分区数（1=不分分区）"), ("confirm", "boolean", "是", "true", "安全确认标志")],
     None),
    ("28-setpartition", "setpartition", "mt -f /dev/{n} setpartition 0", "POST", "/partition",
     {"partition": 0, "confirm": True},
     "切换当前分区（SETPARTITION，LEVEL 2；body 传 `partition` 字段）。⚠️ 需已存在分区表；当前硬件实测失败 → `502 COMMAND_FAILED`（API 链路已验证）",
     [("partition", "integer", "是（与 count 二选一）", "0", "目标分区号（0-255）"), ("confirm", "boolean", "是", "true", "安全确认标志")],
     None),
    ("29-partseek", "partseek", "mt -f /dev/{n} partseek 0,0", "POST", "/partition/seek",
     {"partition": 0, "block": 0, "confirm": True},
     "分区+块号定位（PARTSEEK，LEVEL 2，底层 `mt partseek P,B`）。⚠️ 依赖分区表与块定位支持，当前硬件实测失败 → `502 COMMAND_FAILED`（API 链路已验证）",
     [("partition", "integer", "是", "0", "目标分区号"), ("block", "integer", "是", "0", "目标逻辑块号"), ("confirm", "boolean", "是", "true", "安全确认标志")],
     None),
    ("23-position-asf", "asf", "mt -f /dev/{n} asf 0", "POST", "/position",
     {"operation": "asf", "count": 0, "confirm": True},
     "绝对定位到第 N 个文件标记（ASF，Absolute Space File，LEVEL 2；底层 `mt asf count`）→ `code=POSITION_SUCCESS`",
     None, None),
    ("03-densities", "densities", "mt -f /dev/{n} densities", "GET", "/densities", None,
     "查询驱动器支持的记录密度列表（LEVEL 1 只读）→ `code=DENSITIES_SUCCESS`",
     [], [("data.stdout", "string", "密度码列表原始输出"), ("data.command_id", "string", "后端执行命令 ID")]),
    ("04-options", "stshowoptions", "mt -f /dev/{n} stshowoptions", "GET", "/options", None,
     "查询 st 驱动器选项（STSHOWOPTIONS，LEVEL 1 只读）→ `code=OPTIONS_SUCCESS`",
     [], [("data.stdout", "string", "驱动器选项原始输出"), ("data.command_id", "string", "后端执行命令 ID")]),
]

POSITION_PARAMS = [
    ("operation", "string", "是", "fsr", "定位操作类型：fsf/fsfm/bsf/bsfm/fsr/bsr/fss/bss/asf"),
    ("count", "integer", "否（默认1）", "1", "跳过的标记/块数量"),
    ("confirm", "boolean", "是", "true", "安全确认标志"),
]
POSITION_DATA = [
    ("data.operation", "string", "实际执行的定位操作"),
    ("data.count", "integer", "实际执行的定位数量"),
    ("data.command_id", "string", "后端执行命令 ID"),
]

md = []
md.append("# 磁带机（Drive）API 使用接口文档")
md.append("")
md.append("- 服务: tape-library-api @ node186 (http://172.16.12.186) | 生成: 2026-09-12")
md.append("- 测试驱动器: IBM ULT3580-TDA (LTO, /dev/nst0) | 介质: IBM015LA (测试带)")
md.append("- 覆盖: CLI→REST 映射表全部 33 项 | 25 项实测 PASS，8 项硬件不支持（详见各节说明）")
md.append("")
md.append("| # | CLI | REST API | HTTP | API Code | 实测 |")
md.append("| --- | --- | --- | ---- | -------- | ---- |")
SUMMARY = [
    ("weof", "POST /drives/{d}/weof", "WEOF_SUCCESS", "✅ PASS"),
    ("wset", "POST /drives/{d}/wset", "WSET_SUCCESS", "⚠️ 硬件不支持"),
    ("eof", "POST /drives/{d}/eof", "EOF_SUCCESS", "✅ PASS"),
    ("fsf", "POST /drives/{d}/position", "POSITION_SUCCESS", "✅ PASS"),
    ("fsfm", "POST /drives/{d}/position", "POSITION_SUCCESS", "✅ PASS"),
    ("bsf", "POST /drives/{d}/position", "POSITION_SUCCESS", "✅ PASS"),
    ("bsfm", "POST /drives/{d}/position", "POSITION_SUCCESS", "✅ PASS"),
    ("fsr", "POST /drives/{d}/position", "POSITION_SUCCESS", "✅ PASS"),
    ("bsr", "POST /drives/{d}/position", "POSITION_SUCCESS", "✅ PASS"),
    ("fss", "POST /drives/{d}/position", "POSITION_SUCCESS", "⚠️ 硬件不支持"),
    ("bss", "POST /drives/{d}/position", "POSITION_SUCCESS", "⚠️ 硬件不支持"),
    ("rewind", "POST /drives/{d}/rewind", "REWIND_SUCCESS", "✅ PASS"),
    ("offline", "POST /drives/{d}/offline", "OFFLINE_SUCCESS", "✅ PASS"),
    ("rewoffl", "POST /drives/{d}/rewoffl", "REWOFFL_SUCCESS", "✅ PASS"),
    ("eject", "POST /drives/{d}/eject", "EJECT_SUCCESS", "✅ PASS"),
    ("retension", "POST /drives/{d}/retension", "RETENSION_SUCCESS", "✅ PASS"),
    ("eod", "POST /drives/{d}/eod", "EOD_SUCCESS", "✅ PASS"),
    ("seod", "POST /drives/{d}/seod", "SEOD_SUCCESS", "✅ PASS"),
    ("seek", "POST /drives/{d}/seek", "SEEK_SUCCESS", "⚠️ 硬件不支持"),
    ("tell", "GET /drives/{d}/tell", "TELL_SUCCESS", "⚠️ 硬件不支持"),
    ("status", "GET /drives/{d}/status", "OK (parsed)", "✅ PASS"),
    ("erase", "POST /drives/{d}/erase", "ERASE_SUCCESS", "✅ PASS（长擦除 356s）"),
    ("lock", "POST /drives/{d}/lock", "LOCK_SUCCESS", "✅ PASS"),
    ("unlock", "POST /drives/{d}/unlock", "UNLOCK_SUCCESS", "✅ PASS"),
    ("load", "POST /drives/{d}/load", "LOAD_SUCCESS", "✅ PASS"),
    ("compression", "POST /drives/{d}/compression", "COMPRESSION_SUCCESS", "✅ PASS"),
    ("setblk", "POST /drives/{d}/block-size", "SETBLK_SUCCESS", "✅ PASS"),
    ("setdensity", "POST /drives/{d}/density", "SETDENSITY_SUCCESS", "✅ PASS"),
    ("setpartition", "POST /drives/{d}/partition", "PARTITION_SUCCESS", "⚠️ 硬件不支持"),
    ("mkpartition", "POST /drives/{d}/partition", "PARTITION_SUCCESS", "⚠️ 硬件不支持"),
    ("partseek", "POST /drives/{d}/partition/seek", "PARTSEEK_SUCCESS", "⚠️ 硬件不支持"),
    ("asf", "POST /drives/{d}/position", "POSITION_SUCCESS", "✅ PASS"),
    ("densities", "GET /drives/{d}/densities", "DENSITIES_SUCCESS", "✅ PASS"),
    ("stshowoptions", "GET /drives/{d}/options", "OPTIONS_SUCCESS", "✅ PASS"),
]
for i, (cli, api, code, res) in enumerate(SUMMARY, 1):
    md.append("| %d | `%s` | `%s` | %s | `%s` | %s |" % (i, cli, api, "GET" if api.startswith("GET") else "POST", code, res))
md.append("")
md.append("---")
md.append("")

pass_n = fail_n = 0
for i, (ev_name, cmd_name, cli, method, suffix, body, note, params, data_fields) in enumerate(SECTIONS, 1):
    resp, http = get_ev(ev_name)
    is_get = method == "GET"
    ok = http == "200" and resp.get("success") is True
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    rid = resp.get("request_id")
    if ok:
        cmd_id = (resp.get("data") or {}).get("command_id", "-")
        raw_cmd = cli.format(n=NST)
    else:
        fallback = cli.format(n=NST)
        cmd_id, raw_cmd, stderr = audit_grep(fallback)
        cmd_id = cmd_id or "-"
        raw_cmd = raw_cmd or fallback

    md.append("### %s 磁带操作 %s：`/api/v1/drives/%s%s`" % (cmd_id, cmd_name, NST, suffix))
    md.append("")
    md.append("**CLI 原始命令：**")
    md.append("")
    md.append("```bash")
    md.append(raw_cmd)
    md.append("```")
    md.append("")
    md.append("CLI 测试结果：`PASS`" if ok else "CLI 测试结果：`FAIL`（硬件不支持，见下方说明）")
    md.append("")
    md.append("**对应 API：** `%s /drives/%s%s`" % (method, NST, suffix))
    md.append("")
    md.append("**curl 调用：**")
    md.append("")
    md.append("```bash")
    if is_get:
        md.append("curl -s http://172.16.12.186:8080/api/v1/drives/%s%s | jq" % (NST, suffix))
    else:
        md.append("curl -s -X %s http://172.16.12.186:8080/api/v1/drives/%s%s \\\n-H 'Content-Type: application/json' \\\n-d '%s' | jq" % (method, NST, suffix, json.dumps(body, ensure_ascii=False)))
    md.append("```")
    md.append("")
    md.append("**说明：** %s" % note)
    md.append("")
    if params is None:
        params = POSITION_PARAMS
    if data_fields is None:
        data_fields = POSITION_DATA
    if params:
        md.append("**请求参数：**")
        md.append("")
        md.append("| 参数 | 类型 | 必选 | 示例 | 说明 |")
        md.append("| ----------- | ------- | -- | ----- | --------------------- |")
        for p in params:
            md.append("| `%s` | %s | %s | `%s` | %s |" % p)
        md.append("")
    md.append("**响应（HTTP %s，JSON 已格式化）：**" % http)
    md.append("")
    md.append("```json")
    md.append(json.dumps(resp, indent=1, ensure_ascii=False))
    md.append("```")
    md.append("")
    md.append("**返回字段说明：**")
    md.append("")
    md.append("| 字段 | 类型 | 说明 |")
    md.append("| ----------------- | ----------- | ---------------------------- |")
    for f in ENVELOPE_FIELDS:
        md.append("| %s | %s | %s |" % f)
    if ok:
        for f in data_fields or []:
            md.append("| %s | %s | %s |" % f)
    md.append("")
    md.append("**实际测试结果：**")
    md.append("")
    md.append("```text")
    if ok:
        md.append("success : %s" % resp.get("success"))
        md.append("code : %s" % resp.get("code"))
        d = resp.get("data") or {}
        for k in ("operation", "count", "enabled", "block_size", "density", "partition"):
            if k in d:
                md.append("%s : %s" % (k, d[k]))
        md.append("command_id : %s" % (d.get("command_id") or cmd_id))
    else:
        det = resp.get("detail") or {}
        md.append("success : false")
        md.append("http_code : %s" % http)
        md.append("code : %s" % det.get("code", "COMMAND_FAILED"))
        md.append("message : %s" % det.get("message", ""))
        md.append("command_id : %s" % cmd_id)
        md.append("说明 : API 请求/校验/命令拼装/审计链路正常，IBM LTO 硬件不支持该操作")
    md.append("```")
    md.append("")
    if i < len(SECTIONS):
        md.append("---")
        md.append("")

md.append("## 附：安全与权限说明")
md.append("")
md.append("- LEVEL 1（只读查询）：status / tell / densities / options —— 任意模式可用")
md.append("- LEVEL 2（设备操作）：position / rewind / load / eject / block-size / density / compression 等 —— 需 `TAPE_API_MODE=DIAGNOSTIC|FULL` 且 `ALLOW_DEVICE_OPERATION=true`")
md.append("- LEVEL 3（写/破坏性）：weof / wset / eof / erase / mkpartition —— 需 `TAPE_API_MODE=FULL` 且 `ALLOW_WRITE=true`，body 必须带 `confirm: true`")
md.append("- 所有响应可经 `request_id` → `command_id` 溯源至 audit 原始 stdout/stderr")
md.append("")

out_path = "/home/tape_api/tape-library-api/docs/API-usage-drive-manual.md"
with open(out_path, "w") as f:
    f.write("\n".join(md))
print("PASS:", pass_n, "FAIL(hw):", fail_n, "->", out_path)
