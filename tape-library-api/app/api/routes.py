"""API routers: thin HTTP layer over services. Uniform ApiResponse envelope."""
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from app.models.common import ok, fail
from app.services.services import (
    SystemService, DependencyService, DiscoveryService, DeviceService,
    LibraryService, DriveService, DiagnosticService, TestService, ServiceError,
)

router = APIRouter(prefix="/api/v1")


def ctx(request: Request):
    return request.app.state.chain, request.state.request_id


def build(request: Request, cls):
    chain, rid = ctx(request)
    return cls(request.app.state.runner, chain, rid)


def handle(fn, request_id=""):
    try:
        return fn()
    except ServiceError as e:
        status = 400
        if e.code in ("DEVICE_NOT_FOUND", "LIBRARY_NOT_FOUND", "DRIVE_NOT_FOUND", "MEDIA_NOT_FOUND", "SLOT_NOT_FOUND"):
            status = 404
        elif e.code in ("PERMISSION_DENIED", "WRITE_OPERATION_NOT_AUTHORIZED", "DESTRUCTIVE_OPERATION_NOT_AUTHORIZED"):
            status = 403
        elif e.code == "DEVICE_BUSY":
            status = 409
        elif e.code in ("COMMAND_FAILED", "TIMEOUT", "SCSI_ERROR"):
            status = 502
        detail = {"code": e.code, "message": e.message}
        rec = getattr(e, "command_record", None)
        if rec:
            import re as _re
            err = {"command_id": rec.get("command_id"), "command": rec.get("command"),
                   "exit_code": rec.get("exit_code"),
                   "stderr": rec.get("stderr") or "", "stdout": rec.get("stdout") or ""}
            sense = {}
            for k, v in _re.findall(r"Request Sense: ([^=]+?)=(.+)",
                                     err["stderr"]):
                sense[k.lower().replace(" ", "_")] = v.strip()
            if sense:
                err["sense"] = sense
            m2 = _re.search(r"Data Transfer Element (\d+) is Empty", err["stderr"])
            if m2:
                err["reason_code"] = "DRIVE_EMPTY"
                err["reason"] = "data transfer element %s has no media loaded" % m2.group(1)
            m3 = _re.search(r"Storage Element (\d+) is Already Full", err["stderr"])
            if m3:
                err["reason_code"] = "SLOT_FULL"
                err["reason"] = "storage element %s is already occupied" % m3.group(1)
            detail["error_detail"] = err
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=status, content={
            "success": False, "code": e.code, "message": e.message,
            "request_id": request_id, "data": None,
            "error": {"type": "API_ERROR", "details": e.message},
            "detail": detail,
        })


# ---------- System ----------
@router.get("/system/info", tags=["System"])
def system_info(request: Request):
    svc = build(request, SystemService)
    return handle(lambda: ok(svc.info(), request_id=request.state.request_id), request.state.request_id)


@router.get("/system/kernel", tags=["System"])
def system_kernel(request: Request):
    svc = build(request, SystemService)
    return handle(lambda: ok(svc.kernel(), code="KERNEL_CHECKED", request_id=request.state.request_id))


@router.get("/system/ibm", tags=["System"])
def system_ibm(request: Request):
    svc = build(request, SystemService)
    return handle(lambda: ok(svc.ibm(), code="IBM_CHECKED", request_id=request.state.request_id))


# ---------- 1:1 granular system endpoints (CLI report parity) ----------
@router.get("/system/os-release", tags=["System"])
def system_os_release(request: Request):
    svc = build(request, SystemService)
    return handle(lambda: ok(svc.os_release(), code="OK", request_id=request.state.request_id))


@router.get("/system/uname", tags=["System"])
def system_uname(request: Request):
    svc = build(request, SystemService)
    return handle(lambda: ok(svc.uname_all(), code="OK", request_id=request.state.request_id))


@router.get("/system/hostname", tags=["System"])
def system_hostname(request: Request):
    svc = build(request, SystemService)
    return handle(lambda: ok(svc.hostname_cmd(), code="OK", request_id=request.state.request_id))


@router.get("/system/arch", tags=["System"])
def system_arch(request: Request):
    svc = build(request, SystemService)
    return handle(lambda: ok(svc.arch(), code="OK", request_id=request.state.request_id))


@router.get("/system/user", tags=["System"])
def system_user(request: Request):
    svc = build(request, SystemService)
    return handle(lambda: ok(svc.user_cmd(), code="OK", request_id=request.state.request_id))


# ---------- Dependencies ----------
@router.get("/dependencies", tags=["Dependencies"])
def dependencies(request: Request):
    svc = build(request, DependencyService)
    return handle(lambda: ok(svc.check(), request_id=request.state.request_id))


