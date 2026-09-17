"""API routers: thin HTTP layer over services. Uniform ApiResponse envelope."""
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.models.common import ok, fail
from app.services.services import (
    SystemService, DependencyService, DiscoveryService, DeviceService,
    LibraryService, DriveService, DiagnosticService, TestService, ServiceError,
    ScsiService,
)

router = APIRouter(prefix="/api/v1")


def ctx(request: Request):
    return request.app.state.chain, request.state.request_id


def build(request: Request, cls):
    chain, rid = ctx(request)
    return cls(request.app.state.runner, chain, rid)


def _error_status(code):
    """业务错误码 -> HTTP 状态码（同步 handle 与 /jobs/{id}/result 共用，保证异步结果与同步执行一致）."""
    if code in ("DEVICE_NOT_FOUND", "LIBRARY_NOT_FOUND", "DRIVE_NOT_FOUND", "MEDIA_NOT_FOUND", "SLOT_NOT_FOUND"):
        return 404
    if code in ("PERMISSION_DENIED", "WRITE_OPERATION_NOT_AUTHORIZED", "DESTRUCTIVE_OPERATION_NOT_AUTHORIZED"):
        return 403
    if code == "DEVICE_BUSY":
        return 409
    if code in ("COMMAND_FAILED", "TIMEOUT", "SCSI_ERROR"):
        return 502
    return 400


def handle(fn, request_id=""):
    try:
        return fn()
    except ServiceError as e:
        raise HTTPException(status_code=_error_status(e.code),
                            detail={"code": e.code, "message": e.message})


# ---------- async job helpers ----------
def wants_sync(request: Request) -> bool:
    """Long-running endpoints run as async jobs by default (202 + job_id).
    CLI/legacy clients opt back into the old synchronous behavior with
    query ?async=false or header X-Sync: true."""
    if request.headers.get("x-sync", "").lower() == "true":
        return True
    return request.query_params.get("async", "true").lower() == "false"


