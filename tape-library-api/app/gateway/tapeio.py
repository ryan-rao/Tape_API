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
import shlex
import subprocess
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
# LTFS backend (format='ltfs')
# --------------------------------------------------------------------------
class LtfsBackend(_CmdMixin):
    """LTFS volume backend built on the IBM ltfs binary stack (mkltfs/ltfs/
    ltfsck, FUSE). One media per mount: <ltfs_mount_root>/<barcode>.

    Session model: mount acquires the drive lease for the whole FUSE session
    (lease.ltfs_mounted = barcode). File IO goes through the mountpoint and
    needs no lease; raw/mtx operations are rejected with DRIVE_LEASED until
    unmount returns the drive.

    Crash-consistency: the linearization point is a successful sync+unmount
    (LTFS flushes its index partition at unmount); PG commits only after that.
    A crash between tape write and PG commit leaves an orphan file on the LTFS
    volume (no dangling DB pointers); a crash mid-unmount is healed by ltfsck.
    """

    format_name = "ltfs"

    def __init__(self, runner, chain, cfg, db, mounter, lease):
        self.runner = runner
        self.chain = chain
        self.cfg = cfg
        self.db = db
        self.mounter = mounter
        self.lease = lease
        self.dev = normalize_device(cfg.drive)
        self._ltfs_dev_cache = None  # resolved sg node (LTFS requires sg, not st)
        self._session_lock = threading.RLock()  # serialize session transitions

    # ---------- helpers ----------
    def _bin(self, name):
        return os.path.join(self.cfg.ltfs_bin_dir, name)

    def _mp(self, barcode):
        return os.path.join(self.cfg.ltfs_mount_root, barcode)

    def _mount_timeout(self):
        return int(getattr(self.cfg, "ltfs_mount_timeout_s", 300) or 300)

    def _sg_dev(self):
        """LTFS binaries must talk to the drive's SG node: the st driver
        (nst*) does not pass through partition/attribute CDBs — mkltfs on an
        st node reports success but writes an unreadable index (field-proven
        on 118 / ULT3580-TD9). cfg.ltfs_device wins; else sysfs auto-detect
        from the configured st drive; last resort the drive as-is."""
        if self._ltfs_dev_cache:
            return self._ltfs_dev_cache
        dev = ""
        if str(getattr(self.cfg, "ltfs_device", "") or "").strip():
            dev = normalize_device(str(self.cfg.ltfs_device).strip())
        else:
            try:
                link = "/sys/class/scsi_tape/%s/device/generic" % os.path.basename(self.dev)
                dev = "/dev/" + os.path.basename(os.readlink(link))
            except OSError:
                dev = ""
        if not dev:
            dev = self.dev
        self._ltfs_dev_cache = dev
        return dev

    @staticmethod
    def _ltfs_procs(mp):
        """pids of ltfs daemons bound to this mountpoint (light, no audit)."""
        try:
            out = subprocess.run(["pgrep", "-f", "ltfs %s" % mp],
                                 capture_output=True, text=True, timeout=10)
            return [int(x) for x in out.stdout.split()]
        except Exception:
            return []

    @staticmethod
    def _log_tail(path, n=300):
        try:
            with open(path, "r", errors="replace") as f:
                return f.read()[-n:]
        except OSError:
            return "(no log)"

    def _wait_mountstate(self, mp, want_mounted, timeout_s=None):
        deadline = time.time() + (timeout_s or self._mount_timeout())
        while time.time() < deadline:
            try:
                if os.path.ismount(mp) == want_mounted:
                    return True
            except OSError:
                pass
            time.sleep(0.5)
        return False

    @staticmethod
    def _copy_file(src, dst):
        """Chunked copy + fsync (works for FUSE targets)."""
        with open(src, "rb") as f_in, open(dst, "wb") as f_out:
            while True:
                chunk = f_in.read(4 * 1024 * 1024)
                if not chunk:
                    break
                f_out.write(chunk)
            f_out.flush()
            os.fsync(f_out.fileno())
        return os.path.getsize(dst)

    def capabilities(self):
        return {"format": self.format_name, "addressing": "ltfs_path",
                "operations": ("write_object", "read_object", "format_media",
                               "check_media", "status")}

    # ---------- session management ----------
    def mounted(self):
        return self.lease.ltfs_mounted

    def _mount(self, barcode):
        rid = self._open_op("ltfsmount")
        with self.lease.exclusive("ltfs_mount"):
            self.mounter.ensure_mounted(barcode)
            mp = self._mp(barcode)
            os.makedirs(mp, exist_ok=True)
            dev = self._sg_dev()
            argv = [self._bin("ltfs"), mp, "-o", "devname=" + dev]
            if self.cfg.ltfs_sync_policy == "keep_mounted":
                # durable-enough index updates while the session stays open
                argv += ["-o", "sync_type=close"]
            # ltfs daemonizes on successful mount and keeps inherited fds open,
            # so it must NOT run under captured pipes (the exec would block
            # until unmount). Wrap with bash -c + file redirect: bash exits as
            # soon as the ltfs parent daemonizes; daemon logs land in <mp>.log.
            log = os.path.join(self.cfg.ltfs_mount_root, "%s.mount.log" % barcode)
            cmdline = "%s >>%s 2>&1 </dev/null" % (
                " ".join(shlex.quote(a) for a in argv), shlex.quote(log))
            self._exec(rid, ["bash", "-c", cmdline], "GW_LTFS_MOUNT", "LEVEL_2",
                       device=dev, timeout=self._mount_timeout())
            # ground truth is the mountpoint state, not the wrapper exit code
            if not self._wait_mountstate(mp, True):
                raise TapeError("LTFS_MOUNT_TIMEOUT",
                                "%s not mounted after %ss; ltfs log: %s"
                                % (mp, self._mount_timeout(), self._log_tail(log)))
            self.lease.set_ltfs(barcode)
            return mp

    def _umount(self):
        rid = self._open_op("ltfsumount")
        with self.lease.exclusive("ltfs_umount"):
            barcode = self.lease.ltfs_mounted
            mp = self._mp(barcode) if barcode else None
            if not mp or not os.path.ismount(mp):
                self.lease.clear_ltfs()
                return True
            try:
                os.sync()
            except Exception:
                pass
            rec = self._exec(rid, ["umount", mp], "GW_LTFS_UMOUNT", "LEVEL_2",
                             timeout=self._mount_timeout())
            if rec["exit_code"] != 0:
                rec = self._exec(rid, ["fusermount", "-u", mp], "GW_LTFS_UMOUNT",
                                 "LEVEL_2", timeout=self._mount_timeout())
            self._must_pass(rec, "LTFS_UMOUNT_FAILED",
                            "ltfs umount failed: %s -> %s"
                            % (rec["command"], (rec["stdout"] + rec["stderr"])[:300]))
            if not self._wait_mountstate(mp, False):
                raise TapeError("LTFS_UMOUNT_TIMEOUT",
                                "%s still mounted after %ss" % (mp, self._mount_timeout()))
            self._wait_daemon_exit(mp)
            self.lease.clear_ltfs()
            return True

    def _wait_daemon_exit(self, mp, wait_s=60):
        """FUSE detaches before the ltfs daemon finishes flushing its index;
        wait for the daemon to actually exit (it holds the drive reservation),
        SIGKILL as a last resort after the grace window."""
        deadline = time.time() + wait_s
        while time.time() < deadline:
            if not self._ltfs_procs(mp):
                return True
            time.sleep(1)
        if self._ltfs_procs(mp):
            self._exec(self._open_op("ltfskill"),
                       ["pkill", "-9", "-f", "ltfs %s" % mp],
                       "GW_LTFS_KILL", "LEVEL_2", timeout=30)
        return True

    def _session(self, barcode):
        """Ensure an open LTFS session for `barcode` (one drive -> one media).
        Returns the mountpoint."""
        with self._session_lock:
            cur = self.lease.ltfs_mounted
            if cur == barcode:
                return self._mp(barcode)
            if cur:
                self._umount()
            return self._mount(barcode)

    # ---------- backend interface ----------
    def write_object(self, barcode, src_path, expected_bytes=None, object_id=None,
                     object_type="file"):
        """Copy src_path into the LTFS volume as objects/<type>/<id>.bin.
        With sync_policy=unmount (default) the session is unmounted (index
        flushed) before returning -> caller's PG commit is the safe point."""
        if object_id is None:
            raise TapeError("INVALID_REQUEST", "LTFS write needs object_id")
        media = self.db.tape_get(barcode)
        if media is None:
            raise TapeError("MEDIA_NOT_FOUND", "barcode %s unknown to metadata" % barcode)
        if media.get("format") != "ltfs":
            raise TapeError("MEDIA_FORMAT_MISMATCH",
                            "media %s format=%s, LTFS backend requires ltfs"
                            % (barcode, media.get("format")))
        if media["state"] not in ("appendable", "unknown", "scratch"):
            raise TapeError("MEDIA_NOT_APPENDABLE",
                            "media %s state=%s" % (barcode, media["state"]))
        started = time.time()
        mp = self._session(barcode)
        rel = "objects/%s/%s.bin" % (object_type, object_id)
        dest_dir = os.path.join(mp, os.path.dirname(rel))
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(mp, rel)
        size = self._copy_file(src_path, dest)
        if expected_bytes is not None and size != expected_bytes:
            raise TapeError("LTFS_WRITE_SHORT",
                            "expected %d bytes, wrote %d" % (expected_bytes, size))
        unmounted = False
        if self.cfg.ltfs_sync_policy == "unmount":
            self._umount()
            unmounted = True
        duration_ms = int((time.time() - started) * 1000)
        return {"ltfs_path": rel, "bytes": size, "duration_ms": duration_ms,
                "unmounted": unmounted, "sync_policy": self.cfg.ltfs_sync_policy}

    def read_object(self, barcode, ltfs_path, out_path, expected_size=None):
        """Copy objects/<...> back from the LTFS volume; unmounts afterwards
        to hand the drive back (reads need no index flush)."""
        started = time.time()
        mp = self._session(barcode)
        src = os.path.join(mp, ltfs_path)
        if not os.path.isfile(src):
            raise TapeError("LTFS_FILE_NOT_FOUND",
                            "%s not on LTFS volume %s" % (ltfs_path, barcode))
        size = self._copy_file(src, out_path)
        if expected_size is not None and size != expected_size:
            raise TapeError("LTFS_READ_SHORT",
                            "expected %d bytes, got %d" % (expected_size, size))
        self._umount()
        return size, int((time.time() - started) * 1000)

    def format_media(self, barcode, volume_name=None):
        """mkltfs the media (DESTRUCTIVE: erases everything on it). Caller
        must have re-confirmed the barcode; we re-verify it exists in the
        library and is loaded into the drive before formatting."""
        rid = self._open_op("mkltfs")
        with self.lease.exclusive("ltfs_mount"):
            self.mounter.ensure_mounted(barcode)
            argv = [self._bin("mkltfs"), "-f", "-d", self._sg_dev(),
                    "-n", volume_name or barcode]
            rec = self._exec(rid, argv, "GW_LTFS_FORMAT", "LEVEL_3",
                             device=self._sg_dev(),
                             timeout=self._mount_timeout() * 3)
            self._must_pass(rec, "LTFS_FORMAT_FAILED",
                            "mkltfs failed: %s -> %s"
                            % (rec["command"], (rec["stdout"] + rec["stderr"])[:300]))
        out = (rec["stdout"] + rec["stderr"]).strip()
        return {"barcode": barcode, "formatted": True, "volume_name": volume_name or barcode,
                "output": out[-600:]}

    def check_media(self, barcode):
        """Run ltfsck against the (unmounted) volume in the drive."""
        rid = self._open_op("ltfsck")
        with self.lease.exclusive("ltfs_mount"):
            self.mounter.ensure_mounted(barcode)
            rec = self._exec(rid, [self._bin("ltfsck"), self._sg_dev()],
                             "GW_LTFS_CHECK", "LEVEL_2", device=self._sg_dev(),
                             timeout=self._mount_timeout())
        out = (rec["stdout"] + rec["stderr"]).strip()
        return {"barcode": barcode, "clean": rec["exit_code"] == 0,
                "exit_code": rec["exit_code"], "output": out[-800:]}

    def status(self):
        root = self.cfg.ltfs_mount_root
        mounted_dirs = []
        try:
            for name in sorted(os.listdir(root)):
                p = os.path.join(root, name)
                if os.path.isdir(p) and os.path.ismount(p):
                    mounted_dirs.append(name)
        except OSError:
            pass
        return {
            "ltfs_mounted": self.lease.ltfs_mounted,
            "ltfs_device": self._sg_dev(),
            "mount_root": root,
            "bin_dir": self.cfg.ltfs_bin_dir,
            "sync_policy": self.cfg.ltfs_sync_policy,
            "mount_timeout_s": self._mount_timeout(),
            "binaries": {n: os.path.isfile(self._bin(n))
                         for n in ("ltfs", "mkltfs", "ltfsck")},
            "mounted_dirs": mounted_dirs,
        }

    def recover_stale(self):
        """Gateway restart hook: any LTFS session that outlived the process
        is unmounted best-effort (in-flight writes died with the process)."""
        recovered = []
        root = self.cfg.ltfs_mount_root
        try:
            for name in sorted(os.listdir(root)):
                p = os.path.join(root, name)
                if os.path.isdir(p) and os.path.ismount(p):
                    try:
                        rec = self._exec(self._open_op("ltfsrecover"),
                                         ["fusermount", "-u", p],
                                         "GW_LTFS_UMOUNT", "LEVEL_2",
                                         timeout=self._mount_timeout())
                        if rec["exit_code"] == 0 or not os.path.ismount(p):
                            recovered.append(name)
                    except Exception:
                        pass
        except OSError:
            pass
        self.lease.clear_ltfs()
        return {"unmounted_stale": recovered}


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
                                                self.mounter, self.lease),
                         "ltfs": LtfsBackend(runner, chain, cfg, db,
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
