#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo_manual_tasks.py —— API 使用手册（docs/API-usage-manual-full.md）任务演示

按手册「三、API 接口分类总览」的四类顺序，依次执行手册中描述的 API 任务：
  3.1 带库操作  —— /libraries 发现、inquiry、status、inventory（LEVEL 1）
  3.2 带机操作  —— /devices inquiry/vpd/tur、/drives status/compression/tapealert（LEVEL 1）
  3.3 IO 操作   —— --with-io 时：load → write-verify（小容量）→ unload（LEVEL 2+3，需 8002）
  3.4 其他操作  —— /system/info、/dependencies、/discovery、/diagnostics、审计（LEVEL 1）

用法：
  python3 demo/demo_manual_tasks.py --base http://127.0.0.1:8001
  python3 demo/demo_manual_tasks.py --base http://127.0.0.1:8002 --with-io \
      --changer sg1 --drive sg2 --nst nst1 --slot 6 --volume IBM015LA
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error

STEP = {"n": 0}


def call(method, base, path, body=None, timeout=300):
    url = base.rstrip("/") + "/api/v1" + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def step(title, method, base, path, body=None, show=None, timeout=300):
    STEP["n"] += 1
    code, resp = call(method, base, path, body, timeout)
    ok = resp.get("success", code == 200)
    tag = "OK " if ok else "FAIL"
    print("[{:03d}] {} {:42s} -> HTTP {} {}".format(
        STEP["n"], tag, "{} {}".format(method, path), code, resp.get("code", "")))
    if show:
        data = resp.get("data") or {}
        for key in show:
            if isinstance(data, dict) and key in data:
                val = data[key]
                txt = json.dumps(val, ensure_ascii=False)
                print("      {} = {}".format(key, txt[:160] + ("..." if len(txt) > 160 else "")))
    if not ok:
        print("      error:", json.dumps(resp.get("error"), ensure_ascii=False)[:300])
    return resp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="API base URL，如 http://127.0.0.1:8001")
    ap.add_argument("--with-io", action="store_true", help="执行 3.3 IO 操作（需 FULL 模式 8002）")
    ap.add_argument("--changer", default="sg1")
    ap.add_argument("--drive", default="sg2")
    ap.add_argument("--nst", default="nst1")
    ap.add_argument("--slot", type=int, default=6)
    ap.add_argument("--volume", default="IBM015LA")
    ap.add_argument("--size-mb", type=int, default=64, help="write-verify 数据量（MB）")
    a = ap.parse_args()

    print("=" * 78)
    print("Tape Library API 手册任务演示  base={}  with_io={}".format(a.base, a.with_io))
    print("=" * 78)

    # ---- 前置检查 ----（/health 在应用根路径，不在 /api/v1 前缀下）
    import urllib.request as _u
    try:
        with _u.urlopen(a.base.rstrip("/") + "/health", timeout=10) as r:
            print("[000] 健康检查 GET /health -> HTTP {} {}".format(r.status, r.read().decode()[:120]))
    except Exception as e:
        print("[000] 健康检查 GET /health -> {}（可选，不影响后续任务）".format(e))

    # ---- 3.4 其他操作（先做环境确认，符合手册启动章节 5.4）----
    print("\n--- 3.4 其他操作：系统 / 依赖 / 发现 / 诊断 / 审计 ---")
    step("系统信息", "GET", a.base, "/system/info", show=["os", "kernel_release"])
    step("os-release 1:1", "GET", a.base, "/system/os-release", show=["parsed"])
    step("依赖矩阵", "GET", a.base, "/dependencies", show=["gate", "package_manager"])
    step("设备发现", "GET", a.base, "/discovery", show=["total", "libraries", "drives"])
    step("系统日志诊断", "GET", a.base, "/diagnostics/dmesg?tail=3", show=["matched_lines"])

    # ---- 3.1 带库操作 ----
    print("\n--- 3.1 带库操作：/libraries ---")
    step("带库发现", "GET", a.base, "/libraries")
    step("带库 INQUIRY", "GET", a.base, "/libraries/{}/inquiry".format(a.changer), show=["vendor", "product"])
    step("带库状态", "GET", a.base, "/libraries/{}/status".format(a.changer),
         show=["storage_slots", "occupied_slots", "loaded_drives"])
    step("介质清单", "GET", a.base, "/libraries/{}/inventory".format(a.changer), show=["volumes"])

    # ---- 3.2 带机操作 ----
    print("\n--- 3.2 带机操作：/devices + /drives ---")
    step("带机 INQUIRY", "GET", a.base, "/devices/{}/inquiry".format(a.drive), show=["vendor", "product", "revision"])
    step("带机 VPD", "GET", a.base, "/devices/{}/vpd".format(a.drive), show=["unit_serial_number"])
    step("TEST UNIT READY", "GET", a.base, "/devices/{}/tur".format(a.drive), show=["ready"])
    step("mt status", "GET", a.base, "/drives/{}/status".format(a.nst), show=["state"])
    step("压缩状态", "GET", a.base, "/drives/{}/compression".format(a.nst), show=["enabled"])
    step("TapeAlert", "GET", a.base, "/drives/{}/tapealert".format(a.drive),
         show=["triggered_count", "all_clear"])

    # ---- 3.3 IO 操作 ----
    if a.with_io:
        print("\n--- 3.3 IO 操作：装载 → 写读校验 → 卸载 ---")
        r = step("装带", "POST", a.base, "/libraries/{}/load".format(a.changer),
                 body={"slot": a.slot, "drive": 0, "confirm": True})
        if r.get("success"):
            wv = step("写读校验", "POST", a.base, "/tests/write-verify",
                      body={"drive": "/dev/{}".format(a.nst), "test_media": a.volume,
                            "size_mb": a.size_mb, "allow_write": True, "confirm": True},
                      show=["write", "read", "verify"], timeout=1800)
            if not wv.get("success"):
                print("      写读校验失败详情:", json.dumps(wv.get("error"), ensure_ascii=False)[:400])
            step("卸带归位", "POST", a.base, "/libraries/{}/unload".format(a.changer),
                 body={"slot": a.slot, "drive": 0, "confirm": True})
    else:
        print("\n--- 3.3 IO 操作：跳过（加 --with-io 且使用 8002 FULL 模式执行）---")

    # ---- 审计 ----
    print("\n--- 审计链 ---")
    code, resp = call("GET", a.base, "/commands?limit=5")
    if code == 200:
        for c_ in (resp.get("data") or {}).get("commands", [])[:3]:
            print("      {} {} exit={} {}".format(c_.get("command_id"), c_.get("command", "")[:50],
                                                  c_.get("exit_code"), c_.get("created_at", "")))
    print("\n演示完成：共执行 {} 个手册任务步骤".format(STEP["n"]))


if __name__ == "__main__":
    main()
