"""Archive gateway config.

三层优先级：gateway-config.json（由 /api/v1/archive/gw-config API 写入，
用于**启动网关前**预配置或运行后待重启生效的参数）> GATEWAY_* 环境变量 > 内置默认。

配置文件路径 $GATEWAY_CONFIG_FILE，默认 /home/tape_api/gateway-config.json。
文件键名与 summary() 输出同形（enabled/cache_dir/watermarks_pct/...），
删除文件即回到纯 env 行为。文件损坏或含非法值时该键自动回退 env 层，不阻塞启动。
"""
import json
import os

DEFAULT_CONFIG_FILE = "/home/tape_api/gateway-config.json"

# gateway-config.json 允许的键（与 summary() 对齐；container_target_bytes 为派生值可省略）
FILE_KEYS = (
    "enabled", "cache_dir", "db_dsn", "small_file_mb", "container_target_mb",
    "container_flush_s", "container_max_files", "cache_quota_gb", "watermarks_pct",
    "drive", "changer", "dte_map", "auto_load", "trust_drive", "verify_write",
    "max_attempts", "redis_enabled",
    "preferred_format", "ltfs_mount_root", "ltfs_bin_dir", "ltfs_sync_policy",
    "ltfs_mount_timeout_s",
)


def config_file_path():
    return os.getenv("GATEWAY_CONFIG_FILE", DEFAULT_CONFIG_FILE)


def load_config_file(path=None):
    """Best-effort read of the JSON layer; missing/corrupt file = {} (env wins)."""
    p = path or config_file_path()
    try:
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_config_file(values, path=None):
    """Atomic merge-write of the JSON layer; returns merged document."""
    p = path or config_file_path()
    merged = load_config_file(p)
    merged.update(values)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, p)
    return merged


