"""Archive gateway HTTP API, mounted under /api/v1/archive."""
import os
import traceback
import uuid

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app.models.common import fail, ok
from app.security.policy import require_level
from app.api.routes import submit_or_run

from .config import (FILE_KEYS, GatewayConfig, config_file_path, load_config_file,
                     save_config_file)
from .manager import GatewayError, GatewayManager
from .tapeio import TapeError


def _http(e: GatewayError):
    return HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message})


def _tape_err(e: TapeError):
    return HTTPException(status_code=409, detail={"code": e.code, "message": e.message})


def _gw(request: Request):
    gw = getattr(request.app.state, "gateway", None)
    if gw is None:
        raise HTTPException(status_code=503, detail={
            "code": "GATEWAY_UNAVAILABLE",
            "message": "archive gateway disabled or failed to start (check PG / logs)"})
    return gw


router = APIRouter(prefix="/api/v1/archive", tags=["Archive"])


class MediaRegister(BaseModel):
    barcode: str = Field(min_length=1, max_length=64)
    state: str = Field(default="appendable", pattern="^(unknown|scratch|appendable|full|faulted)$")
    format: str = Field(default="raw", pattern="^(raw|ltfs)$")


class MediaFormatBody(BaseModel):
    """mkltfs 格式化（销毁性）：仅支持转 ltfs；raw 无需格式化。"""
    format: str = Field(default="ltfs", pattern="^(raw|ltfs)$")
    confirm: bool = False
    force: bool = False


def _tape_view(bc):
    """Tape storage info (barcode/state/capacity/usage/blocks) for responses."""
    if not bc:
        return None
    cap = int(bc.get("capacity_bytes") or 0)
    used = int(bc.get("used_bytes") or 0)
    return {
        "barcode": bc.get("barcode"), "state": bc.get("state"),
        "format": bc.get("format") or "raw",
        "capacity_bytes": cap, "used_bytes": used,
        "free_bytes": max(cap - used, 0),
        "used_pct": round(used * 100 / cap, 1) if cap else None,
        "block_records": bc.get("block_records"),
        "last_filemark": bc.get("last_filemark"),
        "mount_count": bc.get("mount_count"),
        "bytes_written": bc.get("bytes_written"),
    }


def _file_location(f, cont, in_cache):
    """Structured location status: where the bytes physically live right now."""
    mbc = (cont or {}).get("media_barcode") or f.get("media_barcode")
    on_tape = f.get("state") == "archived" and bool(mbc)
    return {
        "zone": f.get("storage"),
        "in_cache": bool(in_cache),
        "on_tape": on_tape,
        "media_barcode": mbc,
        "tape_block_index": f.get("tape_block_index")
                            or (cont or {}).get("tape_block_index"),
        "ltfs_path": f.get("ltfs_path") or (cont or {}).get("ltfs_path"),
        "container_id": str(f["container_id"]) if f.get("container_id") else None,
        "offset_in_container": f.get("file_offset_in_container"),
        "download_ready": bool(in_cache),
        "needs_recall": on_tape and not in_cache,
    }


def _files_view(gw, rows):
    """Batch-join file rows with containers + tape media; adds location/tape.

    Two list queries total (independent of row count), then an in-memory join
    on container_id / media_barcode."""
    cont_by_id = {str(c["container_id"]): dict(c)
                  for c in gw.db.container_list(limit=5000)}
    media_by_bc = {m["barcode"]: dict(m) for m in gw.db.tape_list()}
    items = []
    for r in rows:
        f = dict(r)
        cont = cont_by_id.get(str(f.get("container_id"))) \
            if f.get("container_id") else None
        mbc = (cont or {}).get("media_barcode") or f.get("media_barcode")
        in_cache = bool(f.get("cache_path")) and os.path.isfile(f["cache_path"])
        f["location"] = _file_location(f, cont, in_cache)
        f["tape"] = _tape_view(media_by_bc.get(mbc)) if mbc else None
        items.append(f)
    return items


# ---------- meta ----------
@router.get("/config")
def gw_config(request: Request):
    require_level("LEVEL_1")
    gw = _gw(request)
    return ok(gw.cfg.summary(), request_id=request.state.request_id)


# ---------- gw-config: 启动/重启网关前的参数配置（文件层 > env > 默认） ----------
class GwConfigBody(BaseModel):
    """字段与 GET /archive/config 的 summary 同形；只传需要改的键。"""
    enabled: bool = None
    cache_dir: str = None
    db_dsn: str = None
    small_file_mb: int = Field(default=None, ge=1, le=10240)
    container_target_mb: int = Field(default=None, ge=1, le=102400)
    container_flush_s: int = Field(default=None, ge=5, le=86400)
    container_max_files: int = Field(default=None, ge=1, le=200000)
    cache_quota_gb: int = Field(default=None, ge=1, le=102400)
    watermarks_pct: list = None  # [low, high]
    drive: str = None
    changer: str = None
    dte_map: dict = None
    auto_load: bool = None
    trust_drive: str = None
    verify_write: bool = None
    max_attempts: int = Field(default=None, ge=1, le=10)
    redis_enabled: bool = None
    preferred_format: str = None
    ltfs_mount_root: str = None
    ltfs_bin_dir: str = None
    ltfs_sync_policy: str = None
    ltfs_mount_timeout_s: int = Field(default=None, ge=10, le=3600)
    ltfs_device: str = None
    confirm: bool = False
    apply: bool = False  # true: 写完立即重启网关生效


