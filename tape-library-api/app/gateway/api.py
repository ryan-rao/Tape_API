"""Archive gateway HTTP API, mounted under /api/v1/archive."""
import hashlib
import os
import uuid

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app.models.common import fail, ok
from app.security.policy import require_level
from app.api.routes import submit_or_run

from .manager import GatewayError


def _http(e: GatewayError):
    return HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message})


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


def _tape_view(bc):
    """Tape storage info (barcode/state/capacity/usage/blocks) for responses."""
    if not bc:
        return None
    cap = int(bc.get("capacity_bytes") or 0)
    used = int(bc.get("used_bytes") or 0)
    return {
        "barcode": bc.get("barcode"), "state": bc.get("state"),
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
async def gw_upload(request: Request, file: UploadFile = File(...)):
    require_level("LEVEL_2")
    gw = _gw(request)
    try:
        safe = os.path.basename(file.filename or "unnamed")[:255] or "unnamed"
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
                        content_type=file.content_type, origin="api")
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
def gw_download(request: Request, file_id: str, full_container: bool = False):
    require_level("LEVEL_1")
    gw = _gw(request)
    recall_dir = os.path.join(gw.cfg.cache_dir, "recall")
    try:
        res = gw.resolve(file_id)
    except GatewayError as e:
        raise _http(e)
    if res["hit"] in ("cache", "container_cache"):
        try:
            path = gw.download(file_id, recall_dir,
                               force_full_container=full_container)
            return FileResponse(path, filename=os.path.basename(path),
                                media_type="application/octet-stream")
        except GatewayError as e:
            raise _http(e)

    # cold path: recall runs as an async job (progress + retries); the job
    # result carries the local path -- re-GET streams it from cache.
    def target():
        try:
            path = gw.recall_direct(file_id, recall_dir,
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
        cache_key = ("upload/%s" % os.path.basename(f["cache_path"])
                     if f.get("cache_path") else None)
        t = gw.db.task_find_active("archive_file", file_id=file_id)
        if t:
            return ok({"file_id": file_id, "route": "tape", "state": t["state"],
                       "task_id": t["task_id"]}, code="ARCHIVE_ALREADY_QUEUED",
                      request_id=request.state.request_id)
        tid = gw.db.task_create("archive_file",
                                {"file_id": f["file_id"], "cache_key": cache_key},
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
def gw_file_recall(request: Request, file_id: str):
    """Recall file data from tape into the local cache (async job on cold path)."""
    require_level("LEVEL_2")
    gw = _gw(request)
    recall_dir = os.path.join(gw.cfg.cache_dir, "recall")
    try:
        res = gw.resolve(file_id)
    except GatewayError as e:
        raise _http(e)
    if res["hit"] in ("cache", "container_cache"):
        try:
            path = gw.download(file_id, recall_dir)
            return ok({"file_id": file_id, "state": "cached_local", "path": path},
                      code="RECALL_HIT", request_id=request.state.request_id)
        except GatewayError as e:
            raise _http(e)

    def target():
        try:
            path = gw.recall_direct(file_id, recall_dir)
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
        dirs = []
        for sub in ("upload", "containers", "recall"):
            d = os.path.join(gw.cfg.cache_dir, sub)
            used = 0
            try:
                for fn in os.listdir(d):
                    try:
                        used += os.path.getsize(os.path.join(d, fn))
                    except OSError:
                        pass
            except OSError:
                pass
            dirs.append({"dir": sub, "path": d, "used_bytes": used})
        return ok({"stats": st["cache"], "config": {"cache_dir": gw.cfg.cache_dir,
                   "quota_bytes": gw.cfg.cache_quota_bytes,
                   "watermarks_pct": [gw.cfg.low_watermark_pct,
                                       gw.cfg.high_watermark_pct]},
                   "dirs": dirs, "count": len(rows),
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
            row = by_cache_path.get(rel_path)
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
                "capacity_bytes": bc.get("capacity_bytes"),
                "used_bytes": bc.get("used_bytes"),
                "used_pct": round(float(bc["used_bytes"]) * 100
                                  / max(int(bc["capacity_bytes"]), 1), 1)
                if bc.get("capacity_bytes") else None,
                "block_records": bc.get("block_records"),
                "last_filemark": bc.get("last_filemark"),
                "mount_count": bc.get("mount_count"),
            }

        tree = {"name": os.path.basename(gw.cfg.cache_dir) or "archive-cache",
                "path": gw.cfg.cache_dir, "type": "dir", "size_bytes": 0,
                "children": []}
        total_files = 0
        orphans = 0
        for sub in ("upload", "containers", "recall"):
            dpath = os.path.join(gw.cfg.cache_dir, sub)
            node = {"name": sub, "path": dpath, "type": "dir", "size_bytes": 0,
                    "children": []}
            try:
                for fn in sorted(os.listdir(dpath)):
                    fp = os.path.join(dpath, fn)
                    try:
                        sz = os.path.getsize(fp)
                    except OSError:
                        continue
                    rel = "%s/%s" % (sub, fn)
                    meta = meta_for_file(fn, rel, sz)
                    if meta is None:
                        orphans += 1
                    node["children"].append({
                        "name": fn, "path": fp, "type": "file", "size_bytes": sz,
                        "meta": meta})
                    node["size_bytes"] += sz
                    total_files += 1
                tree["children"].append(node)
                tree["size_bytes"] += node["size_bytes"]
            except OSError:
                continue
        return ok({"root": tree, "file_count": total_files,
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
        gw.db.tape_upsert(body.barcode, state=body.state)
        return ok({"barcode": body.barcode, "state": body.state}, code="MEDIA_REGISTERED",
                  request_id=request.state.request_id)
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
