"""Command Runner: executes whitelisted Linux commands via subprocess (shell=False),
records command_id / timing / raw stdout / stderr / exit code into the audit store.

Async-job support: when a job is bound to the current thread (begin_job), commands
run through a streaming Popen path (separate process group) that provides
byte-level dd progress (status=progress), timeout kills and cooperative
cancellation (process-group SIGKILL). Non-job requests keep the original
subprocess.run behavior bit-for-bit."""
import datetime
import os
import re
import selectors
import signal
import subprocess
import threading
import time
import uuid

from app.audit.storage import AuditStorage
from app.jobs import JobCancelled


class CommandResult(dict):
    pass


class DeviceLockRegistry:
    def __init__(self):
        self._locks: dict = {}
        self._guard = threading.Lock()

    def acquire(self, device: str) -> bool:
        with self._guard:
            lock = self._locks.setdefault(device, threading.Lock())
            return lock.acquire(blocking=False)

    def release(self, device: str):
        with self._guard:
            lock = self._locks.get(device)
            if lock is not None:
                try:
                    lock.release()
                except RuntimeError:
                    pass


# ---------- dd progress parsing helpers ----------
_DD_PROGRESS_RE = re.compile(r"(\d+) bytes \(([^)]*)\) copied, ([\d.]+) s(?:, ([\d.]+ \S+?/s))?")

