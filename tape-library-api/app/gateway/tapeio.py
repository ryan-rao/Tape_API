"""Tape engine: media mount scheduling + pluggable storage backends.

Backend layout per tape_media.format (v1.3):

  format='raw'  — LTFS-free, plain filemark-separated blocks:

      [block 0][FM][block 1][FM]...[block k][FM]  <- append point = EOD

      * tape_media.last_filemark = #filemarks written = index of next block
      * one object (big file or container tar) per block, followed by mt weof 1
      * append: rewind + fsf(last_filemark) + dd write + weof
      * recall: rewind + fsf(block_index) + dd read count=ceil(length/bs)

      Crash-consistency rule: the PG transaction that records gw_block +
      last_filemark is the linearization point. If we crash after the tape
      write but before commit, the orphan block is simply overwritten by the
      next append (fsf lands on the stale filemark), so no dangling DB
      pointers ever exist.

  format='ltfs' — LTFS filesystem managed by the IBM ltfs FUSE binary
      (see LtfsBackend; linearization = sync/unmount success -> PG commit).

DriveLease serializes raw mt/dd operations and LTFS mount/umount on the
single configured drive: while an LTFS session holds the drive, any raw
block or mtx robot operation raises DRIVE_LEASED instead of moving the tape
under a mounted FUSE filesystem.
"""
import contextlib
import math
import os
import threading
import time

from app.commands import parsers
from app.security.policy import normalize_device


class TapeError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


# --------------------------------------------------------------------------
# drive lease: raw ops vs LTFS sessions on the single drive
# --------------------------------------------------------------------------
class DriveLease:
    """Single-drive exclusion between raw block/mtx operations and LTFS FUSE
    sessions. `ltfs_mounted` holds the barcode of the media whose LTFS session
    currently owns the drive; while set, every other exclusive purpose is
    rejected with DRIVE_LEASED (only the owning unmount may proceed)."""

    def __init__(self):
        self._mutex = threading.RLock()
        self.ltfs_mounted = None  # barcode while an LTFS session holds the drive

    @contextlib.contextmanager
    def exclusive(self, purpose):
        """Serialize drive-touching operations. purpose: 'mtx' | 'raw' |
        'ltfs_mount' | 'ltfs_umount'. Reentrant for the owning thread."""
        with self._mutex:
            if self.ltfs_mounted and purpose != "ltfs_umount":
                raise TapeError(
                    "DRIVE_LEASED",
                    "drive is held by LTFS session on media %s; refusing %s "
                    "(unmount LTFS first)" % (self.ltfs_mounted, purpose))
            yield

    def set_ltfs(self, barcode):
        self.ltfs_mounted = barcode

    def clear_ltfs(self):
        self.ltfs_mounted = None


# --------------------------------------------------------------------------
# shared command/audit plumbing
# --------------------------------------------------------------------------
class _CmdMixin:
    """runner/chain-backed exec with audit trail; shared by mounter + backends."""

    runner = None
    chain = None
    cfg = None

    def _open_op(self, op):
        rid = "REQ-GW-%s-%s" % (op[:12].upper(), os.urandom(3).hex().upper())
        self.chain.open_request(rid, "GATEWAY", "/tape/%s" % op)
        return rid

    def _exec(self, rid, argv, phase, risk="LEVEL_2", device=None, timeout=None):
        rec = self.runner.run(argv, phase=phase, risk_level=risk, device=device,
                              request_id=rid, timeout=timeout or self.cfg.tape_timeout_s)
        self.chain.record(rid, rec)
        return rec

    @staticmethod
    def _must_pass(rec, code="COMMAND_FAILED", msg=None):
        if rec["exit_code"] != 0:
            raise TapeError(code, msg or ("command failed: %s -> %s"
                                          % (rec["command"], rec["stderr"][:300])))
        return rec


