"""Archive gateway config (env-driven, mirrors app.config.Settings style)."""
import json
import os


class GatewayConfig:
    def __init__(self):
        self.enabled = os.getenv("GATEWAY_ENABLED", "true").lower() == "true"
        self.cache_dir = os.getenv("GATEWAY_CACHE_DIR", "/home/tape_api/archive-cache")
        self.db_dsn = os.getenv(
            "GATEWAY_DB_DSN", "postgresql://postgres@127.0.0.1:5432/tapegw")
        # routing + aggregation
        self.small_file_mb = int(os.getenv("GATEWAY_SMALL_FILE_MB", "64"))
        self.container_target_mb = int(os.getenv("GATEWAY_CONTAINER_TARGET_MB", "1024"))
        self.container_target_bytes = self.container_target_mb * 1024 * 1024
        self.container_flush_s = int(os.getenv("GATEWAY_CONTAINER_FLUSH_S", "120"))
        self.container_max_files = int(os.getenv("GATEWAY_CONTAINER_MAX_FILES", "4000"))
        self.container_header_reserve = int(os.getenv("GATEWAY_CONTAINER_HEADER_KB", "1024")) * 1024
        # cache management
        self.cache_quota_bytes = int(os.getenv("GATEWAY_CACHE_QUOTA_GB", "200")) * 1024 ** 3
        self.high_watermark_pct = int(os.getenv("GATEWAY_HIGH_WATERMARK_PCT", "85"))
        self.low_watermark_pct = int(os.getenv("GATEWAY_LOW_WATERMARK_PCT", "70"))
        self.min_free_gb = int(os.getenv("GATEWAY_MIN_FREE_GB", "5"))
        # tape topology
        self.drive = os.getenv("GATEWAY_DRIVE", "/dev/nst1")
        self.changer = os.getenv("GATEWAY_CHANGER", "/dev/sg1")
        try:
            self.dte_map = json.loads(os.getenv("GATEWAY_DTE_MAP", "{}"))
        except ValueError:
            self.dte_map = {}
        self.auto_load = os.getenv("GATEWAY_AUTO_LOAD", "true").lower() == "true"
        # manual-mount mode: pin the barcode an operator physically loaded into
        # GATEWAY_DRIVE; skips all robot interaction (robot down / single-drive setups)
        self.trust_drive = os.getenv("GATEWAY_TRUST_DRIVE", "")
        self.verify_write = os.getenv("GATEWAY_VERIFY_WRITE", "false").lower() == "true"
        self.tape_timeout_s = int(os.getenv("GATEWAY_TAPE_TIMEOUT_S", "3600"))
        # recall intelligence
        self.recall_hot_window_s = int(os.getenv("GATEWAY_RECALL_HOT_WINDOW_S", "60"))
        self.recall_hot_threshold = int(os.getenv("GATEWAY_RECALL_HOT_THRESHOLD", "3"))
        # workers
        self.poll_interval_s = float(os.getenv("GATEWAY_POLL_INTERVAL_S", "2"))
        self.evict_interval_s = float(os.getenv("GATEWAY_EVICT_INTERVAL_S", "30"))
        self.max_attempts = int(os.getenv("GATEWAY_MAX_ATTEMPTS", "3"))
        self.pool_min = int(os.getenv("GATEWAY_POOL_MIN", "2"))
        self.pool_max = int(os.getenv("GATEWAY_POOL_MAX", "8"))
        # optional acceleration layer (Redis); empty = disabled
        self.redis_url = os.getenv("GATEWAY_REDIS_URL", "")

    def summary(self):
        return {
            "enabled": self.enabled,
            "cache_dir": self.cache_dir,
            "db_dsn": self.db_dsn.rsplit("@", 1)[-1],
            "small_file_mb": self.small_file_mb,
            "container_target_mb": self.container_target_mb,
            "container_target_bytes": self.container_target_bytes,
            "container_flush_s": self.container_flush_s,
            "container_max_files": self.container_max_files,
            "cache_quota_gb": self.cache_quota_bytes // 1024 ** 3,
            "watermarks_pct": [self.low_watermark_pct, self.high_watermark_pct],
            "drive": self.drive,
            "changer": self.changer,
            "dte_map": self.dte_map,
            "auto_load": self.auto_load,
            "trust_drive": self.trust_drive or None,
            "verify_write": self.verify_write,
            "max_attempts": self.max_attempts,
            "redis_enabled": bool(self.redis_url),
        }
