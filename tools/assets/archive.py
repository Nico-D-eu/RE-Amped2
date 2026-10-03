"""Amped 2 .gfx / .res archives.

Both are ordinary ZIP files (entries stored or deflated).  Repacking keeps the
original entry order, names, timestamps and per-entry compression method, so a
rebuilt archive differs from the shipped one only in the entries you changed.
"""
import zipfile
from pathlib import Path

ARCHIVE_EXTS = (".gfx", ".res", ".rui", ".ruirr")


def find_archives(game: Path):
    """Archive paths under game/, relative, with forward slashes, sorted."""
    found = [p for p in game.rglob("*") if p.suffix.lower() in ARCHIVE_EXTS and p.is_file()]
    return sorted(p.relative_to(game).as_posix() for p in found)


def iter_entries(path: Path):
    """Yield (ZipInfo, bytes) for every file entry."""
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if not info.is_dir():
                yield info, z.read(info)


def _norm(name: str) -> str:
    return name.replace("\\", "/").lower()


def repack(original: Path, overrides: dict, out: Path):
    """Write `out` = `original` with entries replaced or added.

    overrides: entry name -> bytes.  Matching is case-insensitive.  New
    entries are deflated.  Returns (replaced, added) name lists.
    """
    pending = {_norm(k): (k, v) for k, v in overrides.items()}
    replaced, added = [], []
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    with zipfile.ZipFile(original) as src, zipfile.ZipFile(tmp, "w") as dst:
        for info in src.infolist():
            key = _norm(info.filename)
            if key in pending:
                data = pending.pop(key)[1]
                replaced.append(info.filename)
            else:
                data = src.read(info)
            new = zipfile.ZipInfo(info.filename, info.date_time)
            new.compress_type = info.compress_type
            new.external_attr = info.external_attr
            dst.writestr(new, data)
        for name, data in pending.values():
            new = zipfile.ZipInfo(name.replace("\\", "/"))
            new.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(new, data)
            added.append(name)
    tmp.replace(out)
    return replaced, added
