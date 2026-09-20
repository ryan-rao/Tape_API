"""Security policy: device path whitelist, shell-injection blocking, risk-level gating."""
import re

from app.config import settings

# Allowed device node patterns
DEVICE_PATTERNS = [
    r"^/dev/sg\d+$",
    r"^/dev/st\d+$",
    r"^/dev/nst\d+$",
    r"^/dev/IBMtape\d+$",
    r"^/dev/IBMchanger\d+$",
    r"^sg\d+$",      # short form accepted in path params
    r"^nst\d+$",
    r"^st\d+$",
]

INJECTION_CHARS = re.compile(r"[;&|`$<>\n\r]")

from fastapi import HTTPException


def _bad(status: int, code: str, message: str = ""):
    raise HTTPException(status_code=status, detail={"code": code, "message": message or code})


def normalize_device(name: str, prefix: str = "/dev/") -> str:
    """Validate + normalize a device name. Raises HTTPException(400) on invalid input."""
    if not name or not isinstance(name, str):
        _bad(400, "INVALID_DEVICE")
    if INJECTION_CHARS.search(name) or ".." in name:
        _bad(400, "INVALID_DEVICE", "invalid device path")
    candidate = name if name.startswith("/dev/") else prefix + name
    for pat in DEVICE_PATTERNS:
        if re.match(pat, candidate):
            return candidate
    _bad(400, "INVALID_DEVICE", "invalid device path")


def validate_slot(slot: int) -> int:
    if not isinstance(slot, int) or isinstance(slot, bool) or slot < 1 or slot > 100000:
        _bad(400, "INVALID_SLOT")
    return slot


def validate_drive(drive: int) -> int:
    if not isinstance(drive, int) or isinstance(drive, bool) or drive < 0 or drive > 1024:
        _bad(400, "INVALID_DRIVE")
    return drive


def validate_setting(value: int, lo: int, hi: int, code: str = "INVALID_VALUE") -> int:
    """Validate a numeric setting/count outside the drive-index range (block size,
    density code, block number, partition count, ...)."""
    if not isinstance(value, int) or isinstance(value, bool) or value < lo or value > hi:
        _bad(400, code)
    return value


def require_level(risk_level: str):
    if not settings.level_allowed(risk_level):
        if risk_level == "LEVEL_2":
            _bad(403, "PERMISSION_DENIED", "device operation not authorized "
                 "(set TAPE_API_MODE=DIAGNOSTIC|FULL and ALLOW_DEVICE_OPERATION=true)")
        if risk_level == "LEVEL_3":
            _bad(403, "WRITE_OPERATION_NOT_AUTHORIZED")
        _bad(403, "PERMISSION_DENIED")


def validate_position_operation(op: str) -> str:
    allowed = {"rewind", "fsf", "fsfm", "bsf", "bsfm", "fsr", "bsr", "fss", "bss", "asf",
               "eom", "eod", "seod", "offline"}
    if op not in allowed:
        _bad(400, "INVALID_OPERATION")
    return op