_BS_UNITS = {"": 1, "c": 1, "w": 2, "b": 512, "k": 1024, "K": 1024,
             "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4, "P": 1024 ** 5}


def _parse_dd_progress(text: str):
    """Extract the last dd status=progress line from a stderr tail buffer.
    dd flushes progress with \\r separators, so split on both \\r and \\n."""
    prog = None
    for seg in re.split(r"[\r\n]", text):
        m = _DD_PROGRESS_RE.search(seg)
        if m:
            prog = {"bytes": int(m.group(1)), "bytes_human": m.group(2),
                    "seconds": float(m.group(3))}
            if m.group(4):
                prog["rate"] = m.group(4)
    return prog


def _dd_total_bytes(argv):
    """Estimate total bytes for dd from bs=/count= args (for percent progress)."""
    bs_s = count_s = None
    for a in argv:
        if a.startswith("bs="):
            bs_s = a[3:]
        elif a.startswith("count="):
            count_s = a[6:]
    if not bs_s or not count_s or not count_s.isdigit():
        return None
    m = re.match(r"^(\d+)([cwbkKMGT]?)B?$", bs_s)
    if not m:
        return None
    try:
        return int(m.group(1)) * _BS_UNITS[m.group(2)] * int(count_s)
    except (KeyError, ValueError):
        return None


def _kill_group(proc):
    """Kill the whole process group (dd | cmp pipelines included)."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


class CommandRunner:
    """Real command runner. argv list only, shell=False, timeout enforced."""

    def __init__(self, audit_storage: AuditStorage, timeout: int = 60):
        self.audit = audit_storage
        self.timeout = timeout
        self.locks = DeviceLockRegistry()

    # ---------- job binding (thread-local; job worker threads only) ----------
    def _current_job(self):
        tl = getattr(self, "_job_local", None)
        return getattr(tl, "job", None) if tl is not None else None

    def begin_job(self, job):
        if not hasattr(self, "_job_local"):
            self._job_local = threading.local()
        self._job_local.job = job

    def end_job(self):
        if hasattr(self, "_job_local"):
            self._job_local.job = None

    # ---------- execution ----------
    def run(self, argv, phase="GENERAL", risk_level="LEVEL_1", device=None,
            request_id=None, audit_id=None, timeout=None) -> CommandResult:
        cmd_id = "CMD-" + uuid.uuid4().hex[:8].upper()
        argv = [str(a) for a in argv]
        job = self._current_job()
        if job is not None:
            job.attach_command(cmd_id)
        effective_timeout = timeout or self.timeout
        started = datetime.datetime.now(datetime.timezone.utc)
        if job is not None:
            try:
                exit_code, stdout, stderr, result = self._run_streaming(
                    argv, job, effective_timeout)
            except JobCancelled:
                record = self._make_record(
                    cmd_id, argv, phase, risk_level, device, started,
                    request_id=request_id, audit_id=audit_id,
                    exit_code=-1, stdout="", stderr="cancelled by user",
                    result="CANCELLED")
                self.audit.save_command(record)
                raise
        else:
            try:
                proc = subprocess.run(
                    argv,
                    shell=False, capture_output=True, text=True,
                    timeout=effective_timeout,
                )
                exit_code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
                result = "PASS" if exit_code == 0 else "FAIL"
            except subprocess.TimeoutExpired as e:
                exit_code = -1
                stdout = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
                stderr = "TIMEOUT after %ss" % effective_timeout
                result = "TIMEOUT"
            except FileNotFoundError:
                exit_code, stdout, stderr, result = 127, "", "command not found: %s" % argv[0], "FAIL"
        record = self._make_record(cmd_id, argv, phase, risk_level, device, started,
                                   request_id=request_id, audit_id=audit_id,
                                   exit_code=exit_code, stdout=stdout, stderr=stderr,
                                   result=result)
        self.audit.save_command(record)
        return record

    @staticmethod
    def _make_record(cmd_id, argv, phase, risk_level, device, started,
                     request_id, audit_id, exit_code, stdout, stderr, result):
        finished = datetime.datetime.now(datetime.timezone.utc)
        duration_ms = int((finished - started).total_seconds() * 1000)
        return CommandResult(
            command_id=cmd_id, command=" ".join(str(a) for a in argv), phase=phase,
            risk_level=risk_level, device=device,
            started_at=started.isoformat(), finished_at=finished.isoformat(),
            duration_ms=duration_ms, exit_code=exit_code,
            stdout=stdout, stderr=stderr, result=result,
            request_id=request_id, audit_id=audit_id,
        )

    # ---------- streaming path (job-bound requests only) ----------
    def _run_streaming(self, argv, job, timeout):
        stream_argv = list(argv)
        is_dd = os.path.basename(stream_argv[0]) == "dd"
        if is_dd and not any(a.startswith("status=") for a in stream_argv):
            stream_argv.append("status=progress")
        total = _dd_total_bytes(stream_argv) if is_dd else None
        proc = subprocess.Popen(
            stream_argv, shell=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True)  # own process group -> group kill on cancel
        job.register_proc(proc)
        started = time.monotonic()
        out_buf, err_buf, err_tail = [], [], ""
        timed_out = False
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout.fileno(), selectors.EVENT_READ, "out")
        sel.register(proc.stderr.fileno(), selectors.EVENT_READ, "err")
        open_fds = 2
        try:
            while open_fds > 0:
                if job.cancel_event.is_set():
                    _kill_group(proc)
                    raise JobCancelled()
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    timed_out = True
                    _kill_group(proc)
                    break
                for key, _mask in sel.select(timeout=min(0.5, remaining)):
                    data = os.read(key.fd, 65536)
                    if not data:
                        sel.unregister(key.fd)
                        open_fds -= 1
                        continue
                    text = data.decode(errors="replace")
                    if key.data == "out":
                        out_buf.append(text)
                    else:
                        err_buf.append(text)
                        err_tail = (err_tail + text)[-1024:]
                # throttled progress update (persisted at most every 2s by Job)
                payload = {"elapsed_s": round(time.monotonic() - started, 1)}
                if is_dd:
                    prog = _parse_dd_progress(err_tail)
                    if prog:
                        payload.update(prog)
                        if total:
                            payload["bytes_total"] = total
                            payload["percent"] = round(
                                min(100.0, prog["bytes"] * 100.0 / total), 2)
                job.touch_progress(payload)
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                _kill_group(proc)
                proc.wait(timeout=10)
            if job.cancel_event.is_set():
                raise JobCancelled()
            stdout_text = "".join(out_buf)
            stderr_text = "".join(err_buf)
            if timed_out:
                return -1, stdout_text, stderr_text + "\nTIMEOUT after %ss" % timeout, "TIMEOUT"
            return (proc.returncode, stdout_text, stderr_text,
                    "PASS" if proc.returncode == 0 else "FAIL")
        finally:
            job.unregister_proc()
            sel.close()
            for pipe in (proc.stdout, proc.stderr):
                try:
                    pipe.close()
                except OSError:
                    pass


class MockCommandRunner(CommandRunner):
    """Mock runner for unit/API tests — no hardware required.

    responses: {(argv[0], key-args...): (exit_code, stdout, stderr)} or callable.
    Simplest: map tuple(argv) prefix match."""
    name = "mock"

    def __init__(self, script=None):
        self.script = script or []  # list of (exit_code, stdout, stderr) popped in order
        self.calls = []
        self.locks = DeviceLockRegistry()
        self.audit = None  # wired by create_app

    def run(self, argv, **kw):
        argv = [str(a) for a in argv]
        self.calls.append((argv, kw))
        if self.script:
            exit_code, stdout, stderr = self.script.pop(0)
        else:
            exit_code, stdout, stderr = 0, "", ""
        cmd_id = "CMD-" + uuid.uuid4().hex[:8].upper()
        job = self._current_job()
        if job is not None:
            job.attach_command(cmd_id)
            if job.cancel_event.is_set():
                raise JobCancelled()
            job.touch_progress({"elapsed_s": 0.1, "command": argv[0] if argv else ""})
        record = CommandResult(
            command_id=cmd_id, command=" ".join(argv), phase=kw.get("phase", "GENERAL"),
            risk_level=kw.get("risk_level", "LEVEL_1"), device=kw.get("device"),
            started_at="2026-01-01T00:00:00+00:00", finished_at="2026-01-01T00:00:01+00:00",
            duration_ms=1000, exit_code=exit_code, stdout=stdout, stderr=stderr,
            result="PASS" if exit_code == 0 else "FAIL",
            request_id=kw.get("request_id"), audit_id=kw.get("audit_id"),
        )
        if self.audit is not None:
            self.audit.save_command(record)
        return record
