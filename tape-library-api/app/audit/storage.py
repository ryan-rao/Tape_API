"""Audit storage: persists raw command outputs, requests, sessions under audit dir."""
import json
import os
import threading


class AuditStorage:
    def __init__(self, base_dir: str = "./audit"):
        self.base_dir = base_dir
        self._seq_lock = threading.Lock()
        self._commands: dict = {}
        self._requests: dict = {}
        os.makedirs(os.path.join(base_dir, "commands"), exist_ok=True)
        os.makedirs(os.path.join(base_dir, "requests"), exist_ok=True)
        os.makedirs(os.path.join(base_dir, "sessions"), exist_ok=True)
        os.makedirs(os.path.join(base_dir, "reports"), exist_ok=True)

    def save_command(self, record: dict):
        cid = record["command_id"]
        self._commands[cid] = record
        d = os.path.join(self.base_dir, "commands", cid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "command.json"), "w") as f:
            json.dump(record, f, indent=1)
        with open(os.path.join(d, "stdout.txt"), "w") as f:
            f.write(record.get("stdout", ""))
        with open(os.path.join(d, "stderr.txt"), "w") as f:
            f.write(record.get("stderr", ""))

    def get_command(self, cid: str):
        return self._commands.get(cid)

    def list_commands(self, request_id: str = None):
        if request_id:
            return [c for c in self._commands.values() if c.get("request_id") == request_id]
        return list(self._commands.values())

    def save_request(self, request_id: str, info: dict):
        self._requests[request_id] = info
        with open(os.path.join(self.base_dir, "requests", request_id + ".json"), "w") as f:
            json.dump(info, f, indent=1)

    def get_request(self, request_id: str):
        return self._requests.get(request_id)
