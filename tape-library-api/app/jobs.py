"""Async job infrastructure: run long-running service calls as background jobs.

Design:
- POST endpoints accept work -> 202 + {job_id}; actual service call runs in a
  daemon thread via JobManager.submit().
- Jobs are persisted as JSON under <audit_dir>/jobs/<job_id>.json; on restart,
  any queued/running job is marked failed/INTERRUPTED (recoverable audit trail).
- Device locks stay inside services (acquire/release around exec), so lock
  lifecycle == job lifecycle automatically; DEVICE_BUSY becomes a job error.
- job_id links to the original request_id, keeping the audit chain intact.
"""
import datetime
import json
import os
import threading
import time
import uuid

JOB_STATES = ("queued", "running", "succeeded", "failed", "cancelled")


class JobCancelled(Exception):
    """Raised inside runner when a job's process was killed by cancel."""


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Job:
    FIELDS = ("job_id", "name", "endpoint", "state", "created_at", "started_at",
              "finished_at", "duration_ms", "request_id", "devices", "result",
              "error", "progress", "command_ids", "cancel_requested", "steps")

    def __init__(self, job_id, name, endpoint, request_id="", devices=()):
        self.job_id = job_id
        self.name = name
        self.endpoint = endpoint
        self.state = "queued"
        self.created_at = _now_iso()
        self.started_at = None
        self.finished_at = None
        self.duration_ms = None
        self.request_id = request_id
        self.devices = list(devices or [])
        self.result = None
        self.error = None            # {"code": ..., "message": ...}
        self.progress = None         # {"elapsed_s":..., "bytes":..., ...}
        self.command_ids = []
        self.cancel_requested = False
        self.steps = []
        # ---- runtime-only (not persisted) ----
        self.cancel_event = threading.Event()
        self._proc = None
        self._proc_lock = threading.Lock()
        self.on_update = None        # set by JobManager: throttled persist
        self._last_persist = 0.0

    # -- process control (called from runner streaming path) --
    def register_proc(self, proc):
        with self._proc_lock:
            self._proc = proc
            kill_now = self.cancel_requested
        if kill_now:
            self._kill_proc()

    def unregister_proc(self):
        with self._proc_lock:
            self._proc = None

    def _kill_proc(self):
        import signal
        with self._proc_lock:
            proc = self._proc
        if proc is None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass

    def request_cancel(self):
        self.cancel_requested = True
        self.cancel_event.set()
        self._kill_proc()

    def attach_command(self, command_id):
        if command_id and command_id not in self.command_ids:
            self.command_ids.append(command_id)

    def touch_progress(self, prog):
        """Called by runner streaming loop; throttled persistence."""
        self.progress = prog
        now = time.monotonic()
        if self.on_update is not None and (now - self._last_persist) > 2.0:
            self._last_persist = now
            try:
                self.on_update()
            except Exception:
                pass

    def to_dict(self, brief=False):
        d = {k: getattr(self, k) for k in self.FIELDS}
        if d.get("progress"):
            d["progress"] = dict(d["progress"])
        if brief:
            d.pop("result", None)
            d.pop("steps", None)
        return d

    @classmethod
    def from_dict(cls, d):
        j = cls(d.get("job_id", ""), d.get("name", ""), d.get("endpoint", ""),
                d.get("request_id", ""), d.get("devices") or ())
        for k in ("state", "created_at", "started_at", "finished_at", "duration_ms",
                  "result", "error", "progress", "command_ids", "cancel_requested", "steps"):
            setattr(j, k, d.get(k))
        return j