class GwApplyBody(BaseModel):
    confirm: bool = False


def _validate_gw_config(values: dict) -> dict:
    """白名单+语义校验，返回清洗后的文件层键值；非法抛 GatewayError(400)。"""
    from app.security.policy import normalize_device

    def bad(msg):
        raise GatewayError("INVALID_GW_CONFIG", msg, status=400)

    out = {}
    for k, v in values.items():
        if k in ("confirm", "apply"):
            continue
        if k not in FILE_KEYS:
            bad("unknown key: %s (allowed: %s)" % (k, ",".join(FILE_KEYS)))
        if v is None and k not in ("trust_drive",):
            continue
        if k in ("enabled", "auto_load", "verify_write", "redis_enabled"):
            out[k] = bool(v)
        elif k == "cache_dir":
            if not (isinstance(v, str) and v.startswith("/")):
                bad("cache_dir must be an absolute path")
            out[k] = os.path.normpath(v)
        elif k == "db_dsn":
            if not (isinstance(v, str) and (v.startswith("postgresql://") or ":" in v)):
                bad("db_dsn must be host:port/dbname or postgresql:// DSN")
            # 支持把 summary 脱敏后的 "host:port/db" 直接回传：补全为完整 DSN
            out[k] = v if "://" in v else "postgresql://postgres@%s" % v
        elif k in ("small_file_mb", "container_target_mb", "container_flush_s",
                   "container_max_files", "cache_quota_gb", "max_attempts"):
            if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
                bad("%s must be a positive int" % k)
            out[k] = v
        elif k == "watermarks_pct":
            if (not isinstance(v, (list, tuple)) or len(v) != 2
                    or not all(isinstance(x, int) and 0 < x < 100 for x in v)
                    or v[0] >= v[1]):
                bad("watermarks_pct must be [low, high], 0<low<high<100")
            out[k] = list(v)
        elif k in ("drive", "changer"):
            try:
                out[k] = normalize_device(str(v))
            except HTTPException:
                bad("%s invalid device: %s" % (k, v))
        elif k == "dte_map":
            if not isinstance(v, dict):
                bad("dte_map must be {dte_index: '/dev/nstN'}")
            dm = {}
            for kk, vv in v.items():
                try:
                    dm[str(kk)] = normalize_device(str(vv))
                except HTTPException:
                    bad("dte_map[%s] invalid device: %s" % (kk, vv))
            out[k] = dm
        elif k == "preferred_format":
            if v not in ("raw", "ltfs"):
                bad("preferred_format must be raw|ltfs")
            out[k] = v
        elif k == "ltfs_sync_policy":
            if v not in ("unmount", "keep_mounted"):
                bad("ltfs_sync_policy must be unmount|keep_mounted")
            out[k] = v
        elif k in ("ltfs_mount_root", "ltfs_bin_dir"):
            if not (isinstance(v, str) and v.startswith("/")):
                bad("%s must be an absolute path" % k)
            out[k] = os.path.normpath(v)
        elif k == "ltfs_mount_timeout_s":
            if not isinstance(v, int) or isinstance(v, bool) or not (10 <= v <= 3600):
                bad("ltfs_mount_timeout_s must be an int in 10..3600")
            out[k] = v
        elif k == "ltfs_device":
            # 空串=显式清除（回 sysfs 自动推导 sg 节点），非空=设备路径
            if v in (None, "", "null"):
                out[k] = ""
            else:
                try:
                    out[k] = normalize_device(str(v))
                except HTTPException:
                    bad("ltfs_device invalid device: %s" % v)
        elif k == "trust_drive":
            # 空串=显式清除（自动模式），仍保留在文件层覆盖 env；非空=条码
            out[k] = "" if v in (None, "", "null") else str(v)[:64]
    if "small_file_mb" in out and "container_target_mb" in out \
            and out["small_file_mb"] > out["container_target_mb"]:
        bad("small_file_mb must be <= container_target_mb")
    return out


def _gateway_candidate_summary():
    """按当前磁盘文件层+env 计算“重启后会生效”的配置预览（不落盘、不启动）。"""
    return GatewayConfig().summary()