def submit_or_run(request: Request, name: str, target, devices=()):
    """target: zero-arg callable returning the sync ApiResponse (or raising ServiceError)."""
    if wants_sync(request):
        return handle(target, request.state.request_id)
    job = request.app.state.jobs.submit(name, request.url.path, target,
                                        request_id=request.state.request_id,
                                        devices=devices)
    body = ok({"job_id": job.job_id, "state": job.state,
               "poll_url": "/api/v1/jobs/%s" % job.job_id},
              code="JOB_SUBMITTED",
              message="job submitted; poll poll_url for status/result",
              request_id=request.state.request_id)
    return JSONResponse(status_code=202, content=body.model_dump())


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
    return submit_or_run(request, "dependencies-install",
                         lambda: ok(svc.install(body.packages, body.confirm), code="DEPENDENCIES_INSTALLED",
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
    return handle(lambda: ok(svc.tur(sg_device), request_id=request.state.request_id))


@router.get("/devices/{sg_device}/modes", tags=["SCSI"])
def device_modes(sg_device: str, request: Request):
    svc = build(request, DeviceService)
    return handle(lambda: ok(svc.modes(sg_device), request_id=request.state.request_id))


@router.get("/devices/{sg_device}/logs", tags=["SCSI"])
def device_logs(sg_device: str, request: Request, page: Optional[str] = None):
    svc = build(request, DeviceService)
    return handle(lambda: ok(svc.logs(sg_device, page), request_id=request.state.request_id))


@router.get("/drives/{sg_device}/tapealert", tags=["Diagnostics"])
def drive_tapealert(sg_device: str, request: Request):
    svc = build(request, DeviceService)
    return handle(lambda: ok(svc.tapealert(sg_device), request_id=request.state.request_id))


@router.get("/scsi/{device}/inquiry", tags=["SCSI"])
def scsi_inquiry(device: str, request: Request):
    svc = build(request, ScsiService)
    return handle(lambda: ok(svc.inquiry(device), code="INQUIRY_SUCCESS",
                             request_id=request.state.request_id))


@router.get("/scsi/{device}/vpd", tags=["SCSI"])
def scsi_vpd(device: str, request: Request, page: str = "0x80"):
    svc = build(request, ScsiService)
    return handle(lambda: ok(svc.vpd(device, page), code="VPD_SUCCESS",
                             request_id=request.state.request_id))


@router.get("/scsi/{device}/logs", tags=["SCSI"])
def scsi_logs(device: str, request: Request, page: Optional[str] = None):
    svc = build(request, ScsiService)
    return handle(lambda: ok(svc.logs(device, page), code="LOGS_SUCCESS",
                             request_id=request.state.request_id))


@router.get("/scsi/{device}/tapealert", tags=["SCSI"])
def scsi_tapealert(device: str, request: Request):
    svc = build(request, ScsiService)
    return handle(lambda: ok(svc.tapealert(device), code="TAPEALERT_SUCCESS",
                             request_id=request.state.request_id))


@router.get("/scsi/{device}/persist", tags=["SCSI"])
def scsi_persist(device: str, request: Request):
    svc = build(request, ScsiService)
    return handle(lambda: ok(svc.persist(device), code="PERSIST_SUCCESS",
                             request_id=request.state.request_id))


from pydantic import BaseModel


class ScsiResetBody(BaseModel):
    confirm: bool = False


@router.post("/scsi/{device}/reset", tags=["SCSI"])
def scsi_reset(device: str, request: Request, body: ScsiResetBody):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, ScsiService)
    return handle(lambda: ok(svc.reset(device, body.confirm), code="RESET_SUCCESS",
                             request_id=request.state.request_id))


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
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, LibraryService)
    return submit_or_run(request, "library-inventory",
                         lambda: ok(svc.inventory(changer), code="INVENTORY_SUCCESS",
                                    request_id=request.state.request_id), devices=(changer,))


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
    return submit_or_run(request, "library-load",
                         lambda: ok(svc.load(changer, body.slot, body.drive), code="LOAD_SUCCESS",
                                    request_id=request.state.request_id), devices=(changer,))


@router.post("/libraries/{changer}/unload", tags=["Library"])
def library_unload(changer: str, body: LoadBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, LibraryService)
    return submit_or_run(request, "library-unload",
                         lambda: ok(svc.unload(changer, body.slot, body.drive), code="UNLOAD_SUCCESS",
                                    request_id=request.state.request_id), devices=(changer,))


@router.post("/libraries/{changer}/transfer", tags=["Library"])
def library_transfer(changer: str, body: TransferBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, LibraryService)
    return submit_or_run(request, "library-transfer",
                         lambda: ok(svc.transfer(changer, body.source, body.destination), code="TRANSFER_SUCCESS",
                                    request_id=request.state.request_id), devices=(changer,))


@router.post("/libraries/{changer}/position", tags=["Library"], include_in_schema=False)
def library_position(changer: str, body: PositionBody, request: Request):
    # 兼容旧路径，等价 robot/position
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, LibraryService)
    return submit_or_run(request, "library-position",
                         lambda: ok(svc.position(changer, body.element), code="POSITION_SUCCESS",
                                    request_id=request.state.request_id), devices=(changer,))


@router.post("/libraries/{changer}/robot/position", tags=["Library"])
def library_robot_position(changer: str, body: PositionBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, LibraryService)
    return submit_or_run(request, "library-position",
                         lambda: ok(svc.position(changer, body.element), code="POSITION_SUCCESS",
                                    request_id=request.state.request_id), devices=(changer,))


@router.post("/libraries/{changer}/exchange", tags=["Library"])
def library_exchange(changer: str, body: TransferBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, LibraryService)
    return submit_or_run(request, "library-exchange",
                         lambda: ok(svc.exchange(changer, body.source, body.destination), code="EXCHANGE_SUCCESS",
                                    request_id=request.state.request_id), devices=(changer,))


