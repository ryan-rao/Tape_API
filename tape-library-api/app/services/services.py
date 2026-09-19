"""Services: orchestrate adapters + runner + audit. All business logic lives here."""
import re

from app.commands.adapters import (LsscsiAdapter, SgAdapter, MtxAdapter, MtAdapter, SgAttrAdapter)
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
        self.mt = MtAdapter()
        self.attr = SgAttrAdapter()

    def _lock(self, changer):
        if not self.runner.locks.acquire(changer):
            raise ServiceError("DEVICE_BUSY", "device %s is busy" % changer)
        return True

    # ---------- 位置参数解析（磁带 barcode/S003 · 带机 nst/sg/DTE/Drive-NN） ----------
    @staticmethod
    def _after_robot_move():
        """机器人动作后清掉 inventory 服务的 20s 缓存，避免 GUI 读到旧状态。"""
        try:
            from app.services.inventory import cache_clear
            cache_clear()
        except Exception:
            pass

    @staticmethod
    def _env_drive_map():
        """GATEWAY_DTE_MAP {"2":"/dev/nst1"} 反转为 nst→DTE（硬件级硬映射）。"""
        import json
        import os
        try:
            raw = json.loads(os.getenv("GATEWAY_DTE_MAP", "{}"))
        except ValueError:
            raw = {}
        out = {}
        for dte, dev in raw.items():
            d = re.sub(r"^/dev/", "", str(dev)).lower()
            if d.startswith("st") and not d.startswith("nst"):
                d = "nst" + d[2:]
            try:
                out[d] = int(dte)
            except (TypeError, ValueError):
                continue
        return out

    def _tape_devices(self):
        disc = DiscoveryService(self.runner, self.chain, self.request_id)
        try:
            devices = disc.discover()["devices"]
        except Exception:
            return []
        return [d for d in devices if d.get("device_type") == "TAPE"]

    def _drive_barcode(self, nst):
        """带机内当前磁带条码（mt + MAM）；空带/探测失败返回 None。"""
        from app.commands import parsers
        if not nst:
            return None
        try:
            rec = self.exec(self.mt.status(nst), "DRIVE_STATUS", "LEVEL_1", device=nst, timeout=20)
        except Exception:
            return None
        p = parsers.parse_mt_status(rec["stdout"])
        if not p.get("tape_online") or p.get("file_number") is None or p["file_number"] < 0:
            return None
        try:
            rec2 = self.exec(self.attr.attributes(nst), "MAM", "LEVEL_1", device=nst, timeout=20)
        except Exception:
            return None
        m = re.search(r"^\s*Barcode:\s*(\S+)", rec2["stdout"], re.M)
        return m.group(1) if m else None

    def _resolve_drive_ref(self, ref, status):
        """带机位置参数 → (mtx DTE 号, 解析方法, 备注)。
        支持：nst1 / st1 / sg2 / DTE2 / dte:2 / Drive-02(1基,lsscsi序) / 33:0:2:0。"""
        s = str(ref).strip()
        if re.fullmatch(r"\d+", s):
            return int(s), "raw_element", None
        low = re.sub(r"^/dev/", "", s).lower().replace(" ", "")
        m = re.fullmatch(r"(?:dte|element)[-_:]?(\d+)", low)
        if m:
            return int(m.group(1)), "dte_label", None
        tapes = self._tape_devices()
        nst = None
        m = re.fullmatch(r"drive[-_:]?0*(\d+)", low)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(tapes):
                nst = (tapes[idx].get("nst_device") or "").replace("/dev/", "")
        elif re.fullmatch(r"nst\d+", low):
            nst = low
        elif re.fullmatch(r"st\d+", low):
            nst = "nst" + low[2:]
        elif re.fullmatch(r"sg\d+", low):
            for d in tapes:
                if (d.get("sg_device") or "").replace("/dev/", "") == low:
                    nst = (d.get("nst_device") or "").replace("/dev/", "")
                    break
        elif re.fullmatch(r"\d+:\d+:\d+:\d+", low):
            for d in tapes:
                if d.get("scsi_address") == low:
                    nst = (d.get("nst_device") or "").replace("/dev/", "")
                    break
        if not nst:
            raise ServiceError("DRIVE_NOT_FOUND",
                               "无法解释带机位置参数: %s（支持 nst*/st*/sg*/DTE<n>/Drive-<n>/SCSI地址/mtx元素号）" % ref)
        em = self._env_drive_map()
        if nst in em:
            return em[nst], "env_map", None
        bc = self._drive_barcode(nst)
        if bc:
            hits = [x for x in status.get("drives", []) if x.get("occupied") and x.get("barcode") == bc]
            if len(hits) == 1:
                return hits[0]["drive"], "barcode_match", "按带机内磁带 %s 匹配 /dev/%s ↔ DTE%d" % (bc, nst, hits[0]["drive"])
        empties = [x for x in status.get("drives", []) if not x.get("occupied")]
        if bc is None and len(empties) == 1:
            return empties[0]["drive"], "single_empty_dte", (
                "/dev/%s 空带且无硬映射（GATEWAY_DTE_MAP 未覆盖且无在机条码可比对），"
                "按带库唯一空闲 DTE%d 推定；建议配置 GATEWAY_DTE_MAP" % (nst, empties[0]["drive"]))
        raise ServiceError("DRIVE_NOT_FOUND",
                           "带机 /dev/%s 无法映射到带库 DTE：请配置 GATEWAY_DTE_MAP 或直接使用 DTE<n>/mtx 元素号" % nst)

    @staticmethod
    def _parse_tape_position(pos):
        """磁带位置参数 → ('slot', N) | ('dte', N)。支持 S003 / s3 / slot:3 / 纯数字 / DTE2。"""
        s = str(pos).strip().lower().replace(" ", "")
        m = re.fullmatch(r"s(?:lot)?[-_:]?0*(\d+)", s) or re.fullmatch(r"(\d+)", s)
        if m:
            return "slot", int(m.group(1))
        m = re.fullmatch(r"(?:dte|element)[-_:]?(\d+)", s)
        if m:
            return "dte", int(m.group(1))
        raise ServiceError("INVALID_REQUEST",
                           "无法解析磁带位置参数: %s（支持 S003 / slot:3 / DTE2）" % pos)

    @staticmethod
    def _find_slot(status, element):
        for x in status.get("slots", []):
            if x.get("element") == element:
                return x
        return None

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
        """触发带库盘点重扫：mtx inventory（INITIALIZE ELEMENT STATUS，
        机械臂会实际扫描槽位重新读条码，耗时与槽数相关）"""
        from app.security.policy import normalize_device
        changer_n = normalize_device(changer)
        self._lock(changer_n)
        try:
            rec = self.ensure_pass(
                self.exec(self.mtx.inventory(changer), "LIBRARY_INVENTORY", "LEVEL_2",
                          device=changer_n, timeout=1800),
                "COMMAND_FAILED", "mtx inventory failed")
            return {"changer": changer_n, "command_id": rec["command_id"]}
        finally:
            self.runner.locks.release(changer_n)

    def _status_inventory(self, changer):
        """执行 mtx status 并解析为结构化槽位/驱动器清单（供 load 等内部逻辑使用）；
        统一走 parsers.parse_mtx_status（含 drive.source_slot / slot.import_export）"""
        from app.security.policy import normalize_device
        from app.commands import parsers
        changer = normalize_device(changer)
        rec = self.exec(self.mtx.status(changer), "LIBRARY_STATUS", "LEVEL_1", device=changer, timeout=120)
        parsed = parsers.parse_mtx_status(rec["stdout"])
        return {"library": {"changer": changer}, "slots": parsed["slots"],
                "drives": parsed["drives"], "command_id": rec["command_id"]}

    def load(self, changer, slot=None, drive=None, barcode=None,
             tape_position=None, drive_position=None):
        """槽位→带机装带。位置参数优先级：
        磁带: barcode(自动定位槽位) > tape_position(S003/slot:3) > slot(旧字段, mtx 元素号)
        带机: drive_position(nst1/st1/sg2/DTE2/Drive-02/SCSI地址) > drive(旧字段, mtx DTE 号)
        返回体 resolved.* 说明每个解析结果与方法。"""
        from app.security.policy import normalize_device, validate_slot, validate_drive
        self._lock(changer)
        try:
            inv = self._status_inventory(changer)
            # ① 目标带机
            method, note = "raw_element", None
            if drive_position is not None:
                drive, method, note = self._resolve_drive_ref(drive_position, inv)
            elif drive is None:
                raise ServiceError("INVALID_REQUEST",
                                   "需提供 drive（mtx 元素号）或 drive_position（nst1/DTE2/Drive-02）")
            drive = validate_drive(int(drive))
            # ② 磁带位置
            src, src_method = None, None
            if slot is not None:
                src, src_method = validate_slot(int(slot)), "slot"
            elif tape_position is not None:
                kind, val = self._parse_tape_position(tape_position)
                if kind != "slot":
                    raise ServiceError("INVALID_REQUEST",
                                       "load 的 tape_position 需为槽位（S003/slot:3）；跨带机取带请先 unload")
                src, src_method = validate_slot(val), "tape_position"
            elif barcode:
                hit = [x for x in inv["slots"] if x.get("occupied") and x.get("barcode") == barcode]
                if not hit:
                    ind = [x for x in inv["drives"] if x.get("occupied") and x.get("barcode") == barcode]
                    if ind:
                        raise ServiceError("MEDIA_IN_DRIVE",
                                           "磁带 %s 已在带机 DTE%d（需先 unload）" % (barcode, ind[0]["drive"]))
                    raise ServiceError("MEDIA_NOT_FOUND", "磁带 %s 不在带库槽位中" % barcode)
                src, src_method = validate_slot(hit[0]["element"]), "barcode_lookup"
            else:
                raise ServiceError("INVALID_REQUEST", "需提供 slot / tape_position / barcode 定位磁带")
            srec = self._find_slot(inv, src)
            if barcode and srec and srec.get("barcode") and srec["barcode"] != barcode:
                raise ServiceError("SLOT_MEDIA_MISMATCH",
                                   "槽位 S%03d 内是 %s 而非 %s" % (src, srec["barcode"], barcode))
            if not barcode and srec and srec.get("barcode"):
                barcode = srec["barcode"]
            if not (srec and srec.get("occupied")) and src_method != "barcode_lookup":
                raise ServiceError("SLOT_EMPTY", "槽位 S%03d 为空，无带可装" % src)
            # ③ 目标带机占用守卫
            for d in inv["drives"]:
                if d["drive"] == drive and d.get("barcode"):
                    raise ServiceError("MEDIA_ALREADY_LOADED",
                                       "带机 DTE%d 已有磁带 %s，请先 unload" % (drive, d["barcode"]))
            try:
                rec = self.ensure_pass(
                    self.exec(self.mtx.load(changer, src, drive), "LIBRARY_LOAD", "LEVEL_2",
                              device=changer, timeout=300),
                    "COMMAND_FAILED", "mtx load failed")
                verified, warning = True, note
            except ServiceError as e:
                # SCSI 44/00 类假失败复核（见 2026-09-19 REQ-20260919-232621-20EC6F）：
                # mtx 报错但机械臂实际到位时，以 status 为准记成功
                post = self._status_inventory(changer)
                dd = next((x for x in post["drives"] if x["drive"] == drive), None)
                if dd and dd.get("occupied") and (not barcode or dd.get("barcode") == barcode):
                    rec = e.command_record if isinstance(e.command_record, dict) else {"command_id": None}
                    verified = False
                    warning = ("mtx 报错(%s)但状态复核确认磁带已物理装载至 DTE%d — 记为 mtx_false_alarm" %
                               (str(e.message)[:160], drive))
                else:
                    raise
            self._after_robot_move()
            return {"slot": src, "drive": drive, "barcode": barcode,
                    "changer": normalize_device(changer),
                    "resolved": {"tape": "S%03d" % src, "tape_method": src_method,
                                 "drive": "DTE%d" % drive, "drive_method": method,
                                 "drive_note": note, "mtx_command": rec.get("command"),
                                 "verified_by_status": verified},
                    "warning": warning, "command_id": rec.get("command_id")}
        finally:
            self.runner.locks.release(changer)

    def unload(self, changer, slot=None, drive=None, barcode=None,
               tape_position=None, drive_position=None):
        """带机→槽位卸带。磁带: barcode(自动定位所在带机) > drive_position/drive(带机内磁带)；
        目标槽: slot(旧) > tape_position(S003) > 自动(原槽 source_slot，不行则首个空槽)。"""
        from app.security.policy import normalize_device, validate_slot, validate_drive
        self._lock(changer)
        try:
            inv = self._status_inventory(changer)
            method, note = "raw_element", None
            dte = None
            holders = ([x for x in inv["drives"] if x.get("occupied") and barcode and x.get("barcode") == barcode]
                       if barcode else [])
            if holders:
                dte, method = holders[0]["drive"], "barcode_holder"
                note = "磁带 %s 定位于带机 DTE%d" % (barcode, dte)
            elif drive_position is not None:
                dte, method, note = self._resolve_drive_ref(drive_position, inv)
            elif drive is not None:
                dte = validate_drive(int(drive))
            if dte is None:
                raise ServiceError("INVALID_REQUEST",
                                   "需提供 drive/drive_position，或 barcode（磁带在带机时）定位带机")
            cur = next((x for x in inv["drives"] if x["drive"] == dte), None)
            if not cur or not cur.get("occupied"):
                raise ServiceError("DRIVE_EMPTY", "带机 DTE%d 为空，无带可卸" % dte)
            if barcode and cur.get("barcode") and cur["barcode"] != barcode:
                raise ServiceError("SLOT_MEDIA_MISMATCH",
                                   "DTE%d 内是 %s 而非 %s" % (dte, cur["barcode"], barcode))
            bc = barcode or cur.get("barcode")
            # 目标槽：显式 slot > tape_position > 原槽 source_slot > 首个空槽
            dest, dmethod = None, None
            if slot is not None:
                dest, dmethod = validate_slot(int(slot)), "slot"
            elif tape_position is not None:
                kind, val = self._parse_tape_position(tape_position)
                if kind == "slot":
                    dest, dmethod = validate_slot(val), "tape_position"
            if dest is None and cur.get("source_slot"):
                es = self._find_slot(inv, cur["source_slot"])
                if es and not es.get("occupied"):
                    dest, dmethod = cur["source_slot"], "source_slot"
            if dest is None:
                for x in inv["slots"]:
                    if not x.get("occupied") and not x.get("import_export"):
                        dest, dmethod = x["element"], "first_empty"
                        break
            if dest is None:
                for x in inv["slots"]:
                    if not x.get("occupied"):
                        dest, dmethod = x["element"], "first_empty_ie"
                        break
            if dest is None:
                raise ServiceError("NO_EMPTY_SLOT", "带库已满，无空槽可卸带")
            if dmethod in ("slot", "tape_position"):
                ds = self._find_slot(inv, dest)
                if ds is None:
                    raise ServiceError("SLOT_NOT_FOUND", "目标槽 S%03d 不存在" % dest)
                if ds.get("occupied"):
                    raise ServiceError("SLOT_OCCUPIED",
                                       "目标槽 S%03d 已被 %s 占用，请换槽或不传（自动选原槽/空槽）"
                                       % (dest, ds.get("barcode") or "他带"))
            try:
                rec = self.ensure_pass(
                    self.exec(self.mtx.unload(changer, dest, dte), "LIBRARY_UNLOAD", "LEVEL_2",
                              device=changer, timeout=300),
                    "COMMAND_FAILED", "mtx unload failed")
                verified, warning = True, note
            except ServiceError as e:
                post = self._status_inventory(changer)
                dd = next((x for x in post["drives"] if x["drive"] == dte), None)
                ds = self._find_slot(post, dest)
                if ((not dd or not dd.get("occupied")) and ds and ds.get("occupied")
                        and (not bc or ds.get("barcode") == bc)):
                    rec = e.command_record if isinstance(e.command_record, dict) else {"command_id": None}
                    verified = False
                    warning = ("mtx 报错(%s)但状态复核确认磁带已落槽 S%03d 且带机已空 — 记为 mtx_false_alarm" %
                               (str(e.message)[:160], dest))
                else:
                    raise
            self._after_robot_move()
            return {"slot": dest, "drive": dte, "barcode": bc,
                    "changer": normalize_device(changer),
                    "resolved": {"drive": "DTE%d" % dte, "drive_method": method,
                                 "drive_note": note, "target": "S%03d" % dest,
                                 "target_method": dmethod, "mtx_command": rec.get("command"),
                                 "verified_by_status": verified},
                    "warning": warning, "command_id": rec.get("command_id")}
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

    def exchange(self, changer, source, destination):
        self._lock(changer)
        try:
            rec = self.ensure_pass(
                self.exec(self.mtx.exchange(changer, source, destination), "LIBRARY_EXCHANGE", "LEVEL_2",
                          device=changer, timeout=300),
                "COMMAND_FAILED", "mtx exchange failed")
            return {"source": source, "destination": destination, "command_id": rec["command_id"]}
        finally:
            self.runner.locks.release(changer)

    def first(self, changer):
        rec = self.ensure_pass(
            self.exec(self.mtx.first(changer), "LIBRARY_FIRST", "LEVEL_1", device=changer, timeout=120),
            "COMMAND_FAILED", "mtx first failed")
        return {"stdout": rec["stdout"], "command_id": rec["command_id"]}

    def next(self, changer):
        rec = self.ensure_pass(
            self.exec(self.mtx.next(changer), "LIBRARY_NEXT", "LEVEL_1", device=changer, timeout=120),
            "COMMAND_FAILED", "mtx next failed")
        return {"stdout": rec["stdout"], "command_id": rec["command_id"]}

    def last(self, changer):
        """仿真 mtx last：mtx 自带的 last 在 IE 槽与存储槽同段编号的库上会误判
        最后一盘磁带的位置，这里改为自行解析 status 后精确装载。"""
        from app.security.policy import normalize_device
        self._lock(changer)
        try:
            st = self.status(changer)
            slots = [s for s in st["parsed"]["slots"]
                     if s["occupied"] and not s.get("import_export")]
            if not slots:
                raise ServiceError("MEDIA_NOT_FOUND", "no tape in regular storage slots")
            last_slot = max(slots, key=lambda s: s["element"])
            rec = self.ensure_pass(
                self.exec(self.mtx.load(changer, last_slot["element"], 0), "LIBRARY_LAST",
                          "LEVEL_2", device=normalize_device(changer), timeout=300),
                "COMMAND_FAILED", "load last tape (slot %d) failed" % last_slot["element"])
            return {"slot": last_slot["element"], "barcode": last_slot.get("barcode"),
                    "drive": 0, "command_id": rec["command_id"]}
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
    def read_test(self, drive, block_size, confirm, timeout, out_file=""):
        if not confirm:
            raise ServiceError("INVALID_REQUEST", "confirm=true required")
        from app.security.policy import normalize_device, validate_output_path
        dev = normalize_device(drive)
        out = "/dev/null"
        if out_file:
            out = validate_output_path(out_file)
        if not self.runner.locks.acquire(dev):
            raise ServiceError("DEVICE_BUSY", "drive busy")
        try:
            rec = self.exec(["dd", "if=" + dev, "of=" + out, "bs=" + block_size],
                            "READ_TEST", "LEVEL_2", device=dev, timeout=timeout)
            self.ensure_pass(rec, "COMMAND_FAILED", "dd read failed")
            from app.commands import parsers
            data = {"drive": dev, "duration_ms": rec["duration_ms"], "command_id": rec["command_id"],
                    "parsed": parsers.parse_dd_summary(rec["stderr"])}
            if out != "/dev/null":
                data["file"] = out
            return data
        finally:
            self.runner.locks.release(dev)

    def write_test(self, drive, test_media, size_mb, allow_write, confirm, timeout, in_file=""):
        import os
        from app.config import settings
        if not (allow_write and settings.allow_write):
            raise ServiceError("WRITE_OPERATION_NOT_AUTHORIZED",
                               "write requires allow_write=true in request AND ALLOW_WRITE=true env")
        if not confirm:
            raise ServiceError("INVALID_REQUEST", "confirm=true required")
        if not test_media:
            raise ServiceError("MISSING_PARAMETER", "media required for write test")
        from app.security.policy import normalize_device, validate_input_path
        dev = normalize_device(drive)
        src = None
        if in_file:
            src = validate_input_path(in_file)
            if not os.path.isfile(src):
                raise ServiceError("FILE_NOT_FOUND", "input file not found: %s" % src)
        if not self.runner.locks.acquire(dev):
            raise ServiceError("DEVICE_BUSY", "drive busy")
        try:
            if src:
                argv = ["dd", "if=" + src, "of=" + dev, "bs=1M", "conv=notrunc"]
            else:
                argv = ["dd", "if=/dev/zero", "of=" + dev, "bs=1M", "count=" + str(size_mb)]
            rec = self.exec(argv, "WRITE_TEST", "LEVEL_3", device=dev, timeout=timeout)
            self.ensure_pass(rec, "COMMAND_FAILED", "dd write failed")
            from app.commands import parsers
            data = {"drive": dev, "duration_ms": rec["duration_ms"],
                    "command_id": rec["command_id"],
                    "parsed": parsers.parse_dd_summary(rec["stderr"])}
            if src:
                data["file"] = src
            else:
                data["size_mb"] = size_mb
            return data
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


