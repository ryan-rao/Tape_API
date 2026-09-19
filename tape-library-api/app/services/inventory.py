"""InventoryService: aggregated read-only views for GUI.

- GET /api/v1/drives/list : every local tape drive with position (SCSI addr /
  library changer + DTE), serial number (sg_inq), loaded tape (mt + MAM),
  environment (log page 0x3d param 0x20 temperature; humidity is not
  measurable on this model -> null, TapeAlert 0x2e flags only) and lifetime
  stats (log page 0x14).
- GET /api/v1/tapes/list  : every visible cartridge: barcode, media serial
  (MAM, readable only while loaded), physical location (slot / drive) and
  ledger fields merged from gateway tape_media when the DB is up.

All probes are LEVEL_1 read-only commands; individual probe failures are
collected per-drive in `errors` instead of failing the whole listing.
Results are TTL-cached (mtx status is robot-heavy: ~1-8 s per changer).
"""
import re
import threading
import time

from app.commands.adapters import MtAdapter, MtxAdapter, SgAdapter, SgAttrAdapter
from app.services.services import BaseService, DiscoveryService


_TTL = 20.0        # mtx status / environment probes: seconds
_TTL_ID = 3600.0   # serial numbers: effectively static

# LTO medium density code (MAM) -> generation
_DENSITY_LTO = {"0x40": "1", "0x41": "2", "0x42": "2", "0x44": "3",
                "0x46": "4", "0x58": "5", "0x5a": "6", "0x5c": "7",
                "0x5d": "7", "0x5e": "8", "0x62": "9"}
_cache_lock = threading.Lock()
_mtx_cache = {}      # changer -> (ts, parsed_or_None)
_env_cache = {}      # sg -> (ts, dict)
_id_cache = {}       # sg -> (ts, dict)


def _cache_get(store, key, ttl=_TTL):
    with _cache_lock:
        hit = store.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1], True
    return None, False


def _cache_put(store, key, value):
    with _cache_lock:
        store[key] = (time.time(), value)


def cache_clear():
    with _cache_lock:
        _mtx_cache.clear()
        _env_cache.clear()
        _id_cache.clear()