# --------------------------------------------------------------------------
# media mount scheduling (format-independent)
# --------------------------------------------------------------------------
class MediaMounter(_CmdMixin):
    """mtx robot scheduling: make a barcode sit in our drive. Shared by the
    raw and LTFS backends; every robot move runs under the drive lease."""

    def __init__(self, runner, chain, cfg, db, lease):
        self.runner = runner
        self.chain = chain
        self.cfg = cfg
        self.db = db
        self.lease = lease
        self.dev = normalize_device(cfg.drive)
        self.changer = normalize_device(cfg.changer)

    # ---------- topology ----------
    def _dte_of(self, dev):
        for k, v in self.cfg.dte_map.items():
            if normalize_device(str(v)) == dev:
                return int(k)
        raise TapeError("CONFIG_ERROR",
                        "drive %s not in GATEWAY_DTE_MAP %s" % (dev, self.cfg.dte_map))

    def library_status(self, rid=None):
        rid = rid or self._open_op("libstatus")
        rec = self._exec(rid, ["mtx", "-f", self.changer, "status"],
                         "GW_LIBRARY_STATUS", "LEVEL_1", device=self.changer, timeout=120)
        parsed = parsers.parse_mtx_status(rec["stdout"])
        if not parsed["parsed_ok"]:
            raise TapeError("COMMAND_FAILED", "mtx status unparseable: %s" % rec["stdout"][:200])
        return parsed

    def drive_online(self):
        rec = self._exec(self._open_op("mtstatus"), ["mt", "-f", self.dev, "status"],
                         "GW_DRIVE_STATUS", "LEVEL_1", device=self.dev, timeout=60)
        return parsers.parse_mt_status(rec["stdout"])["tape_online"]

    # ---------- media mount ----------
    def _first_empty_storage_slot(self, status):
        for s in status["slots"]:
            if s["occupied"] and not s["import_export"]:
                continue
            if not s["occupied"] and not s["import_export"]:
                return s["element"]
        for s in status["slots"]:  # fall back to Import/Export
            if not s["occupied"]:
                return s["element"]
        return None

    def ensure_mounted(self, barcode):
        """Make sure `barcode` is inside our drive. Returns True if a load
        happened. Refused with DRIVE_LEASED while an LTFS session owns the
        drive (unless called by the LTFS backend itself, same thread)."""
        with self.lease.exclusive("mtx"):
            if self.cfg.trust_drive:
                if self.cfg.trust_drive == barcode:
                    if self.drive_online():
                        return False
                    raise TapeError("DRIVE_OFFLINE",
                                    "drive %s has no tape mounted (trusted %s)" % (self.dev, barcode))
                raise TapeError("MEDIA_MISMATCH",
                                "drive trusted as %s but task needs %s; unset "
                                "GATEWAY_TRUST_DRIVE or swap tapes" % (self.cfg.trust_drive, barcode))
            dte = self._dte_of(self.dev)
            status = self.library_status()
            drives = {d["drive"]: d for d in status["drives"]}
            ours = drives.get(dte)
            if ours and ours["occupied"] and ours["barcode"] == barcode:
                return False  # already mounted
            # unload whatever is in our drive
            if ours and ours["occupied"]:
                slot = ours.get("source_slot") or self._first_empty_storage_slot(status)
                if slot is None:
                    raise TapeError("NO_EMPTY_SLOT", "no empty slot to unload drive")
                self._must_pass(
                    self._exec(self._open_op("unload"), ["mtx", "-f", self.changer, "unload",
                                                         str(slot), str(dte)],
                               "GW_UNLOAD", "LEVEL_2", device=self.changer, timeout=600),
                    "COMMAND_FAILED", "unload failed")
                status = self.library_status()
                drives = {d["drive"]: d for d in status["drives"]}
            # locate target
            src_slot = None
            holder = None
            for s in status["slots"]:
                if s["occupied"] and s["barcode"] == barcode:
                    src_slot = s["element"]
                    break
            if src_slot is None:
                for d in status["drives"]:
                    if d["occupied"] and d["barcode"] == barcode:
                        holder = d
                        break
            if holder is not None:
                # media sits in another drive: pull it out first
                slot = (holder.get("source_slot")
                        if holder.get("source_slot") and not any(
                            s["element"] == holder["source_slot"] and s["occupied"]
                            for s in status["slots"])
                        else self._first_empty_storage_slot(status))
                if slot is None:
                    raise TapeError("NO_EMPTY_SLOT", "no empty slot to unload holder drive")
                self._must_pass(
                    self._exec(self._open_op("unload"), ["mtx", "-f", self.changer, "unload",
                                                         str(slot), str(holder["drive"])],
                               "GW_UNLOAD", "LEVEL_2", device=self.changer, timeout=600))
                src_slot = slot
            if src_slot is None:
                raise TapeError("MEDIA_NOT_FOUND", "barcode %s not in library" % barcode)
            self._must_pass(
                self._exec(self._open_op("load"), ["mtx", "-f", self.changer, "load",
                                                   str(src_slot), str(dte)],
                           "GW_LOAD", "LEVEL_2", device=self.changer, timeout=600),
                "COMMAND_FAILED", "load %s from slot %s failed" % (barcode, src_slot))
            self.db.tape_media_mounted(barcode)
            return True