class JobManager:
    """In-memory registry + JSON persistence. Single-process (uvicorn single worker)."""

    def __init__(self, base_dir="./audit", runner=None):
        self.dir = os.path.join(base_dir, "jobs")
        os.makedirs(self.dir, exist_ok=True)
        self.runner = runner
        self._jobs = {}
        self._lock = threading.Lock()
        self._recover()

    # ---------- persistence ----------
    def _path(self, job_id):
        return os.path.join(self.dir, job_id + ".json")

    def _persist(self, job, force=True):
        if not force and job.on_update is None:
            return
        try:
            with open(self._path(job.job_id), "w") as f:
                json.dump(job.to_dict(), f, indent=1, ensure_ascii=False)
        except OSError:
            pass

    def _recover(self):
        """Mark jobs that were queued/running before a restart as interrupted."""
        try:
            names = os.listdir(self.dir)
        except OSError:
            return
        for fn in names:
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.dir, fn)) as f:
                    d = json.load(f)
                job = Job.from_dict(d)
            except (OSError, ValueError, TypeError, KeyError):
                continue
            if job.state in ("queued", "running"):
                job.state = "failed"
                job.error = {"code": "INTERRUPTED",
                             "message": "job interrupted by service restart"}
                job.finished_at = _now_iso()
                try:
                    with open(self._path(job.job_id), "w") as f:
                        json.dump(job.to_dict(), f, indent=1, ensure_ascii=False)
                except OSError:
                    pass
            with self._lock:
                self._jobs[job.job_id] = job

    # ---------- public API ----------
    def submit(self, name, endpoint, target, request_id="", devices=()):
        job = Job("JOB-" + uuid.uuid4().hex[:8].upper(), name, endpoint,
                  request_id, devices)
        job.on_update = lambda: self._persist(job, force=False)
        with self._lock:
            self._jobs[job.job_id] = job
        self._persist(job)
        t = threading.Thread(target=self._worker, args=(job, target),
                             daemon=True, name="job-%s" % job.job_id)
        t.start()
        return job

    def _worker(self, job, target):
        job.state = "running"
        job.started_at = _now_iso()
        self._persist(job)
        runner, began = self.runner, False
        started = time.monotonic()
        try:
            if runner is not None and hasattr(runner, "begin_job"):
                runner.begin_job(job)
                began = True
            if job.cancel_event.is_set():
                raise JobCancelled()
            data = target()
            if job.cancel_event.is_set():
                raise JobCancelled()
            job.state = "succeeded"
            if data is not None and hasattr(data, "model_dump"):
                data = data.model_dump()  # ApiResponse -> plain dict for persistence
            job.result = data
        except JobCancelled:
            job.state = "cancelled"
            job.error = {"code": "CANCELLED", "message": "job cancelled by user"}
        except Exception as e:
            job.state = "failed"
            code, message = "INTERNAL_ERROR", str(e) or e.__class__.__name__
            try:  # ServiceError from app.services.services
                from app.services.services import ServiceError
                if isinstance(e, ServiceError):
                    code, message = e.code, e.message
            except Exception:
                pass
            try:  # HTTPException from app.security.policy validation
                from fastapi import HTTPException
                if isinstance(e, HTTPException):
                    detail = e.detail
                    if isinstance(detail, dict):
                        code = detail.get("code", "HTTP_%s" % e.status_code)
                        message = detail.get("message", "") or code
                    else:
                        code, message = "HTTP_%s" % e.status_code, str(detail)
            except Exception:
                pass
            job.error = {"code": code, "message": message}
        finally:
            job.finished_at = _now_iso()
            job.duration_ms = int((time.monotonic() - started) * 1000)
            if began:
                try:
                    runner.end_job()
                except Exception:
                    pass
            self._persist(job)

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
        if job is not None:
            return job
        # disk fallback: another uvicorn worker/process may own the job
        try:
            with open(self._path(job_id)) as f:
                d = json.load(f)
            job = Job.from_dict(d)
            with self._lock:
                self._jobs.setdefault(job_id, job)
            return self._jobs.get(job_id)
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def list(self, status=None, limit=50, offset=0):
        with self._lock:
            jobs = list(self._jobs.values())
        if status:
            jobs = [j for j in jobs if j.state == status]
        jobs.sort(key=lambda j: j.created_at or "", reverse=True)
        return [j.to_dict(brief=True) for j in jobs[offset:offset + max(1, limit)]]

    def cancel(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job.state not in ("queued", "running"):
            return job
        job.request_cancel()
        self._persist(job)
        return job
