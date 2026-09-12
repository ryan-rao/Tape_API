#!/usr/bin/env python3
"""Round 2: retest the endpoints that failed on a blank tape.
Writes two data files with filemarks first (like the CLI sequence did), so
spacing operations have real data to work on, then calls the failed endpoints."""
import json
import os
import subprocess

BASE = "http://127.0.0.1:8002/api/v1"
NST = "nst0"
OUT = "/tmp/api-doc-evidence"


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    print("$", " ".join(cmd), "->", r.returncode, r.stderr.strip()[:120])
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
    err = parsed.get("error") or {}
    print("%-18s %s %s %s" % (name, code.strip(), parsed.get("code", ""), "" if ok else str(err.get("message", ""))[:100]))
    return ok


# 0) prepare a data-bearing tape: two 8MB files separated by filemarks
sh(["mt", "-f", "/dev/" + NST, "rewind"])
sh(["dd", "if=/dev/zero", "of=/dev/" + NST, "bs=1M", "count=8"])
sh(["mt", "-f", "/dev/" + NST, "weof", "1"])
sh(["dd", "if=/dev/zero", "of=/dev/" + NST, "bs=1M", "count=8"])
sh(["mt", "-f", "/dev/" + NST, "weof", "1"])
sh(["mt", "-f", "/dev/" + NST, "rewind"])

P = "/drives/%s/" % NST
fails = []
fails += [call("02-tell", "GET", P + "tell", None) or True]  # keep file even if hw fails
call("05-lock", "POST", P + "lock", {"confirm": True})
call("13-wset", "POST", P + "wset", {"count": 1, "confirm": True})
call("15-position-fsf", "POST", P + "position", {"operation": "fsf", "count": 1, "confirm": True})
call("16-position-fsfm", "POST", P + "position", {"operation": "fsfm", "count": 1, "confirm": True})
call("17-position-fsr", "POST", P + "position", {"operation": "fsr", "count": 1, "confirm": True})
call("18-position-bsr", "POST", P + "position", {"operation": "bsr", "count": 1, "confirm": True})
call("20-position-bsfm", "POST", P + "position", {"operation": "bsfm", "count": 1, "confirm": True})
call("21-position-fss", "POST", P + "position", {"operation": "fss", "count": 1, "confirm": True})
call("22-position-bss", "POST", P + "position", {"operation": "bss", "count": 1, "confirm": True})
call("26-seek", "POST", P + "seek", {"count": 1, "confirm": True})
call("27-mkpartition", "POST", P + "partition", {"count": 2, "confirm": True})
call("28-setpartition", "POST", P + "partition", {"partition": 0, "confirm": True})
call("29-partseek", "POST", P + "partition/seek", {"partition": 0, "block": 0, "confirm": True})
print("done")
