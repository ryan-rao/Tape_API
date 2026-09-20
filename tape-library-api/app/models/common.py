"""Common response models and error codes."""
from typing import Any, Optional

from pydantic import BaseModel

ERROR_CODES = [
    "OK", "INVALID_REQUEST", "MISSING_PARAMETER", "INVALID_DEVICE", "DEVICE_NOT_FOUND",
    "DEVICE_TYPE_MISMATCH", "COMMAND_NOT_FOUND", "COMMAND_FAILED", "DEPENDENCY_MISSING",
    "DEPENDENCY_INSTALL_FAILED", "DEPENDENCY_GATE_FAILED", "PACKAGE_MANAGER_NOT_FOUND",
    "PERMISSION_DENIED", "LIBRARY_NOT_FOUND", "DRIVE_NOT_FOUND", "MEDIA_NOT_FOUND",
    "SLOT_NOT_FOUND", "INVALID_SLOT", "INVALID_DRIVE", "INVALID_OPERATION",
    "OPERATION_NOT_SUPPORTED", "DEVICE_BUSY", "MEDIA_NOT_PRESENT",
    "WRITE_OPERATION_NOT_AUTHORIZED", "DESTRUCTIVE_OPERATION_NOT_AUTHORIZED",
    "PRODUCTION_SAFETY_BLOCK", "SCSI_ERROR", "TAPE_ALERT", "TIMEOUT", "INTERNAL_ERROR",
    "MEDIA_ALREADY_LOADED", "JOB_NOT_FOUND",
]


class ApiError(BaseModel):
    type: str
    details: str = ""


class ApiResponse(BaseModel):
    success: bool
    code: str
    message: str = ""
    request_id: str = ""
    data: Optional[Any] = None
    error: Optional[ApiError] = None


class CommandExecution(BaseModel):
    command_id: str
    command: str
    phase: str
    risk_level: str
    device: Optional[str] = None
    started_at: str
    finished_at: str
    duration_ms: int
    exit_code: int
    stdout: str
    stderr: str
    result: str


def ok(data: Any = None, code: str = "OK", message: str = "Operation completed successfully",
       request_id: str = "") -> ApiResponse:
    return ApiResponse(success=True, code=code, message=message, request_id=request_id, data=data)


def fail(code: str, message: str, request_id: str = "", error_type: str = "API_ERROR",
         details: str = "") -> ApiResponse:
    return ApiResponse(success=False, code=code, message=message, request_id=request_id,
                       error=ApiError(type=error_type, details=details))