class InstallBody(BaseModel):
    packages: list = Field(default_factory=list)
    confirm: bool = False


@router.post("/dependencies/install", tags=["Dependencies"])
def dependencies_install(body: InstallBody, request: Request):
    svc = build(request, DependencyService)
    return handle(lambda: ok(svc.install(body.packages, body.confirm), code="DEPENDENCIES_INSTALLED",
                             request_id=request.state.request_id))


@router.get("/dependencies/verify", tags=["Dependencies"])
def dependencies_verify(request: Request):
    svc = build(request, DependencyService)
    return handle(lambda: ok(svc.check(), code="DEPENDENCIES_VERIFIED", request_id=request.state.request_id))


@router.get("/dependencies/{name}", tags=["Dependencies"])
def dependency_check_one(name: str, request: Request):
    svc = build(request, DependencyService)
    return handle(lambda: ok(svc.check_one(name), code="OK", request_id=request.state.request_id))


# ---------- Discovery ----------
@router.get("/discovery", tags=["Discovery"])
def discovery(request: Request):
    svc = build(request, DiscoveryService)
    return handle(lambda: ok(svc.discover(), request_id=request.state.request_id))


@router.get("/discovery/g", tags=["Discovery"])
def discovery_g(request: Request):
    svc = build(request, DiscoveryService)
    return handle(lambda: ok(svc.discover(), code="LSSCSI_G_COMPLETED", request_id=request.state.request_id))


@router.get("/discovery/map", tags=["Discovery"])
def discovery_map(request: Request):
    svc = build(request, DeviceService)
    return handle(lambda: ok(svc.discovery_map(), request_id=request.state.request_id))


@router.get("/discovery/list", tags=["Discovery"])
def discovery_list(request: Request):
    svc = build(request, DiscoveryService)
    return handle(lambda: ok(svc.sg_scan_only(), code="SG_SCAN_COMPLETED", request_id=request.state.request_id))


@router.get("/discovery/detail", tags=["Discovery"])
def discovery_detail(request: Request):
    svc = build(request, DiscoveryService)
    return handle(lambda: ok(svc.scan_detail(), code="SCAN_COMPLETED", request_id=request.state.request_id))


# ---------- Device / SCSI ----------
@router.get("/devices/{sg_device}/inquiry", tags=["SCSI"])
def device_inquiry(sg_device: str, request: Request):
    svc = build(request, DeviceService)
    return handle(lambda: ok(svc.inquiry(sg_device), request_id=request.state.request_id))


@router.get("/devices/{sg_device}/vpd", tags=["SCSI"])
def device_vpd(sg_device: str, request: Request, page: str = "0x80"):
    svc = build(request, DeviceService)
    return handle(lambda: ok(svc.vpd(sg_device, page), request_id=request.state.request_id))


@router.get("/devices/{sg_device}/tur", tags=["SCSI"])
def device_tur(sg_device: str, request: Request):
    svc = build(request, DeviceService)
    return handle(lambda: ok(svc.tur(sg_device), request_id=request.state.request_id), request.state.request_id)


@router.get("/devices/{sg_device}/modes/sum", tags=["SCSI"])
def device_modes_sum(sg_device: str, request: Request):
    svc = build(request, DeviceService)
    return handle(lambda: ok(svc.modes_summary(sg_device), request_id=request.state.request_id))


@router.get("/devices/{sg_device}/modes", tags=["SCSI"])
def device_modes(sg_device: str, request: Request, page: str = None):
    svc = build(request, DeviceService)
    return handle(lambda: ok(svc.modes(sg_device, page), request_id=request.state.request_id),
                  request.state.request_id)


@router.get("/devices/{sg_device}/logsense/sum", tags=["SCSI"])
def device_logsense_sum(sg_device: str, request: Request):
    svc = build(request, DeviceService)
    return handle(lambda: ok(svc.logs_summary(sg_device), request_id=request.state.request_id))


@router.get("/devices/{sg_device}/logsense", tags=["SCSI"])
def device_logsense(sg_device: str, request: Request, page: Optional[str] = None):
    svc = build(request, DeviceService)
    return handle(lambda: ok(svc.logs(sg_device, page), request_id=request.state.request_id))


@router.get("/devices/{sg_device}/logs", tags=["SCSI"])
def device_logs(sg_device: str, request: Request, page: Optional[str] = None):
    svc = build(request, DeviceService)
    return handle(lambda: ok(svc.logs(sg_device, page), request_id=request.state.request_id))


