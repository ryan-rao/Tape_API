"""Audit facade: request/audit/command ID chain helpers."""
import datetime
import threading
import uuid


class AuditChain:
    """Generates request / audit ids and links commands to requests."""

    def __init__(self, storage):
        self.storage = storage
        self._lock = threading.Lock()

    def new_request_id(self) -> str:
        now = datetime.datetime.now()
        seq = uuid.uuid4().hex[:6].upper()
        return "REQ-%s-%s" % (now.strftime("%Y%m%d-%H%M%S"), seq)

    def new_audit_id(self) -> str:
        return "AUDIT-%s" % uuid.uuid4().hex[:8].upper()

    def open_request(self, request_id: str, method: str, path: str):
        info = {"request_id": request_id, "method": method, "path": path,
                "audit_ids": [], "command_ids": [],
                "created_at": datetime.datetime.now().isoformat()}
        self.storage.save_request(request_id, info)
        return info

    def record(self, request_id: str, command_record: dict):
        info = self.storage.get_request(request_id) or {"request_id": request_id}
        info.setdefault("audit_ids", [])
        info.setdefault("command_ids", [])
        info["command_ids"].append(command_record["command_id"])
        self.storage.save_request(request_id, info)