class InventoryService(BaseService):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.sg = SgAdapter()
        self.mt = MtAdapter()
        self.mtx = MtxAdapter()
        self.attr = SgAttrAdapter()

    # ---------------- low-level safe probes ----------------
    def _try(self, argv, phase, device=None, timeout=20):
        """Run a read-only probe; never raise. Returns (rec, error|None)."""
        try:
            rec = self.exec(argv, phase, "LEVEL_1", device=device, timeout=timeout)
        except Exception as e:  # HTTPException from validation, runner errors...
            return None, "%s: %s" % (type(e).__name__, e)
        if rec["exit_code"] != 0:
            return rec, "exit %d: %s" % (rec["exit_code"], (rec.get("stderr") or "").strip()[:160])
        return rec, None

    # ---------------- parsers (local, tolerant) ----------------
    @staticmethod
    def _parse_sg_inq(stdout):
        out = {}
        for k in ("vendor_identification", "product_identification",
                  "product_revision_level", "unit_serial_number"):
            m = re.search(r"\s*%s:\s*(.+?)\s*$" % k.replace("_", " "), stdout, re.M | re.I)
            if m:
                out[k] = m.group(1)
        return out

    @staticmethod
    def _parse_logs_text(stdout):
        out = {}
        for key, pat in (
                ("power_on_hours", r"Lifetime power on hours:\s*(\d+)"),
                ("media_loads", r"Lifetime media loads:\s*(\d+)"),
                ("cleaning_operations", r"Lifetime cleaning operations:\s*(\d+)"),
                ("head_motion_hours", r"Lifetime media motion \(head\) hours:\s*(\d+)"),
                ("hard_read_errors", r"Hard read errors:\s*(\d+)"),
                ("hard_write_errors", r"Hard write errors:\s*(\d+)"),
                ("temp_alert", r"Drive temperature:\s*(\d+)"),
                ("humid_alert", r"Drive humidity:\s*(\d+)")):
            m = re.search(pat, stdout)
            if m:
                out[key] = int(m.group(1))
        return out

    @staticmethod
    def _parse_3d_temperature(stdout):
        """sg_logs -H -p 0x3d output (sg3_utils cannot decode it; hex dump).
        Walk binary parameters; param 0x20 = drive temperature sensor, 4 bytes
        big-endian (TSD=1). Returns None when the page/param is absent."""
        data = bytes()
        for line in stdout.splitlines():
            m = re.match(r"\s+[0-9a-f]{2,5}\s+((?:[0-9a-f]{2}\s+){1,16})", line)
            if m:
                data += bytes(int(x, 16) for x in m.group(1).split())
        if len(data) < 8 or data[0] != 0x3D:
            return None
        pos = 4  # skip page header (4 bytes)
        while pos + 4 <= len(data):
            pc = (data[pos] << 8) | data[pos + 1]
            ln = ((data[pos + 2] & 0x1F) << 8) | data[pos + 3]
            val = data[pos + 4:pos + 4 + ln]
            if pc == 0x20 and ln >= 4:
                v = int.from_bytes(val[-4:], "big", signed=True)
                return v
            if ln == 0:
                break
            pos += 4 + ln
        return None

    @staticmethod
    def _parse_mam(stdout):
        out = {}
        m = re.search(r"Medium serial number:\s*(\S+)", stdout)
        if m:
            out["media_serial"] = m.group(1)
        m = re.search(r"^\s*Barcode:\s*(\S+)", stdout, re.M)
        if m:
            out["mam_barcode"] = m.group(1)
        m = re.search(r"Application vendor:\s*(\S+)", stdout)
        if m:
            out["media_vendor"] = m.group(1)
        m = re.search(r"Medium manufacture date:\s*(\d+)\s*$", stdout, re.M)
        if m:
            d = m.group(1)
            out["media_manufactured"] = "%s-%s-%s" % (d[0:4], d[4:6], d[6:8])
        m = re.search(r"Medium density code:\s*(\S+)", stdout)
        if m:
            out["media_density"] = m.group(1)
        return out

    # ---------------- topology ----------------
    def _device_identity(self, sg):
        """sg_inq serial/firmware (cached ~1h; static hardware fact)."""
        hit, fresh = _cache_get(_id_cache, sg, _TTL_ID)
        if fresh:
            return hit
        rec, err = self._try(self.sg.inquiry(sg), "INQUIRY", device=sg, timeout=15)
        info = self._parse_sg_inq(rec["stdout"]) if rec else {}
        _cache_put(_id_cache, sg, info)
        return info

    def _topology(self):
        """lsscsi devices + unique libraries (dedupe multi-path changers by SN)."""
        disc = DiscoveryService(self.runner, self.chain, self.request_id)
        data = disc.discover()
        devices = data["devices"]
        tape_devs = [d for d in devices if d["device_type"] == "TAPE"]
        changers = [d for d in devices if d["device_type"] in ("MEDIUM_CHANGER", "MEDIUMX")]
        libraries = {}  # sn -> {changer, paths, scsi_address}
        for ch in changers:
            sg = (ch.get("sg_device") or "").replace("/dev/", "")
            if not sg:
                continue
            info = self._device_identity(sg)
            sn = info.get("unit_serial_number") or sg
            lib = libraries.setdefault(sn, {"changer": sg, "paths": [sg],
                                            "scsi_address": ch.get("scsi_address"),
                                            "model": info.get("product_identification"),
                                            "status": None, "status_errors": []})
            if sg not in lib["paths"]:
                lib["paths"].append(sg)
        return tape_devs, libraries

    def _library_status(self, changer):
        """mtx status parsed, TTL-cached across requests (robot-heavy probe)."""
        hit, fresh = _cache_get(_mtx_cache, changer)
        if fresh:
            return hit
        rec, err = self._try(self.mtx.status(changer), "LIBRARY_STATUS",
                             device=changer, timeout=120)
        parsed = None
        if rec:
            from app.commands import parsers
            parsed = parsers.parse_mtx_status(rec["stdout"])
        _cache_put(_mtx_cache, changer, parsed)
        return parsed

    def _drive_environment(self, sg):
        """log pages 0x14 + 0x2e + 0x3d for one drive (sg device), TTL-cached."""
        hit, fresh = _cache_get(_env_cache, sg)
        if fresh:
            return hit
        env = {"temperature_c": None, "temperature_source": None, "humidity_pct": None,
               "alert": {}, "stats": {}}
        rec, err = self._try(self.sg.logs_page(sg, "0x14"), "LOGS", device=sg, timeout=15)
        if rec:
            env["stats"] = self._parse_logs_text(rec["stdout"])
        rec, err = self._try(self.sg.logs_page(sg, "0x2e"), "LOGS", device=sg, timeout=15)
        if rec:
            flags = self._parse_logs_text(rec["stdout"])
            env["alert"] = {"drive_temperature": flags.get("temp_alert"),
                            "drive_humidity": flags.get("humid_alert")}
        # 0x3d needs -H (full hex): default output truncates after 64 bytes
        rec, err = self._try(self.sg.logs_page(sg, "0x3d", hex_dump=True), "LOGS", device=sg, timeout=15)
        if rec:
            t = self._parse_3d_temperature(rec["stdout"])
            if t is not None:
                env["temperature_c"] = t
                env["temperature_source"] = "log_page_0x3d_param_0x20"
        _cache_put(_env_cache, sg, env)
        return env

    @staticmethod
    def _match_dte(libraries, barcode):
        """Locate a barcode among library DTEs -> (changer, dte_index, source_slot)."""
        if not barcode:
            return None
        for sn, lib in libraries.items():
            st = lib["status"] or {}
            for drv in st.get("drives", []):
                if drv.get("occupied") and drv.get("barcode") == barcode:
                    return {"changer": lib["changer"], "library_sn": sn,
                            "dte": drv["drive"], "source_slot": drv.get("source_slot")}
        return None

    # ---------------- public API ----------------
    def list_drives(self, refresh=False):
        if refresh:
            cache_clear()
        tape_devs, libraries = self._topology()
        for lib in libraries.values():
            lib["status"] = self._library_status(lib["changer"])
        drives = []
        for i, dev in enumerate(tape_devs):
            sg = (dev.get("sg_device") or "").replace("/dev/", "")
            nst = (dev.get("nst_device") or "").replace("/dev/", "")
            errors = []
            entry = {"index": i, "sg": sg or None, "st": (dev.get("st_device") or "").replace("/dev/", "") or None,
                     "nst": nst or None, "scsi_address": dev.get("scsi_address"),
                     "vendor": dev.get("vendor"), "product": dev.get("product"),
                     "firmware": None, "serial": None,
                     "state": "UNKNOWN", "loaded_tape": None, "media_serial": None,
                     "library": None, "file_number": None, "density_code": None,
                     "environment": None}
            # identity: sg_inq (serial number), cached
            info = self._device_identity(sg) if sg else {}
            entry["serial"] = info.get("unit_serial_number")
            entry["firmware"] = info.get("product_revision_level")
            entry["vendor"] = info.get("vendor_identification") or entry["vendor"]
            entry["product"] = info.get("product_identification") or entry["product"]
            # loaded media: mt status
            rec, err = self._try(self.mt.status(nst), "DRIVE_STATUS", device=nst, timeout=15) if nst else (None, "no nst device")
            if rec:
                from app.commands import parsers
                p = parsers.parse_mt_status(rec["stdout"])
                entry["file_number"] = p.get("file_number")
                entry["density_code"] = p.get("density_code")
                flags = p.get("flags") or []
                if "DR_OPEN" in flags or not p.get("tape_online") or p.get("file_number") is None:
                    entry["state"] = "EMPTY"
                elif p.get("file_number") >= 0:
                    entry["state"] = "LOADED"
            else:
                msg = (err or "").lower()
                entry["state"] = "EMPTY" if ("not ready" in msg or "medium not present" in msg
                                             or "unknown" in msg) else "ERROR"
                errors.append("mt status " + (err or ""))
            # media MAM (serial number of cartridge) when loaded
            if entry["state"] == "LOADED" and nst:
                rec, err = self._try(self.attr.attributes(nst), "MAM", device=nst, timeout=15)
                if rec:
                    mam = self._parse_mam(rec["stdout"])
                    if mam.get("media_serial"):
                        entry["media_serial"] = mam["media_serial"]
                    if mam.get("mam_barcode"):
                        entry["loaded_tape"] = mam["mam_barcode"]
                else:
                    errors.append("sg_read_attr " + (err or ""))
            # position in library: DTE match by barcode (empty drives: by elimination later)
            dte = self._match_dte(libraries, entry.get("loaded_tape"))
            entry["library"] = dte
            # environment + lifetime stats
            if sg:
                entry["environment"] = self._drive_environment(sg)
            entry["errors"] = errors
            drives.append(entry)
        return {"drives": drives, "count": len(drives),
                "libraries": [{"changer": l["changer"], "paths": l["paths"],
                               "serial": sn, "model": l["model"],
                               "loaded_drives": (l["status"] or {}).get("loaded_drives"),
                               "occupied_slots": (l["status"] or {}).get("occupied_slots")}
                              for sn, l in libraries.items()],
                "environment_note": "湿度传感器本机型(ULT3580-TDA/TS4500)不开放读取：humidity_pct=null；"
                                    "温度取 LOG SENSE 0x3d 参数 0x20；0x2e TapeAlert 仅越限告警位(0=正常)。"}

    def list_tapes(self, db=None, refresh=False):
        if refresh:
            cache_clear()
        from app.commands import parsers
        tape_devs, libraries = self._topology()
        ledger = {}
        ledger_error = None
        if db is not None:
            try:
                for row in db.tape_list():
                    ledger[row["barcode"]] = dict(row)
            except Exception as e:
                ledger_error = str(e)[:200]
        else:
            ledger_error = "gateway db not available"
        tapes, seen = [], {}
        slot_total = slot_occupied = ie_total = 0
        for sn, lib in libraries.items():
            status = self._library_status(lib["changer"])
            lib["status"] = status
            if not status:
                continue
            for slot in status.get("slots", []):
                if slot.get("import_export"):
                    ie_total += 1
                    continue
                slot_total += 1
                if slot.get("occupied") and slot.get("barcode"):
                    slot_occupied += 1
                    bc = slot["barcode"]
                    if bc in seen:
                        continue
                    seen[bc] = True
                    tapes.append(self._tape_row(bc, {"type": "slot", "slot": slot.get("slot", slot.get("element")),
                                                     "changer": lib["changer"], "library_sn": sn},
                                                ledger.get(bc)))
            for drv in status.get("drives", []):
                if drv.get("occupied") and drv.get("barcode"):
                    bc = drv["barcode"]
                    loc = {"type": "drive", "dte": drv["drive"], "changer": lib["changer"],
                           "library_sn": sn, "source_slot": drv.get("source_slot")}
                    if bc in seen:
                        for row in tapes:
                            if row["barcode"] == bc:
                                row["location"] = loc
                        continue
                    seen[bc] = True
                    tapes.append(self._tape_row(bc, loc, ledger.get(bc)))
        # media serial (MAM) for loaded cartridges + bind local nst to drive rows
        for i, dev in enumerate(tape_devs):
            nst = (dev.get("nst_device") or "").replace("/dev/", "")
            if not nst:
                continue
            rec, err = self._try(self.mt.status(nst), "DRIVE_STATUS", device=nst, timeout=15)
            if not rec:
                continue
            p = parsers.parse_mt_status(rec["stdout"])
            fn = p.get("file_number")
            if not p.get("tape_online") or fn is None or fn < 0:
                continue
            rec2, err2 = self._try(self.attr.attributes(nst), "MAM", device=nst, timeout=15)
            mam = self._parse_mam(rec2["stdout"]) if rec2 else {}
            bc = mam.get("mam_barcode")
            for row in tapes:
                if bc and row["barcode"] == bc:
                    row["sn"] = mam.get("media_serial")
                    row["media_vendor"] = mam.get("media_vendor")
                    row["manufactured"] = mam.get("media_manufactured")
                    row["location"]["nst"] = nst
                    row["file_number"] = p.get("file_number")
                    if mam.get("media_density"):
                        row["density"] = mam["media_density"]
                        row["media_type"] = "LTO"
                        row["generation"] = _DENSITY_LTO.get(mam["media_density"].lower())
        # sort: in-drive first, then by slot
        tapes.sort(key=lambda r: (r["location"]["type"] != "drive",
                                  str(r["location"].get("slot") or 0)))
        return {"tapes": tapes, "count": len(tapes),
                "slots": {"total": slot_total, "occupied": slot_occupied, "import_export": ie_total},
                "ledger": {"source": "tape_media", "merged": bool(ledger), "error": ledger_error}}

    @staticmethod
    def _tape_row(barcode, location, media):
        row = {"barcode": barcode, "sn": None, "location": location,
               "media_type": None, "generation": None,
               "state": (media or {}).get("state") or "unregistered",
               "capacity_bytes": (media or {}).get("capacity_bytes"),
               "used_bytes": (media or {}).get("used_bytes"),
               "block_records": (media or {}).get("block_records"),
               "last_filemark": (media or {}).get("last_filemark"),
               "mount_count": (media or {}).get("mount_count"),
               "bytes_written": (media or {}).get("bytes_written"),
               "registered": media is not None}
        return row
