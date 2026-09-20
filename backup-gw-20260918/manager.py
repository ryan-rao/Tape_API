"""Gateway manager: the unified brain over metadata + cache + tape.

Responsibilities:
- upload/download entry points (big-file direct tape vs small-file container)
- container lifecycle state machine (buffering -> flushing -> archiving -> archived)
- async task workers (archive_file / archive_container / recall_file)
- LRU watermark eviction loop (clean-only, pinned-refcount aware)
- restart self-healing (rescan cache, requeue stuck states)
- prometheus-style /metrics export
"""
import datetime
import os
import threading
import time
import traceback

from . import container as cfmt
from .config import GatewayConfig
from .metadata import MetadataDB, new_id
from .tapeio import TapeEngine, TapeError


class GatewayError(Exception):
    def __init__(self, code, message, status=400):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


def _fmt_ts(dt):
    if dt is None:
        return None
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)


class GatewayManager:
    def __init__(self, cfg: GatewayConfig = None, runner=None, chain=None):
        self.cfg = cfg or GatewayConfig()
        self.runner = runner
        self.chain = chain
        self.db = MetadataDB(self.cfg)
        self.tape = None
        self._stop = threading.Event()
        self._threads = []
        self._metrics_lock = threading.Lock()
        self._metrics = {"bytes_to_tape": 0, "bytes_from_tape": 0, "mounts": 0,
                         "evictions": 0, "evicted_bytes": 0, "recall_hits": 0,
                         "recall_misses": 0, "errors": 0}
        self._shutting_down = False

    # ================= lifecycle =================
    def start(self):
        os.makedirs(os.path.join(self.cfg.cache_dir, "upload"), exist_ok=True)
        os.makedirs(os.path.join(self.cfg.cache_dir, "containers"), exist_ok=True)
        os.makedirs(os.path.join(self.cfg.cache_dir, "recall"), exist_ok=True)
        self.db.connect()
        self.tape = TapeEngine(self.runner, self.chain, self.cfg, self.db)
        self._self_heal()
        for name, target, interval in (
                ("flusher", self._flush_loop, self.cfg.poll_interval_s),
                ("archiver", self._archive_loop, self.cfg.poll_interval_s),
                ("recaller", self._recall_loop, self.cfg.poll_interval_s),
                ("evictor", self._evict_loop, self.cfg.evict_interval_s)):
            t = threading.Thread(target=self._loop_wrapper, args=(name, target, interval),
                                 name="gw-%s" % name, daemon=True)
            t.start()
            self._threads.append(t)

    def shutdown(self):
        self._shutting_down = True
        self._stop.set()
        for t in self._threads:
            t.join(timeout=10)
        self.db.close()

    def _loop_wrapper(self, name, target, interval):
        while not self._stop.is_set():
            try:
                target()
            except Exception as e:  # never die
                self._bump("errors")
                traceback.print_exc()
            self._stop.wait(interval)

    # ================= restart self-healing =================
    def _self_heal(self):
        """Reconcile cache dir <-> cache_entry, drop dead rows, requeue stuck states."""
        moved, dropped, requeued = 0, 0, 0
        known_dirs = {"upload", "containers", "recall"}
        db_keys = self.db.cache_all_keys() if self._db_alive() else set()
        # 1) filesystem -> DB
        for sub in ("upload", "containers"):
            d = os.path.join(self.cfg.cache_dir, sub)
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                p = os.path.join(d, fn)
                if not os.path.isfile(p):
                    continue
                key = "%s/%s" % (sub, fn)
                if key in db_keys:
                    continue
                moved += 1
                if sub == "upload":
                    self._adopt_orphan_upload(p, fn)
                else:
                    os.remove(p)  # stale container temp from a crashed flush
        # 2) DB -> filesystem
        for key in list(db_keys):
            ent = self.db.cache_get(key)
            if ent and not os.path.isfile(ent["path"]):
                dropped += 1
                self.db.cache_delete(key)
        # 3) requeue stuck task/object states
        if self._db_alive():
            requeued += self.db.self_heal_states()
        return {"adopted_uploads": moved, "dropped_entries": dropped,
                "requeued_states": requeued}

    def _db_alive(self):
        try:
            return self.db.pool is not None
        except Exception:
            return False

    def _adopt_orphan_upload(self, path, fn):
        """Cache file present but no DB row: register as failed-unknown for manual triage."""
        try:
            size = os.path.getsize(path)
            with self.db.conn() as conn:
                fid = new_id()
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO file_meta (file_id, filename, size_bytes, state,"
                        " storage, cache_path, created_at, last_access_at, error)"
                        " VALUES (%s,%s,%s,'failed','cache',%s,now(),now(),%s)",
                        (fid, "orphan/" + fn, size, path, "orphan found on restart"))
                    cur.execute(
                        "INSERT INTO cache_entry (cache_key, kind, object_id, path,"
                        " size_bytes, dirty) VALUES (%s,'file',%s,%s,%s,true)"
                        " ON CONFLICT (cache_key) DO NOTHING",
                        ("upload/" + fn, fid, path, size))
        except Exception:
            traceback.print_exc()

    # ================= upload / download =================
    def upload(self, src_path, filename, size, sha256=None, content_type=None,
               origin="api"):
        """Route a freshly cached upload into big-file or container path."""
        limit = self.cfg.small_file_mb * 1024 * 1024
        now = datetime.datetime.now(datetime.timezone.utc)
        if size > limit:
            fid = self.db.insert_file(filename, size, sha256, content_type, origin,
                                      kind="file", storage="cache",
                                      cache_path=src_path)
            self.db.cache_upsert("upload/" + os.path.basename(src_path),
                                 "file", fid, src_path, size, dirty=True)
            tid = self.db.task_create("archive_file", {"file_id": fid,
                                                       "cache_key": "upload/" + os.path.basename(src_path)},
                                      file_id=fid)
            return {"file_id": fid, "route": "tape", "task_id": tid, "state": "queued"}
        # small file -> active container
        row = self.db.container_get_active()
        if row is None:
            cid = self.db.container_create(now + datetime.timedelta(seconds=self.cfg.container_flush_s))
            row = self.db.container_get(cid)
        cid = row["container_id"]
        if (row["size_bytes"] + size > self.cfg.container_target_bytes
                or row["file_count"] >= self.cfg.container_max_files):
            # capacity/file-count cap reached: seal it, open a new one
            self.db.container_seal(cid)
            cid = self.db.container_create(now + datetime.timedelta(seconds=self.cfg.container_flush_s))
        fid = new_id()
        with self.db.conn() as conn:
            self.db.ensure_month_partition(conn, now)
            offset = self.db.container_current_offset(conn, cid)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO file_meta (file_id, filename, size_bytes, sha256,
                       content_type, origin, kind, state, storage, cache_path,
                       container_id, file_offset_in_container, created_at, last_access_at)
                       VALUES (%s,%s,%s,%s,%s,%s,'container_member','cached','container',%s,%s,%s,now(),now())""",
                    (fid, filename, size, sha256, content_type, origin, src_path,
                     cid, offset))
            self.db.container_bump_size(conn, cid, size)
        self.db.cache_upsert("upload/" + os.path.basename(src_path), "file", fid,
                             src_path, size, dirty=True)
        return {"file_id": fid, "route": "container", "container_id": str(cid),
                "offset_in_container": offset, "state": "buffering"}

    def resolve(self, file_id):
        """Unified addressing: file -> (cache_path | tape location descriptor)."""
        f = self.db.get_file(file_id)
        if f is None:
            raise GatewayError("FILE_NOT_FOUND", "no such file", status=404)
        entry = self.db.cache_get("upload/" + os.path.basename(f["cache_path"])) \
            if f["cache_path"] else None
        if entry and os.path.isfile(entry["path"]):
            self.db.touch_files([f["file_id"]])
            return {"hit": "cache", "path": entry["path"], "file": f}
        if f["storage"] == "container":
            cont = self.db.container_get(f["container_id"])
            centry = self.db.cache_get("containers/%s.tar" % f["container_id"])
            if centry and os.path.isfile(centry["path"]):
                return {"hit": "container_cache", "container_path": centry["path"], "file": f}
            blk = self.db.block_lookup(cont["media_barcode"], f["container_id"]) \
                if cont and cont.get("media_barcode") else self.db.block_lookup_any(f["container_id"])
            if blk is None:
                return {"hit": "none", "file": f,
                        "reason": "container not yet archived and no cached copy"}
            return {"hit": "tape", "mode": "member",
                    "container": cont, "file": f, "block": blk}
        if f["storage"] == "tape":
            blk = self.db.block_lookup_any(f["file_id"])
            return {"hit": "tape", "mode": "file", "file": f, "block": blk,
                    "container": None}
        # storage == 'cache' but cache file gone -> nothing recallable yet
        return {"hit": "none", "file": f,
                "reason": "cache entry missing; archive still pending"}

    def download(self, file_id, dest_dir, force_full_container=False):
        """Recall one file. Returns absolute local path."""
        res = self.resolve(file_id)
        f = res["file"]
        os.makedirs(dest_dir, exist_ok=True)
        if res["hit"] in ("cache",):
            self._bump("recall_hits")
            return res["path"]
        if res["hit"] == "container_cache":
            out = os.path.join(dest_dir, "%s.part" % f["file_id"])
            cfmt.extract_member(res["container_path"], f["filename"], out)
            final = os.path.join(dest_dir, os.path.basename(f["filename"]))
            os.replace(out, final)
            self._recall_done(f, cache_hit=True)
            self._remember_recalled_member(f, final)
            self._bump("recall_hits")
            return final
        if res["hit"] == "none":
            raise GatewayError("FILE_NOT_READY",
                               "file %s not yet on tape and no cached copy (still buffering "
                               "or cache evicted before archive)" % file_id, status=409)
        # tape path (async callers use recall_direct inside a job thread)
        return self.download_tape(file_id, dest_dir, force_full_container)

    def download_tape(self, file_id, dest_dir, force_full_container=False):
        heat = 0
        f = self.db.get_file(file_id)
        if f is None:
            raise GatewayError("FILE_NOT_FOUND", "no such file", status=404)
        if f["storage"] == "container":
            heat = self.db.recall_container_heat(f["container_id"],
                                                 self.cfg.recall_hot_window_s)
        full = force_full_container or (
            f["storage"] == "container" and heat >= self.cfg.recall_hot_threshold)
        self._bump("recall_misses")
        tid = self.db.task_create(
            "recall_file",
            {"file_id": f["file_id"], "dest_dir": dest_dir, "full_container": full},
            file_id=f["file_id"])
        return self._run_recall_sync(tid)

    def recall_direct(self, file_id, dest_dir, force_full_container=False):
        """Synchronous recall used inside job threads (no nested task creation)."""
        f = self.db.get_file(file_id)
        if f is None:
            raise GatewayError("FILE_NOT_FOUND", "no such file", status=404)
        heat = self.db.recall_container_heat(f["container_id"],
                                             self.cfg.recall_hot_window_s) \
            if f["storage"] == "container" else 0
        full = force_full_container or (
            f["storage"] == "container" and heat >= self.cfg.recall_hot_threshold)
        self._bump("recall_misses")
        task = {"task_id": "inline-%s" % new_id()[:8], "attempts": 1,
                "payload": {"file_id": f["file_id"], "dest_dir": dest_dir,
                            "full_container": full}}
        try:
            res = self._run_recall(task)
            return res.get("path")
        except GatewayError:
            raise
        except Exception as e:
            raise GatewayError("RECALL_FAILED", str(e)[:300], status=502)

    def _recall_done(self, f, cache_hit=False):
        self.db.touch_files([f["file_id"]])
        if f.get("container_id"):
            self.db.recall_log(f["file_id"], f["container_id"])

    def _remember_recalled_member(self, f, local_path):
        """Cache a recalled container member as a clean entry (repeat downloads hit cache)."""
        try:
            size = os.path.getsize(local_path)
            key = "upload/%s" % os.path.basename(local_path)
            with self.db.conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE file_meta SET cache_path=%s WHERE file_id=%s",
                                (local_path, str(f["file_id"])))
            self.db.cache_upsert(key, "file", f["file_id"], local_path, size, dirty=False)
        except Exception:
            traceback.print_exc()

    # ================= background loops =================
    def _flush_loop(self):
        """Seal buffering containers by size/time; enqueue archive_container tasks."""
        now = datetime.datetime.now(datetime.timezone.utc)
        for c in self.db.container_ready(self.cfg.container_target_bytes, now, limit=4):
            try:
                self._flush_container(c["container_id"])
            except Exception as e:
                self._bump("errors")
                with self.db.conn() as conn:
                    self.db.container_update(conn, c["container_id"], state="buffering",
                                             error=str(e)[:300])

    def _flush_container(self, cid):
        cid = str(cid)
        cont = self.db.container_get(cid)
        if cont is None or cont["state"] != "buffering":
            return
        files = self.db.container_files(cid, order_by_offset=True)
        if not files:
            with self.db.conn() as conn:
                self.db.container_update(conn, cid, state="aborted",
                                         error="empty container sealed")
            self.db.cache_delete("containers/%s.tar" % cid)
            return
        pairs = [(f["cache_path"], f["filename"]) for f in files]
        tar_path = os.path.join(self.cfg.cache_dir, "containers", "%s.tar" % cid)
        sha, size = cfmt.write_container(pairs, tar_path)
        with self.db.conn() as conn:
            self.db.container_update(conn, cid, state="flushing",
                                     size_bytes=size, archive_sha256=sha)
            self.db.cache_upsert("containers/%s.tar" % cid, "container", cid,
                                 tar_path, size, dirty=True)
            for f in files:  # raw members now live inside the container
                self.db.cache_delete("upload/%s" % os.path.basename(f["cache_path"]))
        for f in files:
            try:
                os.remove(f["cache_path"])
            except OSError:
                pass
        self.db.task_create("archive_container", {"container_id": cid}, container_id=cid)

    # ---------- archive workers ----------
    def _archive_loop(self):
        for kind in ("archive_file", "archive_container"):
            while True:
                task = self.db.task_claim(kind)
                if not task:
                    break
                try:
                    if kind == "archive_file":
                        res = self._archive_big_file(task)
                    else:
                        res = self._archive_container(task)
                    self.db.task_finish(task["task_id"], "succeeded", result=res)
                except Exception as e:
                    self._bump("errors")
                    retry = task["attempts"] < self.cfg.max_attempts
                    self.db.task_finish(task["task_id"], "failed",
                                        error=str(e)[:500],
                                        retry_s=30 if retry else None)
                    if not retry and kind == "archive_file":
                        with self.db.conn() as conn:
                            self.db.mark_files_failed(conn, [task["payload"]["file_id"]],
                                                      str(e)[:400])
                    if not retry and kind == "archive_container":
                        with self.db.conn() as conn:
                            self.db.container_update(conn, task["payload"]["container_id"],
                                                     state="aborted", error=str(e)[:400])

    def _archive_big_file(self, task):
        fid = task["payload"]["file_id"]
        f = self.db.get_file(fid)
        if f is None:
            return {"skipped": "file row missing"}
        if f["state"] == "archived":
            return {"skipped": "already archived"}
        cache_key = task["payload"].get("cache_key") or (
            "upload/" + os.path.basename(f["cache_path"]) if f.get("cache_path") else None)
        barcode = task["payload"].get("media_barcode") or self._pick_media()
        with self.db.conn() as conn:
            self.db.mark_files_archiving(conn, [fid])
        block_index, written, ms = self.tape.write_block(
            barcode, f["cache_path"], expected_bytes=f["size_bytes"])
        with self.db.conn() as conn:
            self.db.block_write_records(conn, barcode, block_index, fid, "file",
                                        offset_in_block=0, length=written)
            self.db.tape_update(conn, barcode, used_bytes_delta=written,
                                block_records_delta=1, last_filemark=block_index + 1,
                                bytes_written_delta=written)
            self.db.file_set_tape_location(conn, fid, barcode, block_index)
            self.db.mark_files_archived(conn, [fid], "tape")
        if cache_key:
            self.db.cache_mark_clean(cache_key)
        else:
            self._mark_upload_clean_by_path(f["cache_path"])
        self._bump("bytes_to_tape", written)
        return {"file_id": str(fid), "media": barcode, "block_index": block_index,
                "bytes": written, "duration_ms": ms}

    def _mark_upload_clean_by_path(self, cache_path):
        """Self-heal requeues may lack cache_key; derive it from the stored path."""
        if not cache_path:
            return
        try:
            key = "upload/" + os.path.basename(cache_path)
            if self.db.cache_get(key):
                self.db.cache_mark_clean(key)
        except Exception:
            traceback.print_exc()

    def _archive_container(self, task):
        cid = task["payload"]["container_id"]
        cont = self.db.container_get(cid)
        if cont is None:
            return {"skipped": "container row missing"}
        if cont["state"] == "archived":
            return {"skipped": "already archived"}
        tar_key = "containers/%s.tar" % cid
        tar_path = os.path.join(self.cfg.cache_dir, "containers", "%s.tar" % cid)
        if not os.path.isfile(tar_path):
            # rebuilt after crash: re-tar from member cache files if still present
            files = self.db.container_files(cid)
            pairs = [(f["cache_path"], f["filename"]) for f in files
                     if f.get("cache_path") and os.path.isfile(f["cache_path"])]
            if len(pairs) != cont["file_count"]:
                raise GatewayError("CONTAINER_UNREBUILDABLE",
                                   "tar missing and members no longer cached")
            sha, size = cfmt.write_container(pairs, tar_path)
            with self.db.conn() as conn:
                self.db.container_update(conn, cid, archive_sha256=sha, size_bytes=size)
            self.db.cache_upsert(tar_key, "container", cid, tar_path, size, dirty=True)
        with self.db.conn() as conn:
            self.db.container_update(conn, cid, state="archiving")
            self.db.mark_files_archiving(conn, [f["file_id"]
                                                for f in self.db.container_files(cid)])
        barcode = task["payload"].get("media_barcode") or self._pick_media()
        block_index, written, ms = self.tape.write_block(
            barcode, tar_path, expected_bytes=cont["size_bytes"])
        with self.db.conn() as conn:
            self.db.block_write_records(conn, barcode, block_index, cid, "container",
                                        offset_in_block=0, length=written)
            self.db.tape_update(conn, barcode, used_bytes_delta=written,
                                block_records_delta=1, last_filemark=block_index + 1,
                                bytes_written_delta=written)
            self.db.container_update(conn, cid, state="archived", media_barcode=barcode,
                                     tape_block_index=block_index, offset_in_tape=0,
                                     length_on_tape=written, error=None,
                                     archived_at=datetime.datetime.now(datetime.timezone.utc))
            self.db.mark_files_archived(conn, [f["file_id"]
                                               for f in self.db.container_files(cid)],
                                        "container")
        self.db.cache_mark_clean(tar_key)
        self._bump("bytes_to_tape", written)
        return {"container_id": cid, "media": barcode, "block_index": block_index,
                "bytes": written, "duration_ms": ms, "files": cont["file_count"]}

    def _pick_media(self):
        """Prefer appendable media with room; else promote a scratch one."""
        for m in self.db.tape_list():
            if m["state"] == "appendable" and m["used_bytes"] < m["capacity_bytes"] * 0.95:
                return m["barcode"]
        for m in self.db.tape_list():
            if m["state"] == "scratch":
                with self.db.conn() as conn:
                    self.db.tape_update(conn, m["barcode"], state="appendable")
                return m["barcode"]
        raise GatewayError("NO_MEDIA", "no appendable/scratch media registered",
                           status=409)

    # ---------- recall worker ----------
    def _recall_loop(self):
        task = self.db.task_claim("recall_file")
        if not task:
            return
        try:
            res = self._run_recall(task)
            self.db.task_finish(task["task_id"], "succeeded", result=res)
        except Exception as e:
            self._bump("errors")
            retry = task["attempts"] < self.cfg.max_attempts
            self.db.task_finish(task["task_id"], "failed", error=str(e)[:500],
                                retry_s=30 if retry else None)

    def _run_recall_sync(self, task_id):
        task = self.db.task_get(task_id)
        try:
            res = self._run_recall(task)
            self.db.task_finish(task_id, "succeeded", result=res)
            return res.get("path")
        except Exception as e:
            retry = task["attempts"] < self.cfg.max_attempts
            self.db.task_finish(task_id, "failed", error=str(e)[:500],
                                retry_s=30 if retry else None)
            raise GatewayError("RECALL_FAILED", str(e)[:300], status=502)

    def _run_recall(self, task):
        fid = task["payload"]["file_id"]
        full = task["payload"].get("full_container", False)
        dest = task["payload"].get("dest_dir") or os.path.join(self.cfg.cache_dir, "recall")
        os.makedirs(dest, exist_ok=True)
        f = self.db.get_file(fid)
        if f is None:
            return {"skipped": "missing"}
        base = os.path.basename(f["filename"]) or str(fid)
        final = self._unique_path(dest, base, fid)
        if f["storage"] == "container":
            cid = f["container_id"]
            cont = self.db.container_get(cid)
            tar_path = os.path.join(self.cfg.cache_dir, "containers", "%s.tar" % cid)
            pulled = False
            if not os.path.isfile(tar_path):
                blk = self.db.block_lookup_any(cid)
                if blk is None:
                    raise GatewayError("TAPE_LOCATION_MISSING",
                                       "no block record for container %s" % cid, status=409)
                self.tape.read_block(blk["media_barcode"], blk["block_index"],
                                     cont["size_bytes"], tar_path)
                self.db.cache_upsert("containers/%s.tar" % cid, "container", cid,
                                     tar_path, os.path.getsize(tar_path), dirty=False)
                pulled = True
            out = final + ".part"
            cfmt.extract_member(tar_path, f["filename"], out)
            os.replace(out, final)
            self._recall_done(f)
            self._remember_recalled_member(f, final)
            self._bump("bytes_from_tape", cont["size_bytes"] if full else f["size_bytes"])
            return {"path": final, "mode": "member", "container_pulled": pulled or None}
        # big file
        blk = self.db.block_lookup_any(fid)
        if blk is None:
            raise GatewayError("TAPE_LOCATION_MISSING", "no block record for %s" % fid,
                               status=409)
        out = final + ".part"
        self.tape.read_block(blk["media_barcode"], blk["block_index"], f["size_bytes"], out)
        os.replace(out, final)
        self._recall_done(f)
        self._remember_recalled_member(f, final)
        self._bump("bytes_from_tape", f["size_bytes"])
        return {"path": final, "mode": "file"}

    @staticmethod
    def _unique_path(dest, base, fid):
        """Avoid clobbering existing recalls of same-named files."""
        stem, ext = os.path.splitext(base)
        candidate = os.path.join(dest, base)
        if not os.path.exists(candidate):
            return candidate
        tag = str(fid)[:8]
        return os.path.join(dest, "%s.%s%s" % (stem, tag, ext))

    # ---------- eviction ----------
    def _evict_loop(self):
        try:
            forced = False
            try:
                if shutil_disk_free(self.cfg.cache_dir) < self.cfg.min_free_gb * 1024 ** 3:
                    forced = True  # filesystem nearly full: act regardless of quota
            except Exception:
                pass
            self.enforce_watermarks(force=forced)
        except Exception:
            self._bump("errors")
            traceback.print_exc()

    def enforce_watermarks(self, force=False):
        total, _, _ = self._cache_usage()
        quota = self.cfg.cache_quota_bytes
        high = quota * self.cfg.high_watermark_pct // 100
        low = quota * self.cfg.low_watermark_pct // 100
        if not force and total <= high:
            return {"action": "none", "used_bytes": total}
        target = min(max(low, total - (high - low)), total)
        need = total - target if total > target else 0
        if need <= 0:
            return {"action": "none", "used_bytes": total}
        freed = 0
        evicted = 0
        # priority 1: clean containers (biggest win), then clean files, LRU first
        for kind in ("container", "file"):
            for ent in self.db.cache_lru_candidates(need - freed, dirty=False):
                if ent["kind"] != kind or freed >= need:
                    continue
                if ent["refcount"] > 0:
                    continue
                try:
                    os.remove(ent["path"])
                except FileNotFoundError:
                    pass
                except OSError:
                    continue
                self.db.cache_delete(ent["cache_key"])
                freed += ent["size_bytes"]
                evicted += 1
                self._bump("evictions")
                self._bump_bytes("evicted_bytes", ent["size_bytes"])
                if freed >= need:
                    break
        return {"action": "evict", "used_bytes": total, "freed_bytes": freed,
                "evicted": evicted, "target_bytes": target}

    def _cache_usage(self):
        st = self.db.cache_stats()
        return st["total_bytes"], st["dirty_bytes"], st["clean_bytes"]

    # ================= observability =================
    def _bump(self, key, n=1):
        with self._metrics_lock:
            self._metrics[key] = self._metrics.get(key, 0) + n

    def _bump_bytes(self, key, n):
        with self._metrics_lock:
            self._metrics[key] = self._metrics.get(key, 0) + n

    def stats(self):
        total, dirty, clean = self._cache_usage()
        try:
            fs_free = shutil_disk_free(self.cfg.cache_dir)
        except Exception:
            fs_free = None
        return {
            "files": self.db.file_counts(),
            "containers": self.db.container_stats(),
            "tasks": self.db.task_counts(),
            "cache": {"total_bytes": total, "dirty_bytes": dirty,
                      "clean_bytes": clean,
                      "quota_bytes": self.cfg.cache_quota_bytes,
                      "high_bytes": self.cfg.cache_quota_bytes * self.cfg.high_watermark_pct // 100,
                      "low_bytes": self.cfg.cache_quota_bytes * self.cfg.low_watermark_pct // 100,
                      "fs_free_bytes": fs_free},
            "tape": {"media": len(self.db.tape_list()),
                     "blocks": self.db.block_stats()},
            "metrics": dict(self._metrics),
            "config": self.cfg.summary(),
        }

    def metrics_prom(self):
        st = self.stats()
        lines = []
        total, dirty, clean = st["cache"]["total_bytes"], st["cache"]["dirty_bytes"], st["cache"]["clean_bytes"]
        lines.append("# TYPE gateway_files_total counter")
        for state, n in st["files"].items():
            lines.append('gateway_files_total{state="%s"} %d' % (state, n))
        lines.append("# TYPE gateway_cache_bytes gauge")
        lines.append('gateway_cache_bytes{layer="dirty"} %d' % dirty)
        lines.append('gateway_cache_bytes{layer="clean"} %d' % clean)
        lines.append("# TYPE gateway_tasks_total counter")
        for kind, bystate in st["tasks"].items():
            for state, n in bystate.items():
                lines.append('gateway_tasks_total{kind="%s",state="%s"} %d' % (kind, state, n))
        m = st["metrics"]
        lines.append("# TYPE gateway_tape_bytes counter")
        lines.append('gateway_tape_bytes{dir="write"} %d' % m.get("bytes_to_tape", 0))
        lines.append('gateway_tape_bytes{dir="read"} %d' % m.get("bytes_from_tape", 0))
        lines.append("# TYPE gateway_cache_evictions counter")
        lines.append('gateway_cache_evictions %d' % m.get("evictions", 0))
        lines.append("# TYPE gateway_recall_total counter")
        lines.append('gateway_recall_total{result="hit"} %d' % m.get("recall_hits", 0))
        lines.append('gateway_recall_total{result="miss"} %d' % m.get("recall_misses", 0))
        return "\n".join(lines) + "\n"


def shutil_disk_free(path):
    import shutil
    return shutil.disk_usage(path).free
