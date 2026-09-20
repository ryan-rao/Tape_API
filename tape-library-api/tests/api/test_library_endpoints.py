"""Per-endpoint tests for the new library robot APIs:
exchange / robot/position / robot/first / robot/next / robot/last."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.api.test_api import make_client


MTX_FIRST = "Storage Element 1:Full :VolumeTag=IBM006LA\n"
MTX_STATUS_FULL = ("Storage Element 1:Full :VolumeTag=IBM006LA\n"
                   "Storage Element 2:Empty:VolumeTag=\n"
                   "Storage Element 3 IMPORT/EXPORT:Full :VolumeTag=T00021L9\n"
                   "Data Transfer Element 0:Empty\n")


def lib(script, monkeypatch):
    return make_client(script, monkeypatch, mode="FULL")


def last_argv(c):
    argv, _ = c.app.state.runner.calls[-1]
    return argv


class TestLibraryRobot:
    def test_robot_position(self, monkeypatch):
        c = lib([], monkeypatch)
        r = c.post("/api/v1/libraries/sg1/robot/position?async=false", json={"element": 1, "confirm": True})
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["code"] == "POSITION_SUCCESS"
        assert b["data"]["element"] == 1
        assert last_argv(c) == ["mtx", "-f", "/dev/sg1", "position", "1"]

    def test_position_legacy_alias(self, monkeypatch):
        c = lib([], monkeypatch)
        r = c.post("/api/v1/libraries/sg1/position?async=false", json={"element": 1, "confirm": True})
        assert r.status_code == 200 and r.json()["code"] == "POSITION_SUCCESS"

    def test_exchange(self, monkeypatch):
        c = lib([], monkeypatch)
        r = c.post("/api/v1/libraries/sg1/exchange?async=false", json={"source": 1, "destination": 2, "confirm": True})
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["code"] == "EXCHANGE_SUCCESS"
        assert b["data"] == {"source": 1, "destination": 2, "command_id": b["data"]["command_id"]}
        assert last_argv(c) == ["mtx", "-f", "/dev/sg1", "exchange", "1", "2"]

    def test_robot_first(self, monkeypatch):
        c = lib([(0, MTX_FIRST, "")], monkeypatch)
        r = c.post("/api/v1/libraries/sg1/robot/first?async=false")
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["code"] == "FIRST_SUCCESS"
        assert "IBM006LA" in b["data"]["stdout"]
        assert last_argv(c) == ["mtx", "-f", "/dev/sg1", "first"]

    def test_robot_next(self, monkeypatch):
        c = lib([(0, "Storage Element 2:Empty:VolumeTag=\n", "")], monkeypatch)
        r = c.post("/api/v1/libraries/sg1/robot/next?async=false")
        assert r.status_code == 200, r.text
        assert r.json()["code"] == "NEXT_SUCCESS"
        assert last_argv(c) == ["mtx", "-f", "/dev/sg1", "next"]

    def test_robot_last(self, monkeypatch):
        # last 仿真：status 解析 + mtx load 最后一个非 IE 满槽
        c = lib([(0, MTX_STATUS_FULL, ""), (0, "", "")], monkeypatch)
        r = c.post("/api/v1/libraries/sg1/robot/last?async=false")
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["code"] == "LAST_SUCCESS"
        assert b["data"]["slot"] == 1  # IE 槽 3 虽满但应被忽略
        assert b["data"]["barcode"] == "IBM006LA"
        argv, _ = c.app.state.runner.calls[-1]
        assert argv == ["mtx", "-f", "/dev/sg1", "load", "1", "0"]

    def test_robot_last_no_media(self, monkeypatch):
        c = lib([(0, "Storage Element 1:Empty:VolumeTag=\n", "")], monkeypatch)
        r = c.post("/api/v1/libraries/sg1/robot/last?async=false")
        assert r.status_code in (404, 409, 400)
        assert r.json()["detail"]["code"] == "MEDIA_NOT_FOUND"

    def test_invalid_slot_rejected(self, monkeypatch):
        c = lib([], monkeypatch)
        r = c.post("/api/v1/libraries/sg1/exchange?async=false", json={"source": 0, "destination": 2, "confirm": True})
        assert r.status_code == 400

    def test_injection_rejected(self, monkeypatch):
        c = lib([], monkeypatch)
        r = c.post("/api/v1/libraries/sg1;rm/robot/position?async=false", json={"element": 1, "confirm": True})
        assert r.status_code == 400