@router.get("/drives/{sg_device}/tapealert", tags=["Diagnostics"])
def drive_tapealert(sg_device: str, request: Request):
    svc = build(request, DeviceService)
    return handle(lambda: ok(svc.tapealert(sg_device), request_id=request.state.request_id))


# ---------- Libraries ----------
@router.get("/libraries", tags=["Library"])
def libraries(request: Request):
    svc = build(request, DiscoveryService)
    def _go():
        data = svc.discover()
        changers = [d for d in data["devices"] if d["device_type"] in ("MEDIUM_CHANGER", "MEDIUMX")]
        return ok(changers, request_id=request.state.request_id)
    return handle(_go)


@router.get("/libraries/{changer}/inquiry", tags=["Library"])
def library_inquiry(changer: str, request: Request):
    svc = build(request, LibraryService)
    return handle(lambda: ok(svc.inquiry(changer), request_id=request.state.request_id))


@router.get("/libraries/{changer}/status", tags=["Library"])
def library_status(changer: str, request: Request):
    svc = build(request, LibraryService)
    return handle(lambda: ok(svc.status(changer), request_id=request.state.request_id))


@router.get("/libraries/{changer}/inventory", tags=["Library"])
def library_inventory(changer: str, request: Request):
    svc = build(request, LibraryService)
    return handle(lambda: ok(svc.inventory(changer), request_id=request.state.request_id))


class ConfirmBody(BaseModel):
    confirm: bool = False


class LoadBody(ConfirmBody):
    slot: int
    drive: int


class TransferBody(ConfirmBody):
    source: int
    destination: int


class PositionBody(ConfirmBody):
    element: int


@router.post("/libraries/{changer}/load", tags=["Library"])
def library_load(changer: str, body: LoadBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, LibraryService)
    return handle(lambda: ok(svc.load(changer, body.slot, body.drive), code="LOAD_SUCCESS",
                             request_id=request.state.request_id), request.state.request_id)


@router.post("/libraries/{changer}/unload", tags=["Library"])
def library_unload(changer: str, body: LoadBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, LibraryService)
    return handle(lambda: ok(svc.unload(changer, body.slot, body.drive), code="UNLOAD_SUCCESS",
                             request_id=request.state.request_id), request.state.request_id)


@router.post("/libraries/{changer}/transfer", tags=["Library"])
def library_transfer(changer: str, body: TransferBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, LibraryService)
    return handle(lambda: ok(svc.transfer(changer, body.source, body.destination), code="TRANSFER_SUCCESS",
                             request_id=request.state.request_id))


@router.post("/libraries/{changer}/position", tags=["Library"])
def library_position(changer: str, body: PositionBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, LibraryService)
    return handle(lambda: ok(svc.position(changer, body.element), code="POSITION_SUCCESS",
                             request_id=request.state.request_id))


# ---------- Drives ----------
@router.get("/drives/{nst_device}/summary", tags=["Drive"])
def drive_summary(nst_device: str, request: Request):
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.summary(nst_device), code="DRIVE_SUMMARY",
                             request_id=request.state.request_id))


@router.get("/drives/{nst_device}/status", tags=["Drive"])
def drive_status(nst_device: str, request: Request):
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.status(nst_device), request_id=request.state.request_id))


class DrivePositionBody(ConfirmBody):
    operation: str
    count: int = 1


@router.post("/drives/{nst_device}/rewind", tags=["Drive"])
def drive_rewind(nst_device: str, body: ConfirmBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.rewind(nst_device), code="REWIND_SUCCESS",
                             request_id=request.state.request_id))


@router.post("/drives/{nst_device}/position", tags=["Drive"])
def drive_position(nst_device: str, body: DrivePositionBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.position(nst_device, body.operation, body.count), code="POSITION_SUCCESS",
                             request_id=request.state.request_id),
                  request.state.request_id)


@router.get("/drives/{nst_device}/compression", tags=["Drive"])
def drive_compression(nst_device: str, request: Request):
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.compression(nst_device), request_id=request.state.request_id))


class WeofBody(ConfirmBody):
    count: int = 1


@router.post("/drives/{nst_device}/weof", tags=["Drive"])
def drive_weof(nst_device: str, body: WeofBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_3")
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.weof(nst_device, body.count), code="WEOF_SUCCESS",
                             request_id=request.state.request_id),
                  request.state.request_id)


# ---------- Diagnostics ----------
@router.get("/diagnostics/system", tags=["Diagnostics"])
def diag_system(request: Request):
    svc = build(request, DiagnosticService)
    return handle(lambda: ok(svc.system(), request_id=request.state.request_id))


@router.get("/diagnostics/dmesg", tags=["Diagnostics"])
def diag_dmesg(request: Request, tail: int = 100):
    svc = build(request, DiagnosticService)
    return handle(lambda: ok(svc.dmesg_log(tail), code="OK", request_id=request.state.request_id))