@router.post("/libraries/{changer}/robot/first", tags=["Library"])
def library_robot_first(changer: str, request: Request):
    svc = build(request, LibraryService)
    return submit_or_run(request, "robot-first",
                         lambda: ok(svc.first(changer), code="FIRST_SUCCESS",
                                    request_id=request.state.request_id), devices=(changer,))


@router.post("/libraries/{changer}/robot/next", tags=["Library"])
def library_robot_next(changer: str, request: Request):
    svc = build(request, LibraryService)
    return submit_or_run(request, "robot-next",
                         lambda: ok(svc.next(changer), code="NEXT_SUCCESS",
                                    request_id=request.state.request_id), devices=(changer,))


@router.post("/libraries/{changer}/robot/last", tags=["Library"])
def library_robot_last(changer: str, request: Request):
    svc = build(request, LibraryService)
    return submit_or_run(request, "robot-last",
                         lambda: ok(svc.last(changer), code="LAST_SUCCESS",
                                    request_id=request.state.request_id), devices=(changer,))


# ---------- Drives ----------
@router.get("/drives/{drive}/status", tags=["Drive"])
def drive_status(drive: str, request: Request):
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.status(drive), request_id=request.state.request_id))


class DrivePositionBody(ConfirmBody):
    operation: str
    count: int = 1


class DriveCountBody(ConfirmBody):
    count: int = 1


class DriveCompressionBody(ConfirmBody):
    enable: bool


class DriveBlockSizeBody(ConfirmBody):
    block_size: int


class DriveDensityBody(ConfirmBody):
    density: int


class DrivePartitionBody(ConfirmBody):
    # setpartition: 传 partition（切换当前分区）；mkpartition: 传 count（重新划分分区，L3）
    partition: Optional[int] = None
    count: Optional[int] = None


class DrivePartSeekBody(ConfirmBody):
    partition: int
    block: int


@router.post("/drives/{drive}/weof", tags=["Drive"])
def drive_weof(drive: str, body: DriveCountBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_3")
    svc = build(request, DriveService)
    return submit_or_run(request, "drive-weof",
                         lambda: ok(svc.weof(drive, body.count), code="WEOF_SUCCESS",
                                    request_id=request.state.request_id), devices=(drive,))


@router.post("/drives/{drive}/wset", tags=["Drive"])
def drive_wset(drive: str, body: DriveCountBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_3")
    svc = build(request, DriveService)
    return submit_or_run(request, "drive-wset",
                         lambda: ok(svc.wset(drive, body.count), code="WSET_SUCCESS",
                                    request_id=request.state.request_id), devices=(drive,))


@router.post("/drives/{drive}/eof", tags=["Drive"])
def drive_eof(drive: str, body: DriveCountBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_3")
    svc = build(request, DriveService)
    return submit_or_run(request, "drive-eof",
                         lambda: ok(svc.eof(drive, body.count), code="EOF_SUCCESS",
                                    request_id=request.state.request_id), devices=(drive,))


@router.post("/drives/{drive}/position", tags=["Drive"])
def drive_position(drive: str, body: DrivePositionBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return submit_or_run(request, "drive-position",
                         lambda: ok(svc.position(drive, body.operation, body.count), code="POSITION_SUCCESS",
                                    request_id=request.state.request_id), devices=(drive,))


@router.post("/drives/{drive}/rewind", tags=["Drive"])
def drive_rewind(drive: str, body: ConfirmBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.rewind(drive), code="REWIND_SUCCESS",
                             request_id=request.state.request_id))


@router.post("/drives/{drive}/offline", tags=["Drive"])
def drive_offline(drive: str, body: ConfirmBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.offline(drive), code="OFFLINE_SUCCESS",
                             request_id=request.state.request_id))


@router.post("/drives/{drive}/rewoffl", tags=["Drive"])
def drive_rewoffl(drive: str, body: ConfirmBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.rewoffl(drive), code="REWOFFL_SUCCESS",
                             request_id=request.state.request_id))


@router.post("/drives/{drive}/eject", tags=["Drive"])
def drive_eject(drive: str, body: ConfirmBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.eject(drive), code="EJECT_SUCCESS",
                             request_id=request.state.request_id))


