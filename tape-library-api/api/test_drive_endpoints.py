"""Per-endpoint tests for the drive API renaming plan (CLI -> REST mapping table).

Every row of the plan is covered one-by-one: exact mt argv built, HTTP method,
and API response code asserted.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.api.test_api import make_client


MT_STATUS_OUT = "SCSI 2 tape drive:\nFile number=1, block number=0, partition=0.\n"
TELL_OUT = "At block 1234.\n"
DENSITIES_OUT = "0:lto1\n"
OPTIONS_OUT = "st0: kcg=1 ssc=1\n"


def drv(script=None, monkeypatch=None):
    # FULL 模式：允许 L2 设备操作与 L3 写操作，逐项验证每个接口成功
    return make_client(script, monkeypatch, mode="FULL")


def post(c, path, body=None, code=200):
    r = c.post("/api/v1/drives/nst1" + path, json=body or {"confirm": True})
    assert r.status_code == code, (path, r.status_code, r.text)
    return r.json()


def get(c, path, code=200):
    r = c.get("/api/v1/drives/nst1" + path)
    assert r.status_code == code, (path, r.status_code, r.text)
    return r.json()


def last_argv(c):
    argv, _ = c.app.state.runner.calls[-1]
    return argv


class TestWriteMarks:
    def test_weof(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/weof", {"count": 2, "confirm": True})
        assert b["code"] == "WEOF_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "weof", "2"]

    def test_wset(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/wset", {"count": 3, "confirm": True})
        assert b["code"] == "WSET_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "wset", "3"]

    def test_eof(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/eof", {"count": 1, "confirm": True})
        assert b["code"] == "EOF_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "weof", "1"]


class TestPositionUnified:
    OPS = [("fsf", ["fsf", "4"]), ("fsfm", ["fsfm", "4"]), ("bsf", ["bsf", "4"]),
           ("bsfm", ["bsfm", "4"]), ("fsr", ["fsr", "4"]), ("bsr", ["bsr", "4"]),
           ("fss", ["fss", "4"]), ("bss", ["bss", "4"]), ("asf", ["asf", "4"])]

    def test_each_position_op(self, monkeypatch):
        for op, args in self.OPS:
            c = drv([], monkeypatch)
            b = post(c, "/position", {"operation": op, "count": 4, "confirm": True})
            assert b["code"] == "POSITION_SUCCESS", op
            assert last_argv(c) == ["mt", "-f", "/dev/nst1"] + args, op

    def test_position_invalid_op_rejected(self, monkeypatch):
        c = drv([], monkeypatch)
        post(c, "/position", {"operation": "format_c", "count": 1, "confirm": True}, code=400)


class TestTapeMotion:
    def test_rewind(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/rewind")
        assert b["code"] == "REWIND_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "rewind"]

    def test_offline(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/offline")
        assert b["code"] == "OFFLINE_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "offline"]

    def test_rewoffl(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/rewoffl")
        assert b["code"] == "REWOFFL_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "rewoffl"]

    def test_eject(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/eject")
        assert b["code"] == "EJECT_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "eject"]

    def test_retension(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/retension")
        assert b["code"] == "RETENSION_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "retension"]

    def test_eod(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/eod")
        assert b["code"] == "EOD_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "seod"]

    def test_seod(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/seod")
        assert b["code"] == "SEOD_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "seod"]

    def test_seek(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/seek", {"count": 1024, "confirm": True})
        assert b["code"] == "SEEK_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "seek", "1024"]


class TestQueries:
    def test_tell(self, monkeypatch):
        c = drv([(0, TELL_OUT, "")], monkeypatch)
        b = get(c, "/tell")
        assert b["code"] == "TELL_SUCCESS"
        assert "1234" in b["data"]["stdout"]
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "tell"]

    def test_status(self, monkeypatch):
        c = drv([(0, MT_STATUS_OUT, "")], monkeypatch)
        b = get(c, "/status")
        assert b["code"] in ("OK", "STATUS_SUCCESS", "DRIVE_STATUS")
        assert b["data"]["parsed"]
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "status"]

    def test_densities(self, monkeypatch):
        c = drv([(0, DENSITIES_OUT, "")], monkeypatch)
        b = get(c, "/densities")
        assert b["code"] == "DENSITIES_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "densities"]

    def test_options(self, monkeypatch):
        c = drv([(0, OPTIONS_OUT, "")], monkeypatch)
        b = get(c, "/options")
        assert b["code"] == "OPTIONS_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "stshowoptions"]


class TestDriveControls:
    def test_erase(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/erase")
        assert b["code"] == "ERASE_SUCCESS"
        assert last_argv(c)[:4] == ["mt", "-f", "/dev/nst1", "erase"]

    def test_lock(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/lock")
        assert b["code"] == "LOCK_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "lock"]

    def test_unlock(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/unlock")
        assert b["code"] == "UNLOCK_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "unlock"]

    def test_load(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/load")
        assert b["code"] == "LOAD_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "load"]


class TestDriveSettings:
    def test_compression_enable(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/compression", {"enable": True, "confirm": True})
        assert b["code"] == "COMPRESSION_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "compression", "1"]

    def test_compression_disable(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/compression", {"enable": False, "confirm": True})
        assert b["code"] == "COMPRESSION_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "compression", "0"]

    def test_setblk(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/block-size", {"block_size": 262144, "confirm": True})
        assert b["code"] == "SETBLK_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "setblk", "262144"]

    def test_setdensity(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/density", {"density": 0x40, "confirm": True})
        assert b["code"] == "SETDENSITY_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "setdensity", "64"]

    def test_setpartition(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/partition", {"partition": 1, "confirm": True})
        assert b["code"] == "PARTITION_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "setpartition", "1"]

    def test_mkpartition(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/partition", {"count": 2, "confirm": True})
        assert b["code"] == "PARTITION_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "mkpartition", "2"]

    def test_partseek(self, monkeypatch):
        c = drv([], monkeypatch)
        b = post(c, "/partition/seek", {"partition": 1, "block": 500, "confirm": True})
        assert b["code"] == "PARTSEEK_SUCCESS"
        assert last_argv(c) == ["mt", "-f", "/dev/nst1", "partseek", "1,500"]


class TestValidation:
    def test_injection_rejected(self, monkeypatch):
        c = drv([], monkeypatch)
        r = c.post("/api/v1/drives/nst0;rm%20-rf/rewind", json={"confirm": True})
        assert r.status_code == 400

    def test_unknown_drive_404(self, monkeypatch):
        c = drv([(1, "", "/dev/nst9: No such device")], monkeypatch)
        r = c.get("/api/v1/drives/nst9/status")
        assert r.status_code == 404

    def test_negative_count_rejected(self, monkeypatch):
        c = drv([], monkeypatch)
        post(c, "/position", {"operation": "fsf", "count": -1, "confirm": True}, code=400)
