# tape-library-api

REST API service for Linux Tape Library management (IBM / Quantum / BDT / HPE / Dell / Oracle / Spectra Logic / standard SCSI medium changers, LTO drives, IBM lin_tape nodes).

## Features

- System info, dependency check/install/verify (dnf/yum/apt/zypper)
- SCSI discovery (`lsscsi -g`), device inquiry/VPD/TUR/modes/logs
- Library inquiry/status/inventory, load/unload/transfer/position (with state pre-checks, MEDIA_ALREADY_LOADED detection)
- Drive status, positioning (rewind/fsf/bsf/fsr/bsr/seod/offline), compression query
- TapeAlert parsing, system & tape diagnostics, full read-only test chain
- Read/write/erase test APIs (safety-gated)
- Full audit chain: request_id → command_id → raw stdout/stderr on disk

## Install

```bash
pip3 install -r requirements.txt
```

Linux tools required: lsscsi, sg3_utils, mtx, mt-st.

## Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
# Swagger: http://host:8000/docs   OpenAPI: /openapi.json
```

## Configuration (.env)

```
TAPE_API_MODE=SAFE            # SAFE | DIAGNOSTIC | FULL
ALLOW_DEVICE_OPERATION=false  # LEVEL_2 enable
ALLOW_WRITE=false             # LEVEL_3 enable
REAL_HARDWARE_TEST=false
COMMAND_TIMEOUT=60
AUDIT_DIR=./audit
TEST_MEDIA=                   # e.g. IBM015LA (required for write tests)
TEST_DRIVE=
```

## Safety Model

- LEVEL 1 (read-only): always allowed
- LEVEL 2 (device ops): DIAGNOSTIC/FULL + ALLOW_DEVICE_OPERATION
- LEVEL 3 (write/erase): FULL + ALLOW_WRITE + request allow_write + confirm + test_media
- No shell=True; device path whitelist; injection chars rejected; per-device locks; all commands time out

## Tests

```bash
python3 -m pytest          # 43 cases, mock hardware, no tape library needed
python3 -m compileall app
```

## Audit

Every command execution saved under `audit/commands/CMD-*/` (command.json + stdout.txt + stderr.txt); requests under `audit/requests/`. Query via `GET /api/v1/commands/{id}` and `GET /api/v1/audit/{request_id}`.

## Real Hardware Testing

Set `REAL_HARDWARE_TEST=true` and configure TEST_MEDIA/TEST_DRIVE. Write/erase additionally require the LEVEL_3 gates above.

## Troubleshooting

See docs/API.md §11.
