"""Unit + API tests using MockCommandRunner — no real hardware needed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi.testclient import TestClient

from app.commands.runner import MockCommandRunner
from app.main import create_app
from app.config import Settings


def make_client(script=None, monkeypatch=None, mode="DIAGNOSTIC", allow_op=True, allow_write=True):
    if monkeypatch is not None:
        monkeypatch.setattr(Settings, "level_allowed", lambda self, lvl: {
            "LEVEL_1": True, "LEVEL_2": mode in ("DIAGNOSTIC", "FULL") and allow_op,
            "LEVEL_3": mode == "FULL" and allow_write}[lvl])
    import app.config as cfg
    monkeypatch_set = monkeypatch is not None
    app_ = create_app(audit_dir="/tmp/tape-api-test-audit", runner=MockCommandRunner(script))
    return TestClient(app_)


LSSCSI_OUTPUT = """[33:0:0:0]   tape    IBM      ULT3580-TDA      T3S0  /dev/st0   /dev/sg0
[33:0:0:1]   mediumx IBM      03584L32         2C02  /dev/sch0  /dev/sg1
"""

MTX_STATUS = """  Storage Changer /dev/sg1:3 Drives, 1840 Slots ( 255 Import/Export )
Data Transfer Element 0:Empty
Data Transfer Element 1:Full (Storage Element 6 Loaded):VolumeTag = IBM015LA
      Storage Element 1:Full :VolumeTag=IBM006LA
      Storage Element 6:Full :VolumeTag=IBM015LA
"""

SG_INQ = """standard INQUIRY:
  PQual=0  Device_type=1  RMB=1  ANSI_version=6
 Vendor identification: IBM
 Product identification: ULT3580-TDA
 Product revision level: T3S0
"""

TAPEALERT = """Tape alert page (ssc-3) [0x2e]
  Read warning: 0
  Write warning: 0
  Hard error: 0
  Cleaning Required: 1