# --------------------------------------------------------------------------
# raw block backend (format='raw') — zero semantic change from v1.2.4
# --------------------------------------------------------------------------
class RawBlockBackend(_CmdMixin):
    """Filemark-separated raw block IO. Addressing via gw_block.block_index;
    orphan-block-overwrite crash rule preserved unchanged."""

    format_name = "raw"

    def __init__(self, runner, chain, cfg, db, mounter, lease):
        self.runner = runner
        self.chain = chain
        self.cfg = cfg
        self.db = db
        self.mounter = mounter
        self.lease = lease
        self.dev = normalize_device(cfg.drive)
        self.op_lock = threading.RLock()  # serialize raw ops on the drive

    # ---------- positioning ----------
    def _position_to_block(self, rid, block_index):
        self._must_pass(self._exec(rid, ["mt", "-f", self.dev, "rewind"],
                                   "GW_REWIND", "LEVEL_2", device=self.dev),
                        "COMMAND_FAILED", "rewind failed")
        if block_index > 0:
            self._must_pass(self._exec(rid, ["mt", "-f", self.dev, "fsf", str(block_index)],
                                       "GW_FSF", "LEVEL_2", device=self.dev),
                            "COMMAND_FAILED", "fsf %d failed" % block_index)

    def _bootstrap_filemark(self, rid):
        """First write to media we have no state for: seek EOD, count filemarks.
        mt tell reports the block-within-file number (0 at EOD), so the file
        count must come from mt status File number (= filemarks passed)."""
        self._must_pass(self._exec(rid, ["mt", "-f", self.dev, "rewind"],
                                   "GW_REWIND", "LEVEL_2", device=self.dev))
        self._must_pass(self._exec(rid, ["mt", "-f", self.dev, "seod"],
                                   "GW_SEOD", "LEVEL_2", device=self.dev),
                        "COMMAND_FAILED", "seod failed")
        rec = self._must_pass(self._exec(rid, ["mt", "-f", self.dev, "status"],
                                        "GW_DRIVE_STATUS", "LEVEL_1", device=self.dev),
                             "COMMAND_FAILED", "mt status failed")
        parsed = parsers.parse_mt_status(rec["stdout"])
        if not parsed.get("parsed_ok") or parsed.get("file_number") is None:
            raise TapeError("COMMAND_FAILED", "cannot parse mt status: %r" % rec["stdout"][:120])
        fn = parsed["file_number"]
        return max(0, fn) if fn is not None else 0

    # ---------- backend interface ----------
    def capabilities(self):
        return {"format": self.format_name, "addressing": "gw_block.block_index",
                "operations": ("write_object", "read_object")}

    def write_object(self, barcode, src_path, expected_bytes=None, object_id=None,
                     object_type="file"):
        """Append src_path as one new block. Returns dict with block_index /
        bytes / duration_ms (v1.3 backend contract)."""
        with self.op_lock:
            if not self.cfg.auto_load:
                raise TapeError("CONFIG_ERROR", "auto_load disabled")
            rid = self._open_op("write")
            with self.lease.exclusive("raw"):
                self.mounter.ensure_mounted(barcode)
                media = self.db.tape_get(barcode)
                if media is None:
                    raise TapeError("MEDIA_NOT_FOUND", "barcode %s unknown to metadata" % barcode)
                if media["state"] not in ("appendable", "unknown", "scratch"):
                    raise TapeError("MEDIA_NOT_APPENDABLE",
                                    "media %s state=%s" % (barcode, media["state"]))
                block_index = media["last_filemark"]
                if block_index is None:
                    block_index = self._bootstrap_filemark(rid)
                    with self.db.conn() as conn:
                        self.db.tape_update(conn, barcode, last_filemark=block_index)
                    media = self.db.tape_get(barcode)
                block_index = int(block_index)
                self._position_to_block(rid, block_index)
                rec = self._exec(rid, ["dd", "if=" + src_path, "of=" + self.dev,
                                       "bs=256k", "conv=notrunc"],
                                 "GW_TAPE_WRITE", "LEVEL_3", device=self.dev)
                self._must_pass(rec, "COMMAND_FAILED", "tape write failed")
                self._must_pass(self._exec(rid, ["mt", "-f", self.dev, "weof", "1"],
                                           "GW_WEOF", "LEVEL_3", device=self.dev),
                                "COMMAND_FAILED", "weof failed")
            written = expected_bytes if expected_bytes is not None else os.path.getsize(src_path)
            return {"block_index": block_index, "bytes": written,
                    "duration_ms": rec["duration_ms"]}

    def read_object(self, barcode, block_index, length, out_path, expected_size=None):
        """Read exactly one block (filemark-terminated) into out_path.
        Returns (size, duration_ms)."""
        with self.op_lock:
            rid = self._open_op("read")
            with self.lease.exclusive("raw"):
                self.mounter.ensure_mounted(barcode)
                media = self.db.tape_get(barcode)
                if media is None:
                    raise TapeError("MEDIA_NOT_FOUND", "barcode %s unknown to metadata" % barcode)
                self._position_to_block(rid, int(block_index))
                bs = 256 * 1024
                count = max(1, math.ceil(length / bs))
                rec = self._exec(rid, ["dd", "if=" + self.dev, "of=" + out_path,
                                       "bs=256k", "count=" + str(count)],
                                 "GW_TAPE_READ", "LEVEL_2", device=self.dev)
                self._must_pass(rec, "COMMAND_FAILED", "tape read failed")
            size = os.path.getsize(out_path)
            if size < length:
                raise TapeError("TAPE_READ_SHORT",
                                "expected %d bytes, got %d" % (length, size))
            return size, rec["duration_ms"]

    def format_media(self, barcode, **kw):
        raise TapeError("UNSUPPORTED",
                        "raw media needs no formatting; first write bootstraps "
                        "the filemark index (barcode %s)" % barcode)


