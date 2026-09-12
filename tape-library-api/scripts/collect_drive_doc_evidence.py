#!/usr/bin/env python3
"""Live per-endpoint evidence collector for the renamed drive API (node186).
Runs every endpoint of the CLI->REST mapping table against the FULL-mode server,
in hardware-safe order, saving each JSON response + http code for doc composing."""
import json
import os
import subprocess
import sys
import time

BASE = "http://127.0.0.1:8002/api/v1"
NST = sys.argv[1] if len(sys.argv) > 1 else "nst0"
OUT = "/tmp/api-doc-evidence"
os.makedirs(OUT, exist_ok=True)

# (seq, cli_name, method, path, body, note)
CALLS = [
    ("status",       "GET",  "/drives/%s/status" % NST, None),
    ("tell",         "GET",  "/drives/%s/tell" % NST, None),
    ("densities",    "GET",  "/drives/%s/densities" % NST, None),
    ("options",      "GET",  "/drives/%s/options" % NST, None),
    ("lock",         "POST", "/drives/%s/lock" % NST, {"confirm": True}),
    ("load",         "POST", "/drives/%s/load" % NST, {"confirm": True}),
    ("compression",  "POST", "/drives/%s/compression" % NST, {"enable": True, "confirm": True}),
    ("compression-off", "POST", "/drives/%s/compression" % NST, {"enable": False, "confirm": True}),
    ("block-size",   "POST", "/drives/%s/block-size" % NST, {"block_size": 262144, "confirm": True}),
    ("density",      "POST", "/drives/%s/density" % NST, {"density": 0, "confirm": True}),
    ("rewind",       "POST", "/drives/%s/rewind" % NST, {"confirm": True}),
    ("weof",         "POST", "/drives/%s/weof" % NST, {"count": 1, "confirm": True}),
    ("wset",         "POST", "/drives/%s/wset" % NST, {"count": 1, "confirm": True}),
    ("eof",          "POST", "/drives/%s/eof" % NST, {"count": 1, "confirm": True}),
    ("position-fsf", "POST", "/drives/%s/position" % NST, {"operation": "fsf", "count": 1, "confirm": True}),
    ("position-fsfm","POST", "/drives/%s/position" % NST, {"operation": "fsfm", "count": 1, "confirm": True}),
    ("position-fsr", "POST", "/drives/%s/position" % NST, {"operation": "fsr", "count": 1, "confirm": True}),
    ("position-bsr", "POST", "/drives/%s/position" % NST, {"operation": "bsr", "count": 1, "confirm": True}),
    ("position-bsf", "POST", "/drives/%s/position" % NST, {"operation": "bsf", "count": 1, "confirm": True}),
    ("position-bsfm","POST", "/drives/%s/position" % NST, {"operation": "bsfm", "count": 1, "confirm": True}),
    ("position-fss", "POST", "/drives/%s/position" % NST, {"operation": "fss", "count": 1, "confirm": True}),
    ("position-bss", "POST", "/drives/%s/position" % NST, {"operation": "bss", "count": 1, "confirm": True}),
    ("position-asf", "POST", "/drives/%s/position" % NST, {"operation": "asf", "count": 0, "confirm": True}),
    ("eod",          "POST", "/drives/%s/eod" % NST, {"confirm": True}),
    ("seod",         "POST", "/drives/%s/seod" % NST, {"confirm": True}),
    ("seek",         "POST", "/drives/%s/seek" % NST, {"count": 0, "confirm": True}),
    ("mkpartition",  "POST", "/drives/%s/partition" % NST, {"count": 2, "confirm": True}),
    ("setpartition", "POST", "/drives/%s/partition" % NST, {"partition": 0, "confirm": True}),
    ("partseek",     "POST", "/drives/%s/partition/seek" % NST, {"partition": 0, "block": 0, "confirm": True}),
    ("retension",    "POST", "/drives/%s/retension" % NST, {"confirm": True}),
    ("erase",        "POST", "/drives/%s/erase" % NST, {"confirm": True}),
    ("unlock",       "POST", "/drives/%s/unlock" % NST, {"confirm": True}),
    ("rewoffl",      "POST", "/drives/%s/rewoffl" % NST, {"confirm": True}),
    ("load2",        "POST", "/drives/%s/load" % NST, {"confirm": True}),
    ("eject",        "POST", "/drives/%s/eject" % NST, {"confirm": True}),
    ("load3",        "POST", "/drives/%s/load" % NST, {"confirm": True}),
    ("offline",      "POST", "/drives/%s/offline" % NST, {"confirm": True}),
    ("load4",        "POST", "/drives/%s/load" % NST, {"confirm": True}),
    ("rewind2",      "POST", "/drives/%s/rewind" % NST, {"confirm": True}),
]


def call(name, method, path, body):
    cmd = ["curl", "-s", "-m", "3600", "-w", "\n%{http_code}"]
    if method != "GET":
        cmd += ["-X", method, "-H", "Content-Type: application/json", "-d", json.dumps(body)]
    cmd.append(BASE + path)
    t0 = time.time()
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    el = round(time.time() - t0, 2)
    raw, _, code = out.rpartition("\n")
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {"raw": raw}
    with open(os.path.join(OUT, name + ".json"), "w") as f:
        json.dump({"http_code": code.strip(), "elapsed_s": el, "method": method,
                   "path": path, "body": body, "response": parsed}, f, indent=2, ensure_ascii=False)
    ok = code.strip() == "200" and parsed.get("success") is True
    print("%-16s %s  %ss  %s" % (name, code.strip(), el, parsed.get("code", parsed.get("raw", "")[:60])))
    return ok


fails = []
for i, (name, method, path, body) in enumerate(CALLS, 1):
    if not call("%02d-%s" % (i, name), method, path, body):
        fails.append(name)
print("\nFAILS:", fails if fails else "none")
