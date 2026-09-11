# Tape Library API

## 1. Overview

REST API for Linux Tape Library management, wrapping `lsscsi` / `sg3_utils` / `mtx` / `mt` into a safe, JSON-standardized, fully-audited interface. Built with FastAPI + Pydantic; every underlying command execution is recorded with command_id / raw stdout / raw stderr / exit code / duration.

## 2. Architecture

```
FastAPI REST (app/api/routes.py)
  → Services (app/services/services.py: System/Dependency/Discovery/Device/Library/Drive/Diagnostic/Test)
    → Command Adapters (app/commands/adapters.py: Lsscsi/Sg/Mtx/Mt — argv whitelist only)
      → CommandRunner (app/commands/runner.py: subprocess shell=False + timeout + device locks)
        → AuditStorage (app/audit/: commands/, requests/ raw outputs on disk)
```

## 3. Authentication / Authorization

No auth by default (lab service). Safety enforced via API mode + env flags (see §4). For production exposure, place behind a reverse proxy with auth.

## 4. Safety Model

| Level | Operations | Gating |
|---|---|---|
| LEVEL_1 | lsscsi, sg_inq/vpd/turs/modes/logs, mtx status/inquiry/inventory, mt status, dmesg | always allowed |
| LEVEL_2 | mtx load/unload/transfer/position, mt rewind/fsf/bsf/eom, dd read | `TAPE_API_MODE=DIAGNOSTIC|FULL` + `ALLOW_DEVICE_OPERATION=true` |
| LEVEL_3 | dd write, mt erase | `TAPE_API_MODE=FULL` + `ALLOW_WRITE=true` + request `allow_write=true` + `confirm=true` + `test_media` |

API modes: `SAFE` (L1) / `DIAGNOSTIC` (L1+L2) / `FULL` (L1+L2+L3-with-authorization).

## 5. Common Response

```json
{"success": true, "code": "OK", "message": "...", "request_id": "REQ-...", "data": {...}, "error": null}
{"success": false, "code": "DEVICE_NOT_FOUND", "message": "...", "request_id": "REQ-...", "data": null, "error": {"type": "...", "details": "..."}}
```

## 6. Error Codes

OK, INVALID_REQUEST, MISSING_PARAMETER, INVALID_DEVICE, DEVICE_NOT_FOUND, DEVICE_TYPE_MISMATCH, COMMAND_NOT_FOUND, COMMAND_FAILED, DEPENDENCY_MISSING, DEPENDENCY_INSTALL_FAILED, DEPENDENCY_GATE_FAILED, PACKAGE_MANAGER_NOT_FOUND, PERMISSION_DENIED, LIBRARY_NOT_FOUND, DRIVE_NOT_FOUND, MEDIA_NOT_FOUND, SLOT_NOT_FOUND, INVALID_SLOT, INVALID_DRIVE, INVALID_OPERATION, OPERATION_NOT_SUPPORTED, DEVICE_BUSY, MEDIA_NOT_PRESENT, MEDIA_ALREADY_LOADED, WRITE_OPERATION_NOT_AUTHORIZED, DESTRUCTIVE_OPERATION_NOT_AUTHORIZED, PRODUCTION_SAFETY_BLOCK, SCSI_ERROR, TAPE_ALERT, TIMEOUT, INTERNAL_ERROR

## 7. API & Command Mapping

