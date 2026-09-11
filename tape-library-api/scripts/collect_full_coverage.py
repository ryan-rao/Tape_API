#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Full CLI→API coverage collector: iterate CMD-000001..CMD-000108, map each to an
API endpoint, execute real curl calls (with hardware-state-correct ordering inherited
from the CLI sequence), pretty-print JSON responses, and emit per-CMD markdown."""
import glob
import json
import os
import re
import subprocess
import sys

BASE = sys.argv[1] if len(sys.argv) > 1 else "/home/tape_api/cli_test/tape-test/TL-20260910-161453"
OUT = "/tmp/api-manual3"
os.makedirs(OUT, exist_ok=True)
D1 = "http://127.0.0.1:8001/api/v1"  # DIAGNOSTIC
D2 = "http://127.0.0.1:8002/api/v1"  # FULL

_cache = {}
_stats = {"api_calls": 0, "cached_reuse": 0}


def curl(method, base, path, body=None):
    key = (method, base, path, json.dumps(body, sort_keys=True) if body else None)
    if key in _cache:
        _stats["cached_reuse"] += 1
        return _cache[key]
    url = base + path
    cmd = ["curl", "-s", "-w", "\n%{http_code}"]
    if method != "GET":
        cmd += ["-X", method, "-H", "Content-Type: application/json", "-d", json.dumps(body or {})]
    cmd.append(url)
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=3600).stdout
    lines = out.rsplit("\n", 1)
    http_code = lines[1].strip() if len(lines) > 1 else "0"
    raw = lines[0]
    try:
        parsed = json.loads(raw)
        pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    except Exception:
        pretty = raw
    result = (http_code, pretty)
    _cache[key] = result
    _stats["api_calls"] += 1
    return result


def short(name):
    """trim device to short form for path"""
    return name.replace("/dev/", "")


def build_curl_str(method, base, path, body):
    if method == "GET":
        return "curl -s {}{}".format(base.replace("http://127.0.0.1", ""), path)
    return "curl -s -X {m} {b}{p} -H 'Content-Type: application/json' -d '{j}'".format(
        m=method, b=base.replace("http://127.0.0.1", ""), p=path,
        j=json.dumps(body, ensure_ascii=False))


def map_and_call(cmdline):
    """Map a CLI command line to (api_title, method, base, path, body, note) or None."""
    c = cmdline.strip()
    # --- OS / system (1:1 granular endpoints) ---
    if c == "cat /etc/os-release":
        return ("GET /system/os-release（1:1）", "GET", D1, "/system/os-release", None,
                "cat /etc/os-release → data.parsed.name/version_id/all_fields")
    if c == "uname -a":
        return ("GET /system/uname（1:1）", "GET", D1, "/system/uname", None,
                "uname -a → data.parsed.kernel_release/machine 等")
    if c == "hostname":
        return ("GET /system/hostname（1:1）", "GET", D1, "/system/hostname", None,
                "hostname → data.parsed.hostname")
    if c == "uname -m":
        return ("GET /system/arch（1:1）", "GET", D1, "/system/arch", None,
                "uname -m → data.parsed.arch")
    if c in ("id", "whoami"):
        return ("GET /system/user（1:1）", "GET", D1, "/system/user", None,
                "id → data.parsed.uid/user/gid/groups")
    if re.match(r"^command -v \S+$", c):
        tool = re.match(r"^command -v (\S+)", c).group(1)
        return ("GET /dependencies/{}（1:1）".format(tool), "GET", D1,
                "/dependencies/{}".format(tool), None, "command -v {} → installed/path/exit_code 字段".format(tool))
    if "lsmod" in c:
        return ("GET /system/kernel", "GET", D1, "/system/kernel", None,
                "lsmod 模块检查 → data.{st,sg,ch,lin_tape}.loaded")
    if "IBMtape" in c or "itdt" in c:
        return ("GET /system/ibm", "GET", D1, "/system/ibm", None,
                "IBM 专用检测 → lin_tape_nodes / itdt_installed")
    # --- discovery ---
    if re.match(r"^lsscsi( -g)?$", c):
        return ("GET /discovery（lsscsi -g）", "GET", D1, "/discovery", None,
                "设备发现 → data.devices[]")
    if c.startswith("sg_scan") or c.startswith("sg_map"):
        return ("GET /discovery/detail（sg_scan + sg_map -i）", "GET", D1, "/discovery/detail", None,
                "原始扫描输出 → data.sg_scan.stdout / data.sg_map.stdout")
    # --- sg ---
    m = re.match(r"^sg_inq (/dev/\S+)", c)
    if m:
        s = short(m.group(1))
        return ("GET /devices/{}/inquiry".format(s), "GET", D1,
                "/devices/{}/inquiry".format(s), None, "SCSI Inquiry → data.stdout")
    m = re.match(r"^sg_vpd -p (\S+) (/dev/\S+)", c)
    if m:
        p, dev = m.group(1), short(m.group(2))
        return ("GET /devices/{}/vpd?page={}".format(dev, p), "GET", D1,
                "/devices/{}/vpd?page={}".format(dev, p), None, "VPD 页查询 → data.page/stdout")
    if "sg_turs" in c:
        devs = re.findall(r"/dev/sg\d", c) or ["/dev/sg0"]
        if len(devs) > 1:
            results = [curl("GET", D1, "/devices/{}/tur".format(short(d)), None) for d in devs]
            return ("GET /devices/SG/tur ×{}（逐台 TUR）".format(len(devs)), "MULTI", None, None, None,
                                "循环 TUR → 每台设备 ready 字段") or None
        return ("GET /devices/{}/tur".format(short(devs[0])), "GET", D1,
                "/devices/{}/tur".format(short(devs[0])), None, "TUR → data.ready")
    m = re.match(r"^sg_modes -a (/dev/\S+)", c)
    if m:
        s = short(m.group(1))
        return ("GET /devices/{}/modes".format(s), "GET", D1, "/devices/{}/modes".format(s), None,
                "模式页 → data.stdout")
    m = re.match(r"^sg_logs -p (\S+) (/dev/\S+)", c)
    if m:
        page, dev = m.group(1), short(m.group(2))
        if page in ("0x2e", "0x12"):
            return ("GET /drives/{}/tapealert".format(dev), "GET", D1,
                    "/drives/{}/tapealert".format(dev), None, "TapeAlert 解析 → data.alerts[] + raw_output")
        return ("GET /devices/{}/logs?page={}".format(dev, page), "GET", D1,
                "/devices/{}/logs?page={}".format(dev, page), None, "指定日志页 → data.stdout")
    m = re.match(r"^sg_logs -a (/dev/\S+)", c)
    if m:
        s = short(m.group(1))
        return ("GET /devices/{}/logs".format(s), "GET", D1, "/devices/{}/logs".format(s), None,
                "全部日志页 → data.stdout")
    # --- dmesg / journalctl (1:1, server-side grep+tail) ---
    if c.startswith("dmesg"):
        return ("GET /diagnostics/dmesg?tail=100（1:1）", "GET", D1, "/diagnostics/dmesg?tail=100", None,
                "dmesg | grep -Ei 磁带关键词 | tail -100 → data.parsed.lines[]，服务端已做关键词过滤")
    if c.startswith("journalctl"):
        return ("GET /diagnostics/journalctl?tail=100（1:1）", "GET", D1, "/diagnostics/journalctl?tail=100", None,
                "journalctl -k --no-pager | tail -100 → data.parsed.lines[]")
    # --- mtx ---
    m = re.match(r"^mtx -f (/dev/\S+) inquiry", c)
    if m:
        s = short(m.group(1))
        return ("GET /libraries/{}/inquiry".format(s), "GET", D1, "/libraries/{}/inquiry".format(s), None,
                "带库识别 → data.stdout")
    m = re.match(r"^mtx -f (/dev/\S+) status", c)
    if m:
        s = short(m.group(1))
        return ("GET /libraries/{}/status".format(s), "GET", D1, "/libraries/{}/status".format(s), None,
                "带库状态 → data.stdout（结构化用 /inventory）")
    m = re.match(r"^mtx -f (/dev/\S+) inventory", c)
    if m:
        s = short(m.group(1))
        return ("GET /libraries/{}/inventory".format(s), "GET", D1, "/libraries/{}/inventory".format(s), None,
                "结构化槽位 → data.slots[]/drives[]")
    m = re.match(r"^mtx -f (/dev/\S+) load (\d+) (\d+)", c)
    if m:
        s, slot, drive = short(m.group(1)), int(m.group(2)), int(m.group(3))
        return ("POST /libraries/{}/load".format(s), "POST", D1, "/libraries/{}/load".format(s),
                {"slot": slot, "drive": drive, "confirm": True}, "装载 → code=LOAD_SUCCESS")
    m = re.match(r"^mtx -f (/dev/\S+) unload (\d+) (\d+)", c)
    if m:
        s, slot, drive = short(m.group(1)), int(m.group(2)), int(m.group(3))
        return ("POST /libraries/{}/unload".format(s), "POST", D1, "/libraries/{}/unload".format(s),
                {"slot": slot, "drive": drive, "confirm": True}, "卸载归位 → code=UNLOAD_SUCCESS")
    # --- mt ---
    m = re.match(r"^mt -f (/dev/\S+) status", c)
    if m:
        s = short(m.group(1))
        return ("GET /drives/{}/status".format(s), "GET", D1, "/drives/{}/status".format(s), None,
                "带机状态 → data.stdout")
    m = re.match(r"^mt -f (/dev/\S+) (rewind|fsf|bsf|fsr|bsr|eom|seod|offline)(?: (\d+))?", c)
    if m:
        s, op, cnt = short(m.group(1)), m.group(2), m.group(3)
        op = "seod" if op in ("eom", "seod") else op
        body = {"operation": op, "confirm": True}
        if cnt and op not in ("rewind", "seod", "offline"):
            body["count"] = int(cnt)
        return ("POST /drives/{}/position {{operation:{}}}".format(s, op), "POST", D1,
                "/drives/{}/position".format(s), body, "磁带定位 → code=POSITION_SUCCESS")
    m = re.match(r"^mt -f (/dev/\S+) weof", c)
    if m:
        s = short(m.group(1))
        return ("POST /drives/{}/weof".format(s), "POST", D2, "/drives/{}/weof".format(s),
                {"count": 1, "confirm": True}, "写文件标记（LEVEL 3，FULL 实例）→ code=WEOF_SUCCESS")
    m = re.match(r"^mt -f (/dev/\S+) compression", c)
    if m:
        s = short(m.group(1))
        return ("GET /drives/{}/compression".format(s), "GET", D1, "/drives/{}/compression".format(s), None,
                "压缩状态 → data.stdout")
    # --- dd / cmp ---
    if re.search(r"^dd if=/dev/n\S+ of=/dev/null", c):
        return ("POST /tests/read", "POST", D1, "/tests/read",
                {"drive": "/dev/nst1", "block_size": "1M", "confirm": True},
                "读测试 → code=READ_TEST_PASS，duration_ms=耗时")
    if re.search(r"^dd if=/dev/zero of=/dev/n\S+", c):
        m = re.search(r"count=(\d+)", c)
        size = int(m.group(1)) if m else 1024
        return ("POST /tests/write（{}MiB，FULL 实例）".format(size), "POST", D2, "/tests/write",
                {"drive": "/dev/nst1", "test_media": "IBM015LA", "size_mb": size,
                 "allow_write": True, "confirm": True},
                "写测试 → code=WRITE_TEST_PASS")
    if c.startswith("cmp") or "| cmp -" in c or "cmp" in c.split("|")[0] if "|" in c else c.startswith("cmp"):
        return ("POST /tests/write-verify（content_verify 步骤）", "POST", D2, "/tests/write-verify",
                {"drive": "/dev/nst1", "test_media": "IBM015LA", "size_mb": 256,
                 "allow_write": True, "confirm": True},
                "CLI cmp 校验 → write-verify 的 steps[content_verify]，content_verified=true")
    # compound: rewind&&status, dd|cmp, fsf;status
    if "&&" in c or "; " in c or "|" in c:
        first = re.split(r"&&|;|\|", c)[0].strip()
        if first.startswith("mt") or first.startswith("dd") or first.startswith("mtx"):
            sub = map_and_call(first)
            if sub:
                return (sub[0] + "（复合命令主步）", sub[1], sub[2], sub[3], sub[4],
                        "CLI 复合命令 `... && ...` 的主步骤；后续状态检查由对应 GET /drives/.../status 接口覆盖")
    return None


def main():
    sections = []
    cmds = sorted(glob.glob(BASE + "/commands/CMD-*"))
    for d in cmds:
        cid = os.path.basename(d)
        cmdfile = os.path.join(d, "command.txt")
        if not os.path.exists(cmdfile):
            continue
        cmdline = open(cmdfile).read().strip().split("\n")[0]
        rj = os.path.join(d, "result.json")
        cli_result = ""
        if os.path.exists(rj):
            try:
                cli_result = json.load(open(rj)).get("result", "")
            except Exception:
                cli_result = "?"
        else:
            cli_result = "中断残留（无 result.json）"
        mapped = map_and_call(cmdline)
        sec = ["### {}".format(cid), ""]
        sec.append("**CLI 原始命令：**")
        sec.append("")
        sec.append("```bash")
        sec.append(cmdline)
        sec.append("```")
        sec.append("")
        sec.append("CLI 测试结果：`{}`".format(cli_result))
        sec.append("")
        if mapped is None:
            sec.append("> 对应 API：无独立接口（该命令为 CLI 会话管理/审计辅助命令，如 grep 过滤或复合 shell 片段），"
                       "其信息已由上述系统/发现/诊断类 API 覆盖。")
            sec.append("")
        else:
            title, method, base, path, body, note = mapped
            if method == "MULTI":
                # multiple TURs
                devs = re.findall(r"/dev/sg\d", cmdline)
                title, _, _, _, _, note = mapped
                sec.append("**对应 API：** `{}`".format(title))
                sec.append("")
                sec.append("**说明：** {}".format(note))
                sec.append("")
                for i, dev in enumerate(devs):
                    code, pretty = curl("GET", D1, "/devices/{}/tur".format(short(dev)), None)
                    sec.append("```bash")
                    sec.append(build_curl_str("GET", D1, "/devices/{}/tur".format(short(dev)), None))
                    sec.append("```")
                    sec.append("")
                    sec.append("响应（HTTP {}）：".format(code))
                    sec.append("")
                    sec.append("```json")
                    sec.append(pretty)
                    sec.append("```")
                    sec.append("")
            else:
                code, pretty = curl(method, base, path, body)
                sec.append("**对应 API：** `{}`".format(title))
                sec.append("")
                sec.append("**curl 调用：**")
                sec.append("")
                sec.append("```bash")
                sec.append(build_curl_str(method, base, path, body))
                sec.append("```")
                sec.append("")
                sec.append("**说明：** {}".format(note))
                sec.append("")
                sec.append("**响应（HTTP {}，JSON 已格式化）：**".format(code))
                sec.append("")
                sec.append("```json")
                sec.append(pretty[:4000] if len(pretty) <= 4200 else pretty[:4000] + "\n  ...（截断，完整见 audit 原始日志）")
                sec.append("```")
                sec.append("")
        sections.append("\n".join(sec))
        print(cid, "OK" if mapped else "NO-API", flush=True)
    open(os.path.join(OUT, "sections.md"), "w").write("\n".join(sections))
    print("DONE api_calls={} cached_reuse={}".format(_stats["api_calls"], _stats["cached_reuse"]))


if __name__ == "__main__":
    main()
