"""Command adapters: whitelist wrappers around lsscsi / sg3_utils / mtx / mt.
Services never build shell strings; all argv lists are constructed here with validated args."""
from fastapi import HTTPException

from app.security.policy import normalize_device, validate_slot, validate_drive, validate_position_operation


class LsscsiAdapter:
    def list_all(self):  # LEVEL_1
        return ["lsscsi", "-g"]

    def scan(self):
        return ["sg_scan"]

    def map(self):
        return ["sg_map", "-i"]


class SystemProbeAdapter:
    """Kernel / driver / IBM-specific probes used in CLI test phases."""

    def lsmod(self, module):
        return ["bash", "-c", "lsmod | grep -E '(^| )%s( |$)' || true" % module]

    def ibm_nodes(self):
        return ["bash", "-c", "ls -l /dev/IBMtape* /dev/IBMchanger* 2>&1 || true"]

    def itdt(self):
        return ["bash", "-c", "command -v itdt || true"]


class SgAdapter:
    def inquiry(self, sg: str):
        return ["sg_inq", normalize_device(sg)]

    VPD_PAGES = {
        "0x00": "Supported VPD Pages",
        "0x80": "Unit Serial Number",
        "0x83": "Device Identification",
        "0xb0": "Block Limits",
        "0xb1": "Block Device Characteristics",
        "0xb2": "Logical Block Provisioning",
        "0xb4": "Management Network Addresses",
    }

    def vpd(self, sg: str, page: str = "0x80"):
        import re as _re
        if not _re.fullmatch(r"0x[0-9a-fA-F]{2}", page):
            raise HTTPException(status_code=400, detail={"code": "INVALID_REQUEST",
                                                        "message": "page must be hex like 0x80 (0x00-0xff)"})
        return ["sg_vpd", "-p", page.lower(), normalize_device(sg)]

    def tur(self, sg: str):
        return ["sg_turs", normalize_device(sg)]

    def modes(self, sg: str, page: str = None):
        if page:
            import re as _re
            if not _re.fullmatch(r"0x[0-9a-fA-F]{2}", page):
                raise HTTPException(status_code=400, detail={"code": "INVALID_REQUEST",
                                                            "message": "page must be hex like 0x0f"})
            return ["sg_modes", "--page=" + page.lower(), normalize_device(sg)]
        return ["sg_modes", "-a", normalize_device(sg)]

    def logs(self, sg: str, page=None):
        argv = ["sg_logs"]
        if page:
            argv += ["--page=" + page]
        else:
            argv += ["-a"]
        argv += [normalize_device(sg)]
        return argv

    def tapealert(self, sg: str):
        return ["sg_logs", "-p", "0x2e", normalize_device(sg)]


class MtxAdapter:
    def inquiry(self, changer: str):
        return ["mtx", "-f", normalize_device(changer), "inquiry"]

    def status(self, changer: str):
        return ["mtx", "-f", normalize_device(changer), "status"]

    def inventory(self, changer: str):
        return ["mtx", "-f", normalize_device(changer), "inventory"]

    def load(self, changer: str, slot: int, drive: int):
        return ["mtx", "-f", normalize_device(changer), "load",
                str(validate_slot(slot)), str(validate_drive(drive))]

    def unload(self, changer: str, slot: int, drive: int):
        return ["mtx", "-f", normalize_device(changer), "unload",
                str(validate_slot(slot)), str(validate_drive(drive))]

    def transfer(self, changer: str, source: int, destination: int):
        return ["mtx", "-f", normalize_device(changer), "transfer",
                str(validate_slot(source)), str(validate_slot(destination))]

    def position(self, changer: str, element: int):
        return ["mtx", "-f", normalize_device(changer), "position", str(validate_slot(element))]


class MtAdapter:
    def status(self, nst: str):
        return ["mt", "-f", normalize_device(nst), "status"]

    def position(self, nst: str, operation: str, count: int = 1):
        operation = validate_position_operation(operation)
        argv = ["mt", "-f", normalize_device(nst)]
        if operation == "rewind":
            argv.append("rewind")
        elif operation in ("offline", "eject"):
            argv.append("offline")
        elif operation in ("eom", "seod", "eod"):
            argv.append("seod")
        elif operation in ("tell", "load", "rewoffl"):
            argv.append(operation)
        else:
            count = validate_drive(count)  # non-negative
            argv += [operation, str(count)]
        return argv

    def compression(self, nst: str):
        return ["mt", "-f", normalize_device(nst), "compression"]

    def weof(self, nst: str, count: int = 1):
        count = validate_drive(count)
        return ["mt", "-f", normalize_device(nst), "weof", str(count)]

    def erase(self, nst: str):
        return ["mt", "-f", normalize_device(nst), "erase"]
