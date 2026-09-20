"""Container format: a streaming tar archive carrying small files to tape.

Format v1 = POSIX ustar tar (fixed 512-byte headers, path from file_meta
filenames, size from file_meta size_bytes). Members are appended in
file_offset_in_container order by the flush worker. Index lives in PG
(file_meta.file_offset_in_container), not on tape, keeping the format plain
tar so external tooling (tar, mt, dd) can inspect/restore containers.

tarfile in stream mode (mode 'w', format=USTAR_FORMAT) writes to a fileobj
without seeking, so it works on pipes; we drive it over our buffered cache
files directly. Padding to 10240-byte record boundary (RECORDSIZE * 2) keeps
the block tar-compatible.
"""
import io
import os
import tarfile

FORMAT_VERSION = 1
RECORDSIZE = 512


class _FilenameCodec:
    """ustar name+prefix splitting (max 100 + 155 chars)."""

    @staticmethod
    def split(name: str):
        name = name.replace("\\", "/").lstrip("/")
        raw = name.encode("utf-8", "surrogateescape")
        if len(raw) <= 100:
            return name, ""
        # try splitting at a '/' so prefix+name fit
        for cut in range(min(len(raw), 255) - 1, 0, -1):
            if raw[cut:cut + 1] == b"/":
                prefix, rest = raw[:cut], raw[cut + 1:]
                if len(prefix) <= 155 and len(rest) <= 100 and len(prefix) > 0:
                    return prefix.decode("utf-8", "surrogateescape"), rest.decode("utf-8", "surrogateescape")
        raise ValueError("filename too long for ustar: %r" % name)


def tar_header(name: str, size: int) -> bytes:
    """Build a single 512-byte ustar header via tarfile internals (no file)."""
    info = tarfile.TarInfo(name)
    info.size = size
    info.mtime = 0
    info.mode = 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    prefix, rest = _FilenameCodec.split(name)
    if prefix:
        info.name = rest
    t = tarfile.TarInfo.__new__(tarfile.TarInfo)
    t.__dict__.update(info.__dict__)
    info.name, info.pax_headers = rest, {}
    buf = info.tobuf(format=tarfile.USTAR_FORMAT, encoding="utf-8", errors="surrogateescape")
    return buf


def member_total_size(size: int) -> int:
    """On-tape footprint of one member: header + data + zero padding."""
    return RECORDSIZE + size + (RECORDSIZE - size % RECORDSIZE) % RECORDSIZE


def container_total_size(sizes) -> int:
    """Header+data for all members plus the two-record end-of-archive marker."""
    total = 2 * RECORDSIZE
    for s in sizes:
        total += member_total_size(s)
    return total


def write_container(cache_paths_names, out_path, on_member=None):
    """cache_paths_names: list of (abs_path, tar_name) in offset order.
    Writes a complete tar container to out_path; returns (sha256_hex, size).
    on_member(path, name, written_so_far) optional progress callback."""
    import hashlib
    h = hashlib.sha256()
    with open(out_path, "wb") as out:
        with tarfile.open(fileobj=out, mode="w", format=tarfile.USTAR_FORMAT) as tf:
            written = 0
            for path, name in cache_paths_names:
                info = tarfile.TarInfo(name)
                info.size = os.path.getsize(path)
                info.mtime = 0
                info.mode = 0o644
                with open(path, "rb") as f:
                    tf.addfile(info, f)
                written += member_total_size(info.size)
                if on_member:
                    on_member(path, name, written)
        # tarfile close writes two zero records; ensure 10240 blocking
        out.truncate(_round_up_10240(out.tell()))
    with open(out_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest(), os.path.getsize(out_path)


def _round_up_10240(n):
    r = n % 10240
    return n if r == 0 else n + 10240 - r


def extract_member(container_path, tar_name, out_path):
    """Precise single-member recall: stream-seek the member out of the container."""
    with tarfile.open(container_path) as tf:
        member = tf.getmember(tar_name)
        src = tf.extractfile(member)
        if src is None:
            raise ValueError("member %r is not a regular file" % tar_name)
        with open(out_path, "wb") as out:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    return os.path.getsize(out_path)