@router.get("/gw-config", summary="网关配置全貌：运行值/文件层/重启后预览与 pending_diff")
def gw_config_read(request: Request):
    """读取网关配置全貌：当前运行值、配置文件层内容、重启后将生效值与差异项。
    网关未运行时也可用（用于启动前预配置核对）。"""
    require_level("LEVEL_1")
    gw = getattr(request.app.state, "gateway", None)
    candidate = _gateway_candidate_summary()
    live = gw.cfg.summary() if gw else None
    diff = []
    if live:
        for k, v in candidate.items():
            if k in ("config_file", "file_keys", "sources"):
                continue
            if live.get(k) != v:
                diff.append({"key": k, "live": live.get(k), "after_restart": v})
    return ok({
        "running": bool(gw),
        "live": live,
        "file_layer": load_config_file(),
        "config_file": config_file_path(),
        "candidate_after_restart": {k: v for k, v in candidate.items()
                                    if k not in ("sources",)},
        "restart_required": bool(diff),
        "pending_diff": diff,
    }, request_id=request.state.request_id)


@router.post("/gw-config", summary="保存网关参数到 gateway-config.json（文件层>env；apply=true 写后立即重启生效）")
def gw_config_write(request: Request, body: GwConfigBody):
    """启动网关前/运行中配置网关参数：写入 gateway-config.json（文件层 > GATEWAY_* env）。
    apply=false 仅保存，重启网关（POST /gw-config/apply 或 start-gw.sh）后生效；
    apply=true 写后立即原地重启。LEVEL_2，confirm=true 必需。"""
    require_level("LEVEL_2")
    if not body.confirm:
        raise HTTPException(status_code=400, detail={
            "code": "INVALID_REQUEST", "message": "confirm=true required for gateway config change"})
    provided = body.model_dump(exclude_unset=True)
    try:
        values = _validate_gw_config(provided)
    except GatewayError as e:
        raise _http(e)
    if not values:
        raise _http(GatewayError("INVALID_GW_CONFIG", "no valid keys provided", status=400))
    merged = save_config_file(values)
    candidate = _gateway_candidate_summary()
    resp = {
        "saved": values,
        "config_file": config_file_path(),
        "file_layer": merged,
        "candidate_after_restart": {k: v for k, v in candidate.items() if k not in ("sources",)},
        "applied": False,
        "restart_required": True,
    }
    if body.apply:
        st = _restart_gateway(request.app, request.state.request_id)
        resp["applied"] = True
        resp["restart"] = st
        resp["restart_required"] = not st["running"] and bool(candidate.get("enabled"))
    return ok(resp, code="GW_CONFIG_SAVED", request_id=request.state.request_id)


@router.post("/gw-config/apply", summary="按已存 gw-config 原地重启网关 worker（有 running job 则 409 拒绝）")
def gw_config_apply(request: Request, body: GwApplyBody):
    """按已保存的 gw-config 原地重启归档网关 worker（停止旧实例→重建→启动）。
    有运行中的网关 job 时拒绝（409），除非无活跃 job。LEVEL_2 + confirm。"""
    require_level("LEVEL_2")
    if not body.confirm:
        raise HTTPException(status_code=400, detail={
            "code": "INVALID_REQUEST", "message": "confirm=true required for gateway restart"})
    st = _restart_gateway(request.app, request.state.request_id)
    return ok(st, code="GW_RESTARTED" if st["running"] else "GW_STOPPED",
              request_id=request.state.request_id)


def _restart_gateway(app, request_id=""):
    """停止当前网关实例并按磁盘配置层重建。PG 不可达时网关保持停止并回报原因。"""
    jobs = getattr(app.state, "jobs", None)
    if jobs is not None:
        active = [j for j in jobs.list(status="running", limit=100)]
        if active:
            raise HTTPException(status_code=409, detail={
                "code": "GW_JOBS_RUNNING",
                "message": "gateway restart refused: %d job(s) running (%s); retry later"
                           % (len(active), ",".join(j["job_id"] for j in active[:5]))})
    old = getattr(app.state, "gateway", None)
    if old is not None:
        try:
            old.shutdown()
        except Exception:
            traceback.print_exc()
        app.state.gateway = None
    cfg = GatewayConfig()
    if not cfg.enabled:
        return {"running": False, "reason": "enabled=false in gw-config; gateway stopped",
                "config": cfg.summary()}
    try:
        gw = GatewayManager(cfg, runner=app.state.runner, chain=app.state.chain)
        gw.start()
        app.state.gateway = gw
        return {"running": True, "reason": "gateway restarted with gw-config", "config": cfg.summary()}
    except Exception as e:
        return {"running": False, "reason": "gateway start failed: %s" % e,
                "config": cfg.summary()}


