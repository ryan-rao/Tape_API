"""SCSI 通用接口测试：/scsi/{device}/inquiry|vpd|logs|tapealert|persist|reset"""
from tests.api.test_api import make_client


class TestScsiAPI:
    def test_inquiry(self, monkeypatch):
        c = make_client([(0, "vendor: IBM  product: ULT3580-TDA\n", "")], monkeypatch, mode="FULL")
        r = c.get("/api/v1/scsi/sg4/inquiry")
        b = r.json()
        assert r.status_code == 200 and b["code"] == "INQUIRY_SUCCESS"
        argv, _ = c.app.state.runner.calls[-1]
        assert argv == ["sg_inq", "/dev/sg4"]

    def test_vpd_default_page(self, monkeypatch):
        c = make_client([(0, "Unit serial number: XXXX\n", "")], monkeypatch, mode="FULL")
        r = c.get("/api/v1/scsi/sg4/vpd")
        assert r.json()["code"] == "VPD_SUCCESS"
        argv, _ = c.app.state.runner.calls[-1]
        assert argv == ["sg_vpd", "-p", "0x80", "/dev/sg4"]

    def test_vpd_page_83(self, monkeypatch):
        c = make_client([(0, "", "")], monkeypatch, mode="FULL")
        r = c.get("/api/v1/scsi/sg4/vpd?page=0x83")
        assert r.json()["code"] == "VPD_SUCCESS"
        argv, _ = c.app.state.runner.calls[-1]
        assert argv == ["sg_vpd", "-p", "0x83", "/dev/sg4"]

    def test_logs(self, monkeypatch):
        c = make_client([(0, "TapeAlert page\n", "")], monkeypatch, mode="FULL")
        r = c.get("/api/v1/scsi/sg4/logs")
        assert r.json()["code"] == "LOGS_SUCCESS"
        argv, _ = c.app.state.runner.calls[-1]
        assert argv == ["sg_logs", "/dev/sg4"]

    def test_logs_page_validation(self, monkeypatch):
        c = make_client([(0, "", "")], monkeypatch, mode="FULL")
        r = c.get("/api/v1/scsi/sg4/logs?page=boom")
        assert r.status_code == 400

    def test_tapealert(self, monkeypatch):
        c = make_client([(0, "TapeAlert#1: 0\n", "")], monkeypatch, mode="FULL")
        r = c.get("/api/v1/scsi/sg4/tapealert")
        assert r.json()["code"] == "TAPEALERT_SUCCESS"
        argv, _ = c.app.state.runner.calls[-1]
        assert argv == ["sg_logs", "-p", "0x2e", "/dev/sg4"]

    def test_persist(self, monkeypatch):
        c = make_client([(0, "PR generation=0x1\n", "")], monkeypatch, mode="FULL")
        r = c.get("/api/v1/scsi/sg4/persist")
        assert r.json()["code"] == "PERSIST_SUCCESS"
        argv, _ = c.app.state.runner.calls[-1]
        assert argv == ["sg_persist", "/dev/sg4"]

    def test_reset(self, monkeypatch):
        c = make_client([(0, "", "")], monkeypatch, mode="FULL")
        r = c.post("/api/v1/scsi/sg4/reset?async=false", json={"confirm": True})
        b = r.json()
        assert r.status_code == 200 and b["code"] == "RESET_SUCCESS"
        argv, _ = c.app.state.runner.calls[-1]
        assert argv == ["sg_reset", "-d", "/dev/sg4"]

    def test_reset_requires_confirm(self, monkeypatch):
        c = make_client([(0, "", "")], monkeypatch, mode="FULL")
        r = c.post("/api/v1/scsi/sg4/reset?async=false", json={"confirm": False})
        assert r.status_code == 400

    def test_invalid_device_rejected(self, monkeypatch):
        c = make_client([(0, "", "")], monkeypatch, mode="FULL")
        r = c.get("/api/v1/scsi/sd../../inquiry")
        assert r.status_code in (400, 404)
