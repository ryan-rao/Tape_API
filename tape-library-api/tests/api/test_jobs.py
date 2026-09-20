"""Async job API tests: 202 submission, polling, sync compat, cancel, recovery."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi.testclient import TestClient

from app.commands.runner import MockCommandRunner
from app.config import Settings
from app.jobs import JobManager
from app.main import create_app


def make_client(script=None, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr(Settings, "level_allowed", lambda self, lvl: {
            "LEVEL_1": True, "LEVEL_2": True, "LEVEL_3": True}[lvl])
    app_ = create_app(audit_dir=tempfile.mkdtemp(prefix="tape-jobs-test-"),
                      runner=MockCommandRunner(script))
    return TestClient(app_)


DD_STDERR = ("1024+0 records in\n1024+0 records out\n"
             "1073741824 bytes (1.1 GB, 1.0 GiB) copied, 4.4 s, 243 MB/s\n")


def wait_terminal(c, job_id, timeout=10):
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        body = c.get("/api/v1/jobs/%s" % job_id).json()["data"]
        if body["state"] in ("succeeded", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    pytest.fail("job %s not terminal: %s" % (job_id, body))


class TestJobSubmission:
    def test_read_test_returns_202_and_job_id(self, monkeypatch):
        c = make_client([(0, "", DD_STDERR)], monkeypatch)
        r = c.post("/api/v1/read",
                   json={"drive": "/dev/nst1", "block_size": "1M", "confirm": True})
        assert r.status_code == 202
        body = r.json()
        assert body["success"] is True
        assert body["code"] == "JOB_SUBMITTED"
        job_id = body["data"]["job_id"]
        assert job_id.startswith("JOB-")
        assert body["data"]["poll_url"] == "/api/v1/jobs/%s" % job_id

        final = wait_terminal(c, job_id)
        assert final["state"] == "succeeded", final.get("error")
        assert final["result"]["code"] == "READ_SUCCESS"
        assert final["result"]["data"]["parsed"]["bytes"] == 1073741824
        assert final["duration_ms"] is not None

    def test_job_links_request_and_commands(self, monkeypatch):
        c = make_client([(0, "", DD_STDERR)], monkeypatch)
        r = c.post("/api/v1/read", json={"drive": "/dev/nst1", "confirm": True})
        job_id = r.json()["data"]["job_id"]
        final = wait_terminal(c, job_id)
        assert final["request_id"]
        assert final["command_ids"], "command ids should be attached to job"
        # audit chain: request record must include the same command ids
        audit = c.get("/api/v1/audit/%s" % final["request_id"]).json()["data"]
        for cid in final["command_ids"]:
            assert cid in audit["command_ids"]

    def test_sync_compat_query_and_header(self, monkeypatch):
        c = make_client([(0, "", DD_STDERR)], monkeypatch)
        r = c.post("/api/v1/read?async=false",
                   json={"drive": "/dev/nst1", "confirm": True})
        assert r.status_code == 200
        assert r.json()["data"]["parsed"]["bytes"] == 1073741824
        c2 = make_client([(0, "", DD_STDERR)], monkeypatch)
        r2 = c2.post("/api/v1/read", json={"drive": "/dev/nst1", "confirm": True},
                     headers={"X-Sync": "true"})
        assert r2.status_code == 200

    def test_service_error_becomes_job_failure(self, monkeypatch):
        c = make_client([(1, "", "dd: /dev/nst1: No such device")], monkeypatch)
        r = c.post("/api/v1/read", json={"drive": "/dev/nst1", "confirm": True})
        job_id = r.json()["data"]["job_id"]
        final = wait_terminal(c, job_id)
        assert final["state"] == "failed"
        assert final["error"]["code"] == "COMMAND_FAILED"

    def test_validation_error_becomes_job_failure(self, monkeypatch):
        c = make_client([], monkeypatch)
        r = c.post("/api/v1/read",
                   json={"drive": "/dev/nst1", "file": "relative/x", "confirm": True})
        assert r.status_code == 202
        final = wait_terminal(c, r.json()["data"]["job_id"])
        assert final["state"] == "failed"
        assert final["error"]["code"] == "INVALID_PATH"


class TestJobEndpoints:
    def test_list_jobs(self, monkeypatch):
        c = make_client([(0, "", DD_STDERR)], monkeypatch)
        c.post("/api/v1/read", json={"drive": "/dev/nst1", "confirm": True})
        r = c.get("/api/v1/jobs")
        assert r.status_code == 200
        items = r.json()["data"]
        assert len(items) >= 1
        assert all("result" not in i for i in items), "list view must be brief"
        r2 = c.get("/api/v1/jobs", params={"status": "succeeded"})
        assert all(i["state"] == "succeeded" for i in r2.json()["data"])

    def test_unknown_job_404_envelope(self, monkeypatch):
        c = make_client([], monkeypatch)
        r = c.get("/api/v1/jobs/JOB-NOPE")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is False and body["code"] == "JOB_NOT_FOUND"

    def test_cancel_finished_job_is_noop(self, monkeypatch):
        c = make_client([(0, "", DD_STDERR)], monkeypatch)
        job_id = c.post("/api/v1/read", json={"drive": "/dev/nst1",
                                              "confirm": True}).json()["data"]["job_id"]
        wait_terminal(c, job_id)
        r = c.post("/api/v1/jobs/%s/cancel" % job_id)
        body = r.json()
        assert body["code"] == "CANCEL_REQUESTED"
        assert body["data"]["state"] == "succeeded", "cancel after finish must not change state"


class TestJobManager:
    def test_restart_recovery_marks_interrupted(self):
        d = tempfile.mkdtemp(prefix="tape-jobs-recover-")
        running = {"job_id": "JOB-OLDRUN1", "name": "write-test", "endpoint": "/api/v1/write",
                   "state": "running", "request_id": "REQ-OLD", "devices": ["/dev/nst1"],
                   "created_at": "2026-01-01T00:00:00+00:00", "command_ids": []}
        os.makedirs(os.path.join(d, "jobs"), exist_ok=True)
        with open(os.path.join(d, "jobs", "JOB-OLDRUN1.json"), "w") as f:
            json.dump(running, f)
        mgr = JobManager(d)
        job = mgr.get("JOB-OLDRUN1")
        assert job is not None
        assert job.state == "failed"
        assert job.error["code"] == "INTERRUPTED"

    def test_job_persisted_to_disk(self, monkeypatch):
        c = make_client([(0, "", DD_STDERR)], monkeypatch)
        job_id = c.post("/api/v1/read", json={"drive": "/dev/nst1",
                                              "confirm": True}).json()["data"]["job_id"]
        wait_terminal(c, job_id)
        # find the jobs dir under the temp audit dir
        from app.jobs import JobManager as JM
        # locate persisted file via app state
        mgr = c.app.state.jobs
        p = os.path.join(mgr.dir, job_id + ".json")
        assert os.path.exists(p)
        with open(p) as f:
            d = json.load(f)
        assert d["state"] == "succeeded"
