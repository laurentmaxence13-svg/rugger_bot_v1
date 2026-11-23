"""On-disk state of the pilot: atomic JSON, gz pages written directly (never raw), SHA256SUMS, deterministic archive
split in parts (90 MB by default) for the hand-over to the owner. Nothing is ever deleted."""
import gzip
import hashlib
import io
import json
import os
import tarfile
from pathlib import Path

from .budget import _write_atomic

PART_BYTES = 90 * 1024 * 1024


class StoreError(RuntimeError):
    pass


def write_json(path, doc):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(Path(path), (json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False, default=str)
                               + '\n').encode())


def read_json(path):
    return json.loads(Path(path).read_text())


def file_sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def write_gz_page(path, doc):
    """One page = one gz file, deterministic (mtime 0, no name); written via a temporary file then renamed."""
    raw = json.dumps(doc, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0, filename='') as handle:
        handle.write(raw)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(Path(path), buffer.getvalue())


def read_gz_page(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def sha256sums(root, out_name='SHA256SUMS'):
    root = Path(root)
    lines = ['%s  %s' % (file_sha(p), p.relative_to(root).as_posix())
             for p in sorted(root.rglob('*')) if p.is_file() and p.name != out_name and not p.name.endswith('.tmp')]
    (root / out_name).write_text('\n'.join(lines) + '\n')
    return file_sha(root / out_name)


def disk_free_ok(path, minimum_bytes):
    stat = os.statvfs(path)
    return stat.f_bavail * stat.f_frsize >= minimum_bytes


def archive_parts(root, out_dir, *, part_bytes=PART_BYTES, name='CPMMPILOT'):
    """Deterministic tar.gz of ``root`` cut in parts of at most ``part_bytes``; returns the sha of each part and of
    the whole archive. Reassembly: cat parts in order."""
    root, out_dir = Path(root), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0, filename='') as gz:
        with tarfile.open(fileobj=gz, mode='w', format=tarfile.PAX_FORMAT) as tar:
            for p in sorted(root.rglob('*')):
                if p.is_file() and not p.name.endswith('.tmp'):
                    info = tar.gettarinfo(str(p), arcname=p.relative_to(root.parent).as_posix())
                    info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, '', ''
                    with open(p, 'rb') as handle:
                        tar.addfile(info, handle)
    whole = buffer.getvalue()
    parts = []
    for k in range(0, max(1, (len(whole) + part_bytes - 1) // part_bytes)):
        chunk = whole[k * part_bytes:(k + 1) * part_bytes]
        path = out_dir / ('%s.tar.gz.part%02d' % (name, k))
        _write_atomic(path, chunk)
        parts.append(dict(name=path.name, bytes=len(chunk), sha256=hashlib.sha256(chunk).hexdigest()))
    doc = dict(archive_sha256=hashlib.sha256(whole).hexdigest(), archive_bytes=len(whole), parts=parts,
               reassemble='cat %s.tar.gz.part* > %s.tar.gz' % (name, name))
    write_json(out_dir / ('%s.PARTS.json' % name), doc)
    return doc
