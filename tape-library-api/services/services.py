"""Services: orchestrate adapters + runner + audit. All business logic lives here."""
import re

from app.commands.adapters import LsscsiAdapter, SgAdapter, MtxAdapter, MtAdapter
from app.commands.runner import CommandRunner
from app.audit.audit import AuditChain


class BaseService:
    def __init__(self, runner: CommandRunner, chain: AuditChain, request_id: str):
        self.runner = runner
        self.chain = chain
        self.request_id = request_id

    def exec(self, argv, phase, risk_level, device=None, timeout=None):
        rec = self.runner.run(argv, phase=phase, risk_level=risk_level, device=device,
                               request_id=self.request_id, timeout=timeout)
        self.chain.record(self.request_id, rec)
        return rec

    @staticmethod
    def ensure_pass(rec, fail_code="COMMAND_FAILED", fail_message=None):
        if rec["exit_code"] != 0:
            from app.models.common import ApiError
            detail = fail_message or ("command failed: %s -> %s" % (rec["command"], rec["stderr"][:200]))
            raise ServiceError(fail_code, detail, rec)
        return rec


class ServiceError(Exception):
    def __init__(self, code, message, command_record=None):
        self.code = code
        self.message = message
        self.command_record = command_record
        super().__init__(message)


class SystemService(BaseService):
    def info(self):
        from app.commands import parsers
        out = {}
        for key, argv in {
            "os_release": ["cat", "/etc/os-release"],
            "kernel": ["uname", "-a"],
            "hostname": ["hostname"],
            "arch": ["uname", "-m"],
            "user": ["id"],
        }.items():
            rec = self.exec(argv, "SYSTEM_INFO", "LEVEL_1")
            out[key] = rec["stdout"].strip() if rec["exit_code"] == 0 else ""
            out[key + "_command_id"] = rec["command_id"]
        out["parsed"] = {
            "os_release": parsers.parse_os_release(out["os_release"]),
            "kernel": parsers.parse_uname(out["kernel"]),
            "user": parsers.parse_id(out["user"]),
            "hostname": {"hostname": out["hostname"], "parsed_ok": bool(out["hostname"])},
            "arch": {"arch": out["arch"], "parsed_ok": bool(out["arch"])},
        }
        return out

    # ---- 1:1 granular endpoints (CLI report parity: one endpoint per CLI command) ----
    def os_release(self):
        from app.commands import parsers
        rec = self.exec(["cat", "/etc/os-release"], "SYSTEM_INFO", "LEVEL_1")
        return {"stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": parsers.parse_os_release(rec["stdout"])}

    def uname_all(self):
        from app.commands import parsers
        rec = self.exec(["uname", "-a"], "SYSTEM_INFO", "LEVEL_1")
        return {"stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": parsers.parse_uname(rec["stdout"])}

    def hostname_cmd(self):
        rec = self.exec(["hostname"], "SYSTEM_INFO", "LEVEL_1")
        return {"stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": {"hostname": rec["stdout"].strip(), "parsed_ok": bool(rec["stdout"].strip())}}

    def arch(self):
        rec = self.exec(["uname", "-m"], "SYSTEM_INFO", "LEVEL_1")
        return {"stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": {"arch": rec["stdout"].strip(), "parsed_ok": bool(rec["stdout"].strip())}}

    def user_cmd(self):
        from app.commands import parsers
        rec = self.exec(["id"], "SYSTEM_INFO", "LEVEL_1")
        return {"stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": parsers.parse_id(rec["stdout"])}

    def kernel(self):
        from app.commands.adapters import SystemProbeAdapter
        from app.commands import parsers
        probe = SystemProbeAdapter()
        out = {}
        for mod in ("st", "sg", "ch", "lin_tape"):
            rec = self.exec(probe.lsmod(mod), "KERNEL_DRIVER", "LEVEL_1")
            out[mod] = {"loaded": bool(rec["stdout"].strip()),
                        "stdout": rec["stdout"].strip(),
                        "parsed": parsers.parse_lsmod(rec["stdout"]),
                        "command_id": rec["command_id"]}
        return out

    def ibm(self):
        from app.commands.adapters import SystemProbeAdapter
        probe = SystemProbeAdapter()
        nodes = self.exec(probe.ibm_nodes(), "IBM_CHECK", "LEVEL_1")
        itdt = self.exec(probe.itdt(), "IBM_CHECK", "LEVEL_1")
        return {
            "lin_tape_nodes": nodes["stdout"].strip(),
            "lin_tape_nodes_list": [ln.strip() for ln in nodes["stdout"].splitlines() if ln.strip()],
            "itdt_installed": bool(itdt["stdout"].strip()),
            "commands": [nodes["command_id"], itdt["command_id"]],
        }


