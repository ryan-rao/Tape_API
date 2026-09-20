"""Tests for the CLI-parity additions: system/kernel, system/ibm, discovery/detail,
logs?page=, drives/{nst}/weof, tests/write-verify."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.api.test_api import make_client


LSMOD = "st                     77824  0\n"
SG_SCAN = """/dev/sg0: scsi33 channel=0 id=0 lun=0
/dev/sg1: scsi33 channel=0 id=0 lun=1
"""
SG_MAP = """/dev/sg0  /dev/nst0  IBM       ULT3580-TDA       T3S0
/dev/sg1  IBM       03584L32          2C02
"""
VOL_STATS = """Volume statistics page [0x11]
  Volume mounts: 12
"""


class TestSystemExtensions:
    def test_kernel_check(self, monkeypatch):
        script = [(0, "st                     77824  0\n", ""),
                  (0, "sg                     53248  0\n", ""),
                  (0, "ch                     24576  0\n", ""),
                  (0, "", "")]
        c = make_client(script, monkeypatch)
        r = c.get("/api/v1/system/kernel")
        body = r.json()
        assert body["code"] == "KERNEL_CHECKED"
        assert body["data"]["st"]["loaded"] is True
        assert body["data"]["lin_tape"]["loaded"] is False

    def test_ibm_check(self, monkeypatch):
        c = make_client([(1, "", "ls: cannot access '/dev/IBMtape*': No such file"),
                         (1, "", "")], monkeypatch)
        r = c.get("/api/v1/system/ibm")
        body = r.json()
        assert body["code"] == "IBM_CHECKED"
        assert body["data"]["itdt_installed"] is False


class TestDiscoveryDetail:
    def test_scan_detail(self, monkeypatch):
        c = make_client([(0, SG_SCAN, ""), (0, SG_MAP, "")], monkeypatch)
        r = c.get("/api/v1/discovery/detail")
        body = r.json()
        assert body["code"] == "SCAN_COMPLETED"
        assert "/dev/sg0: scsi33" in body["data"]["sg_scan"]["stdout"]
        assert "ULT3580" in body["data"]["sg_map"]["stdout"]


class TestLogsPage:
    def test_logs_with_page(self, monkeypatch):
        c = make_client([(0, VOL_STATS, "")], monkeypatch)
        r = c.get("/api/v1/devices/sg2/logs?page=0x11")
        body = r.json()
        assert body["data"]["page"] == "0x11"
        assert "Volume mounts" in body["data"]["stdout"]


class TestWeof:
    def test_weof_success(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.settings, "tape_api_mode", "FULL")
        monkeypatch.setattr(cfg.settings, "allow_write", True)
        c = make_client([(0, "", "")], None)
        r = c.post("/api/v1/drives/nst1/weof", json={"count": 1, "confirm": True})
        assert r.json()["code"] == "WEOF_SUCCESS"

    def test_weof_unauthorized(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.settings, "tape_api_mode", "DIAGNOSTIC")
        c = make_client([], None)
        r = c.post("/api/v1/drives/nst1/weof", json={"count": 1, "confirm": True})
        assert r.status_code == 403


class TestWriteVerify:
    def test_write_verify_success(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.settings, "tape_api_mode", "FULL")
        monkeypatch.setattr(cfg.settings, "allow_write", True)
        # rewind, dd write, weof, rewind, dd read, rewind, cmp
        script = [(0, "", ""), (0, "256+0 records out\n", "268435456 bytes copied\n"),
                  (0, "", ""), (0, "", ""), (0, "256+0 records in\n", "268435456 bytes copied\n"),
                  (0, "", ""), (0, "CONTENT_VERIFY_OK\n", "")]
        c = make_client(script, None)
        r = c.post("/api/v1/tests/write-verify",
                   json={"drive": "/dev/nst1", "test_media": "IBM015LA", "size_mb": 256,
                         "allow_write": True, "confirm": True})
        body = r.json()
        assert body["code"] == "WRITE_VERIFY_PASS"
        assert body["data"]["content_verified"] is True
        assert len(body["data"]["steps"]) == 5

    def test_write_verify_unauthorized(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.settings, "tape_api_mode", "FULL")
        monkeypatch.setattr(cfg.settings, "allow_write", True)
        c = make_client([], None)
        r = c.post("/api/v1/tests/write-verify",
                   json={"drive": "/dev/nst1", "size_mb": 256, "allow_write": False, "confirm": True})
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "WRITE_OPERATION_NOT_AUTHORIZED"

    def test_write_verify_requires_media(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.settings, "tape_api_mode", "FULL")
        monkeypatch.setattr(cfg.settings, "allow_write", True)
        c = make_client([], None)
        r = c.post("/api/v1/tests/write-verify",
                   json={"drive": "/dev/nst1", "size_mb": 256, "allow_write": True, "confirm": True})
        assert r.status_code == 400
