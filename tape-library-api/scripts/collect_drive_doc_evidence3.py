#!/usr/bin/env python3
"""Round 3: final retest — variable block mode first, then partition ops on a
fresh (erased) medium, then fsr/bsr on a data-bearing variable-block tape."""
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
    err = (parsed.get("error") or {})
    print("%-18s %s %s %s" % (name, code.strip(), parsed.get("code", ""), "" if ok else str(err.get("message", parsed.get("detail", "")))[:100]))
    return ok


# 1) 恢复可变块模式 + 擦除磁带（为分区操作准备干净介质）
call("09-block-size", "POST", P + "block-size", {"block_size": 0, "confirm": True})  # 覆盖为 0=可变块
call("11-rewind", "POST", P + "rewind", {"confirm": True})
call("31-erase", "POST", P + "erase", {"confirm": True})

# 2) 分区三连：mkpartition -> setpartition -> partseek
call("27-mkpartition", "POST", P + "partition", {"count": 2, "confirm": True})
call("28-setpartition", "POST", P + "partition", {"partition": 0, "confirm": True})
call("29-partseek", "POST", P + "partition/seek", {"partition": 0, "block": 0, "confirm": True})

# 3) 可变块模式下的定位操作（fsr/bsr 需要可变块 + 有数据）
sh(["mt", "-f", DEV, "rewind"])
sh(["dd", "if=/dev/zero", "of=" + DEV, "bs=1M", "count=8"])
sh(["mt", "-f", DEV, "weof", "1"])
sh(["mt", "-f", DEV, "rewind"])
call("17-position-fsr", "POST", P + "position", {"operation": "fsr", "count": 1, "confirm": True})
call("18-position-bsr", "POST", P + "position", {"operation": "bsr", "count": 1, "confirm": True})
call("15-position-fsf", "POST", P + "position", {"operation": "fsf", "count": 1, "confirm": True})
call("20-position-bsfm", "POST", P + "position", {"operation": "bsfm", "count": 1, "confirm": True})
print("done")