"""


# ---------------- System / Dependencies ----------------

class TestSystemAPI:
    def test_system_info_success(self, monkeypatch):
        c = make_client([(0, 'NAME="RHEL"\n', ""), (0, "Linux node186\n", ""), (0, "node186\n", ""),
                         (0, "x86_64\n", ""), (0, "uid=0(root)\n", "")], monkeypatch)
        r = c.get("/api/v1/system/info")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True and body["code"] == "OK"
        assert "os_release" in body["data"]

    def test_system_info_command_failure(self, monkeypatch):
        c = make_client([(1, "", "cat: /etc/os-release: No such file")] * 5, monkeypatch)
        r = c.get("/api/v1/system/info")
        assert r.status_code == 200  # degraded info still returns
        assert r.json()["success"] is True


class TestDependencyAPI:
    def test_dependencies_pass(self, monkeypatch):
        script = [(0, "/usr/bin/lsscsi\n", "")] * 11 + [(0, "/usr/bin/dnf\n", "")]
        c = make_client(script, monkeypatch)
        r = c.get("/api/v1/dependencies")
        body = r.json()
        assert body["success"] is True
        assert body["data"]["gate"] == "PASS"
        assert body["data"]["package_manager"] == "dnf"

    def test_dependencies_gate_fail(self, monkeypatch):
        # 16 dependency probes (11 required + 5 optional), mtx (#9) and tar (#11) missing, then all PM probes fail
        script = [(0, "/usr/bin/lsscsi\n", "")] * 8 + [(1, "", "not found"), (0, "/usr/bin/mt\n", ""),
                                                       (1, "", "not found")] + [(0, "/usr/bin/jq\n", "")] * 5 \
                 + [(1, "", "")] * 4
        c = make_client(script, monkeypatch)
        r = c.get("/api/v1/dependencies")
        body = r.json()
        assert body["success"] is True
        assert body["data"]["gate"] == "FAIL"
        deps = {d["name"]: d for d in body["data"]["dependencies"]}
        assert deps["mtx"]["installed"] is False

    def test_dependencies_no_package_manager(self, monkeypatch):
        script = [(0, "/usr/bin/lsscsi\n", "")] * 16 + [(1, "", "")] * 4
        c = make_client(script, monkeypatch)
        r = c.get("/api/v1/dependencies")
        assert r.json()["data"]["package_manager"] is None


# ---------------- Discovery / Devices ----------------

class TestDiscoveryAPI:
    def test_discovery_success(self, monkeypatch):
        c = make_client([(0, LSSCSI_OUTPUT, "")], monkeypatch)
        r = c.get("/api/v1/discovery")
        body = r.json()
        assert body["success"] is True
        devices = body["data"]["devices"]
        assert devices[0]["device_type"] == "TAPE"
        assert devices[0]["sg_device"] == "/dev/sg0"
        assert devices[1]["device_type"] == "MEDIUMX"

    def test_discovery_command_failure(self, monkeypatch):
        c = make_client([(1, "", "lsscsi: error")], monkeypatch)
        r = c.get("/api/v1/discovery")
        assert r.status_code == 502
        assert r.json()["detail"]["code"] == "COMMAND_FAILED"


class TestDeviceAPI:
    def test_inquiry_success(self, monkeypatch):
        c = make_client([(0, SG_INQ, "")], monkeypatch)
        r = c.get("/api/v1/devices/sg2/inquiry")
        body = r.json()
        assert body["success"] is True and "ULT3580" in body["data"]["stdout"]

    def test_inquiry_invalid_device(self, monkeypatch):
        c = make_client([], monkeypatch)
        r = c.get("/api/v1/devices/sg2;rm%20-rf%20/inquiry")
        assert r.status_code == 400

    def test_inquiry_not_found(self, monkeypatch):
        c = make_client([(1, "", "sg_inq: /dev/sg9: No such device")], monkeypatch)
        r = c.get("/api/v1/devices/sg9/inquiry")
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "DEVICE_NOT_FOUND"

    def test_vpd_invalid_page(self, monkeypatch):
        c = make_client([], monkeypatch)
        r = c.get("/api/v1/devices/sg2/vpd?page=0x99")
        assert r.status_code in (400, 422)

    def test_tur_not_ready(self, monkeypatch):
        c = make_client([(1, "", "device not ready")], monkeypatch)
        r = c.get("/api/v1/devices/sg2/tur")
        body = r.json()
        assert body["data"]["ready"] is False

    def test_tapealert_parses_flags(self, monkeypatch):
        c = make_client([(0, TAPEALERT, "")], monkeypatch)
        r = c.get("/api/v1/drives/sg2/tapealert")
        alerts = r.json()["data"]["alerts"]
        assert any(a["name"] == "Cleaning Required" for a in alerts)

    def test_path_traversal_rejected(self, monkeypatch):
        c = make_client([], monkeypatch)
        r = c.get("/api/v1/devices/../../etc/passwd/inquiry")
        assert r.status_code in (400, 404)


# ---------------- Library ----------------

class TestLibraryAPI:
    def test_library_list(self, monkeypatch):
        c = make_client([(0, LSSCSI_OUTPUT, "")], monkeypatch)
        r = c.get("/api/v1/libraries")
        changers = r.json()["data"]
        assert changers[0]["sg_device"] == "/dev/sg1"

    def test_inventory_triggers_mtx_inventory(self, monkeypatch):
        c = make_client([], monkeypatch, mode="FULL")
        r = c.get("/api/v1/libraries/sg1/inventory")
        b = r.json()
        assert r.status_code == 200, r.text
        assert b["code"] == "INVENTORY_SUCCESS"
        assert b["data"]["changer"] == "/dev/sg1"
        argv, _ = c.app.state.runner.calls[-1]
        assert argv == ["mtx", "-f", "/dev/sg1", "inventory"]

    def test_load_success(self, monkeypatch):
        script = [(0, MTX_STATUS, ""), (0, "Loading media...done\n", "")]
        c = make_client(script, monkeypatch)
        r = c.post("/api/v1/libraries/sg1/load", json={"slot": 6, "drive": 0, "confirm": True})
        body = r.json()
        assert body["success"] is True and body["code"] == "LOAD_SUCCESS"

    def test_load_already_loaded(self, monkeypatch):
        script = [(0, MTX_STATUS, "")]  # DTE1 occupied
        c = make_client(script, monkeypatch)
        r = c.post("/api/v1/libraries/sg1/load", json={"slot": 6, "drive": 1, "confirm": True})
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "MEDIA_ALREADY_LOADED"

    def test_load_invalid_slot(self, monkeypatch):
        c = make_client([], monkeypatch)
        r = c.post("/api/v1/libraries/sg1/load", json={"slot": -1, "drive": 0, "confirm": True})
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "INVALID_SLOT"

    def test_load_command_failure(self, monkeypatch):
        script = [(0, MTX_STATUS, ""), (1, "", "mtx: load failed")]
        c = make_client(script, monkeypatch)
        r = c.post("/api/v1/libraries/sg1/load", json={"slot": 6, "drive": 0, "confirm": True})
        assert r.status_code == 502

    def test_load_not_authorized_in_safe_mode(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.settings, "tape_api_mode", "SAFE")
        monkeypatch.setattr(cfg.settings, "allow_device_operation", False)
        c = make_client([], None)
        r = c.post("/api/v1/libraries/sg1/load", json={"slot": 6, "drive": 0, "confirm": True})
        assert r.status_code == 403


# ---------------- Drive ----------------

class TestDriveAPI:
    def test_status_success(self, monkeypatch):
        c = make_client([(0, "SCSI 2 tape drive:\nFile number=-1\n", "")], monkeypatch)
        r = c.get("/api/v1/drives/nst1/status")
        assert r.json()["success"] is True

    def test_status_not_found(self, monkeypatch):
        c = make_client([(1, "", "mt: no such device")], monkeypatch)
        r = c.get("/api/v1/drives/nst9/status")
        assert r.status_code == 404

    def test_position_success(self, monkeypatch):
        c = make_client([(0, "", "")], monkeypatch)
        r = c.post("/api/v1/drives/nst1/position", json={"operation": "fsf", "count": 1, "confirm": True})
        assert r.json()["code"] == "POSITION_SUCCESS"

    def test_position_invalid_operation(self, monkeypatch):
        c = make_client([], monkeypatch)
        r = c.post("/api/v1/drives/nst1/position", json={"operation": "format_c", "count": 1, "confirm": True})
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "INVALID_OPERATION"

    def test_position_injection_rejected(self, monkeypatch):
        c = make_client([], monkeypatch)
        r = c.post("/api/v1/drives/nst0;rm%20-rf/position", json={"operation": "fsf", "count": 1})
        assert r.status_code in (400, 404)
        # ensure mock runner never executed anything for injection attempts
        if r.status_code == 400:
            assert c.app.state.runner.calls == []


# ---------------- Read / Write / Erase ----------------

class TestIOAPI:
    def test_read_success(self, monkeypatch):
        c = make_client([(0, "1024+0 records in\n", "1073741824 bytes copied\n")], monkeypatch)
        r = c.post("/api/v1/read", json={"drive": "/dev/nst1", "block_size": "1M", "confirm": True})
        body = r.json()
        assert body["code"] == "READ_SUCCESS" and "command_id" in body["data"]

    def test_read_to_file(self, monkeypatch):
        c = make_client([(0, "", "512 bytes copied\n")], monkeypatch)
        r = c.post("/api/v1/read", json={"drive": "/dev/nst1", "block_size": "1M",
                                         "file": "/root/f2", "confirm": True})
        body = r.json()
        assert body["code"] == "READ_SUCCESS" and body["data"]["file"] == "/root/f2"
        argv, _ = c.app.state.runner.calls[-1]
        assert argv == ["dd", "if=/dev/nst1", "of=/root/f2", "bs=1M"]

    def test_read_rejects_bad_file(self, monkeypatch):
        c = make_client([(0, "", "")], monkeypatch)
        r = c.post("/api/v1/read", json={"drive": "/dev/nst1", "file": "relative/x", "confirm": True})
        assert r.status_code == 400
        r = c.post("/api/v1/read", json={"drive": "/dev/nst1", "file": "/dev/nst0", "confirm": True})
        assert r.status_code == 400

    def test_read_legacy_alias(self, monkeypatch):
        c = make_client([(0, "", "")], monkeypatch)
        r = c.post("/api/v1/tests/read", json={"drive": "/dev/nst1", "block_size": "1M", "confirm": True})
        assert r.json()["code"] == "READ_SUCCESS"

    def test_read_requires_confirm(self, monkeypatch):
        c = make_client([(0, "", "")], monkeypatch)
        r = c.post("/api/v1/tests/read", json={"drive": "/dev/nst1", "confirm": False})
        assert r.status_code == 400

    def test_write_unauthorized(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.settings, "tape_api_mode", "FULL")
        monkeypatch.setattr(cfg.settings, "allow_write", True)
        c = make_client([], None)
        r = c.post("/api/v1/write",
                   json={"drive": "/dev/nst1", "size_mb": 1024, "allow_write": False, "confirm": True})
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "WRITE_OPERATION_NOT_AUTHORIZED"

    def test_write_success(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.settings, "tape_api_mode", "FULL")
        monkeypatch.setattr(cfg.settings, "allow_write", True)
        c = make_client([(0, "1024+0 records out\n", "1073741824 bytes copied\n")], None)
        r = c.post("/api/v1/write",
                   json={"drive": "/dev/nst1", "media": "IBM015LA", "size_mb": 1024,
                         "allow_write": True, "confirm": True})
        assert r.json()["code"] == "WRITE_SUCCESS"
        argv, _ = c.app.state.runner.calls[-1]
        assert argv == ["dd", "if=/dev/zero", "of=/dev/nst1", "bs=1M", "count=1024"]

    def test_write_legacy_alias(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.settings, "tape_api_mode", "FULL")
        monkeypatch.setattr(cfg.settings, "allow_write", True)
        c = make_client([(0, "", "")], None)
        r = c.post("/api/v1/tests/write",
                   json={"drive": "/dev/nst1", "test_media": "IBM015LA", "size_mb": 1,
                         "allow_write": True, "confirm": True})
        assert r.json()["code"] == "WRITE_SUCCESS"

    def test_write_from_file(self, monkeypatch, tmp_path):
        import app.config as cfg
        monkeypatch.setattr(cfg.settings, "tape_api_mode", "FULL")
        monkeypatch.setattr(cfg.settings, "allow_write", True)
        f = tmp_path / "f1.bin"
        f.write_bytes(b"x" * 4096)
        c = make_client([(0, "", "4096 bytes copied\n")], None)
        r = c.post("/api/v1/write",
                   json={"drive": "/dev/nst1", "media": "IBM015LA", "file": str(f),
                         "allow_write": True, "confirm": True})
        body = r.json()
        assert body["code"] == "WRITE_SUCCESS" and body["data"]["file"] == str(f)
        argv, _ = c.app.state.runner.calls[-1]
        assert argv == ["dd", "if=" + str(f), "of=/dev/nst1", "bs=1M", "conv=notrunc"]

    def test_write_file_validation(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.settings, "tape_api_mode", "FULL")
        monkeypatch.setattr(cfg.settings, "allow_write", True)
        c = make_client([], None)
        # 相对路径拒绝
        r = c.post("/api/v1/write", json={"drive": "/dev/nst1", "media": "X",
                                          "file": "rel/f", "allow_write": True, "confirm": True})
        assert r.status_code == 400
        # 设备路径拒绝
        r = c.post("/api/v1/write", json={"drive": "/dev/nst1", "media": "X",
                                          "file": "/dev/zero", "allow_write": True, "confirm": True})
        assert r.status_code == 400
        # 不存在文件拒绝
        r = c.post("/api/v1/write", json={"drive": "/dev/nst1", "media": "X",
                                          "file": "/no/such/file.bin", "allow_write": True, "confirm": True})
        assert r.status_code in (400, 404)

    def test_erase_unauthorized(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.settings, "tape_api_mode", "FULL")
        monkeypatch.setattr(cfg.settings, "allow_write", True)
        c = make_client([], None)
        r = c.post("/api/v1/tests/erase", json={"drive": "/dev/nst1", "allow_write": False, "confirm": False})
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "DESTRUCTIVE_OPERATION_NOT_AUTHORIZED"


# ---------------- Security ----------------

class TestSecurity:
    @pytest.mark.parametrize("bad", [
        "/dev/nst0;rm -rf /", "/dev/../../etc/passwd", "/dev/sg0|reboot", "`reboot`",
        "/dev/nst0$(id)", "/dev/sg0>etc", "dev/null", "",
    ])
    def test_injection_paths_rejected(self, monkeypatch, bad):
        c = make_client([], monkeypatch)
        r = c.get("/api/v1/devices/{}/inquiry".format(bad.replace("/", "%2F")))
        assert r.status_code in (400, 404), bad
        assert c.app.state.runner.calls == []

    def test_huge_slot_rejected(self, monkeypatch):
        c = make_client([], monkeypatch)
        r = c.post("/api/v1/libraries/sg1/load", json={"slot": 10 ** 12, "drive": 0, "confirm": True})
        assert r.status_code == 400

    def test_safety_endpoint(self, monkeypatch):
        c = make_client([], monkeypatch)
        r = c.get("/api/v1/safety")
        assert r.status_code == 200 and "api_mode" in r.json()


# ---------------- Audit ----------------

class TestAudit:
    def test_command_audit_roundtrip(self, monkeypatch):
        c = make_client([(0, SG_INQ, "")], monkeypatch)
        r = c.get("/api/v1/devices/sg2/inquiry")
        rid = r.headers["X-Request-ID"]
        audit = c.get("/api/v1/audit/" + rid).json()
        assert audit["success"] is True
        cmds = audit["data"]["commands"]
        assert len(cmds) >= 1 and cmds[0]["command"].startswith("sg_inq")
        cid = cmds[0]["command_id"]
        single = c.get("/api/v1/commands/" + cid).json()
        assert single["data"]["stdout"] == SG_INQ
        assert single["data"]["exit_code"] == 0

    def test_openapi_contains_all_groups(self, monkeypatch):
        c = make_client([], monkeypatch)
        spec = c.get("/openapi.json").json()
        paths = spec["paths"]
        for frag in ["/system/info", "/system/kernel", "/system/ibm", "/system/os-release", "/system/uname",
                     "/system/hostname", "/system/arch", "/system/user", "/dependencies", "/discovery/detail",
                     "/dependencies/{name}",
                     "/inquiry", "/vpd", "/tur", "/modes", "/logs",
                     "/libraries/{changer}/load", "/libraries/{changer}/inventory",
                     "/drives/{drive}/status", "/drives/{drive}/position",
                     "/drives/{drive}/weof", "/drives/{drive}/wset", "/drives/{drive}/eof",
                     "/drives/{drive}/rewind", "/drives/{drive}/offline", "/drives/{drive}/rewoffl",
                     "/drives/{drive}/eject", "/drives/{drive}/retension", "/drives/{drive}/eod",
                     "/drives/{drive}/seod", "/drives/{drive}/seek", "/drives/{drive}/tell",
                     "/drives/{drive}/densities", "/drives/{drive}/options", "/drives/{drive}/erase",
                     "/drives/{drive}/lock", "/drives/{drive}/unlock", "/drives/{drive}/load",
                     "/drives/{drive}/compression", "/drives/{drive}/block-size", "/drives/{drive}/density",
                     "/drives/{drive}/partition", "/drives/{drive}/partition/seek",
                     "/tapealert", "/diagnostics/system",
                     "/diagnostics/dmesg", "/diagnostics/journalctl",
                     "/read", "/write", "/tests/write-verify",
                     "/tests/erase", "/tests/full", "/commands/{command_id}", "/audit/{request_id}"]:
            assert any(frag in p for p in paths), frag