# --------------------------------------------------------------------------
# engine facade
# --------------------------------------------------------------------------
class TapeEngine(_CmdMixin):
    """Coordinates the drive lease, the robot mounter and the format backends.
    manager code routes through backend_for(media); legacy write_block /
    read_block helpers keep the v1.2.x tuple contract for the raw path."""

    def __init__(self, runner, chain, cfg, db):
        self.runner = runner
        self.chain = chain
        self.cfg = cfg
        self.db = db
        self.dev = normalize_device(cfg.drive)
        self.changer = normalize_device(cfg.changer)
        self.lease = DriveLease()
        self.mounter = MediaMounter(runner, chain, cfg, db, self.lease)
        self.backends = {"raw": RawBlockBackend(runner, chain, cfg, db,
                                                self.mounter, self.lease)}
        self._req = None

    # ---------- backend routing ----------
    def backend_for(self, media):
        fmt = (media or {}).get("format") or "raw"
        backend = self.backends.get(fmt)
        if backend is None:
            raise TapeError("UNKNOWN_FORMAT",
                            "media format %r has no backend (loaded: %s)"
                            % (fmt, ",".join(sorted(self.backends))))
        return backend

    # ---------- recovery ----------
    def recover(self):
        """Startup recovery hook (LTFS backend clears stale sessions)."""
        out = {}
        for name, backend in self.backends.items():
            fn = getattr(backend, "recover_stale", None)
            if callable(fn):
                out[name] = fn()
        return out

    # ---------- topology (delegated) ----------
    def library_status(self, rid=None):
        return self.mounter.library_status(rid)

    def drive_online(self):
        return self.mounter.drive_online()

    # ---------- legacy raw facade (tuple contract, v1.2.x) ----------
    @property
    def op_lock(self):
        return self.backends["raw"].op_lock

    def write_block(self, barcode, src_path, expected_bytes=None):
        res = self.backends["raw"].write_object(barcode, src_path,
                                                expected_bytes=expected_bytes)
        return res["block_index"], res["bytes"], res["duration_ms"]

    def read_block(self, barcode, block_index, length, out_path, refcount_guard=None):
        return self.backends["raw"].read_object(barcode, block_index, length, out_path)