class DependencyService(BaseService):
    REQUIRED = ["lsscsi", "sg_scan", "sg_map", "sg_inq", "sg_vpd", "sg_turs",
                "sg_modes", "sg_logs", "mtx", "mt", "tar"]
    OPTIONAL = ["jq", "python3", "gzip", "file", "udevadm"]
    PKG_MAP = {"lsscsi": "lsscsi", "sg_*": "sg3_utils", "mtx": "mtx", "mt": "mt-st"}

    def check(self):
        deps = []
        for cmd in self.REQUIRED + self.OPTIONAL:
            rec = self.exec(["/usr/bin/which", cmd], "DEPENDENCY_CHECK", "LEVEL_1")
            installed = rec["exit_code"] == 0
            deps.append({
                "name": cmd, "required": cmd in self.REQUIRED, "installed": installed,
                "path": rec["stdout"].strip() or None, "command_id": rec["command_id"],
            })
        pm = None
        for pmcmd in ("dnf", "yum", "apt-get", "zypper"):
            rec = self.exec(["/usr/bin/which", pmcmd], "DEPENDENCY_CHECK", "LEVEL_1")
            if rec["exit_code"] == 0:
                pm = pmcmd
                break
        gate = all(d["installed"] for d in deps if d["required"])
        return {"package_manager": pm, "dependencies": deps, "gate": "PASS" if gate else "FAIL"}

    def check_one(self, name):
        """1:1 for CLI 'command -v <name>' / which <name>."""
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise ServiceError("INVALID_REQUEST", "invalid tool name")
        rec = self.exec(["/usr/bin/which", name], "DEPENDENCY_CHECK", "LEVEL_1")
        installed = rec["exit_code"] == 0
        return {"name": name,
                "required": name in self.REQUIRED,
                "optional": name in self.OPTIONAL,
                "installed": installed,
                "path": rec["stdout"].strip() or None,
                "exit_code": rec["exit_code"],
                "command_id": rec["command_id"],
                "parsed": {"installed": installed, "path": rec["stdout"].strip() or None,
                           "exit_code": rec["exit_code"], "parsed_ok": True}}

    def install(self, packages, confirm):
        if not confirm:
            raise ServiceError("INVALID_REQUEST", "confirm=true required")
        status = self.check()
        missing = [d["name"] for d in status["dependencies"]
                   if d["name"] in packages and not d["installed"]]
        pm = status["package_manager"]
        if pm is None:
            raise ServiceError("PACKAGE_MANAGER_NOT_FOUND", "no package manager found")
        results = []
        for pkg in missing:
            rec = self.exec([pm, "install", "-y", pkg], "DEPENDENCY_INSTALL", "LEVEL_2", timeout=600)
            results.append({"package": pkg, "exit_code": rec["exit_code"], "command_id": rec["command_id"]})
        return {"installed": results, "already_present": [p for p in packages if p not in missing]}