def _as_bool(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _as_int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _as_float(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class GatewayConfig:
    def __init__(self, file_cfg=None):
        # file_cfg=None → 读取磁盘上的 gateway-config.json；显式传 dict 供校验/预览用
        self.file_cfg = (load_config_file() if file_cfg is None else dict(file_cfg))
        self.sources = {}

        def pick(key, env, default=None):
            """file > env > default; records provenance for gw-config readback."""
            if key in self.file_cfg and self.file_cfg[key] is not None:
                self.sources[key] = "file"
                return self.file_cfg[key]
            ev = os.getenv(env)
            if ev is not None:
                self.sources[key] = "env"
                return ev
            self.sources[key] = "default"
            return default

        self.enabled = _as_bool(pick("enabled", "GATEWAY_ENABLED", "true"))
        self.cache_dir = str(pick("cache_dir", "GATEWAY_CACHE_DIR",
                                  "/home/tape_api/archive-cache"))
        self.db_dsn = str(pick("db_dsn", "GATEWAY_DB_DSN",
                               "postgresql://postgres@127.0.0.1:5432/tapegw"))
        # routing + aggregation
        self.small_file_mb = _as_int(pick("small_file_mb", "GATEWAY_SMALL_FILE_MB", 64), 64)
        self.container_target_mb = _as_int(
            pick("container_target_mb", "GATEWAY_CONTAINER_TARGET_MB", 1024), 1024)
        self.container_target_bytes = self.container_target_mb * 1024 * 1024
        self.container_flush_s = _as_int(
            pick("container_flush_s", "GATEWAY_CONTAINER_FLUSH_S", 120), 120)
        self.container_max_files = _as_int(
            pick("container_max_files", "GATEWAY_CONTAINER_MAX_FILES", 4000), 4000)
        self.container_header_reserve = int(os.getenv("GATEWAY_CONTAINER_HEADER_KB", "1024")) * 1024
        # cache management
        self.cache_quota_bytes = _as_int(
            pick("cache_quota_gb", "GATEWAY_CACHE_QUOTA_GB", 200), 200) * 1024 ** 3
        wm = self.file_cfg.get("watermarks_pct")
        if isinstance(wm, (list, tuple)) and len(wm) == 2:
            self.sources["watermarks_pct"] = "file"
            self.low_watermark_pct = _as_int(wm[0], 70)
            self.high_watermark_pct = _as_int(wm[1], 85)
        else:
            ew = os.getenv("GATEWAY_HIGH_WATERMARK_PCT")
            lw = os.getenv("GATEWAY_LOW_WATERMARK_PCT")
            self.high_watermark_pct = _as_int(ew if ew is not None else "85", 85)
            self.low_watermark_pct = _as_int(lw if lw is not None else "70", 70)
            self.sources["watermarks_pct"] = "env" if (ew is not None or lw is not None) else "default"
        self.min_free_gb = int(os.getenv("GATEWAY_MIN_FREE_GB", "5"))
        # tape topology
        self.drive = str(pick("drive", "GATEWAY_DRIVE", "/dev/nst1"))
        self.changer = str(pick("changer", "GATEWAY_CHANGER", "/dev/sg1"))
        dm = self.file_cfg.get("dte_map")
        if isinstance(dm, dict):
            self.dte_map = {str(k): str(v) for k, v in dm.items()}
            self.sources["dte_map"] = "file"
        else:
            try:
                self.dte_map = json.loads(os.getenv("GATEWAY_DTE_MAP", "{}"))
                self.sources["dte_map"] = "env"
            except ValueError:
                self.dte_map = {}
        self.auto_load = _as_bool(pick("auto_load", "GATEWAY_AUTO_LOAD", "true"))
        # manual-mount mode: pin the barcode an operator physically loaded into
        # GATEWAY_DRIVE; skips all robot interaction (robot down / single-drive setups)
        td = pick("trust_drive", "GATEWAY_TRUST_DRIVE", "")
        self.trust_drive = str(td or "")
        self.verify_write = _as_bool(pick("verify_write", "GATEWAY_VERIFY_WRITE", "false"))
        self.tape_timeout_s = _as_int(os.getenv("GATEWAY_TAPE_TIMEOUT_S", "3600"), 3600)
        # dual-format backends (raw | ltfs)
        self.preferred_format = str(pick("preferred_format", "GATEWAY_PREFERRED_FORMAT", "raw"))
        if self.preferred_format not in ("raw", "ltfs"):
            self.preferred_format = "raw"
        self.ltfs_mount_root = str(pick("ltfs_mount_root", "GATEWAY_LTFS_MOUNT_ROOT",
                                        "/home/tape_api/ltfs"))
        self.ltfs_bin_dir = str(pick("ltfs_bin_dir", "GATEWAY_LTFS_BIN_DIR",
                                     "/opt/ibm/ltfssde/bin"))
        self.ltfs_sync_policy = str(pick("ltfs_sync_policy", "GATEWAY_LTFS_SYNC_POLICY",
                                         "unmount"))
        if self.ltfs_sync_policy not in ("unmount", "keep_mounted"):
            self.ltfs_sync_policy = "unmount"
        self.ltfs_mount_timeout_s = _as_int(
            pick("ltfs_mount_timeout_s", "GATEWAY_LTFS_MOUNT_TIMEOUT_S", 300), 300)
        # recall intelligence
        self.recall_hot_window_s = int(os.getenv("GATEWAY_RECALL_HOT_WINDOW_S", "60"))
        self.recall_hot_threshold = int(os.getenv("GATEWAY_RECALL_HOT_THRESHOLD", "3"))
        # workers
        self.poll_interval_s = _as_float(os.getenv("GATEWAY_POLL_INTERVAL_S", "2"), 2.0)
        self.evict_interval_s = _as_float(os.getenv("GATEWAY_EVICT_INTERVAL_S", "30"), 30.0)
        self.max_attempts = _as_int(pick("max_attempts", "GATEWAY_MAX_ATTEMPTS", 3), 3)
        self.pool_min = int(os.getenv("GATEWAY_POOL_MIN", "2"))
        self.pool_max = int(os.getenv("GATEWAY_POOL_MAX", "8"))
        # optional acceleration layer (Redis); empty = disabled
        if "redis_enabled" in self.file_cfg and self.file_cfg["redis_enabled"] is not None:
            self.sources["redis_enabled"] = "file"
            on = _as_bool(self.file_cfg["redis_enabled"])
            url = os.getenv("GATEWAY_REDIS_URL", "redis://127.0.0.1:6379/0")
            self.redis_url = url if on else ""
        else:
            self.sources["redis_enabled"] = "env"
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
            "preferred_format": self.preferred_format,
            "ltfs_mount_root": self.ltfs_mount_root,
            "ltfs_bin_dir": self.ltfs_bin_dir,
            "ltfs_sync_policy": self.ltfs_sync_policy,
            "ltfs_mount_timeout_s": self.ltfs_mount_timeout_s,
            "config_file": config_file_path(),
            "file_keys": sorted(k for k in self.file_cfg if k in FILE_KEYS),
            "sources": dict(self.sources),
        }
