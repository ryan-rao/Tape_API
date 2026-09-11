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

    def sg_scan_only(self):
        """Run only sg_scan and return raw + parsed output."""
        from app.commands import parsers
        scan = self.ensure_pass(self.exec(LsscsiAdapter().scan(), "DISCOVERY", "LEVEL_1"))
        return {"sg_scan": {"stdout": scan["stdout"], "command_id": scan["command_id"],
                            "parsed": parsers.parse_sg_scan(scan["stdout"])}}

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
        if not ready:
            # empty output == device ready (per sg_turs semantics); any error output
            # means Test Unit Ready failed -> report as API failure
            raise ServiceError("DEVICE_NOT_READY",
                               "device %s not ready: %s" % (sg, (rec["stdout"] or rec["stderr"] or "test unit ready failed").strip().splitlines()[0]),
                               rec)
        return {"ready": ready, "stdout": rec["stdout"], "stderr": rec["stderr"],
                "command_id": rec["command_id"],
                "parsed": parsers.parse_tur(rec["stdout"], rec["stderr"], rec["exit_code"])}

    def modes(self, sg, page=None):
        """Formatted MODE SENSE output: drive summary + structured mode pages.
        page: optional hex page code (e.g. 0x0f) to query a single mode page."""
        from app.commands import parsers
        from app.commands.adapters import LsscsiAdapter, MtAdapter
        import re as _re
        sg_full = sg if sg.startswith("/dev/") else "/dev/" + sg
        rec = self.ensure_pass(self.exec(self.sg.modes(sg_full, page), "MODES", "LEVEL_1", device=sg_full))
        parsed = parsers.parse_sg_modes(rec["stdout"])
        if page:
            pg = page.lower()
            matched = [x for x in parsed.get("mode_pages", []) if x.get("page_code") == pg]
            return {"page": pg,
                    "mode_page": matched[0] if matched else None,
                    "mode_pages": matched,
                    "stdout": rec["stdout"], "command_id": rec["command_id"],
                    "parsed": parsed}

        drive = {}
        head = rec["stdout"].splitlines()
        if head:
            m = _re.match(r"\s*(\S+)\s+(\S+)\s+(\S+)\s+peripheral_type:\s*(\S+)", head[0])
            if m:
                drive = {"vendor": m.group(1), "model": m.group(1) + " " + m.group(2),
                         "firmware": m.group(3), "peripheral_type": m.group(4)}
        hf = parsed.get("header_fields", {})
        drive["density_code"] = hf.get("density_code")
        drive["mode_data_length"] = hf.get("mode_data_length")

        # enrich: serial (inquiry), ready (tur), tape position (mt status)
        try:
            inq = self.ensure_pass(self.exec(self.sg.inquiry(sg_full), "INQUIRY", "LEVEL_1", device=sg_full))
            ip = parsers.parse_sg_inq(inq["stdout"])
            drive["serial_number"] = ip.get("unit_serial_number")
        except Exception:
            drive["serial_number"] = None
        try:
            tur = self.exec(self.sg.tur(sg_full), "TUR", "LEVEL_1", device=sg_full)
            drive["status"] = "READY" if tur["exit_code"] == 0 else "NOT READY"
            drive["scsi"] = "ONLINE"
        except Exception:
            drive["status"] = drive["scsi"] = "UNKNOWN"
        # find nst for this sg, then mt status for position/medium
        drive.update({"medium": "UNKNOWN", "file_number": None, "block_number": None,
                      "partition": None, "block_size": None})
        try:
            lrec = self.ensure_pass(self.exec(LsscsiAdapter().list_all(), "DISCOVERY", "LEVEL_1"))
            nst = None
            for line in lrec["stdout"].splitlines():
                if line.rstrip().endswith(sg_full):
                    m2 = _re.search(r"/dev/st\d+", line)
                    if m2:
                        nst = m2.group(0).replace("/dev/st", "/dev/nst")
                    break
            if nst:
                mt = MtAdapter()
                srec = self.ensure_pass(self.exec(mt.status(nst), "DRIVE_STATUS", "LEVEL_1", device=nst))
                sp = parsers.parse_mt_status(srec["stdout"])
                drive.update({"file_number": sp.get("file_number"),
                              "block_number": sp.get("block_number"),
                              "partition": sp.get("partition"),
                              "block_size": sp.get("block_size"),
                              "density_code": sp.get("density_code") or drive.get("density_code")})
                fl = sp.get("flags") or []
                drive["medium"] = "NOT LOADED" if "DR_OPEN" in fl else "LOADED"
        except Exception:
            pass
        return {"drive": drive, "mode_pages": parsed.get("mode_pages", []),
                "header_fields": hf, "stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": parsed}

    def logs(self, sg, page=None):
        from app.commands import parsers
        rec = self.ensure_pass(self.exec(self.sg.logs(sg, page), "LOGS", "LEVEL_1", device=sg))
        return {"page": page or "all", "stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": parsers.parse_sg_logs(rec["stdout"], page)}

    def discovery_map(self):
        """Full device inventory: lsscsi + sg_inq + sysfs + dmesg(lpfc) + block limits."""
        import os
        import re as _re
        from app.commands import parsers
        from app.commands.adapters import LsscsiAdapter
        lrec = self.ensure_pass(self.exec(LsscsiAdapter().list_all(), "DISCOVERY", "LEVEL_1"))
        entries = parsers.parse_lsscsi_g_entries(lrec["stdout"])

        # fc adapter info from dmesg lpfc PCI lines
        fc_pci = {}
        try:
            drec = self.exec(["dmesg"], "SYSTEM_DIAG", "LEVEL_1", timeout=60)
            for ln in drec["stdout"].splitlines():
                m = _re.search(r"lpfc [0-9:]+\.(\d):", ln)
                if m:
                    fc_pci.setdefault(m.group(1), None)
        except Exception:
            pass

        devices = []
        for e in entries:
            addr = e["scsi_address"]
            host = addr.split(":")[0]
            blkname = e["block_device"].split("/")[-1]      # st0 / ch0
            sgname = e["sg_device"].split("/")[-1]
            is_tape = blkname.startswith("st")
            # sg_inq for PDT / ANSI / kernel identity
            pdt = ansi = None
            ident = serial = None
            try:
                irec = self.ensure_pass(self.exec(self.sg.inquiry(e["sg_device"]), "INQUIRY", "LEVEL_1", device=e["sg_device"]))
                mt = _re.search(r"PDT=(\d+)", irec["stdout"])
                mv = _re.search(r"version=0x([0-9a-f]+)", irec["stdout"])
                mi = _re.search(r"Peripheral device type:\s*(.+)$", irec["stdout"], _re.M)
                ms = _re.search(r"Unit serial number:\s*(\S+)", irec["stdout"])
                if mt: pdt = int(mt.group(1))
                if mv: ansi = int(mv.group(1), 16)
                ident = mi.group(1).strip() if mi else None
                serial = ms.group(1) if ms else None
            except Exception:
                pass
            # sysfs driver
            drv = None
            try:
                drv = os.path.basename(os.path.realpath("/sys/bus/scsi/devices/%s/driver" % addr))
            except Exception:
                pass
            # PCI path via host device symlink
            pci = None
            try:
                p = os.path.realpath("/sys/class/scsi_host/host%s/device" % host)
                mpcl = _re.findall(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]", p)
                if mpcl:
                    pci = mpcl[-1]
            except Exception:
                pass
            fc_model = None
            if pci:
                try:
                    pv = open("/sys/bus/pci/devices/%s/vendor" % pci).read().strip()
                    pd = open("/sys/bus/pci/devices/%s/device" % pci).read().strip()
                    if (pv, pd) == ("0x10df", "0xf100"):
                        fc_model = "Emulex LPe12000"
                    else:
                        fc_model = "PCI %s:%s" % (pv, pd)
                except Exception:
                    pass
            # block limits for tape drives
            blk_limits = None
            if is_tape:
                try:
                    import subprocess as _sp
                    r = _sp.run(["sg_read_block_limits", e["sg_device"]],
                                capture_output=True, text=True, timeout=30)
                    rout = r.stdout + r.stderr  # sg_read_block_limits prints to stderr
                    mn = _re.search(r"Minimum block size:\s*(\d+)", rout)
                    mx = _re.search(r"Maximum block size:\s*(\d+)", rout)
                    if mn or mx:
                        blk_limits = {"min_bytes": int(mn.group(1)) if mn else None,
                                      "max_bytes": int(mx.group(1)) if mx else None}
                except Exception:
                    pass
            dev = {
                "label": None,
                "device_type": "Tape Drive" if is_tape else "Medium Changer",
                "vendor": e["vendor"], "model": e["model"], "firmware": e["firmware"],
                "serial_number": serial,
                "scsi_address": addr, "scsi_host": "host" + host,
                "target": addr.split(":")[2], "lun": addr.split(":")[3],
                "ansi_version": ansi, "pdt": pdt,
                "st_device": e["block_device"] if is_tape else None,
                "ch_device": e["block_device"] if not is_tape else None,
                "sg_device": e["sg_device"],
                "kernel_driver": drv, "sg_driver": "sg",
                "kernel_identity": ident or ("Sequential-Access" if is_tape else "Medium Changer"),
                "fc_adapter": fc_model, "fc_driver": "lpfc",
                "pci_path": pci, "discovered": True,
                "block_limits": blk_limits,
                "function": "磁带读写" if is_tape else "机械手/带库控制",
                "operations": "Read/Write/Rewind/Mode Sense/Log Sense" if is_tape else "Inventory/Move/Load/Unload",
                "component": "Tape Drive" if is_tape else "Library Robot",
            }
            devices.append(dev)
        # label: order by sg number (sg0 -> Drive 1, sg2 -> Drive 2, ...)
        devices.sort(key=lambda d: int(d["sg_device"].split("sg")[-1]))
        di = li = 0
        for d in devices:
            if d["device_type"] == "Tape Drive":
                di += 1
                d["label"] = "Drive %d" % di
            else:
                li += 1
                d["label"] = "Library %d" % li
        matrix = [{"sg": d["sg_device"],
                   "block_device": d["st_device"] or d["ch_device"],
                   "scsi_address": d["scsi_address"],
                   "device_type": d["device_type"],
                   "model": d["model"],
                   "firmware": d["firmware"]} for d in devices]
        # group by FC HBA host (tree view)
        by_hba = {}
        for d in devices:
            h = by_hba.setdefault(d["scsi_host"], {
                "fc_adapter": d["fc_adapter"], "fc_driver": d["fc_driver"],
                "host": d["scsi_host"], "pci_path": d["pci_path"], "targets": []})
            h["targets"].append({
                "scsi_address": d["scsi_address"],
                "vendor": d["vendor"], "model": d["model"],
                "block_device": d["st_device"] or d["ch_device"],
                "sg_device": d["sg_device"],
                "device_type": d["device_type"]})
        hba_tree = sorted(by_hba.values(), key=lambda x: x["host"])
        return {"matrix": matrix, "devices": devices,
                "hba_tree": hba_tree, "command_id": lrec["command_id"]}

    def modes_summary(self, sg):
        """Curated MODE SENSE summary: drive + block descriptor + compression
        + partition + light-weight page list."""
        full = self.modes(sg)
        drive = full.get("drive", {})
        hf = full.get("header_fields", {})
        pages = full.get("mode_pages", [])

        def page(code):
            for x in pages:
                if x.get("page_code") == code:
                    return x
            return None

        comp = page("0x0f") or {}
        part = page("0x11") or {}
        cf = comp.get("fields", {})
        bf = part.get("byte_fields", {})
        return {
            "drive": drive,
            "block_descriptor": {
                "density_code": hf.get("density_code"),
                "number_of_blocks": hf.get("number_of_blocks"),
                "block_length": hf.get("block_length"),
            },
            "compression": {
                "compression_control": cf.get("compression_control"),
                "decompression_control": cf.get("decompression_control"),
                "compression_algorithm": cf.get("compression_algorithm"),
                "decompression_algorithm": cf.get("decompression_algorithm"),
                "scsi": comp.get("scsi"),
            },
            "partition": {
                "partition_config": bf.get("byte_2"),
                "partition_status": bf.get("byte_3"),
                "scsi": part.get("scsi"),
            },
            "pages": [{"page_code": x.get("page_code"), "page_name": x.get("page_name"),
                       "description": x.get("description", ""),
                       "page_length_bytes": x.get("page_length_bytes"),
                       "scsi": x.get("scsi")} for x in pages],
            "command_id": full.get("command_id"),
        }

    def logs_summary(self, sg):
        """Curated LOG SENSE summary: key health/lifetime/error/volume metrics."""
        from app.commands import parsers
        sg_full = sg if sg.startswith("/dev/") else "/dev/" + sg
        rec = self.ensure_pass(self.exec(self.sg.logs(sg_full), "LOGS", "LEVEL_1", device=sg_full))
        parsed = parsers.parse_sg_logs(rec["stdout"], None)
        pages = {p["page_code"]: p for p in parsed.get("log_pages", [])}

        def val(page_code, name, default=None):
            pg = pages.get(page_code) or {}
            for f in pg.get("fields", []):
                if f["name"] == name:
                    return f["value"]
            return default

        alerts = [f for f in (pages.get("0x2e") or {}).get("fields", [])
                  if isinstance(f.get("value"), int) and f["value"]]
        diags = (pages.get("0x16") or {}).get("records", [])
        last_diag = None
        for rec16 in diags:
            f = {x["name"]: x["value"] for x in rec16.get("fields", [])}
            if f.get("Sense key") and not str(f.get("Sense key", "")).startswith("0x0 "):
                last_diag = {
                    "parameter_code": rec16.get("parameter_code"),
                    "sense_key": f.get("Sense key"),
                    "additional_sense": f.get("Additional sense"),
                    "medium_type": f.get("Medium type"),
                    "medium_id": f.get("Volume reference") or f.get("Medium ID"),
                    "repeat": f.get("Repeat"),
                }
            else:
                break
        # partition capacities from 0x17 counters
        def part_counters(prefix_hint):
            out = {}
            pg = pages.get("0x17") or {}
            names = [f["name"] for f in pg.get("fields", [])]
            # counters appear in order; skip (keys not tracked), fall back to None
            return out
        summary = {
            "device": parsed.get("device", {}),
            "health": parsed.get("health_summary", []),
            "tape_alert_active": len(alerts),
            "tape_alert_flags": [f["name"] for f in alerts] if alerts else [],
            "lifetime": {
                "media_loads": val("0x14", "Lifetime media loads"),
                "power_on_hours": val("0x14", "Lifetime power on hours"),
                "media_motion_hours": val("0x14", "Lifetime media motion (head) hours"),
                "metres_of_tape": val("0x14", "Lifetime metres of tape processed"),
                "power_cycles": val("0x14", "Lifetime power cycles"),
                "cleaning_operations": val("0x14", "Lifetime cleaning operations"),
                "hours_since_cleaning": val("0x14", "Media motion (head) hours since last successful cleaning operation"),
            },
            "errors": {
                "hard_write": val("0x14", "Hard write errors"),
                "hard_read": val("0x14", "Hard read errors"),
                "uncorrected_write": val("0x02", "Total uncorrected errors"),
                "uncorrected_read": val("0x03", "Total uncorrected errors"),
                "non_medium": val("0x06", "Non-medium error count"),
                "write_retries": val("0x17", "Total write retries") or val("0x30", "Total write retries"),
                "read_retries": val("0x17", "Total read retries") or val("0x30", "Total read retries"),
            },
            "duty_cycle_pct": {
                "read": val("0x14", "Read duty cycle"),
                "write": val("0x14", "Write duty cycle"),
                "activity": val("0x14", "Activity duty cycle"),
                "ready": val("0x14", "Ready duty cycle"),
                "volume_not_present": val("0x14", "Volume not present duty cycle"),
            },
            "volume": {
                "page_valid": val("0x17", "Page valid"),
                "barcode": val("0x17", "Volume barcode"),
                "serial": val("0x17", "Volume serial number"),
                "personality": val("0x17", "Volume personality"),
                "write_protect": val("0x17", "Write protect"),
                "worm": val("0x17", "WORM"),
                "total_native_capacity_mb": val("0x17", "Total native capacity"),
                "used_native_capacity_mb": val("0x17", "Total used native capacity"),
                "data_sets_written": val("0x17", "Total data sets written"),
                "data_sets_read": val("0x17", "Total data sets read"),
            },
            "capacity_mib": {
                "main_remaining": val("0x31", "Main partition remaining capacity (in MiB)"),
                "main_maximum": val("0x31", "Main partition maximum capacity (in MiB)"),
                "alt_remaining": val("0x31", "Alternate partition remaining capacity (in MiB)"),
                "alt_maximum": val("0x31", "Alternate partition maximum capacity (in MiB)"),
            },
            "last_diagnostic_record": last_diag,
            "supported_pages": len((pages.get("0x00") or {}).get("supported_pages", [])),
            "command_id": rec["command_id"],
        }
        return summary

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
            # BUGFIX 2026-09-11: target slot may be occupied (frontend default 6);
            # fall back to the first empty storage slot so mtx unload does not fail
            # with "Storage Element N is Already Full".
            inv = self.inventory(changer)
            if slot:
                target_full = any(x.get("slot") == slot and x.get("occupied") for x in inv["slots"])
                if target_full:
                    empty = sorted([x["slot"] for x in inv["slots"] if not x.get("occupied")])
                    if not empty:
                        raise ServiceError("NO_EMPTY_SLOT", "target slot %s full and no empty slot available" % slot)
                    slot = empty[0]
            else:
                empty = sorted([x["slot"] for x in inv["slots"] if not x.get("occupied")])
                if not empty:
                    raise ServiceError("NO_EMPTY_SLOT", "no empty slot available for unload")
                slot = empty[0]
            drv = next((d for d in inv["drives"] if d["drive"] == drive), None)
            if drv is None:
                raise ServiceError("DRIVE_NOT_FOUND", "drive %d not found in library" % drive)
            if not drv.get("occupied"):
                raise ServiceError("DRIVE_EMPTY",
                                   "drive %d (%s) is empty: nothing to unload"
                                   % (drive, drv.get("nst_device") or "DTE %d" % drive))
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

    def _find_sg_for_nst(self, nst):
        import re as _re
        from app.commands.adapters import LsscsiAdapter
        nst = nst if nst.startswith("/dev/") else "/dev/" + nst
        st = nst.replace("/dev/nst", "/dev/st")
        rec = self.ensure_pass(self.exec(LsscsiAdapter().list_all(), "DISCOVERY", "LEVEL_1"))
        for line in rec["stdout"].splitlines():
            if _re.search(_re.escape(st) + r"(\s|$)", line):
                m = _re.search(r"(/dev/sg\d+)\s*$", line)
                if m:
                    return m.group(1), nst
        return None, nst

    def summary(self, nst):
        """Aggregate all drive info: identity (sg_inq), mt status, compression, tapealert."""
        from app.commands import parsers
        from app.commands.adapters import SgAdapter
        sg = SgAdapter()
        sg_dev, nst_full = self._find_sg_for_nst(nst)
        out = {"nst_device": nst_full, "sg_device": sg_dev}
        if sg_dev:
            inq = self.ensure_pass(self.exec(sg.inquiry(sg_dev), "INQUIRY", "LEVEL_1", device=sg_dev),
                                   "DEVICE_NOT_FOUND")
            out["identity"] = parsers.parse_sg_inq(inq["stdout"])
            out["identity"]["command_id"] = inq["command_id"]
            ta = self.exec(sg.tapealert(sg_dev), "TAPEALERT", "LEVEL_1", device=sg_dev)
            out["tapealert"] = {"command_id": ta["command_id"],
                                "alerts": parsers.parse_tapealert(ta["stdout"]).get("alerts", [])}
        st = self.ensure_pass(self.exec(self.mt.status(nst_full), "DRIVE_STATUS", "LEVEL_1", device=nst_full),
                              "DRIVE_NOT_FOUND")
        out["status"] = parsers.parse_mt_status(st["stdout"])
        out["status"]["command_id"] = st["command_id"]
        comp = self.exec(self.mt.compression(nst_full), "DRIVE_COMPRESSION", "LEVEL_1", device=nst_full)
        out["compression"] = parsers.parse_mt_compression(comp["stdout"])
        out["compression"]["command_id"] = comp["command_id"]
        return out

    def status(self, nst):
        from app.commands import parsers
        rec = self.ensure_pass(self.exec(self.mt.status(nst), "DRIVE_STATUS", "LEVEL_1", device=nst),
                               "DRIVE_NOT_FOUND")
        return {"stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": parsers.parse_mt_status(rec["stdout"])}

    def position(self, nst, operation, count):
        # pre-check: refuse positioning operations on empty drive
        # (mt rewind/seek on a no-medium drive can hang in the kernel)
        from app.commands import parsers
        nst_full = nst if nst.startswith("/dev/") else "/dev/" + nst
        srec = self.ensure_pass(self.exec(self.mt.status(nst_full), "DRIVE_STATUS", "LEVEL_1", device=nst_full))
        sp = parsers.parse_mt_status(srec["stdout"])
        if "DR_OPEN" in (sp.get("flags") or []):
            if operation in ("offline", "eject"):
                # idempotent: drive already empty, and mt offline would hang
                # in the kernel on a no-medium drive
                return {"operation": operation, "count": count,
                        "result": "already_empty_noop", "command_id": srec["command_id"]}
            raise ServiceError("NO_MEDIUM", "no medium loaded in %s: cannot %s" % (nst_full, operation),
                               srec)
        rec = self.ensure_pass(
            self.exec(self.mt.position(nst, operation, count), "DRIVE_POSITION", "LEVEL_2", device=nst, timeout=600),
            "COMMAND_FAILED")
        return {"operation": operation, "count": count, "command_id": rec["command_id"]}

    def rewind(self, nst):
        return self.position(nst, "rewind", 0)

    def compression(self, nst):
        from app.commands import parsers
        rec = self.exec(self.mt.compression(nst), "DRIVE_COMPRESSION", "LEVEL_1", device=nst)
        return {"stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": parsers.parse_mt_compression(rec["stdout"])}

    def weof(self, nst, count):
        from app.commands import parsers
        nst_full = nst if nst.startswith("/dev/") else "/dev/" + nst
        rec = self.ensure_pass(
            self.exec(self.mt.weof(nst_full, count), "DRIVE_WEOF", "LEVEL_3", device=nst_full, timeout=600),
            "COMMAND_FAILED", "mt weof failed")
        # post-write position for verification
        position = {}
        try:
            srec = self.ensure_pass(self.exec(self.mt.status(nst_full), "DRIVE_STATUS", "LEVEL_1", device=nst_full))
            sp = parsers.parse_mt_status(srec["stdout"])
            position = {k: sp.get(k) for k in ("file_number", "block_number", "partition")}
            position["flags"] = sp.get("flags")
        except Exception:
            pass
        return {"device": nst_full, "operation": "weof", "count": count,
                "position_after": position, "command_id": rec["command_id"]}


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
        from app.commands import parsers
        rec = self.exec(["dmesg"], "SYSTEM_DIAG", "LEVEL_1", timeout=60)
        pat = _re.compile(r"tape|changer|scsi|st\d|sg\d|lto|ibm|quantum", _re.I)
        lines = [ln for ln in rec["stdout"].splitlines() if pat.search(ln)]
        tail = max(1, min(int(tail or 100), 1000))
        sel = lines[-tail:]
        return {"filter": "tape|changer|scsi|st[0-9]|sg[0-9]|lto|ibm|quantum (case-insensitive)",
                "tail": tail, "matched_lines": len(lines),
                "stdout": "\n".join(sel), "command_id": rec["command_id"],
                "device_map": parsers.parse_dmesg_device_map(rec["stdout"]),
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