class DiscoveryService(BaseService):
    def discover(self):
        lsscsi = LsscsiAdapter()
        rec = self.ensure_pass(self.exec(lsscsi.list_all(), "DISCOVERY", "LEVEL_1"),
                               "COMMAND_FAILED", "lsscsi failed")
        devices = []
        for line in rec["stdout"].splitlines():
            m = re.match(r"\[([^\]]+)\]\s+(\S+)\s+(\S+)\s+(.*?)\s{2,}.*?(/dev/\S+)?\s*(/dev/sg\d+)?\s*$", line)
            if not m:
                continue
            hba, dtype, vendor, product, st, sg = m.groups()
            dev = {"scsi_address": hba, "device_type": dtype.upper(),
                   "vendor": vendor, "product": product.strip(),
                   "sg_device": sg, "st_device": st if st and st.startswith("/dev/st") else None,
                   "nst_device": st.replace("/dev/st", "/dev/nst") if st and st.startswith("/dev/st") else None}
            devices.append(dev)
        return {"devices": devices, "command_id": rec["command_id"]}

    def scan_detail(self):
        """Raw sg_scan + sg_map -i results (CLI PHASE 09 equivalents)."""
        from app.commands import parsers
        lsscsi = LsscsiAdapter()
        scan = self.ensure_pass(self.exec(lsscsi.scan(), "DISCOVERY", "LEVEL_1"))
        mapping = self.ensure_pass(self.exec(lsscsi.map(), "DISCOVERY", "LEVEL_1"))
        return {"sg_scan": {"stdout": scan["stdout"], "command_id": scan["command_id"],
                            "parsed": parsers.parse_sg_scan(scan["stdout"])},
                "sg_map": {"stdout": mapping["stdout"], "command_id": mapping["command_id"],
                           "parsed": parsers.parse_sg_map(mapping["stdout"])}}


class DeviceService(BaseService):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.sg = SgAdapter()

    def inquiry(self, sg):
        from app.commands import parsers
        rec = self.ensure_pass(self.exec(self.sg.inquiry(sg), "INQUIRY", "LEVEL_1", device=sg),
                               "DEVICE_NOT_FOUND")
        return {"stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": parsers.parse_sg_inq(rec["stdout"])}

    def vpd(self, sg, page):
        from app.commands import parsers
        rec = self.ensure_pass(self.exec(self.sg.vpd(sg, page), "VPD", "LEVEL_1", device=sg),
                               "COMMAND_FAILED")
        return {"page": page, "stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": parsers.parse_sg_vpd(rec["stdout"])}

    def tur(self, sg):
        from app.commands import parsers
        rec = self.exec(self.sg.tur(sg), "TUR", "LEVEL_1", device=sg)
        ready = rec["exit_code"] == 0
        return {"ready": ready, "stdout": rec["stdout"], "stderr": rec["stderr"],
                "command_id": rec["command_id"],
                "parsed": parsers.parse_tur(rec["stdout"], rec["stderr"], rec["exit_code"])}

    def modes(self, sg):
        from app.commands import parsers
        rec = self.ensure_pass(self.exec(self.sg.modes(sg), "MODES", "LEVEL_1", device=sg))
        return {"stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": parsers.parse_sg_modes(rec["stdout"])}

    def logs(self, sg, page=None):
        from app.commands import parsers
        rec = self.ensure_pass(self.exec(self.sg.logs(sg, page), "LOGS", "LEVEL_1", device=sg))
        return {"page": page or "all", "stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": parsers.parse_sg_logs(rec["stdout"], page)}

    def tapealert(self, sg):
        from app.commands import parsers
        rec = self.exec(self.sg.tapealert(sg), "TAPEALERT", "LEVEL_1", device=sg)
        return {"alerts": parsers.parse_tapealert(rec["stdout"])["triggered_alerts"],
                "parsed": parsers.parse_tapealert(rec["stdout"]),
                "stdout": rec["stdout"], "command_id": rec["command_id"]}