class ScsiService(BaseService):
    """SCSI 通用设备操作：sg_inq / sg_vpd / sg_logs / sg_logs -p 0x2e / sg_reset / sg_persist"""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.sg = SgAdapter()

    def inquiry(self, device):
        from app.security.policy import normalize_device
        from app.commands import parsers
        dev = normalize_device(device)
        rec = self.ensure_pass(self.exec(self.sg.inquiry(dev), "SCSI_INQUIRY", "LEVEL_1", device=dev),
                               "DEVICE_NOT_FOUND")
        return {"device": dev, "stdout": rec["stdout"], "command_id": rec["command_id"],
                "parsed": parsers.parse_sg_inq(rec["stdout"])}

    def vpd(self, device, page="0x80"):
        from app.security.policy import normalize_device
        from app.commands import parsers
        dev = normalize_device(device)
        rec = self.ensure_pass(self.exec(self.sg.vpd(dev, page), "SCSI_VPD", "LEVEL_1", device=dev),
                               "COMMAND_FAILED")
        return {"device": dev, "page": page, "stdout": rec["stdout"],
                "command_id": rec["command_id"], "parsed": parsers.parse_sg_vpd(rec["stdout"])}

    def logs(self, device, page=None):
        import re as _re
        from app.security.policy import normalize_device
        dev = normalize_device(device)
        if page is not None and not _re.match(r"^0x[0-9a-fA-F]{1,4}$", page):
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail={"code": "INVALID_REQUEST",
                                                         "message": "page must be hex like 0x2e"})
        argv = ["sg_logs"] + (["-p", page] if page else []) + [dev]
        rec = self.ensure_pass(self.exec(argv, "SCSI_LOGS", "LEVEL_1", device=dev),
                               "COMMAND_FAILED")
        return {"device": dev, "stdout": rec["stdout"], "command_id": rec["command_id"]}

    def tapealert(self, device):
        from app.security.policy import normalize_device
        dev = normalize_device(device)
        rec = self.ensure_pass(self.exec(self.sg.tapealert(dev), "SCSI_TAPEALERT", "LEVEL_1",
                                          device=dev), "COMMAND_FAILED")
        return {"device": dev, "stdout": rec["stdout"], "command_id": rec["command_id"]}

    def persist(self, device):
        from app.security.policy import normalize_device
        dev = normalize_device(device)
        rec = self.ensure_pass(self.exec(["sg_persist", dev], "SCSI_PERSIST", "LEVEL_1", device=dev),
                               "COMMAND_FAILED")
        return {"device": dev, "stdout": rec["stdout"], "command_id": rec["command_id"]}

    def reset(self, device, confirm):
        from app.security.policy import normalize_device
        dev = normalize_device(device)
        if not confirm:
            raise ServiceError("INVALID_REQUEST", "confirm=true required")
        if not self.runner.locks.acquire(dev):
            raise ServiceError("DEVICE_BUSY", "device busy")
        try:
            rec = self.ensure_pass(self.exec(["sg_reset", "-d", dev], "SCSI_RESET", "LEVEL_2",
                                              device=dev, timeout=120),
                                   "RESET_FAILED", "sg_reset failed")
            return {"device": dev, "reset": "device", "command_id": rec["command_id"]}
        finally:
            self.runner.locks.release(dev)
