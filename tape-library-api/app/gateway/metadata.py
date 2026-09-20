"""Metadata layer: PostgreSQL pool + schema + typed data access.

PostgreSQL is the single source of truth. All multi-step state transitions run
inside transactions (ctx.conn). file_meta is partitioned monthly (native
declarative partitioning, plus a DEFAULT partition as safety net); hot-path
indexes propagate automatically from the partitioned parents.
"""
import datetime
import json
import threading
import uuid
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool

from .config import GatewayConfig

FILE_STATES = ("cached", "archiving", "archived", "failed")
CONTAINER_STATES = ("buffering", "flushing", "archiving", "archived", "aborted")
TASK_KINDS = ("archive_file", "archive_container", "recall_file")
TASK_STATES = ("queued", "running", "succeeded", "failed", "cancelled")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS file_meta (
    file_id     UUID NOT NULL,
    filename    TEXT NOT NULL,
    size_bytes  BIGINT NOT NULL CHECK (size_bytes >= 0),
    sha256      CHAR(64),
    content_type TEXT,
    origin      TEXT,
    kind        TEXT NOT NULL DEFAULT 'file' CHECK (kind IN ('file','container_member')),
    state       TEXT NOT NULL DEFAULT 'cached' CHECK (state IN ('cached','archiving','archived','failed')),
    storage     TEXT NOT NULL DEFAULT 'cache' CHECK (storage IN ('cache','container','tape')),
    cache_path  TEXT,
    cache_rel_path TEXT,
    member_path TEXT,
    file_offset_in_container BIGINT,
    container_id UUID,
    media_barcode  TEXT,
    tape_block_index BIGINT,
    ltfs_path    TEXT,
    error       TEXT,
    attempts    INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    last_access_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (file_id, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE IF NOT EXISTS file_meta_p_default PARTITION OF file_meta DEFAULT;

CREATE TABLE IF NOT EXISTS container_meta (
    container_id UUID PRIMARY KEY,
    state       TEXT NOT NULL DEFAULT 'buffering'
                CHECK (state IN ('buffering','flushing','archiving','archived','aborted')),
    size_bytes  BIGINT NOT NULL DEFAULT 0,
    file_count  INT NOT NULL DEFAULT 0,
    media_barcode TEXT,
    tape_block_index BIGINT,
    offset_in_tape  BIGINT,
    length_on_tape  BIGINT,
    ltfs_path       TEXT,
    archive_sha256  CHAR(64),
    error       TEXT,
    attempts    INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    first_flush_after TIMESTAMPTZ NOT NULL,
    archived_at TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tape_media (
    barcode     TEXT PRIMARY KEY,
    state       TEXT NOT NULL DEFAULT 'appendable'
                CHECK (state IN ('unknown','scratch','appendable','full','faulted')),
    format      TEXT NOT NULL DEFAULT 'raw' CHECK (format IN ('raw','ltfs')),
    capacity_bytes BIGINT NOT NULL DEFAULT 1224438927360,
    used_bytes  BIGINT NOT NULL DEFAULT 0,
    block_records INT NOT NULL DEFAULT 0,
    last_filemark  BIGINT,
    mount_count INT NOT NULL DEFAULT 0,
    bytes_written BIGINT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gw_block (
    id BIGSERIAL PRIMARY KEY,
    media_barcode TEXT NOT NULL,
    block_index  BIGINT NOT NULL,
    object_id    UUID NOT NULL,
    object_type  TEXT NOT NULL CHECK (object_type IN ('file','container')),
    offset_in_block BIGINT NOT NULL DEFAULT 0,
    length        BIGINT NOT NULL DEFAULT 0,
    written_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cache_entry (
    cache_key   TEXT PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('file','container')),
    object_id   UUID NOT NULL,
    path        TEXT NOT NULL,
    size_bytes  BIGINT NOT NULL DEFAULT 0,
    dirty       BOOLEAN NOT NULL DEFAULT TRUE,
    refcount    INT NOT NULL DEFAULT 0,
    last_access_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gw_task (
    task_id     TEXT PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('archive_file','archive_container','recall_file')),
    state       TEXT NOT NULL DEFAULT 'queued'
                CHECK (state IN ('queued','running','succeeded','failed','cancelled')),
    payload     JSONB NOT NULL,
    file_id     UUID,
    container_id UUID,
    attempts    INT NOT NULL DEFAULT 0,
    next_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error       TEXT,
    result      JSONB
);

CREATE TABLE IF NOT EXISTS recall_events (
    id BIGSERIAL PRIMARY KEY,
    file_id      UUID,
    container_id UUID,
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_file_state_created ON file_meta (state, created_at);
CREATE INDEX IF NOT EXISTS idx_file_container ON file_meta (container_id) WHERE container_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_file_last_access ON file_meta (last_access_at);
CREATE INDEX IF NOT EXISTS idx_container_state ON container_meta (state);
CREATE INDEX IF NOT EXISTS idx_container_flush_due ON container_meta (state, first_flush_after);
CREATE INDEX IF NOT EXISTS idx_block_object ON gw_block (media_barcode, object_id);
CREATE INDEX IF NOT EXISTS idx_block_media ON gw_block (media_barcode, block_index);
CREATE INDEX IF NOT EXISTS idx_cache_lru ON cache_entry (last_access_at) WHERE dirty = false;
CREATE INDEX IF NOT EXISTS idx_cache_object ON cache_entry (object_id, kind);
CREATE INDEX IF NOT EXISTS idx_file_member_path ON file_meta (member_path) WHERE member_path IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_task_queue ON gw_task (kind, state, next_run_at);
CREATE INDEX IF NOT EXISTS idx_recall_heat ON recall_events (container_id, ts);
"""

# online migration for pre-directory-tree / pre-LTFS deployments: add new
# columns to already-created partitioned file_meta (cascades to every
# partition) and tape_media/container_meta. New-column CREATE INDEX statements
# (none so far) must stay BELOW these ALTERs.
MIGRATION_SQL = """
ALTER TABLE file_meta ADD COLUMN IF NOT EXISTS cache_rel_path TEXT;
ALTER TABLE file_meta ADD COLUMN IF NOT EXISTS member_path TEXT;
ALTER TABLE file_meta ADD COLUMN IF NOT EXISTS ltfs_path TEXT;
ALTER TABLE container_meta ADD COLUMN IF NOT EXISTS ltfs_path TEXT;
ALTER TABLE tape_media ADD COLUMN IF NOT EXISTS format TEXT
    NOT NULL DEFAULT 'raw' CHECK (format IN ('raw','ltfs'));
"""


def new_id():
    return str(uuid.uuid4())


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _uuid(v):
    return str(v) if v is not None else None


class MetadataDB:
    """Threaded pool over psycopg2; all access via self.conn() context."""

    def __init__(self, cfg: GatewayConfig):
        self.cfg = cfg
        self.pool = None
        self._partition_guard = threading.Lock()
        self._known_partitions = set()

    # ---------- lifecycle ----------
    def connect(self):
        self.pool = psycopg2.pool.ThreadedConnectionPool(
            self.cfg.pool_min, self.cfg.pool_max, self.cfg.db_dsn)
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
                cur.execute(MIGRATION_SQL)   # add new columns before indexing them
                cur.execute(INDEXES_SQL)
                cur.execute("SELECT inhrelid::regclass FROM pg_inherits "
                            "WHERE inhparent = 'file_meta'::regclass")
                import re as _re
                for (rel,) in cur.fetchall():
                    m = _re.search(r"file_meta_p_(\d{6})$", str(rel))
                    if m:
                        s = m.group(1)
                        self._known_partitions.add("%s-%s" % (s[:4], s[4:6]))

    def close(self):
        if self.pool:
            self.pool.closeall()
            self.pool = None

    @contextmanager
    def conn(self):
        c = self.pool.getconn()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            self.pool.putconn(c)

    # ---------- partitions ----------
    def ensure_month_partition(self, conn, dt: datetime.datetime):
        month = dt.strftime("%Y%m")          # partition suffix
        month_dash = dt.strftime("%Y-%m")    # guard key
        name = "file_meta_p_%s" % month
        if month_dash in self._known_partitions:
            return name
        with self._partition_guard:
            if month_dash in self._known_partitions:
                return name
            with conn.cursor() as cur:
                year, mon = int(month[:4]), int(month[4:6])
                y2, m2 = (year + 1, 1) if mon == 12 else (year, mon + 1)
                lo = month_dash + "-01"
                hi = "%04d-%02d-01" % (y2, m2)
                # rows for this month may already sit in DEFAULT (insert paths
                # that predate partitioning / bypassed ensure) -> stash+move
                cur.execute("SELECT count(*) FROM file_meta_p_default "
                            "WHERE created_at >= %s AND created_at < %s", (lo, hi))
                stashed = cur.fetchone()[0]
                if stashed:
                    cur.execute("DROP TABLE IF EXISTS pg_temp._part_stash")
                    cur.execute("CREATE TEMP TABLE _part_stash ON COMMIT DROP AS "
                                "SELECT * FROM file_meta_p_default "
                                "WHERE created_at >= %s AND created_at < %s", (lo, hi))
                    cur.execute("DELETE FROM file_meta_p_default "
                                "WHERE created_at >= %s AND created_at < %s", (lo, hi))
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS %s PARTITION OF file_meta "
                    "FOR VALUES FROM ('%s') TO ('%s')" % (name, lo, hi))
                if stashed:
                    cur.execute("INSERT INTO file_meta SELECT * FROM _part_stash")
            self._known_partitions.add(month_dash)
        return name

    # ---------- files ----------
    def insert_file(self, filename, size_bytes, sha256=None, content_type=None,
                    origin=None, kind="file", storage="cache", cache_path=None,
                    cache_rel_path=None, member_path=None):
        fid = new_id()
        now = _now()
        with self.conn() as conn:
            self.ensure_month_partition(conn, now)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO file_meta (file_id, filename, size_bytes, sha256,
                       content_type, origin, kind, state, storage, cache_path,
                       cache_rel_path, member_path, created_at, last_access_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,'cached',%s,%s,%s,%s,%s,%s)""",
                    (fid, filename, size_bytes, sha256, content_type, origin, kind,
                     storage, cache_path, cache_rel_path, member_path, now, now))
        return fid

    def get_file(self, file_id):
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM file_meta WHERE file_id = %s "
                            "ORDER BY created_at DESC LIMIT 1", (_uuid(file_id),))
                return cur.fetchone()

    def find_files(self, name_like, limit=50):
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT file_id, filename, size_bytes, sha256, state, storage, kind,"
                            " container_id, file_offset_in_container, media_barcode,"
                            " tape_block_index, ltfs_path, cache_path, cache_rel_path, member_path,"
                            " error, created_at, archived_at"
                            " FROM file_meta "
                            "WHERE filename ILIKE %s ORDER BY created_at DESC LIMIT %s",
                            ("%" + name_like + "%", limit))
                return cur.fetchall()

    def list_files(self, state=None, limit=100, offset=0):
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if state:
                    cur.execute("SELECT * FROM file_meta WHERE state = %s "
                                "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                                (state, limit, offset))
                else:
                    cur.execute("SELECT * FROM file_meta "
                                "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                                (limit, offset))
                return cur.fetchall()

    def count_files(self, state=None, name_like=None):
        """Row count for /files listing (same filters as list/find_files)."""
        where, args = [], []
        if name_like:
            where.append("filename ILIKE %s")
            args.append("%" + name_like + "%")
        elif state:
            where.append("state = %s")
            args.append(state)
        sql = "SELECT count(*) FROM file_meta"
        if where:
            sql += " WHERE " + " AND ".join(where)
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                return cur.fetchone()[0]

    def files_pending_archive(self, limit=200):
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM file_meta WHERE state='cached' AND kind='file' "
                            "ORDER BY created_at LIMIT %s", (limit,))
                return cur.fetchall()

    def mark_files_archiving(self, conn, file_ids):
        with conn.cursor() as cur:
            cur.execute("UPDATE file_meta SET state='archiving' "
                        "WHERE file_id = ANY(%s::uuid[]) AND state='cached'",
                        ([_uuid(x) for x in file_ids],))

    def mark_files_archived(self, conn, file_ids, storage, archived_at=None):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE file_meta SET state='archived', storage=%s, archived_at=%s "
                "WHERE file_id = ANY(%s::uuid[])",
                (storage, archived_at or _now(), [_uuid(x) for x in file_ids]))

    def mark_files_failed(self, conn, file_ids, error, storage="cache"):
        with conn.cursor() as cur:
            cur.execute("UPDATE file_meta SET state='failed', storage=%s, error=%s, "
                        "attempts = attempts + 1 WHERE file_id = ANY(%s::uuid[])",
                        (storage, str(error)[:500], [_uuid(x) for x in file_ids]))

    def touch_files(self, file_ids):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE file_meta SET last_access_at = %s WHERE file_id = ANY(%s::uuid[])",
                            (_now(), [_uuid(x) for x in file_ids]))

    def file_counts(self):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT state, count(*) FROM file_meta GROUP BY state")
                return {r[0]: r[1] for r in cur.fetchall()}

    # ---------- containers ----------
    def container_get_active(self):
        """Oldest buffering container still open for members (not yet sealed/due)."""
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM container_meta WHERE state='buffering' "
                            "AND first_flush_after > now() "
                            "ORDER BY created_at LIMIT 1")
                return cur.fetchone()

    def container_create(self, flush_after):
        cid = new_id()
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO container_meta (container_id, first_flush_after) VALUES (%s,%s)",
                    (cid, flush_after))
        return cid

    def container_get(self, container_id):
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM container_meta WHERE container_id = %s",
                            (_uuid(container_id),))
                return cur.fetchone()

    def container_files(self, container_id, order_by_offset=True):
        col = "file_offset_in_container" if order_by_offset else "created_at"
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM file_meta WHERE container_id = %%s "
                            "ORDER BY %s" % col, (_uuid(container_id),))
                return cur.fetchall()

    def container_current_offset(self, conn, container_id):
        """Next member's tar offset = sum of ustar footprints of current members."""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT coalesce(sum(512 + size_bytes + (512 - size_bytes %% 512) %% 512), 0) "
                "FROM file_meta WHERE container_id = %s AND state = 'cached'",
                (_uuid(container_id),))
            return cur.fetchone()[0]

    def container_bump_size(self, conn, container_id, size_bytes):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE container_meta SET size_bytes = size_bytes + %s, "
                "file_count = file_count + 1, updated_at = now() "
                "WHERE container_id = %s AND state = 'buffering'",
                (size_bytes, _uuid(container_id)))
            if cur.rowcount != 1:
                raise RuntimeError("container %s not buffering" % container_id)

    def container_seal(self, container_id):
        """Mark due for immediate flush (size cap reached / manual seal)."""
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE container_meta SET first_flush_after = now(), updated_at = now() "
                    "WHERE container_id = %s AND state = 'buffering'",
                    (_uuid(container_id),))
                return cur.rowcount == 1

    def container_update(self, conn, container_id, **kw):
        if not kw:
            return
        sets, vals = [], []
        for k, v in kw.items():
            sets.append("%s = %%s" % k)
            if isinstance(v, (dict, list)):
                v = psycopg2.extras.Json(v)
            vals.append(v)
        vals.append(_uuid(container_id))
        with conn.cursor() as cur:
            cur.execute("UPDATE container_meta SET %s, updated_at=now() "
                        "WHERE container_id = %%s" % ", ".join(sets), vals)

    def container_ready(self, target_bytes, flush_horizon, limit=4):
        """Buffering containers due by size or time, oldest first."""
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM container_meta WHERE state='buffering' AND "
                    "(size_bytes >= %s OR first_flush_after <= %s) "
                    "ORDER BY created_at LIMIT %s", (target_bytes, flush_horizon, limit))
                return cur.fetchall()

    def container_stats(self):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT state, count(*), coalesce(sum(size_bytes),0) "
                            "FROM container_meta GROUP BY state")
                rows = cur.fetchall()
        return [{"state": r[0], "count": r[1], "bytes": r[2]} for r in rows]

    def container_list(self, state=None, limit=50):
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if state:
                    cur.execute("SELECT * FROM container_meta WHERE state=%s "
                                "ORDER BY created_at DESC LIMIT %s", (state, limit))
                else:
                    cur.execute("SELECT * FROM container_meta "
                                "ORDER BY created_at DESC LIMIT %s", (limit,))
                return cur.fetchall()

    # ---------- tape media + blocks ----------
    def tape_upsert(self, barcode, state="appendable", format="raw"):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO tape_media (barcode, state, format) VALUES (%s,%s,%s) "
                    "ON CONFLICT (barcode) DO NOTHING", (barcode, state, format))

    def tape_get(self, barcode):
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM tape_media WHERE barcode=%s", (barcode,))
                return cur.fetchone()

    def tape_update(self, conn, barcode, used_bytes_delta=0, block_records_delta=0,
                    last_filemark=None, state=None, bytes_written_delta=0,
                    format=None):
        sets = ["used_bytes = used_bytes + %s", "block_records = block_records + %s",
                "bytes_written = bytes_written + %s", "updated_at = now()"]
        vals = [used_bytes_delta, block_records_delta, bytes_written_delta]
        if last_filemark is not None:
            sets.append("last_filemark = %s")
            vals.append(last_filemark)
        if state is not None:
            sets.append("state = %s")
            vals.append(state)
        if format is not None:
            sets.append("format = %s")
            vals.append(format)
        vals.append(barcode)
        with conn.cursor() as cur:
            cur.execute("UPDATE tape_media SET %s WHERE barcode = %%s" % ", ".join(sets), vals)

    def tape_media_mounted(self, barcode):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE tape_media SET mount_count = mount_count + 1, "
                            "updated_at=now() WHERE barcode=%s", (barcode,))

    def tape_list(self):
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM tape_media ORDER BY barcode")
                return cur.fetchall()

    def block_write_records(self, conn, barcode, block_index, object_id, object_type,
                            offset_in_block, length):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO gw_block (media_barcode, block_index, object_id, object_type,"
                " offset_in_block, length) VALUES (%s,%s,%s,%s,%s,%s)",
                (barcode, block_index, _uuid(object_id), object_type, offset_in_block, length))

    def block_lookup(self, barcode, object_id):
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM gw_block WHERE media_barcode=%s AND object_id=%s "
                            "ORDER BY block_index DESC LIMIT 1", (barcode, _uuid(object_id)))
                return cur.fetchone()

    def block_lookup_any(self, object_id):
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM gw_block WHERE object_id=%s "
                            "ORDER BY written_at DESC LIMIT 1", (_uuid(object_id),))
                return cur.fetchone()

    def file_set_tape_location(self, conn, file_id, barcode, block_index,
                                ltfs_path=None):
        with conn.cursor() as cur:
            cur.execute("UPDATE file_meta SET media_barcode=%s, tape_block_index=%s, "
                        "ltfs_path=%s WHERE file_id=%s",
                        (barcode, block_index, ltfs_path, _uuid(file_id)))

    def self_heal_states(self):
        """Restart recovery for DB-side states. Returns count of requeued items.
        Crash rule: an uncommitted gw_block means the tape block never existed
        (next append overwrites the orphan), so mid-flight states roll back."""
        requeued = 0
        requeue_files, requeue_containers = [], []
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE gw_task SET state='queued', next_run_at=now() "
                            "WHERE state='running'")
                requeued += cur.rowcount
                cur.execute("UPDATE file_meta SET state='cached' WHERE state='archiving'")
                requeued += cur.rowcount
                cur.execute("UPDATE container_meta SET state='flushing' "
                            "WHERE state='archiving'")
                requeued += cur.rowcount
                cur.execute(
                    """SELECT file_id FROM file_meta
                       WHERE state='cached' AND storage='cache' AND kind='file'
                       AND cache_path IS NOT NULL
                       AND NOT EXISTS (SELECT 1 FROM gw_task t
                                       WHERE t.file_id = file_meta.file_id
                                       AND t.kind='archive_file'
                                       AND t.state IN ('queued','running'))""")
                requeue_files = [r[0] for r in cur.fetchall()]
                cur.execute(
                    """SELECT container_id FROM container_meta
                       WHERE state='flushing'
                       AND NOT EXISTS (SELECT 1 FROM gw_task t
                                       WHERE t.container_id = container_meta.container_id
                                       AND t.kind='archive_container'
                                       AND t.state IN ('queued','running'))""")
                requeue_containers = [r[0] for r in cur.fetchall()]
        for fid in requeue_files:
            self.task_create("archive_file", {"file_id": fid}, file_id=fid)
        for cid in requeue_containers:
            self.task_create("archive_container", {"container_id": cid}, container_id=cid)
        requeued += len(requeue_files) + len(requeue_containers)
        return requeued

    def block_stats(self):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT media_barcode, count(*), coalesce(sum(length),0) "
                            "FROM gw_block GROUP BY media_barcode")
                rows = cur.fetchall()
        return [{"barcode": r[0], "blocks": r[1], "bytes": r[2]} for r in rows]

    # ---------- cache entries ----------
    def cache_upsert(self, cache_key, kind, object_id, path, size_bytes, dirty):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO cache_entry (cache_key, kind, object_id, path, size_bytes, dirty)
                       VALUES (%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (cache_key) DO UPDATE SET
                         path=EXCLUDED.path, size_bytes=EXCLUDED.size_bytes,
                         dirty=EXCLUDED.dirty, last_access_at=now()""",
                    (cache_key, kind, _uuid(object_id), path, size_bytes, dirty))

    def cache_get(self, cache_key):
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM cache_entry WHERE cache_key=%s", (cache_key,))
                return cur.fetchone()

    def cache_get_by_object(self, object_id, kind):
        """Directory-tree addressing: find the cache entry by object identity
        (cache_key is now just a bookkeeping record of the rel path)."""
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM cache_entry WHERE object_id=%s AND kind=%s "
                            "ORDER BY created_at DESC LIMIT 1",
                            (_uuid(object_id), kind))
                return cur.fetchone()

    def cache_all_keys(self):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT cache_key FROM cache_entry")
                return {r[0] for r in cur.fetchall()}

    def cache_all_paths(self):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT path FROM cache_entry")
                return {r[0] for r in cur.fetchall()}

    def cache_mark_clean(self, cache_key):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE cache_entry SET dirty=false, last_access_at=now() "
                            "WHERE cache_key=%s", (cache_key,))

    def cache_mark_clean_by_object(self, object_id, kind):
        """Mark all cache copies of an object clean (tape write committed)."""
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE cache_entry SET dirty=false, last_access_at=now() "
                            "WHERE object_id=%s AND kind=%s", (_uuid(object_id), kind))

    def cache_touch(self, cache_keys):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE cache_entry SET last_access_at=now() "
                            "WHERE cache_key = ANY(%s)", (list(cache_keys),))

    def cache_delete(self, cache_key):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM cache_entry WHERE cache_key=%s", (cache_key,))

    def cache_delete_many(self, cache_keys):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM cache_entry WHERE cache_key = ANY(%s)",
                            (list(cache_keys),))

    def cache_delete_by_path(self, path):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM cache_entry WHERE path=%s", (path,))

    def cache_delete_by_object(self, object_id, kind, only_path=None):
        """Drop cache entries for an object; optionally keep entries that point
        at a different (e.g. recalled clean) copy on disk."""
        with self.conn() as conn:
            with conn.cursor() as cur:
                q = "DELETE FROM cache_entry WHERE object_id=%s AND kind=%s"
                args = [_uuid(object_id), kind]
                if only_path is not None:
                    q += " AND path=%s"
                    args.append(only_path)
                cur.execute(q, args)

    def backfill_rel_paths(self, cache_dir):
        """One-shot (idempotent) migration: derive cache_rel_path for legacy rows."""
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE file_meta SET cache_rel_path = substr(cache_path, %s) "
                    "WHERE cache_rel_path IS NULL AND cache_path IS NOT NULL "
                    "AND cache_path LIKE %s",
                    (len(cache_dir.rstrip('/')) + 2, cache_dir.rstrip('/') + '/%'))
                return cur.rowcount

    def files_set_member_paths(self, conn, pairs):
        """Persist flush-time member renames (duplicate-name dedup in container)."""
        with conn.cursor() as cur:
            for fid, member_path in pairs:
                cur.execute("UPDATE file_meta SET member_path=%s WHERE file_id=%s",
                            (member_path, _uuid(fid)))

    def cache_lru_candidates(self, total_bytes, dirty=False):
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM cache_entry WHERE dirty=%s AND refcount=0 "
                    "ORDER BY last_access_at ASC", (dirty,))
                rows, acc = [], 0
                for r in cur.fetchall():
                    acc += r["size_bytes"]
                    rows.append(r)
                    if total_bytes and acc >= total_bytes:
                        break
                return rows

    def cache_list(self, kind=None, dirty=None, limit=200, offset=0):
        """Cache entries for the management page (biggest first)."""
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                q = "SELECT * FROM cache_entry"
                conds, vals = [], []
                if kind:
                    conds.append("kind=%s"); vals.append(kind)
                if dirty is not None:
                    conds.append("dirty=%s"); vals.append(dirty)
                if conds:
                    q += " WHERE " + " AND ".join(conds)
                q += " ORDER BY size_bytes DESC LIMIT %s OFFSET %s"
                vals += [limit, offset]
                cur.execute(q, vals)
                return cur.fetchall()

    def cache_stats(self):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT coalesce(sum(size_bytes),0), "
                            "coalesce(sum(size_bytes) FILTER (WHERE dirty),0), count(*) "
                            "FROM cache_entry")
                total, dirty, n = cur.fetchone()
        return {"total_bytes": total, "dirty_bytes": dirty, "clean_bytes": total - dirty,
                "entries": n}

    def cache_set_refcount(self, conn, cache_key, delta):
        with conn.cursor() as cur:
            cur.execute("UPDATE cache_entry SET refcount = refcount + %s "
                        "WHERE cache_key=%s", (delta, cache_key))

    # ---------- cache tree ----------
    def tree_index(self, file_limit=5000):
        """Bulk metadata for GET /archive/tree (single transaction).
        Returns files/containers/blocks/media/recall-counts for correlation
        with on-disk cache files."""
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT file_id, filename, size_bytes, sha256, kind, state, storage, "
                    "cache_path, cache_rel_path, member_path, file_offset_in_container, "
                    "container_id, media_barcode, tape_block_index, ltfs_path, error, created_at, "
                    "archived_at, last_access_at "
                    "FROM file_meta ORDER BY created_at DESC LIMIT %s", (file_limit,))
                files = cur.fetchall()
                cur.execute(
                    "SELECT container_id, state, size_bytes, file_count, media_barcode, "
                    "tape_block_index, offset_in_tape, length_on_tape, ltfs_path, "
                    "archive_sha256, error, created_at, archived_at FROM container_meta")
                containers = cur.fetchall()
                cur.execute(
                    "SELECT media_barcode, block_index, object_id, object_type, "
                    "offset_in_block, length FROM gw_block "
                    "ORDER BY block_index, offset_in_block")
                blocks = cur.fetchall()
                cur.execute(
                    "SELECT barcode, state, format, capacity_bytes, used_bytes, block_records, "
                    "last_filemark, mount_count, bytes_written FROM tape_media ORDER BY barcode")
                media = cur.fetchall()
                cur.execute(
                    "SELECT file_id, count(*) AS n, max(ts) AS last_ts "
                    "FROM recall_events GROUP BY file_id")
                recalls = cur.fetchall()
        return files, containers, blocks, media, recalls

    # ---------- recall heat ----------
    def recall_log(self, file_id, container_id):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO recall_events (file_id, container_id) VALUES (%s,%s)",
                            (_uuid(file_id), _uuid(container_id)))

    def recall_container_heat(self, container_id, window_s):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM recall_events WHERE container_id=%s "
                            "AND ts > now() - make_interval(secs => %s)",
                            (_uuid(container_id), window_s))
                return cur.fetchone()[0]

    # ---------- tasks ----------
    def task_create(self, kind, payload, file_id=None, container_id=None):
        tid = "tsk-" + uuid.uuid4().hex[:12]
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO gw_task (task_id, kind, payload, file_id, container_id) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (tid, kind, psycopg2.extras.Json(payload), _uuid(file_id), _uuid(container_id)))
        return tid

    def task_get(self, task_id):
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM gw_task WHERE task_id=%s", (task_id,))
                r = cur.fetchone()
        if r and isinstance(r["payload"], str):
            r["payload"] = json.loads(r["payload"])
        return r

    def task_list(self, kind=None, state=None, limit=50):
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                q = "SELECT * FROM gw_task"
                conds, vals = [], []
                if kind:
                    conds.append("kind=%s"); vals.append(kind)
                if state:
                    conds.append("state=%s"); vals.append(state)
                if conds:
                    q += " WHERE " + " AND ".join(conds)
                q += " ORDER BY created_at DESC LIMIT %s"
                vals.append(limit)
                cur.execute(q, vals)
                return cur.fetchall()

    def task_claim(self, kind):
        """Atomically claim one queued task (FOR UPDATE SKIP LOCKED)."""
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """UPDATE gw_task SET state='running', started_at=now(),
                       attempts = attempts + 1
                       WHERE task_id = (
                         SELECT task_id FROM gw_task
                         WHERE kind=%s AND state='queued' AND next_run_at <= now()
                         ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
                       RETURNING *""", (kind,))
                r = cur.fetchone()
        if r and isinstance(r["payload"], str):
            r["payload"] = json.loads(r["payload"])
        return r

    def task_finish(self, task_id, state, error=None, result=None, retry_s=None):
        with self.conn() as conn:
            with conn.cursor() as cur:
                if state == "failed" and retry_s is not None:
                    cur.execute(
                        "UPDATE gw_task SET state='queued', error=%s, next_run_at=now() + "
                        "make_interval(secs => %s) WHERE task_id=%s",
                        (str(error)[:500] if error else None, retry_s, task_id))
                else:
                    cur.execute(
                        "UPDATE gw_task SET state=%s, error=%s, result=%s, finished_at=now() "
                        "WHERE task_id=%s",
                        (state, str(error)[:500] if error else None,
                         psycopg2.extras.Json(result) if result is not None else None, task_id))

    def task_find_active(self, kind, file_id=None, container_id=None):
        """Newest queued/running task of a kind, optionally scoped to file/container."""
        with self.conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM gw_task WHERE kind=%s AND state IN ('queued','running') "
                    "AND (%s::uuid IS NULL OR file_id=%s) "
                    "AND (%s::uuid IS NULL OR container_id=%s) "
                    "ORDER BY created_at DESC LIMIT 1",
                    (kind,
                     _uuid(file_id) if file_id else None, _uuid(file_id) if file_id else None,
                     _uuid(container_id) if container_id else None,
                     _uuid(container_id) if container_id else None))
                return cur.fetchone()

    def task_counts(self):
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT kind, state, count(*) FROM gw_task GROUP BY kind, state")
                out = {}
                for k, s, n in cur.fetchall():
                    out.setdefault(k, {})[s] = n
                return out
