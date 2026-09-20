"""Tape engine: media mount scheduling, block positioning, streaming IO.

Block layout per media (LTFS-free, plain filemark-separated blocks):

    [block 0][FM][block 1][FM]...[block k][FM]  <- append point = EOD

- tape_media.last_filemark = #filemarks written = index of next block (0-based)
- one object (big file or container tar) per block, followed by mt weof 1
- append: rewind + fsf(last_filemark) + dd write + weof
- recall: rewind + fsf(block_index) + dd read count=ceil(length/bs)

Crash-consistency rule: the PG transaction that records gw_block +
last_filemark is the linearization point. If we crash after the tape write
but before commit, the orphan block is simply overwritten by the next append
(fsf lands on the stale filemark), so no dangling DB pointers ever exist.
"""
import math
import os
import threading

from app.commands import parsers
from app.security.policy import normalize_device


class TapeError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


class TapeEngine:
    """Serializes all tape operations behind one global lock (single drive)."""

    def __init__(self, runner, chain, cfg, db):
        self.runner = runner
        self.chain = chain
        self.cfg = cfg
        self.db = db
        self.dev = normalize_device(cfg.drive)
        self.changer = normalize_device(cfg.changer)
        self.op_lock = threading.RLock()
        self._req = None

    # ---------- audit plumbing ----------
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
        """Make sure `barcode` is inside our drive. Returns True if a load happened."""
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

    # ---------- public write / read ----------
    def write_block(self, barcode, src_path, expected_bytes=None):
        """Append src_path as one new block. Returns (block_index, bytes_written, duration_ms)."""
        with self.op_lock:
            if not self.cfg.auto_load:
                raise TapeError("CONFIG_ERROR", "auto_load disabled")
            rid = self._open_op("write")
            self.ensure_mounted(barcode)
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
            return block_index, written, rec["duration_ms"]

    def read_block(self, barcode, block_index, length, out_path, refcount_guard=None):
        """Read exactly one block (filemark-terminated) into out_path."""
        with self.op_lock:
            rid = self._open_op("read")
            self.ensure_mounted(barcode)
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
