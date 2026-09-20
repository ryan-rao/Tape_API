"""Command adapters: whitelist wrappers around lsscsi / sg3_utils / mtx / mt.
Services never build shell strings; all argv lists are constructed here with validated args."""
from fastapi import HTTPException

from app.security.policy import (normalize_device, validate_slot, validate_drive, validate_position_operation,
                                validate_setting)


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

    def vpd(self, sg: str, page: str = "0x80"):
        if page not in ("0x80", "0x83"):
            raise HTTPException(status_code=400, detail={"code": "INVALID_REQUEST",
                                                        "message": "page must be 0x80 or 0x83"})
        return ["sg_vpd", "-p", page, normalize_device(sg)]

    def tur(self, sg: str):
        return ["sg_turs", normalize_device(sg)]

    def modes(self, sg: str):
        return ["sg_modes", "-a", normalize_device(sg)]

    def logs(self, sg: str, page=None):
        argv = ["sg_logs"]
        if page:
            argv += ["-p", page]
        argv += ["-a", normalize_device(sg)]
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
        if operation in ("rewind", "offline"):
            argv.append(operation)
        elif operation in ("eom", "eod", "seod"):
            argv.append("seod")
        else:
            count = validate_setting(count, 0, 2**31 - 1, "INVALID_COUNT")
            argv += [operation, str(count)]
        return argv

    def compression(self, nst: str):
        return ["mt", "-f", normalize_device(nst), "compression"]

    def compression_set(self, nst: str, enable: bool):
        return ["mt", "-f", normalize_device(nst), "compression", "1" if enable else "0"]

    def weof(self, nst: str, count: int = 1):
        count = validate_setting(count, 0, 2**31 - 1, "INVALID_COUNT")
        return ["mt", "-f", normalize_device(nst), "weof", str(count)]

    def wset(self, nst: str, count: int = 1):
        count = validate_setting(count, 0, 2**31 - 1, "INVALID_COUNT")
        return ["mt", "-f", normalize_device(nst), "wset", str(count)]

    def eof(self, nst: str, count: int = 1):
        # `mt eof` is an alias of `mt weof`
        return self.weof(nst, count)

    def tell(self, nst: str):
        return ["mt", "-f", normalize_device(nst), "tell"]

    def seek(self, nst: str, count: int):
        count = validate_setting(count, 0, 2**31 - 1, "INVALID_BLOCK")
        return ["mt", "-f", normalize_device(nst), "seek", str(count)]

    def rewoffl(self, nst: str):
        return ["mt", "-f", normalize_device(nst), "rewoffl"]

    def eject(self, nst: str):
        return ["mt", "-f", normalize_device(nst), "eject"]

    def retension(self, nst: str):
        return ["mt", "-f", normalize_device(nst), "retension"]

    def erase(self, nst: str, count: int = 0):
        argv = ["mt", "-f", normalize_device(nst), "erase"]
        if count:
            argv.append(str(validate_drive(count)))
        return argv

    def lock(self, nst: str):
        return ["mt", "-f", normalize_device(nst), "lock"]

    def unlock(self, nst: str):
        return ["mt", "-f", normalize_device(nst), "unlock"]

    def load(self, nst: str):
        return ["mt", "-f", normalize_device(nst), "load"]

    def setblk(self, nst: str, block_size: int):
        # 0 = variable block mode; allow 0..16MB
        block_size = validate_setting(block_size, 0, 16 * 1024 * 1024, "INVALID_BLOCK_SIZE")
        return ["mt", "-f", normalize_device(nst), "setblk", str(block_size)]

    def setdensity(self, nst: str, density: int):
        density = validate_setting(density, 0, 255, "INVALID_DENSITY")
        return ["mt", "-f", normalize_device(nst), "setdensity", str(density)]

    def setpartition(self, nst: str, partition: int):
        partition = validate_drive(partition)
        return ["mt", "-f", normalize_device(nst), "setpartition", str(partition)]

    def mkpartition(self, nst: str, count: int = 1):
        count = validate_drive(count)
        return ["mt", "-f", normalize_device(nst), "mkpartition", str(count)]

    def partseek(self, nst: str, partition: int, block: int):
        partition = validate_setting(partition, 0, 255, "INVALID_PARTITION")
        block = validate_setting(block, 0, 2**31 - 1, "INVALID_BLOCK")
        return ["mt", "-f", normalize_device(nst), "partseek", "%d,%d" % (partition, block)]

    def densities(self, nst: str):
        return ["mt", "-f", normalize_device(nst), "densities"]

    def stshowoptions(self, nst: str):
        return ["mt", "-f", normalize_device(nst), "stshowoptions"]