class LibraryService(BaseService):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.mtx = MtxAdapter()

    def _lock(self, changer):
        if not self.runner.locks.acquire(changer):
            raise ServiceError("DEVICE_BUSY", "device %s is busy" % changer)
        return True

    def inquiry(self, changer):
        from app.commands import parsers
        rec = self.ensure_pass(self.exec(self.mtx.inquiry(changer), "LIBRARY_INQUIRY", "LEVEL_1", device=changer),
                               "LIBRARY_NOT_FOUND", "changer not found or not a medium changer")
        return {"stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": parsers.parse_sg_inq(rec["stdout"])}

    def status(self, changer):
        from app.commands import parsers
        rec = self.ensure_pass(self.exec(self.mtx.status(changer), "LIBRARY_STATUS", "LEVEL_1", device=changer, timeout=120),
                               "LIBRARY_NOT_FOUND")
        return {"stdout": rec["stdout"], "command_id": rec["command_id"], "exit_code": rec["exit_code"],
                "parsed": parsers.parse_mtx_status(rec["stdout"])}

    def inventory(self, changer):
        from app.security.policy import normalize_device
        changer = normalize_device(changer)
        rec = self.exec(self.mtx.status(changer), "LIBRARY_INVENTORY", "LEVEL_1", device=changer, timeout=120)
        slots, drives = [], []
        for line in rec["stdout"].splitlines():
            m = re.match(r"\s*Storage Element (\d+):(Full|Empty)\s*:?\s*VolumeTag=\s*(\S*)", line)
            if m:
                slots.append({"element": int(m.group(1)), "slot": int(m.group(1)),
                              "occupied": m.group(2) == "Full", "barcode": m.group(3) or None})
                continue
            m = re.match(r"\s*Data Transfer Element (\d+):(Full|Empty)(.*)", line)
            if m:
                d = {"element": int(m.group(1)), "drive": int(m.group(1)), "occupied": m.group(2) == "Full"}
                tag = re.search(r"VolumeTag\s*=?\s*(\S+)", m.group(3))
                if tag:
                    d["barcode"] = tag.group(1)
                drives.append(d)
        return {"library": {"changer": changer}, "slots": slots, "drives": drives,
                "command_id": rec["command_id"]}

    def load(self, changer, slot, drive):
        self._lock(changer)
        try:
            inv = self.inventory(changer)
            for d in inv["drives"]:
                if d["drive"] == drive and d.get("barcode"):
                    raise ServiceError("MEDIA_ALREADY_LOADED", "drive %d already has media" % drive)
            rec = self.ensure_pass(
                self.exec(self.mtx.load(changer, slot, drive), "LIBRARY_LOAD", "LEVEL_2", device=changer, timeout=300),
                "COMMAND_FAILED", "mtx load failed")
            return {"slot": slot, "drive": drive, "command_id": rec["command_id"]}
        finally:
            self.runner.locks.release(changer)

    def unload(self, changer, slot, drive):
        self._lock(changer)
        try:
            rec = self.ensure_pass(
                self.exec(self.mtx.unload(changer, slot, drive), "LIBRARY_UNLOAD", "LEVEL_2", device=changer, timeout=300),
                "COMMAND_FAILED", "mtx unload failed")
            return {"slot": slot, "drive": drive, "command_id": rec["command_id"]}
        finally:
            self.runner.locks.release(changer)

    def transfer(self, changer, source, destination):
        self._lock(changer)
        try:
            rec = self.ensure_pass(
                self.exec(self.mtx.transfer(changer, source, destination), "LIBRARY_TRANSFER", "LEVEL_2", device=changer, timeout=300),
                "COMMAND_FAILED")
            return {"source": source, "destination": destination, "command_id": rec["command_id"]}
        finally:
            self.runner.locks.release(changer)

    def position(self, changer, element):
        self._lock(changer)
        try:
            rec = self.ensure_pass(
                self.exec(self.mtx.position(changer, element), "LIBRARY_POSITION", "LEVEL_2", device=changer, timeout=300),
                "COMMAND_FAILED")
            return {"element": element, "command_id": rec["command_id"]}
        finally:
            self.runner.locks.release(changer)