@router.get("/stats")
def gw_stats(request: Request):
    require_level("LEVEL_1")
    gw = _gw(request)
    try:
        return ok(gw.stats(), request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


@router.get("/metrics")
def gw_metrics(request: Request):
    require_level("LEVEL_1")
    gw = _gw(request)
    return PlainTextResponse(gw.metrics_prom(), media_type="text/plain; version=0.0.4")


@router.post("/selfheal")
def gw_selfheal(request: Request):
    require_level("LEVEL_2")
    gw = _gw(request)
    try:
        return ok(gw._self_heal(), code="SELFHEAL_DONE", request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


@router.post("/evict")
def gw_evict(request: Request):
    require_level("LEVEL_2")
    gw = _gw(request)
    try:
        return ok(gw.enforce_watermarks(force=True), code="EVICTION_DONE",
                  request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


# ---------- files ----------
@router.post("/upload")
async def gw_upload(request: Request, file: UploadFile = File(...),
                    dir: str = Query(None, max_length=512,
                                     description="cache subdirectory (absolute path "
                                                "inside cache_dir, or relative)")):
    """Upload a file. Optional dir= places the cached copy under a user
    directory tree inside the cache root (name kept as-is, conflicts get a
    fid8 suffix); without it the legacy flat upload/ layout applies."""
    import hashlib
    require_level("LEVEL_2")
    gw = _gw(request)
    try:
        user_dir = gw.validate_user_dir(dir)
        safe = os.path.basename(file.filename or "unnamed")[:255] or "unnamed"
        tag = uuid.uuid4().hex[:8]
        if user_dir:
            dest_dir = gw.user_dir_abs(user_dir)
            os.makedirs(dest_dir, exist_ok=True)
            stored = safe
            dest = os.path.join(dest_dir, stored)
            if os.path.exists(dest):  # name conflict: keep original, add tag
                stem, ext = os.path.splitext(stored)
                stored = "%s.%s%s" % (stem, tag, ext)
                dest = os.path.join(dest_dir, stored)
        else:
            stored = "%s_%s" % (uuid.uuid4().hex[:12], safe)
            dest = os.path.join(gw.cfg.cache_dir, "upload", stored)
        h = hashlib.sha256()
        size = 0
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                h.update(chunk)
                size += len(chunk)
        res = gw.upload(dest, safe, size, sha256=h.hexdigest(),
                        content_type=file.content_type, origin="api",
                        user_dir=user_dir)
        code = "TAPE_ARCHIVE_QUEUED" if res["route"] == "tape" else "CONTAINER_BUFFERED"
        return ok(res, code=code, request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


@router.get("/files")
def gw_files(request: Request, name: str = None, state: str = None,
             limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    require_level("LEVEL_1")
    gw = _gw(request)
    try:
        rows = gw.db.find_files(name, limit=limit) if name else gw.db.list_files(
            state=state, limit=limit, offset=offset)
        return ok({"count": len(rows), "total": gw.db.count_files(
                       state=state, name_like=name),
                   "items": _files_view(gw, rows)},
                  request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


@router.get("/files/{file_id}")
def gw_file_get(request: Request, file_id: str):
    require_level("LEVEL_1")
    gw = _gw(request)
    try:
        res = gw.resolve(file_id)
        f = dict(res["file"])
        cont = dict(res["container"]) if res.get("container") else None
        mbc = (cont or {}).get("media_barcode") or f.get("media_barcode")
        tape_rec = gw.db.tape_get(mbc) if mbc else None
        location = _file_location(f, cont, res["hit"] in ("cache", "container_cache"))
        location["hit"] = res["hit"]
        location["mode"] = res.get("mode")
        location["available"] = res["hit"] != "none"
        location["needs_recall"] = res["hit"] == "tape"
        if res.get("reason"):
            location["reason"] = res["reason"]
        return ok({"hit": res["hit"], "mode": res.get("mode"), "file": f,
                   "block": dict(res["block"]) if res.get("block") else None,
                   "container": cont,
                   "tape": _tape_view(dict(tape_rec)) if tape_rec else None,
                   "location": location},
                  request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


@router.get("/files/{file_id}/download")
def gw_download(request: Request, file_id: str, full_container: bool = False,
                dir: str = Query(None, max_length=512,
                                 description="recall destination dir inside cache_dir")):
    require_level("LEVEL_1")
    gw = _gw(request)
    try:
        dest_dir = gw.recall_dest_dir(dir) if dir else None
        res = gw.resolve(file_id)
    except GatewayError as e:
        raise _http(e)
    if res["hit"] in ("cache", "container_cache"):
        try:
            path = gw.download(file_id, dest_dir,
                               force_full_container=full_container)
            return FileResponse(path, filename=os.path.basename(path),
                                media_type="application/octet-stream")
        except GatewayError as e:
            raise _http(e)

    # cold path: recall runs as an async job (progress + retries); the job
    # result carries the local path -- re-GET streams it from cache.
    def target():
        try:
            path = gw.recall_direct(file_id, dest_dir,
                                   force_full_container=full_container)
            return ok({"file_id": file_id, "path": path,
                       "hint": "recall complete; GET download again to stream"},
                      code="RECALLED", request_id=request.state.request_id)
        except GatewayError as e:
            raise _http(e)

    return submit_or_run(request, "gateway-recall", target)


# ---------- manual archive / recall ----------
@router.post("/files/{file_id}/archive")
def gw_file_archive(request: Request, file_id: str):
    """Manual archive: container member seals its container now; big file queues tape write."""
    require_level("LEVEL_2")
    gw = _gw(request)
    try:
        f = gw.db.get_file(file_id)
        if f is None:
            return fail("FILE_NOT_FOUND", "no such file",
                        request_id=request.state.request_id)
        if f["state"] not in ("cached", "failed"):
            return fail("INVALID_STATE",
                        "file state %s not archivable (cached/failed only)" % f["state"],
                        request_id=request.state.request_id)
        if f["storage"] == "container" and f.get("container_id"):
            cid = str(f["container_id"])
            if not gw.db.container_seal(cid):
                t = gw.db.task_find_active("archive_container", container_id=cid)
                if t:
                    return ok({"file_id": file_id, "route": "container",
                               "container_id": cid, "state": t["state"],
                               "task_id": t["task_id"]},
                              code="ARCHIVE_ALREADY_QUEUED",
                              request_id=request.state.request_id)
                return fail("INVALID_STATE", "container not buffering; nothing to do",
                            request_id=request.state.request_id)
            return ok({"file_id": file_id, "route": "container", "container_id": cid,
                       "state": "flush-due"}, code="CONTAINER_SEALED",
                      request_id=request.state.request_id)
        t = gw.db.task_find_active("archive_file", file_id=file_id)
        if t:
            return ok({"file_id": file_id, "route": "tape", "state": t["state"],
                       "task_id": t["task_id"]}, code="ARCHIVE_ALREADY_QUEUED",
                      request_id=request.state.request_id)
        tid = gw.db.task_create("archive_file", {"file_id": f["file_id"]},
                                file_id=f["file_id"])
        if f["state"] == "failed":
            with gw.db.conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE file_meta SET state='cached', error=NULL "
                                "WHERE file_id=%s", (f["file_id"],))
        return ok({"file_id": file_id, "route": "tape", "state": "queued",
                   "task_id": tid}, code="TAPE_ARCHIVE_QUEUED",
                  request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


@router.post("/files/{file_id}/recall")
def gw_file_recall(request: Request, file_id: str,
                   dir: str = Query(None, max_length=512)):
    """Recall file data from tape into the local cache (async job on cold path).
    Optional dir= selects the recall destination inside cache_dir; default
    restores the file under its original directory-tree path when known."""
    require_level("LEVEL_2")
    gw = _gw(request)
    try:
        dest_dir = gw.recall_dest_dir(dir) if dir else None
        res = gw.resolve(file_id)
    except GatewayError as e:
        raise _http(e)
    if res["hit"] in ("cache", "container_cache"):
        try:
            path = gw.download(file_id, dest_dir)
            return ok({"file_id": file_id, "state": "cached_local", "path": path},
                      code="RECALL_HIT", request_id=request.state.request_id)
        except GatewayError as e:
            raise _http(e)

    def target():
        try:
            path = gw.recall_direct(file_id, dest_dir)
            return ok({"file_id": file_id, "path": path,
                       "hint": "recall complete; data now on disk"},
                      code="RECALLED", request_id=request.state.request_id)
        except GatewayError as e:
            raise _http(e)

    return submit_or_run(request, "gateway-recall", target)


# ---------- cache ----------
@router.get("/cache")
def gw_cache(request: Request, kind: str = None, dirty: bool = None,
             limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0)):
    """Cache entries + per-directory usage for the cache management page."""
    require_level("LEVEL_1")
    gw = _gw(request)
    try:
        st = gw.stats()
        rows = gw.db.cache_list(kind=kind, dirty=dirty, limit=limit, offset=offset)
        # per-directory usage over the whole cache tree (any depth)
        dirs = {}
        for root, _d, files in os.walk(gw.cfg.cache_dir):
            rel = os.path.relpath(root, gw.cfg.cache_dir)
            used = 0
            for fn in files:
                try:
                    used += os.path.getsize(os.path.join(root, fn))
                except OSError:
                    pass
            if used or rel != ".":
                dirs[rel.replace(os.sep, "/")] = used
        dir_items = [{"dir": d, "path": os.path.join(gw.cfg.cache_dir, d),
                      "used_bytes": v}
                     for d, v in sorted(dirs.items()) if d != "."]
        return ok({"stats": st["cache"], "config": {"cache_dir": gw.cfg.cache_dir,
                   "quota_bytes": gw.cfg.cache_quota_bytes,
                   "watermarks_pct": [gw.cfg.low_watermark_pct,
                                       gw.cfg.high_watermark_pct]},
                   "dirs": dir_items, "count": len(rows),
                   "items": [dict(r) for r in rows]},
                  request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


# ---------- cache tree ----------
@router.get("/tree")
def gw_tree(request: Request):
    """Cache directory tree with per-file metadata correlation.

    Walks the cache dir (upload/containers/recall), then joins each on-disk
    file with file_meta/container_meta/gw_block/tape_media + recall counts so
    the UI can show size/state/archive-recall status/tape placement in one
    round trip."""
    require_level("LEVEL_1")
    gw = _gw(request)
    try:
        files, containers, blocks, media, recalls = gw.db.tree_index()
        by_cache_path = {f["cache_path"]: f for f in files if f.get("cache_path")}
        by_rel_path = {f["cache_rel_path"]: f for f in files if f.get("cache_rel_path")}
        by_id = {str(f["file_id"]): f for f in files}
        c_by_id = {str(c["container_id"]): c for c in containers}
        blocks_by_obj = {}
        for b in blocks:
            blocks_by_obj.setdefault(str(b["object_id"]), []).append(dict(b))
        media_by_bc = {m["barcode"]: dict(m) for m in media}
        recall_by_fid = {str(r["file_id"]): {"n": r["n"], "last": r["last_ts"]}
                         for r in recalls}

        def meta_for_file(fname, rel_path, size):
            """Correlate an on-disk entry with metadata; safe-miss -> None."""
            row = by_rel_path.get(rel_path) or by_cache_path.get(rel_path)
            if row is None:
                # containers/<uuid>.tar / recall/<name> matches
                import re as _re
                m = _re.match(r"containers/([0-9a-f-]{36})\.tar$", rel_path)
                if m:
                    c = c_by_id.get(m.group(1))
                    if c:
                        bl = blocks_by_obj.get(m.group(1), [])
                        bc = media_by_bc.get(c.get("media_barcode")) or {}
                        return {"type": "container", "container": _c_view(c, bc, bl)}
                    return {"type": "container", "container": None}
                # recall/<name>: match by filename among files with same name
                nm = os.path.basename(rel_path)
                cands = [f for f in files if f["filename"] == nm]
                if len(cands) == 1:
                    row = cands[0]
                elif not cands:
                    return None
            if row is None:
                return None
            return {"type": "file", "file": _f_view(row, c_by_id, blocks_by_obj,
                                                   media_by_bc, recall_by_fid)}

        def _f_view(f, c_by_id, blocks_by_obj, media_by_bc, recall_by_fid):
            fid = str(f["file_id"])
            c = c_by_id.get(str(f.get("container_id"))) if f.get("container_id") else None
            bl = blocks_by_obj.get(fid, [])
            mbc = (c or {}).get("media_barcode") or f.get("media_barcode")
            bc = media_by_bc.get(mbc) or {}
            rc = recall_by_fid.get(fid)
            return {
                "file_id": fid, "filename": f["filename"],
                "size_bytes": f["size_bytes"], "sha256": f.get("sha256"),
                "kind": f["kind"], "state": f["state"], "storage": f["storage"],
                "container_id": str(f["container_id"]) if f.get("container_id") else None,
                "offset_in_container": f.get("file_offset_in_container"),
                "media_barcode": mbc,
                "tape_block_index": f.get("tape_block_index")
                                    or (c or {}).get("tape_block_index"),
                "tape": _tape_view(bc) if bc else None,
                "recalls": rc or {"n": 0, "last": None},
                "archived_at": f.get("archived_at"),
                "created_at": f.get("created_at"),
                "last_access_at": f.get("last_access_at"),
                "error": f.get("error"),
            }

        def _c_view(c, bc, bl):
            return {
                "container_id": str(c["container_id"]), "state": c["state"],
                "size_bytes": c["size_bytes"], "file_count": c["file_count"],
                "media_barcode": c.get("media_barcode"),
                "tape_block_index": c.get("tape_block_index"),
                "offset_on_tape": c.get("offset_in_tape"),
                "length_on_tape": c.get("length_on_tape"),
                "archive_sha256": c.get("archive_sha256"),
                "members": [str(f["file_id"]) for f in files
                            if str(f.get("container_id")) == str(c["container_id"])],
                "tape": _tape_view(bc) if bc else None,
                "blocks": bl, "error": c.get("error"),
                "archived_at": c.get("archived_at"), "created_at": c.get("created_at"),
            }

        def _tape_view(bc):
            return {
                "barcode": bc.get("barcode"), "state": bc.get("state"),
                "format": bc.get("format") or "raw",
                "capacity_bytes": bc.get("capacity_bytes"),
                "used_bytes": bc.get("used_bytes"),
                "used_pct": round(float(bc["used_bytes"]) * 100
                                  / max(int(bc["capacity_bytes"]), 1), 1)
                if bc.get("capacity_bytes") else None,
                "block_records": bc.get("block_records"),
                "last_filemark": bc.get("last_filemark"),
                "mount_count": bc.get("mount_count"),
            }

        root = {"name": os.path.basename(gw.cfg.cache_dir) or "archive-cache",
                "path": gw.cfg.cache_dir, "type": "dir", "size_bytes": 0,
                "children": []}
        dir_nodes = {"": root}

        def dir_node(rel):
            """Get-or-create a nested directory node by '/'-separated rel path."""
            if rel in dir_nodes:
                return dir_nodes[rel]
            parent_rel, _, name = rel.rpartition("/")
            parent = dir_node(parent_rel)
            node = {"name": name, "path": os.path.join(gw.cfg.cache_dir, rel),
                    "type": "dir", "size_bytes": 0, "children": []}
            parent["children"].append(node)
            dir_nodes[rel] = node
            return node

        present = set()
        total_files = 0
        orphans = 0
        for cur_dir, _subs, fnames in os.walk(gw.cfg.cache_dir):
            rel_dir = os.path.relpath(cur_dir, gw.cfg.cache_dir)
            rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
            node = dir_node(rel_dir)
            for fn in sorted(fnames):
                fp = os.path.join(cur_dir, fn)
                try:
                    sz = os.path.getsize(fp)
                except OSError:
                    continue
                present.add(fp)
                rel = "%s/%s" % (rel_dir, fn) if rel_dir else fn
                meta = meta_for_file(fn, rel, sz)
                if meta is None:
                    orphans += 1
                node["children"].append({
                    "name": fn, "path": fp, "type": "file", "size_bytes": sz,
                    "meta": meta})
                node["size_bytes"] += sz
                total_files += 1

        # virtual nodes: sealed members whose bytes now live inside a
        # container tar / on tape still appear under their member_path
        virtual_count = 0
        seen_virt = set()
        for f in files:
            mp = f.get("member_path")
            if not mp or mp in seen_virt:
                continue
            if f.get("cache_path") and f["cache_path"] in present:
                continue  # physical copy already listed
            seen_virt.add(mp)
            drel, _, name = mp.rpartition("/")
            vnode = dir_node(drel)
            vnode["children"].append({
                "name": name, "path": os.path.join(gw.cfg.cache_dir, mp),
                "type": "member", "size_bytes": f["size_bytes"],
                "meta": {"type": "file", "file": _f_view(f, c_by_id, blocks_by_obj,
                                                         media_by_bc, recall_by_fid)}})
            virtual_count += 1

        def _roll(n):
            if n["type"] != "dir":
                return n["size_bytes"] if n["type"] == "file" else 0
            n["size_bytes"] = sum(_roll(c) for c in n["children"])
            n["children"].sort(key=lambda c: (c["type"] != "dir", c["name"]))
            return n["size_bytes"]
        _roll(root)

        return ok({"root": root, "file_count": total_files,
                   "virtual_count": virtual_count,
                   "unmatched": orphans,
                   "meta_counts": {"files": len(files), "containers": len(containers),
                                   "blocks": len(blocks), "media": len(media)}},
                  request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


# ---------- containers ----------
@router.get("/containers")
def gw_containers(request: Request, state: str = None,
                  limit: int = Query(50, ge=1, le=500)):
    require_level("LEVEL_1")
    gw = _gw(request)
    try:
        rows = gw.db.container_list(state=state, limit=limit)
        return ok({"count": len(rows), "items": [dict(r) for r in rows]},
                  request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


@router.get("/containers/{container_id}")
def gw_container_get(request: Request, container_id: str):
    require_level("LEVEL_1")
    gw = _gw(request)
    try:
        cont = gw.db.container_get(container_id)
        if cont is None:
            return fail("NOT_FOUND", "no such container",
                        request_id=request.state.request_id)
        files = gw.db.container_files(container_id)
        return ok({"container": dict(cont),
                   "files": [{k: f[k] for k in ("file_id", "filename", "size_bytes",
                                                "state", "file_offset_in_container")}
                             for f in files]},
                  request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


@router.post("/containers/{container_id}/seal")
def gw_container_seal(request: Request, container_id: str):
    require_level("LEVEL_2")
    gw = _gw(request)
    try:
        if not gw.db.container_seal(container_id):
            return fail("INVALID_STATE", "container not buffering",
                        request_id=request.state.request_id)
        return ok({"container_id": container_id, "state": "flush-due"},
                  code="CONTAINER_SEALED", request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


@router.post("/containers/{container_id}/retry")
def gw_container_retry(request: Request, container_id: str):
    """Revive an aborted/failed container: requeue archive from cached tar."""
    require_level("LEVEL_2")
    gw = _gw(request)
    try:
        cont = gw.db.container_get(container_id)
        if cont is None:
            return fail("NOT_FOUND", "no such container",
                        request_id=request.state.request_id)
        tar_path = os.path.join(gw.cfg.cache_dir, "containers",
                                "%s.tar" % container_id)
        if cont["state"] not in ("aborted", "flushing", "archiving"):
            return fail("INVALID_STATE", "container state %s not retryable"
                        % cont["state"], request_id=request.state.request_id)
        if not os.path.isfile(tar_path):
            return fail("TAR_MISSING", "cached tar gone; cannot retry archive",
                        request_id=request.state.request_id)
        with gw.db.conn() as conn:
            gw.db.container_update(conn, container_id, state="flushing", error=None)
        tid = gw.db.task_create("archive_container", {"container_id": container_id},
                                container_id=container_id)
        return ok({"container_id": container_id, "state": "flushing",
                   "task_id": tid}, code="CONTAINER_REQUEUED",
                  request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


# ---------- media ----------
@router.get("/media")
def gw_media(request: Request):
    require_level("LEVEL_1")
    gw = _gw(request)
    try:
        rows = gw.db.tape_list()
        return ok({"count": len(rows), "items": [dict(r) for r in rows]},
                  request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


@router.post("/media")
def gw_media_register(request: Request, body: MediaRegister):
    require_level("LEVEL_2")
    gw = _gw(request)
    try:
        gw.db.tape_upsert(body.barcode, state=body.state, format=body.format)
        return ok({"barcode": body.barcode, "state": body.state,
                   "format": body.format}, code="MEDIA_REGISTERED",
                  request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


@router.post("/media/{barcode}/format",
             summary="介质格式化（销毁性）：mkltfs 转 LTFS，抹除介质全部数据")
def gw_media_format(request: Request, barcode: str, body: MediaFormatBody):
    """mkltfs 将介质格式化为 LTFS——销毁性操作，抹掉介质上全部数据。
    LEVEL_3 + confirm=true 必需；介质已有数据（gw_block 记录或 used_bytes>0）
    时还须 force=true。执行前回读台账并复述条码。"""
    require_level("LEVEL_3")
    gw = _gw(request)
    if not body.confirm:
        raise HTTPException(status_code=400, detail={
            "code": "INVALID_REQUEST",
            "message": "confirm=true required (mkltfs erases the whole media)"})
    if body.format != "ltfs":
        return fail("UNSUPPORTED",
                    "only formatting TO ltfs is supported; raw media needs no format "
                    "(first write bootstraps the filemark index)",
                    request_id=request.state.request_id)
    try:
        m = gw.db.tape_get(barcode)
        if m is None:
            return fail("MEDIA_NOT_FOUND",
                        "barcode %s not registered; POST /archive/media first" % barcode,
                        request_id=request.state.request_id)
        used_blocks = next((b["blocks"] for b in gw.db.block_stats()
                            if b["barcode"] == barcode), 0)
        if (used_blocks > 0 or int(m.get("used_bytes") or 0) > 0) and not body.force:
            raise HTTPException(status_code=409, detail={
                "code": "MEDIA_NOT_EMPTY",
                "message": "media %s carries %d block records / %d bytes; "
                           "force=true required to erase"
                           % (barcode, used_blocks, int(m.get("used_bytes") or 0))})
        res = gw.tape.backends["ltfs"].format_media(barcode)
        with gw.db.conn() as conn:
            gw.db.tape_format_reset(conn, barcode, "ltfs")
        return ok({"barcode": barcode, "format": "ltfs", "state": "appendable",
                   "erased_media": barcode, "mkltfs": res["output"]},
                  code="MEDIA_FORMATTED", request_id=request.state.request_id)
    except TapeError as e:
        raise _tape_err(e)
    except GatewayError as e:
        raise _http(e)


# ---------- LTFS ----------
@router.get("/ltfs/status", summary="LTFS 栈与会话健康：二进制/挂载点/租约状态")
def gw_ltfs_status(request: Request):
    require_level("LEVEL_1")
    gw = _gw(request)
    try:
        return ok(gw.tape.backends["ltfs"].status(),
                  request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


@router.post("/ltfs/{barcode}/check",
             summary="对介质运行 ltfsck 一致性检查（LEVEL_2，会装载介质）")
def gw_ltfs_check(request: Request, barcode: str):
    require_level("LEVEL_2")
    gw = _gw(request)
    try:
        m = gw.db.tape_get(barcode)
        if m is None:
            return fail("MEDIA_NOT_FOUND", "barcode %s not registered" % barcode,
                        request_id=request.state.request_id)
        res = gw.tape.backends["ltfs"].check_media(barcode)
        return ok(res, code="LTFS_CHECK_DONE" if res["clean"] else "LTFS_CHECK_DIRTY",
                  request_id=request.state.request_id)
    except TapeError as e:
        raise _tape_err(e)
    except GatewayError as e:
        raise _http(e)


# ---------- tasks ----------
@router.get("/tasks")
def gw_tasks(request: Request, kind: str = None, state: str = None,
             limit: int = Query(50, ge=1, le=500)):
    require_level("LEVEL_1")
    gw = _gw(request)
    try:
        rows = gw.db.task_list(kind=kind, state=state, limit=limit)
        return ok({"count": len(rows), "items": [dict(r) for r in rows]},
                  request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)


@router.get("/tasks/{task_id}")
def gw_task_get(request: Request, task_id: str):
    require_level("LEVEL_1")
    gw = _gw(request)
    try:
        t = gw.db.task_get(task_id)
        if t is None:
            return fail("TASK_NOT_FOUND", "no such task",
                        request_id=request.state.request_id)
        return ok(dict(t), request_id=request.state.request_id)
    except GatewayError as e:
        raise _http(e)