@router.post("/drives/{drive}/retension", tags=["Drive"])
def drive_retension(drive: str, body: ConfirmBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return submit_or_run(request, "drive-retension",
                         lambda: ok(svc.retension(drive), code="RETENSION_SUCCESS",
                                    request_id=request.state.request_id), devices=(drive,))


@router.post("/drives/{drive}/eod", tags=["Drive"])
def drive_eod(drive: str, body: ConfirmBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return submit_or_run(request, "drive-eod",
                         lambda: ok(svc.eod(drive), code="EOD_SUCCESS",
                                    request_id=request.state.request_id), devices=(drive,))


@router.post("/drives/{drive}/seod", tags=["Drive"])
def drive_seod(drive: str, body: ConfirmBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return submit_or_run(request, "drive-seod",
                         lambda: ok(svc.seod(drive), code="SEOD_SUCCESS",
                                    request_id=request.state.request_id), devices=(drive,))


@router.post("/drives/{drive}/seek", tags=["Drive"])
def drive_seek(drive: str, body: DriveCountBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return submit_or_run(request, "drive-seek",
                         lambda: ok(svc.seek(drive, body.count), code="SEEK_SUCCESS",
                                    request_id=request.state.request_id), devices=(drive,))


@router.get("/drives/{drive}/tell", tags=["Drive"])
def drive_tell(drive: str, request: Request):
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.tell(drive), code="TELL_SUCCESS",
                             request_id=request.state.request_id))


@router.get("/drives/{drive}/densities", tags=["Drive"])
def drive_densities(drive: str, request: Request):
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.densities(drive), code="DENSITIES_SUCCESS",
                             request_id=request.state.request_id))


@router.get("/drives/{drive}/options", tags=["Drive"])
def drive_options(drive: str, request: Request):
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.stshowoptions(drive), code="OPTIONS_SUCCESS",
                             request_id=request.state.request_id))


@router.post("/drives/{drive}/erase", tags=["Drive"])
def drive_erase(drive: str, body: DriveCountBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_3")
    svc = build(request, DriveService)
    return submit_or_run(request, "drive-erase",
                         lambda: ok(svc.erase(drive, body.count), code="ERASE_SUCCESS",
                                    request_id=request.state.request_id), devices=(drive,))


@router.post("/drives/{drive}/lock", tags=["Drive"])
def drive_lock(drive: str, body: ConfirmBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.lock(drive), code="LOCK_SUCCESS",
                             request_id=request.state.request_id))


@router.post("/drives/{drive}/unlock", tags=["Drive"])
def drive_unlock(drive: str, body: ConfirmBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.unlock(drive), code="UNLOCK_SUCCESS",
                             request_id=request.state.request_id))


@router.post("/drives/{drive}/load", tags=["Drive"])
def drive_load(drive: str, body: ConfirmBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.load(drive), code="LOAD_SUCCESS",
                             request_id=request.state.request_id))


@router.post("/drives/{drive}/compression", tags=["Drive"])
def drive_compression_set(drive: str, body: DriveCompressionBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.compression_set(drive, body.enable), code="COMPRESSION_SUCCESS",
                             request_id=request.state.request_id))


@router.post("/drives/{drive}/block-size", tags=["Drive"])
def drive_block_size(drive: str, body: DriveBlockSizeBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.setblk(drive, body.block_size), code="SETBLK_SUCCESS",
                             request_id=request.state.request_id))


@router.post("/drives/{drive}/density", tags=["Drive"])
def drive_density(drive: str, body: DriveDensityBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.setdensity(drive, body.density), code="SETDENSITY_SUCCESS",
                             request_id=request.state.request_id))