class DriveService(BaseService):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.mt = MtAdapter()

    def status(self, nst):
        from app.commands import parsers
        rec = self.ensure_pass(self.exec(self.mt.status(nst), "DRIVE_STATUS", "LEVEL_1", device=nst),
                               "DRIVE_NOT_FOUND")
        return {"stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": parsers.parse_mt_status(rec["stdout"])}

    def position(self, nst, operation, count):
        rec = self.ensure_pass(
            self.exec(self.mt.position(nst, operation, count), "DRIVE_POSITION", "LEVEL_2", device=nst, timeout=600),
            "COMMAND_FAILED")
        return {"operation": operation, "count": count, "command_id": rec["command_id"]}

    def rewind(self, nst):
        return self.position(nst, "rewind", 0)

    def _simple(self, nst, argv, phase, risk, timeout=600, fail="COMMAND_FAILED"):
        rec = self.ensure_pass(self.exec(argv, phase, risk, device=nst, timeout=timeout), fail)
        return {"command_id": rec["command_id"], "stdout": rec["stdout"], "stderr": rec["stderr"],
                "exit_code": rec["exit_code"]}

    def wset(self, nst, count):
        rec = self.ensure_pass(
            self.exec(self.mt.wset(nst, count), "DRIVE_WSET", "LEVEL_3", device=nst, timeout=600),
            "COMMAND_FAILED", "mt wset failed")
        return {"count": count, "command_id": rec["command_id"]}

    def eof(self, nst, count):
        return self.weof(nst, count)  # `mt eof` is an alias of `mt weof`

    def offline(self, nst):
        return self.position(nst, "offline", 0)

    def rewoffl(self, nst):
        return self._simple(nst, self.mt.rewoffl(nst), "DRIVE_REWOFFL", "LEVEL_2")

    def eject(self, nst):
        return self._simple(nst, self.mt.eject(nst), "DRIVE_EJECT", "LEVEL_2")

    def retension(self, nst):
        return self._simple(nst, self.mt.retension(nst), "DRIVE_RETENSION", "LEVEL_2", timeout=3600)

    def eod(self, nst):
        return self.position(nst, "eod", 0)

    def seod(self, nst):
        return self.position(nst, "seod", 0)

    def seek(self, nst, count):
        rec = self.ensure_pass(
            self.exec(self.mt.seek(nst, count), "DRIVE_SEEK", "LEVEL_2", device=nst, timeout=600),
            "COMMAND_FAILED", "mt seek failed")
        return {"block": count, "command_id": rec["command_id"]}

    def tell(self, nst):
        rec = self.ensure_pass(self.exec(self.mt.tell(nst), "DRIVE_TELL", "LEVEL_1", device=nst),
                               "COMMAND_FAILED", "mt tell failed")
        return {"stdout": rec["stdout"], "command_id": rec["command_id"]}

    def erase(self, nst, count=0):
        rec = self.ensure_pass(
            self.exec(self.mt.erase(nst, count), "DRIVE_ERASE", "LEVEL_3", device=nst, timeout=3600),
            "COMMAND_FAILED", "mt erase failed")
        return {"command_id": rec["command_id"]}

    def lock(self, nst):
        return self._simple(nst, self.mt.lock(nst), "DRIVE_LOCK", "LEVEL_2")

    def unlock(self, nst):
        return self._simple(nst, self.mt.unlock(nst), "DRIVE_UNLOCK", "LEVEL_2")

    def load(self, nst):
        return self._simple(nst, self.mt.load(nst), "DRIVE_LOAD", "LEVEL_2")

    def compression_set(self, nst, enable):
        rec = self.ensure_pass(
            self.exec(self.mt.compression_set(nst, enable), "DRIVE_COMPRESSION", "LEVEL_2",
                      device=nst, timeout=600),
            "COMMAND_FAILED", "mt compression set failed")
        return {"enabled": bool(enable), "command_id": rec["command_id"]}

    def setblk(self, nst, block_size):
        rec = self.ensure_pass(
            self.exec(self.mt.setblk(nst, block_size), "DRIVE_SETBLK", "LEVEL_2", device=nst),
            "COMMAND_FAILED", "mt setblk failed")
        return {"block_size": block_size, "command_id": rec["command_id"]}

    def setdensity(self, nst, density):
        rec = self.ensure_pass(
            self.exec(self.mt.setdensity(nst, density), "DRIVE_SETDENSITY", "LEVEL_2", device=nst),
            "COMMAND_FAILED", "mt setdensity failed")
        return {"density": density, "command_id": rec["command_id"]}

    def setpartition(self, nst, partition):
        rec = self.ensure_pass(
            self.exec(self.mt.setpartition(nst, partition), "DRIVE_SETPARTITION", "LEVEL_2", device=nst),
            "COMMAND_FAILED", "mt setpartition failed")
        return {"partition": partition, "command_id": rec["command_id"]}

    def mkpartition(self, nst, count):
        rec = self.ensure_pass(
            self.exec(self.mt.mkpartition(nst, count), "DRIVE_MKPARTITION", "LEVEL_3",
                      device=nst, timeout=3600),
            "COMMAND_FAILED", "mt mkpartition failed")
        return {"count": count, "command_id": rec["command_id"]}

    def partseek(self, nst, partition, block):
        rec = self.ensure_pass(
            self.exec(self.mt.partseek(nst, partition, block), "DRIVE_PARTSEEK", "LEVEL_2",
                      device=nst, timeout=600),
            "COMMAND_FAILED", "mt partseek failed")
        return {"partition": partition, "block": block, "command_id": rec["command_id"]}

    def densities(self, nst):
        rec = self.ensure_pass(self.exec(self.mt.densities(nst), "DRIVE_DENSITIES", "LEVEL_1", device=nst),
                               "COMMAND_FAILED", "mt densities failed")
        return {"stdout": rec["stdout"], "command_id": rec["command_id"]}

    def stshowoptions(self, nst):
        rec = self.ensure_pass(self.exec(self.mt.stshowoptions(nst), "DRIVE_OPTIONS", "LEVEL_1", device=nst),
                               "COMMAND_FAILED", "mt stshowoptions failed")
        return {"stdout": rec["stdout"], "command_id": rec["command_id"]}

    def compression(self, nst):
        from app.commands import parsers
        rec = self.exec(self.mt.compression(nst), "DRIVE_COMPRESSION", "LEVEL_1", device=nst)
        return {"stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": parsers.parse_mt_compression(rec["stdout"])}

    def weof(self, nst, count):
        rec = self.ensure_pass(
            self.exec(self.mt.weof(nst, count), "DRIVE_WEOF", "LEVEL_3", device=nst, timeout=600),
            "COMMAND_FAILED", "mt weof failed")
        return {"count": count, "command_id": rec["command_id"]}