| API | Linux Command | Risk |
|---|---|---|
| GET /api/v1/system/info | `cat /etc/os-release`, `uname -a`, `hostname`, `uname -m`, `id` | L1 |
| GET /api/v1/dependencies | `which <cmd>` per dependency | L1 |
| POST /api/v1/dependencies/install | `dnf install -y <pkg>` | L2 |
| GET /api/v1/dependencies/verify | `which` re-check | L1 |
| GET /api/v1/discovery | `lsscsi -g` | L1 |
| GET /api/v1/devices/{sg}/inquiry | `sg_inq /dev/sgX` | L1 |
| GET /api/v1/devices/{sg}/vpd?page=0x80|0x83 | `sg_vpd -p page /dev/sgX` | L1 |
| GET /api/v1/devices/{sg}/tur | `sg_turs /dev/sgX` | L1 |
| GET /api/v1/devices/{sg}/modes | `sg_modes -a /dev/sgX` | L1 |
| GET /api/v1/devices/{sg}/logs | `sg_logs -a /dev/sgX` | L1 |
| GET /api/v1/libraries | `lsscsi -g` (filtered) | L1 |
| GET /api/v1/libraries/{changer}/inquiry | `mtx -f /dev/sgX inquiry` | L1 |
| GET /api/v1/libraries/{changer}/status | `mtx -f /dev/sgX status` | L1 |
| GET /api/v1/libraries/{changer}/inventory | `mtx -f /dev/sgX status` (parsed) | L1 |
| POST /api/v1/libraries/{changer}/load | `mtx -f /dev/sgX load S D` | L2 |
| POST /api/v1/libraries/{changer}/unload | `mtx -f /dev/sgX unload S D` | L2 |
| POST /api/v1/libraries/{changer}/transfer | `mtx -f /dev/sgX transfer S D` | L2 |
| POST /api/v1/libraries/{changer}/position | `mtx -f /dev/sgX position E` | L2 |
| GET /api/v1/drives/{nst}/status | `mt -f /dev/nstX status` | L1 |
| POST /api/v1/drives/{nst}/rewind | `mt -f /dev/nstX rewind` | L2 |
| POST /api/v1/drives/{nst}/position | `mt -f /dev/nstX {rewind,fsf,bsf,fsr,bsr,seod,offline}` | L2 |
| GET /api/v1/drives/{nst}/compression | `mt -f /dev/nstX compression` | L1 |
| GET /api/v1/drives/{sg}/tapealert | `sg_logs -p 0x2e /dev/sgX` (parsed) | L1 |
| GET /api/v1/diagnostics/system | `dmesg`, `journalctl -k` | L1 |
| GET /api/v1/diagnostics/tape/{sg} | sg_inq + vpd + tur + tapealert | L1 |
| POST /api/v1/tests/read | `dd if=/dev/nstX of=/dev/null bs=1M` | L2 |
| POST /api/v1/tests/write | `dd if=/dev/zero of=/dev/nstX bs=1M count=N` | L3 |
| POST /api/v1/tests/erase | `mt -f /dev/nstX erase` | L3 |
| POST /api/v1/tests/full | dependency→discovery→library→drive→diag chain | L1 |
| GET /api/v1/commands/{command_id} | audit lookup | L1 |
| GET /api/v1/audit/{request_id} | request→commands chain | L1 |

## 8. Example: Load

```
POST /api/v1/libraries/sg1/load
{"slot": 6, "drive": 0, "confirm": true}

Service chain: LibraryService.load()
  → pre-check inventory (MEDIA_ALREADY_LOADED if drive occupied)
  → MtxAdapter.load() → mtx -f /dev/sg1 load 6 0
  → CommandRunner (L2 gate, device lock, timeout 300s, audit)

200 {"success": true, "code": "LOAD_SUCCESS", "data": {"slot": 6, "drive": 0, "command_id": "CMD-..."}}
400 INVALID_SLOT / MEDIA_ALREADY_LOADED | 403 PERMISSION_DENIED | 409 DEVICE_BUSY | 502 COMMAND_FAILED
```

## 9. Test Cases (summary)

43 cases: positive, negative (invalid device/slot/operation), security (shell injection, path traversal, unauthorized write/erase), audit roundtrip, OpenAPI completeness. See `test-results/api-test-report.md`.

## 10. Security Notes

- No `shell=True` anywhere; argv lists only, built exclusively in adapters from validated args.
- Device paths whitelist-validated (`^/dev/(sg|st|nst|IBMtape|IBMchanger)\d+$`); `; && | $() > <` and `..` rejected with HTTP 400 and **no command executed**.
- LEVEL 2/3 gated by env config + per-request confirmation; write/erase double-gated.
- Per-device locks prevent concurrent load/unload on same changer/drive (409 DEVICE_BUSY).
- All commands timeout-bounded (default 60s, load/unload 300s, IO configurable).
- Raw stdout/stderr persisted per command under `audit/commands/CMD-*/`.

## 11. Troubleshooting

- `PERMISSION_DENIED` on L2 → set `TAPE_API_MODE=DIAGNOSTIC` + `ALLOW_DEVICE_OPERATION=true`, restart.
- `WRITE_OPERATION_NOT_AUTHORIZED` → `TAPE_API_MODE=FULL` + `ALLOW_WRITE=true` AND `allow_write:true` in body.
- `DEVICE_BUSY` → another request holds the device lock.
- 502 COMMAND_FAILED → see `audit/commands/<id>/stderr.txt`.