@router.post("/drives/{drive}/partition", tags=["Drive"])
def drive_partition(drive: str, body: DrivePartitionBody, request: Request):
    from app.security.policy import require_level
    svc = build(request, DriveService)
    if body.partition is not None:
        # setpartition: 切换到指定分区
        require_level("LEVEL_2")
        return handle(lambda: ok(svc.setpartition(drive, body.partition), code="PARTITION_SUCCESS",
                                 request_id=request.state.request_id))
    # mkpartition: 重新划分分区（会破坏数据，L3）
    require_level("LEVEL_3")
    count = body.count if body.count is not None else 1
    return handle(lambda: ok(svc.mkpartition(drive, count), code="PARTITION_SUCCESS",
                             request_id=request.state.request_id))


@router.post("/drives/{drive}/partition/seek", tags=["Drive"])
def drive_partition_seek(drive: str, body: DrivePartSeekBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.partseek(drive, body.partition, body.block), code="PARTSEEK_SUCCESS",
                             request_id=request.state.request_id))


@router.get("/drives/{nst_device}/compression", tags=["Drive"], include_in_schema=False)
def drive_compression(nst_device: str, request: Request):
    # 保留只读查询（query compression）兼容旧客户端；设置压缩走 POST /compression
    svc = build(request, DriveService)
    return handle(lambda: ok(svc.compression(nst_device), request_id=request.state.request_id))


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
    file: str = ""
    timeout: int = 3600


class WriteTestBody(ConfirmBody):
    drive: str
    media: str = ""
    test_media: str = ""  # 兼容旧字段名
    file: str = ""  # 指定则将该文件内容写入磁带；缺省写入 size_mb 的零数据
    size_mb: int = 1024
    allow_write: bool = False
    timeout: int = 7200


def _media_of(body) -> str:
    return body.media or body.test_media