class DiagnosticService(BaseService):
    def system(self):
        from app.commands import parsers
        dmesg = self.exec(["dmesg"], "SYSTEM_DIAG", "LEVEL_1", timeout=60)
        jc = self.exec(["journalctl", "-k", "--no-pager"], "SYSTEM_DIAG", "LEVEL_1", timeout=60)
        return {"dmesg": {"stdout": dmesg["stdout"][-20000:], "command_id": dmesg["command_id"],
                         "parsed": parsers.parse_dmesg_lines(dmesg["stdout"][-20000:])},
                "journalctl_kernel": {"stdout": jc["stdout"][-20000:], "command_id": jc["command_id"],
                                      "parsed": parsers.parse_dmesg_lines(jc["stdout"][-20000:])}}

    def dmesg_log(self, tail=100):
        """1:1 for CLI: dmesg | grep -Ei 'tape|changer|scsi|st[0-9]|sg[0-9]|...' | tail -N"""
        import re as _re
        rec = self.exec(["dmesg"], "SYSTEM_DIAG", "LEVEL_1", timeout=60)
        pat = _re.compile(r"tape|changer|scsi|st\d|sg\d|lto|ibm|quantum", _re.I)
        lines = [ln for ln in rec["stdout"].splitlines() if pat.search(ln)]
        tail = max(1, min(int(tail or 100), 1000))
        sel = lines[-tail:]
        return {"filter": "tape|changer|scsi|st[0-9]|sg[0-9]|lto|ibm|quantum (case-insensitive)",
                "tail": tail, "matched_lines": len(lines),
                "stdout": "\n".join(sel), "command_id": rec["command_id"],
                "parsed": {"lines": sel, "total_matched": len(lines), "shown": len(sel),
                           "parsed_ok": True}}

    def journalctl_log(self, tail=100):
        """1:1 for CLI: journalctl -k --no-pager | tail -N"""
        rec = self.exec(["journalctl", "-k", "--no-pager"], "SYSTEM_DIAG", "LEVEL_1", timeout=60)
        lines = [ln for ln in rec["stdout"].splitlines() if ln.strip()]
        tail = max(1, min(int(tail or 100), 1000))
        sel = lines[-tail:]
        return {"tail": tail, "total_lines": len(lines),
                "stdout": "\n".join(sel), "command_id": rec["command_id"],
                "parsed": {"lines": sel, "total_lines": len(lines), "shown": len(sel),
                           "parsed_ok": True}}

    def tape(self, sg):
        svc = DeviceService(self.runner, self.chain, self.request_id)
        return {"inquiry": svc.inquiry(sg), "vpd_0x80": svc.vpd(sg, "0x80"),
                "tur": svc.tur(sg), "tapealert": svc.tapealert(sg)}


