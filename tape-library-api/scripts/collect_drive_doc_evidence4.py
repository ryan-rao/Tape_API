#!/usr/bin/env python3
"""Round 4 (final): variable-block data tape, then fsr/bsr + partition ops."""
import json
import os
import subprocess

BASE = "http://127.0.0.1:8002/api/v1"
NST = "nst0"
OUT = "/tmp/api-doc-evidence"
DEV = "/dev/" + NST
P = "/drives/%s/" % NST


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    print("$", " ".join(cmd), "->", r.returncode, r.stderr.strip()[:100])
    return r


def call(name, method, path, body):
    cmd = ["curl", "-s", "-m", "3600", "-w", "\n%{http_code}"]
    if method != "GET":
        cmd += ["-X", method, "-H", "Content-Type: application/json", "-d", json.dumps(body)]
    cmd.append(BASE + path)
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    raw, _, code = out.rpartition("\n")
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {"raw": raw}
    with open(os.path.join(OUT, name + ".json"), "w") as f:
        json.dump({"http_code": code.strip(), "method": method, "path": path,
                   "body": body, "response": parsed}, f, indent=2, ensure_ascii=False)
    ok = code.strip() == "200" and parsed.get("success") is True
    err = (parsed.get("error") or parsed.get("detail") or {})
    print("%-18s %s %s %s" % (name, code.strip(), parsed.get("code", ""), "" if ok else str(err.get("message", ""))[:100]))
    return ok


# 数据带：两个文件（可变块模式）
sh(["mt", "-f", DEV, "setblk", "0"])
sh(["mt", "-f", DEV, "rewind"])
sh(["dd", "if=/dev/zero", "of=" + DEV, "bs=1M", "count=8"])
sh(["mt", "-f", DEV, "weof", "1"])
sh(["dd", "if=/dev/zero", "of=" + DEV, "bs=1M", "count=8"])
sh(["mt", "-f", DEV, "weof", "1"])
sh(["mt", "-f", DEV, "rewind"])

call("17-position-fsr", "POST", P + "position", {"operation": "fsr", "count": 1, "confirm": True})
call("18-position-bsr", "POST", P + "position", {"operation": "bsr", "count": 1, "confirm": True})

# 分区（LTO 分区表需要 FORMAT，mkpartition 在 st 驱动上对 LTO 的支持取决于驱动/固件）
call("27-mkpartition", "POST", P + "partition", {"count": 2, "confirm": True})
call("28-setpartition", "POST", P + "partition", {"partition": 0, "confirm": True})
call("29-partseek", "POST", P + "partition/seek", {"partition": 0, "block": 0, "confirm": True})

# 硬件层不支持的 setmark / 逻辑块定位（wset/fss/bss/tell/seek）逐个采集真实响应
call("13-wset", "POST", P + "wset", {"count": 1, "confirm": True})
call("21-position-fss", "POST", P + "position", {"operation": "fss", "count": 1, "confirm": True})
call("22-position-bss", "POST", P + "position", {"operation": "bss", "count": 1, "confirm": True})
call("02-tell", "GET", P + "tell", None)
call("26-seek", "POST", P + "seek", {"count": 1, "confirm": True})

# 收尾：rewind
call("11-rewind", "POST", P + "rewind", {"confirm": True})
print("done")