@router.post("/write", tags=["Tests"])
def api_write(body: WriteTestBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_3")
    svc = build(request, TestService)
    return submit_or_run(request, "write-test",
                         lambda: ok(svc.write_test(body.drive, _media_of(body), body.size_mb,
                                                   body.allow_write, body.confirm, body.timeout,
                                                   in_file=getattr(body, "file", "")),
                                    code="WRITE_SUCCESS", request_id=request.state.request_id),
                         devices=(body.drive,))


@router.post("/tests/write", tags=["Tests"], include_in_schema=False)
def tests_write(body: WriteTestBody, request: Request):
    # 兼容旧路径，等价 /write
    return api_write(body, request)


class EraseBody(ConfirmBody):
    drive: str
    allow_write: bool = False


@router.post("/read", tags=["Tests"])
def api_read(body: ReadTestBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_2")
    svc = build(request, TestService)
    return submit_or_run(request, "read-test",
                         lambda: ok(svc.read_test(body.drive, body.block_size, body.confirm, body.timeout,
                                                  getattr(body, "file", "")),
                                    code="READ_SUCCESS", request_id=request.state.request_id),
                         devices=(body.drive,))


@router.post("/tests/read", tags=["Tests"], include_in_schema=False)
def tests_read(body: ReadTestBody, request: Request):
    # 兼容旧路径，等价 /read
    return api_read(body, request)


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
    return submit_or_run(request, "write-verify",
                         lambda: ok(svc.write_verify(body.drive, body.test_media, body.size_mb,
                                                     body.allow_write, body.confirm, body.timeout),
                                    code="WRITE_VERIFY_PASS", request_id=request.state.request_id),
                         devices=(body.drive,))


@router.post("/tests/erase", tags=["Tests"])
def tests_erase(body: EraseBody, request: Request):
    from app.security.policy import require_level
    require_level("LEVEL_3")
    svc = build(request, TestService)
    return submit_or_run(request, "erase",
                         lambda: ok(svc.erase(body.drive, body.allow_write, body.confirm),
                                    code="ERASE_COMPLETED", request_id=request.state.request_id),
                         devices=(body.drive,))


@router.post("/tests/full", tags=["Tests"])
def tests_full(request: Request):
    svc = build(request, TestService)
    def _go():
        data = svc.full_test()
        return ok(data, code="FULL_TEST_COMPLETED", request_id=request.state.request_id)
    return submit_or_run(request, "full-test", _go)


# ---------- Jobs ----------
@router.get("/jobs", tags=["Jobs"])
def jobs_list(request: Request, status: str = None, limit: int = 50, offset: int = 0):
    data = request.app.state.jobs.list(status=status, limit=limit, offset=offset)
    return ok(data, code="OK", request_id=request.state.request_id)


@router.get("/jobs/{job_id}", tags=["Jobs"])
def jobs_get(job_id: str, request: Request):
    job = request.app.state.jobs.get(job_id)
    if job is None:
        return fail("JOB_NOT_FOUND", "unknown job id", request_id=request.state.request_id)
    d = job.to_dict()
    d["audit_url"] = "/api/v1/audit/%s" % job.request_id if job.request_id else None
    return ok(d, code="OK", request_id=request.state.request_id)


@router.post("/jobs/{job_id}/cancel", tags=["Jobs"])
def jobs_cancel(job_id: str, request: Request):
    job = request.app.state.jobs.cancel(job_id)
    if job is None:
        return fail("JOB_NOT_FOUND", "unknown job id", request_id=request.state.request_id)
    return ok(job.to_dict(brief=True), code="CANCEL_REQUESTED",
              message="cancel requested" if job.cancel_requested else "job already finished",
              request_id=request.state.request_id)


@router.get("/jobs/{job_id}/progress", tags=["Jobs"])
def jobs_progress(job_id: str, request: Request):
    """轻量进度查询（轮询友好）：仅状态与进度字段，不含 result/steps 明细."""
    job = request.app.state.jobs.get(job_id)
    if job is None:
        return fail("JOB_NOT_FOUND", "unknown job id", request_id=request.state.request_id)
    return ok({
        "job_id": job.job_id,
        "name": job.name,
        "state": job.state,
        "progress": job.progress,
        "started_at": job.started_at,
        "duration_ms": job.duration_ms,
        "cancel_requested": job.cancel_requested,
    }, code="OK", request_id=request.state.request_id)


@router.get("/jobs/{job_id}/result", tags=["Jobs"])
def jobs_result(job_id: str, request: Request):
    """结果查询：返回与同步执行一致的业务信封。
    成功：服务层原始信封（code=INVENTORY_SUCCESS 等业务码 + data），HTTP 200；
    失败：与同步相同的错误码->状态码映射（502/404/409...）+ 错误信封；
    均附 job_id/state/finished/command_ids/audit_url 供关联，job 明细仍走 GET /jobs/{id}."""
    job = request.app.state.jobs.get(job_id)
    if job is None:
        return fail("JOB_NOT_FOUND", "unknown job id", request_id=request.state.request_id)
    if job.state not in ("succeeded", "failed", "cancelled"):
        return ok({"job_id": job.job_id, "state": job.state, "finished": False,
                   "progress": job.progress,
                   "message": "job not finished yet"},
                  code="NOT_FINISHED", request_id=request.state.request_id)
    extra = {"job_id": job.job_id, "state": job.state, "finished": True,
             "duration_ms": job.duration_ms, "command_ids": job.command_ids,
             "audit_url": "/api/v1/audit/%s" % job.request_id if job.request_id else None}
    rid = job.request_id or request.state.request_id
    if job.state == "succeeded":
        if isinstance(job.result, dict) and job.result.get("code"):
            body = dict(job.result)   # 服务层原始信封（业务 code + data）
        else:
            body = ok(job.result, request_id=rid).model_dump()
    elif job.state == "cancelled":
        body = fail("CANCELLED", "job cancelled by user", request_id=rid).model_dump()
    else:
        err = job.error or {}
        body = fail(err.get("code", "INTERNAL_ERROR"), err.get("message", "job failed"),
                    request_id=rid).model_dump()
    body.update(extra)
    status = _error_status((job.error or {}).get("code", "")) if job.state == "failed" else 200
    return JSONResponse(status_code=status, content=body)


# ---------- Audit / Commands ----------
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