@router.get("/diagnostics/journalctl", tags=["Diagnostics"])
def diag_journalctl(request: Request, tail: int = 100):
    svc = build(request, DiagnosticService)
    return handle(lambda: ok(svc.journalctl_log(tail), code="OK", request_id=request.state.request_id))


@router.get("/diagnostics/tape/{sg_device}", tags=["Diagnostics"])
def diag_tape(sg_device: str, request: Request):
    svc = build(request, DiagnosticService)
    return handle(lambda: ok(svc.tape(sg_device), request_id=request.state.request_id))


# ---------- Tests ----------
class ReadTestBody(ConfirmBody):
    drive: str
    block_size: str = "1M"
    timeout: int = 3600


class WriteTestBody(ConfirmBody):
    drive: str
    test_media: str = ""
    size_mb: int = 1024
    allow_write: bool = False
    timeout: int = 7200


class EraseBody(ConfirmBody):
    drive: str
    allow_write: bool = False


@router.post("/tests/read", tags=["Tests"])
def tests_read(body: ReadTestBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, TestService)
    return handle(lambda: ok(svc.read_test(body.drive, body.block_size, body.confirm, body.timeout),
                             code="READ_TEST_PASS", request_id=request.state.request_id))


@router.post("/tests/write", tags=["Tests"])
def tests_write(body: WriteTestBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_3")
    svc = build(request, TestService)
    return handle(lambda: ok(svc.write_test(body.drive, body.test_media, body.size_mb,
                                            body.allow_write, body.confirm, body.timeout),
                             code="WRITE_TEST_PASS", request_id=request.state.request_id))


class WriteVerifyBody(ConfirmBody):
    drive: str
    test_media: str = ""
    size_mb: int = 256
    allow_write: bool = False
    timeout: int = 7200


@router.post("/tests/write-verify", tags=["Tests"])
def tests_write_verify(body: WriteVerifyBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_3")
    svc = build(request, TestService)
    return handle(lambda: ok(svc.write_verify(body.drive, body.test_media, body.size_mb,
                                              body.allow_write, body.confirm, body.timeout),
                             code="WRITE_VERIFY_PASS", request_id=request.state.request_id))


@router.post("/tests/erase", tags=["Tests"])
def tests_erase(body: EraseBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_3")
    svc = build(request, TestService)
    return handle(lambda: ok(svc.erase(body.drive, body.allow_write, body.confirm),
                             code="ERASE_COMPLETED", request_id=request.state.request_id))


@router.post("/tests/full", tags=["Tests"])
def tests_full(request: Request):
    svc = build(request, TestService)
    def _go():
        data = svc.full_test()
        return ok(data, code="FULL_TEST_COMPLETED", request_id=request.state.request_id)
    return handle(_go)


# ---------- Audit / Commands ----------
@router.get("/commands", tags=["Audit"])
def list_commands(limit: int = 50, request_id: str = None, request: Request = None):
    recs = request.app.state.storage.list_commands(request_id)
    recs = sorted(recs, key=lambda r: r.get("started_at") or "", reverse=True)[:max(1, min(limit, 500))]
    data = [{k: r.get(k) for k in ("command_id", "command", "phase", "risk_level", "device",
                                   "started_at", "finished_at", "duration_ms", "exit_code", "result")}
            for r in recs]
    return ok(data, request_id=request.state.request_id)


@router.get("/commands/{command_id}", tags=["Audit"])
def get_command(command_id: str, request: Request):
    rec = request.app.state.storage.get_command(command_id)
    if rec is None:
        return fail("COMMAND_NOT_FOUND", "unknown command id", request_id=request.state.request_id)
    from app.commands.parsers import auto_parse
    data = {k: rec.get(k) for k in ("command_id", "command", "phase", "risk_level", "device",
                                    "started_at", "finished_at", "duration_ms", "exit_code",
                                    "stdout", "stderr", "result")}
    data["parsed"] = auto_parse(rec.get("command") or "", rec.get("stdout") or "",
                                rec.get("stderr") or "", rec.get("exit_code") or 0)
    return ok(data, request_id=request.state.request_id)


@router.get("/audit/{request_id}", tags=["Audit"])
def get_audit(request_id: str, request: Request):
    info = request.app.state.storage.get_request(request_id)
    if info is None:
        return fail("COMMAND_NOT_FOUND", "unknown request id", request_id=request_id)
    info = dict(info)
    info["commands"] = [request.app.state.storage.get_command(cid) for cid in info.get("command_ids", [])]
    return ok(info, request_id=request.state.request_id)
