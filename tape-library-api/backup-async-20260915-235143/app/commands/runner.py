"""Command Runner: executes whitelisted Linux commands via subprocess (shell=False),
records command_id / timing / raw stdout / stderr / exit code into the audit store."""
import datetime
import subprocess
import threading
import uuid

from app.audit.storage import AuditStorage


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


class CommandRunner:
    """Real command runner. argv list only, shell=False, timeout enforced."""

    def __init__(self, audit_storage: AuditStorage, timeout: int = 60):
        self.audit = audit_storage
        self.timeout = timeout
        self.locks = DeviceLockRegistry()

    def run(self, argv, phase="GENERAL", risk_level="LEVEL_1", device=None,
            request_id=None, audit_id=None, timeout=None) -> CommandResult:
        cmd_id = "CMD-" + uuid.uuid4().hex[:8].upper()
        started = datetime.datetime.now(datetime.timezone.utc)
        try:
            proc = subprocess.run(
                [str(a) for a in argv],
                shell=False, capture_output=True, text=True,
                timeout=timeout or self.timeout,
            )
            exit_code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
            result = "PASS" if exit_code == 0 else "FAIL"
        except subprocess.TimeoutExpired as e:
            exit_code = -1
            stdout = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = "TIMEOUT after %ss" % (timeout or self.timeout)
            result = "TIMEOUT"
        except FileNotFoundError:
            exit_code, stdout, stderr, result = 127, "", "command not found: %s" % argv[0], "FAIL"
        finished = datetime.datetime.now(datetime.timezone.utc)
        duration_ms = int((finished - started).total_seconds() * 1000)
        record = CommandResult(
            command_id=cmd_id, command=" ".join(str(a) for a in argv), phase=phase,
            risk_level=risk_level, device=device,
            started_at=started.isoformat(), finished_at=finished.isoformat(),
            duration_ms=duration_ms, exit_code=exit_code,
            stdout=stdout, stderr=stderr, result=result,
            request_id=request_id, audit_id=audit_id,
        )
        self.audit.save_command(record)
        return record


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