class TestService(BaseService):
    def read_test(self, drive, block_size, confirm, timeout):
        if not confirm:
            raise ServiceError("INVALID_REQUEST", "confirm=true required")
        from app.security.policy import normalize_device
        dev = normalize_device(drive)
        if not self.runner.locks.acquire(dev):
            raise ServiceError("DEVICE_BUSY", "drive busy")
        try:
            rec = self.exec(["dd", "if=" + dev, "of=/dev/null", "bs=" + block_size],
                            "READ_TEST", "LEVEL_2", device=dev, timeout=timeout)
            self.ensure_pass(rec, "COMMAND_FAILED", "dd read failed")
            from app.commands import parsers
            return {"drive": dev, "duration_ms": rec["duration_ms"], "command_id": rec["command_id"],
                    "parsed": parsers.parse_dd_summary(rec["stderr"])}
        finally:
            self.runner.locks.release(dev)

    def write_test(self, drive, test_media, size_mb, allow_write, confirm, timeout):
        from app.config import settings
        if not (allow_write and settings.allow_write):
            raise ServiceError("WRITE_OPERATION_NOT_AUTHORIZED",
                               "write requires allow_write=true in request AND ALLOW_WRITE=true env")
        if not confirm:
            raise ServiceError("INVALID_REQUEST", "confirm=true required")
        if not test_media:
            raise ServiceError("MISSING_PARAMETER", "test_media required for write test")
        from app.security.policy import normalize_device
        dev = normalize_device(drive)
        if not self.runner.locks.acquire(dev):
            raise ServiceError("DEVICE_BUSY", "drive busy")
        try:
            rec = self.exec(["dd", "if=/dev/zero", "of=" + dev, "bs=1M", "count=" + str(size_mb)],
                            "WRITE_TEST", "LEVEL_3", device=dev, timeout=timeout)
            self.ensure_pass(rec, "COMMAND_FAILED", "dd write failed")
            from app.commands import parsers
            return {"drive": dev, "size_mb": size_mb, "duration_ms": rec["duration_ms"],
                    "command_id": rec["command_id"],
                    "parsed": parsers.parse_dd_summary(rec["stderr"])}
        finally:
            self.runner.locks.release(dev)

    def write_verify(self, drive, test_media, size_mb, allow_write, confirm, timeout):
        """CLI 等价流程: dd 写入 → mt weof → mt rewind → dd 读回 → cmp 内容校验"""
        from app.config import settings
        if not (allow_write and settings.allow_write):
            raise ServiceError("WRITE_OPERATION_NOT_AUTHORIZED",
                               "write requires allow_write=true in request AND ALLOW_WRITE=true env")
        if not confirm:
            raise ServiceError("INVALID_REQUEST", "confirm=true required")
        if not test_media:
            raise ServiceError("MISSING_PARAMETER", "test_media required")
        from app.security.policy import normalize_device
        dev = normalize_device(drive)
        mt = MtAdapter()
        if not self.runner.locks.acquire(dev):
            raise ServiceError("DEVICE_BUSY", "drive busy")
        try:
            steps = []
            # 1. rewind
            rec = self.exec(mt.position(dev, "rewind", 0), "WRITE_VERIFY", "LEVEL_3", device=dev, timeout=600)
            self.ensure_pass(rec, "COMMAND_FAILED", "rewind before write failed")
            steps.append({"step": "rewind", "command_id": rec["command_id"]})
            # 2. dd write
            rec = self.exec(["dd", "if=/dev/zero", "of=" + dev, "bs=1M", "count=" + str(size_mb)],
                            "WRITE_VERIFY", "LEVEL_3", device=dev, timeout=timeout)
            self.ensure_pass(rec, "COMMAND_FAILED", "dd write failed")
            written_ms = rec["duration_ms"]
            steps.append({"step": "write", "bytes": size_mb * 1024 * 1024,
                          "duration_ms": rec["duration_ms"], "command_id": rec["command_id"]})
            # 3. weof
            rec = self.exec(mt.weof(dev, 1), "WRITE_VERIFY", "LEVEL_3", device=dev, timeout=600)
            self.ensure_pass(rec, "COMMAND_FAILED", "weof failed")
            steps.append({"step": "weof", "command_id": rec["command_id"]})
            # 4. rewind + read back
            rec = self.exec(mt.position(dev, "rewind", 0), "WRITE_VERIFY", "LEVEL_3", device=dev, timeout=600)
            self.ensure_pass(rec, "COMMAND_FAILED", "rewind before verify failed")
            rec = self.exec(["dd", "if=" + dev, "of=/dev/null", "bs=1M", "count=" + str(size_mb)],
                            "WRITE_VERIFY", "LEVEL_2", device=dev, timeout=timeout)
            self.ensure_pass(rec, "COMMAND_FAILED", "dd read-back failed")
            read_ms = rec["duration_ms"]
            steps.append({"step": "read_verify", "duration_ms": rec["duration_ms"],
                          "command_id": rec["command_id"]})
            # 5. rewind + cmp content verify
            rec = self.exec(mt.position(dev, "rewind", 0), "WRITE_VERIFY", "LEVEL_3", device=dev, timeout=600)
            rec = self.exec(["bash", "-c",
                             "dd if=%s bs=1M count=%d status=none | cmp - <(head -c %d /dev/zero) && echo CONTENT_VERIFY_OK"
                             % (dev, size_mb, size_mb * 1024 * 1024)],
                            "WRITE_VERIFY", "LEVEL_2", device=dev, timeout=timeout)
            self.ensure_pass(rec, "COMMAND_FAILED", "content cmp verify failed")
            content_ok = "CONTENT_VERIFY_OK" in rec["stdout"]
            steps.append({"step": "content_verify", "content_ok": content_ok,
                          "command_id": rec["command_id"]})
            return {"drive": dev, "media": test_media, "size_mb": size_mb,
                    "write_duration_ms": written_ms, "read_duration_ms": read_ms,
                    "content_verified": content_ok, "steps": steps}
        finally:
            self.runner.locks.release(dev)

    def erase(self, drive, allow_write, confirm):
        from app.config import settings
        if not (allow_write and settings.allow_write and confirm):
            raise ServiceError("DESTRUCTIVE_OPERATION_NOT_AUTHORIZED",
                               "erase requires allow_write=true + confirm=true + ALLOW_WRITE env")
        rec = self.exec(MtAdapter().erase(drive), "ERASE", "LEVEL_3", device=drive, timeout=3600)
        self.ensure_pass(rec, "COMMAND_FAILED", "mt erase failed")
        return {"drive": drive, "command_id": rec["command_id"]}

    def full_test(self):
        results = {}
        dep = DependencyService(self.runner, self.chain, self.request_id)
        results["dependencies"] = dep.check()
        disc = DiscoveryService(self.runner, self.chain, self.request_id)
        results["discovery"] = disc.discover()
        devices = results["discovery"]["devices"]
        changers = [d for d in devices if d["device_type"] in ("MEDIUM_CHANGER", "MEDIUMX")]
        drives = [d for d in devices if d["device_type"] == "TAPE"]
        lib = LibraryService(self.runner, self.chain, self.request_id)
        if changers:
            ch = changers[0]["sg_device"]
            results["library_inquiry"] = lib.inquiry(ch)
            results["library_status"] = lib.status(ch)
        dev_svc = DeviceService(self.runner, self.chain, self.request_id)
        if drives:
            sg = drives[0]["sg_device"]
            results["device_tur"] = dev_svc.tur(sg)
            results["tapealert"] = dev_svc.tapealert(sg)
        diag = DiagnosticService(self.runner, self.chain, self.request_id)
        results["system_diag"] = diag.system()
        return results
