"""Tape Library API configuration (env-driven, no hardcoded safety settings)."""
import os


class Settings:
    def __init__(self):
        self.tape_api_mode = os.getenv("TAPE_API_MODE", "SAFE")  # SAFE | DIAGNOSTIC | FULL
        self.allow_device_operation = os.getenv("ALLOW_DEVICE_OPERATION", "false").lower() == "true"
        self.allow_write = os.getenv("ALLOW_WRITE", "false").lower() == "true"
        self.real_hardware_test = os.getenv("REAL_HARDWARE_TEST", "false").lower() == "true"
        self.command_timeout = int(os.getenv("COMMAND_TIMEOUT", "60"))
        self.audit_dir = os.getenv("AUDIT_DIR", "./audit")
        self.test_media = os.getenv("TEST_MEDIA", "")
        self.test_drive = os.getenv("TEST_DRIVE", "")

    def level_allowed(self, risk_level: str) -> bool:
        if risk_level == "LEVEL_1":
            return True
        if risk_level == "LEVEL_2":
            return self.tape_api_mode in ("DIAGNOSTIC", "FULL") and self.allow_device_operation
        if risk_level == "LEVEL_3":
            return self.tape_api_mode == "FULL" and self.allow_write
        return False


settings = Settings()
