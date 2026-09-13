"""Short-lived safety copies of presentations, kept out of the user's folders.

An in-place writeback overwrites the user's own file, so we snapshot it first.
Two constraints shape where that snapshot goes and how long it lives:

1. It must not appear in the folder the user browses.  A ``.sb_backup.pptx``
   next to the presentation is clutter the user has to reason about and
   eventually clean up by hand.
2. It must not accumulate.  A snapshot is an undo buffer, not an archive, so it
   is pruned by age and by count, and the user can drop it the moment they are
   satisfied with the result.

Both decisions live here so the rest of the codebase never has to make them.
Callers ask for a backup, a listing, or a restore and get a plain dict back.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from .core import SlideBridgeError, _path_string

#: How long a snapshot stays available before it is pruned automatically.
DEFAULT_RETENTION_DAYS = 7

#: Hard cap per presentation, so a burst of edits cannot fill the disk.
DEFAULT_MAX_PER_PRESENTATION = 5

_INDEX_NAME = "manifest.json"
_INDEX_VERSION = 1
_STAMP_FORMAT = "%Y%m%d-%H%M%S"
_STAMP_RE = re.compile(r"\.(\d{8}-\d{6})(?:-(\d+))?$")
_MAX_STEM_BYTES = 120


def _env_int(name: str, fallback: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return fallback
    try:
        value = int(raw)
    except ValueError:
        return fallback
    return value if value > 0 else fallback


def default_retention_days() -> int:
    return _env_int("SLIDEBRIDGE_BACKUP_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)


def default_max_per_presentation() -> int:
    return _env_int("SLIDEBRIDGE_BACKUP_KEEP", DEFAULT_MAX_PER_PRESENTATION)


def backup_root() -> Path:
    """Return the root of the backup store, creating it if needed.

    ``~/Library/Application Support`` rather than ``~/Library/Caches``: the OS
    may purge caches at any time, and a snapshot that vanishes on its own is
    worse than no snapshot at all.
    """
    override = os.environ.get("SLIDEBRIDGE_BACKUP_DIR")
    if override:
        root = Path(override).expanduser()
    else:
        root = Path.home() / "Library" / "Application Support" / "SlideBridge" / "backups"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _canonical(path: Path) -> str:
    return os.path.realpath(str(path))


def _key_for(source: Path) -> str:
    """Hash the presentation path so the store layout leaks no folder names."""
    return hashlib.sha256(_canonical(source).encode("utf-8")).hexdigest()[:16]


def _store_for(source: Path) -> Path:
    return backup_root() / _key_for(source)


def _iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def _parse_iso(value: str) -> float:
    try:
        return datetime.datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _short_stem(stem: str) -> str:
    """Trim the stem so ``stem + stamp + suffix`` stays inside the name limit."""
    encoded = stem.encode("utf-8")
    if len(encoded) <= _MAX_STEM_BYTES:
        return stem
    return encoded[:_MAX_STEM_BYTES].decode("utf-8", "ignore")


def _unique_name(store: Path, stem: str, suffix: str, ts: float) -> str:
    base = f"{_short_stem(stem)}.{datetime.datetime.fromtimestamp(ts).strftime(_STAMP_FORMAT)}"
    candidate = f"{base}{suffix}"
    counter = 2
    while (store / candidate).exists():
        candidate = f"{base}-{counter}{suffix}"
        counter += 1
        if counter > 100:
            return f"{base}-{os.urandom(3).hex()}{suffix}"
    return candidate


def _entry(store: Path, name: str, *, source: str, reason: str, ts: float, size: int) -> dict:
    return {
        "id": name,
        "path": str(store / name),
        "source": source,
        "created": _iso(ts),
        "ts": ts,
        "bytes": size,
        "reason": reason,
    }


def _read_index(store: Path) -> dict:
    try:
        data = json.loads((store / _INDEX_NAME).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"version": _INDEX_VERSION, "source": None, "backups": []}
    if not isinstance(data, dict) or not isinstance(data.get("backups"), list):
        return {"version": _INDEX_VERSION, "source": None, "backups": []}
    return data


def _write_index(store: Path, index: dict) -> None:
    payload = json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True)
    temporary = store / f".{_INDEX_NAME}.tmp"
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, store / _INDEX_NAME)
    except OSError as exc:
        raise SlideBridgeError(f"could not update backup index: {store}") from exc


def _reconcile(store: Path, source: str) -> dict:
    """Rebuild the index from disk, adopting files the index has lost.

    The files on disk are what actually matter.  If the index is corrupt or was
    deleted, the snapshots must still be listed rather than silently orphaned,
    so anything found on disk wins over what the index claims.
    """
    index = _read_index(store)
    recorded = {e.get("id"): e for e in index["backups"] if isinstance(e, dict)}
    source_value = source or index.get("source") or ""
    entries: list[dict] = []

    for name in sorted(p.name for p in store.iterdir() if p.is_file()):
        if not name.endswith(".pptx"):
            continue
        file_path = store / name
        try:
            stat = file_path.stat()
        except OSError:
            continue

        if name in recorded:
            entry = dict(recorded[name])
            entry["path"] = str(file_path)
            entry["bytes"] = stat.st_size
            entry["source"] = entry.get("source") or source_value
            entry["ts"] = float(entry.get("ts") or _parse_iso(entry.get("created", "")) or stat.st_mtime)
            entry["created"] = entry.get("created") or _iso(entry["ts"])
            entry["reason"] = entry.get("reason") or "unknown"
        else:
            match = _STAMP_RE.search(Path(name).stem)
            ts = stat.st_mtime
            if match:
                try:
                    ts = datetime.datetime.strptime(match.group(1), _STAMP_FORMAT).timestamp()
                except ValueError:
                    ts = stat.st_mtime
            entry = _entry(store, name, source=source_value, reason="unknown", ts=ts, size=stat.st_size)

        entries.append(entry)

    entries.sort(key=lambda e: e["ts"])
    index["version"] = _INDEX_VERSION
    index["source"] = source_value or None
    index["backups"] = entries
    return index


def _apply_retention(store: Path, index: dict, days: int, keep: int) -> list[dict]:
    """Drop snapshots past the age window, then trim to the newest ``keep``.

    A snapshot that cannot be deleted stays listed: an undeletable file the user
    can still see beats an invisible one that silently occupies the disk.
    """
    cutoff = time.time() - days * 86400
    entries = sorted(index["backups"], key=lambda e: e["ts"])

    survivors = [entry for entry in entries if entry["ts"] > cutoff]
    doomed = [entry for entry in entries if entry["ts"] <= cutoff]

    if keep > 0 and len(survivors) > keep:
        doomed.extend(survivors[: len(survivors) - keep])
        survivors = survivors[len(survivors) - keep :]

    removed: list[dict] = []
    for entry in doomed:
        try:
            (store / entry["id"]).unlink()
        except FileNotFoundError:
            removed.append(entry)
        except OSError:
            survivors.append(entry)
        else:
            removed.append(entry)

    index["backups"] = sorted(survivors, key=lambda e: e["ts"])
    return removed


def _drop_store(store: Path) -> None:
    try:
        shutil.rmtree(store)
    except OSError:
        pass


def _prune_other_stores(days: int, keep: int, skip: Path) -> list[dict]:
    """Apply the age window to presentations the user has not touched lately."""
    removed: list[dict] = []
    for store in sorted(p for p in backup_root().iterdir() if p.is_dir()):
        if store == skip:
            continue
        recorded = _read_index(store).get("source")
        if not recorded:
            continue
        index = _reconcile(store, recorded)
        removed.extend(_apply_retention(store, index, days, keep))
        if index["backups"]:
            _write_index(store, index)
        else:
            _drop_store(store)
    return removed


def create_backup(
    source: os.PathLike[str] | str,
    *,
    reason: str = "in-place-writeback",
    retention_days: int | None = None,
    max_per_presentation: int | None = None,
) -> dict:
    """Snapshot ``source`` into the hidden store and prune what has expired.

    Returns the new snapshot plus everything retention removed, so callers can
    report what happened without doing any bookkeeping themselves.
    """
    src = Path(_path_string(source))
    if not src.is_file():
        raise SlideBridgeError(f"cannot back up missing presentation: {src}")

    days = retention_days or default_retention_days()
    keep = max_per_presentation or default_max_per_presentation()

    store = _store_for(src)
    try:
        store.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SlideBridgeError(f"could not create backup store: {store}") from exc

    ts = time.time()
    name = _unique_name(store, src.stem, src.suffix, ts)
    destination = store / name

    # Reconcile before the copy: _reconcile adopts every file it finds on disk,
    # so running it afterwards would pick up the snapshot we are about to
    # create and then have it appended a second time.  Two index entries for
    # one file make retention delete the file while an entry still points at
    # it, which silently collapses the store to a single snapshot.
    index = _reconcile(store, str(src))

    try:
        shutil.copy2(src, destination)
    except OSError as exc:
        # Deliberately distinct from the writeback failure message: nothing has
        # been written to the presentation yet, and the user's file is intact.
        raise SlideBridgeError(f"could not create backup of {src.name}: {exc}") from exc

    try:
        size = destination.stat().st_size
    except OSError:
        size = 0

    entry = _entry(store, name, source=str(src), reason=reason, ts=ts, size=size)
    index["backups"] = [e for e in index["backups"] if e["id"] != name]
    index["backups"].append(entry)
    index["updated"] = _iso(ts)

    pruned = _apply_retention(store, index, days, keep)
    pruned.extend(_prune_other_stores(days, keep, skip=store))
    _write_index(store, index)

    return {
        "backup": entry,
        "pruned": pruned,
        "store": str(store),
        "retention_days": days,
        "max_per_presentation": keep,
    }


def _collect(source: Path | None) -> tuple[list[dict], Path | None]:
    if source is not None:
        store = _store_for(source)
        if not store.is_dir():
            return [], store
        return _reconcile(store, str(source))["backups"], store

    entries: list[dict] = []
    for store in sorted(p for p in backup_root().iterdir() if p.is_dir()):
        recorded = _read_index(store).get("source")
        if not recorded:
            continue
        entries.extend(_reconcile(store, recorded)["backups"])
    return entries, None


def list_backups(
    source: os.PathLike[str] | str | None = None,
    *,
    retention_days: int | None = None,
    max_per_presentation: int | None = None,
) -> dict:
    """List snapshots for one presentation, or across the whole store."""
    source_path = Path(_path_string(source)) if source is not None else None
    entries, store = _collect(source_path)
    entries.sort(key=lambda e: e["ts"], reverse=True)

    return {
        "store": str(store) if store is not None else str(backup_root()),
        "presentation": str(source_path) if source_path is not None else None,
        "retention_days": retention_days or default_retention_days(),
        "max_per_presentation": max_per_presentation or default_max_per_presentation(),
        "count": len(entries),
        "total_bytes": sum(e["bytes"] for e in entries),
        "backups": entries,
    }


def _resolve_entry(entries: list[dict], backup_id: str | None) -> dict:
    if not entries:
        raise SlideBridgeError("no backups available for this presentation")
    if backup_id is None:
        return max(entries, key=lambda e: e["ts"])
    if Path(backup_id).name != backup_id:
        raise SlideBridgeError(f"invalid backup id: {backup_id}")
    for entry in entries:
        if entry["id"] == backup_id:
            return entry
    raise SlideBridgeError(f"backup not found: {backup_id}")


def restore_backup(
    source: os.PathLike[str] | str,
    backup_id: str | None = None,
    *,
    keep_current: bool = True,
) -> dict:
    """Put a snapshot back over the presentation.

    The current state is snapshotted first, so a restore is itself undoable —
    without that, restoring the wrong version would destroy the good one.
    """
    src = Path(_path_string(source))
    if not src.is_file():
        raise SlideBridgeError(f"presentation not found: {src}")

    store = _store_for(src)
    if not store.is_dir():
        raise SlideBridgeError("no backups available for this presentation")

    entries = _reconcile(store, str(src))["backups"]
    chosen = _resolve_entry(entries, backup_id)
    backup_file = store / chosen["id"]
    if not backup_file.is_file():
        raise SlideBridgeError(f"backup file is missing: {chosen['id']}")

    if _sha256(src) == _sha256(backup_file):
        return {
            "status": "unchanged",
            "presentation": str(src),
            "restored": chosen,
            "message": "Presentation already matches this backup.",
        }

    # Stage the snapshot beside the presentation before anything else touches
    # it: the safety snapshot below may prune the store, and pruning must never
    # be able to delete the very snapshot we are about to restore.
    fd, staged = tempfile.mkstemp(prefix=".slidebridge-restore-", suffix=src.suffix, dir=str(src.parent))
    os.close(fd)
    try:
        shutil.copy2(backup_file, staged)
        safety = create_backup(src, reason="pre-restore")["backup"] if keep_current else None
        os.replace(staged, src)
    except OSError as exc:
        raise SlideBridgeError(f"could not restore backup: {exc}") from exc
    finally:
        if os.path.exists(staged):
            try:
                os.unlink(staged)
            except OSError:
                pass

    return {
        "status": "success",
        "presentation": str(src),
        "restored": chosen,
        "previous_backup": safety,
    }


def clear_backups(source: os.PathLike[str] | str | None = None) -> dict:
    """Delete snapshots for one presentation, or the entire store."""
    if source is not None:
        src = Path(_path_string(source))
        store = _store_for(src)
        entries = _reconcile(store, str(src))["backups"] if store.is_dir() else []
        _drop_store(store)
        return {
            "presentation": str(src),
            "removed": entries,
            "removed_count": len(entries),
            "removed_bytes": sum(e["bytes"] for e in entries),
        }

    removed: list[dict] = []
    for store in sorted(p for p in backup_root().iterdir() if p.is_dir()):
        recorded = _read_index(store).get("source")
        if recorded:
            removed.extend(_reconcile(store, recorded)["backups"])
        _drop_store(store)

    return {
        "presentation": None,
        "removed": removed,
        "removed_count": len(removed),
        "removed_bytes": sum(e["bytes"] for e in removed),
    }


def prune_backups(
    *,
    retention_days: int | None = None,
    max_per_presentation: int | None = None,
) -> dict:
    """Apply the retention policy to every presentation in the store."""
    days = retention_days or default_retention_days()
    keep = max_per_presentation or default_max_per_presentation()
    removed: list[dict] = []

    for store in sorted(p for p in backup_root().iterdir() if p.is_dir()):
        recorded = _read_index(store).get("source")
        if not recorded:
            continue
        index = _reconcile(store, recorded)
        removed.extend(_apply_retention(store, index, days, keep))
        if index["backups"]:
            _write_index(store, index)
        else:
            _drop_store(store)

    return {
        "retention_days": days,
        "max_per_presentation": keep,
        "removed": removed,
        "removed_count": len(removed),
        "removed_bytes": sum(e["bytes"] for e in removed),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "DEFAULT_MAX_PER_PRESENTATION",
    "DEFAULT_RETENTION_DAYS",
    "backup_root",
    "clear_backups",
    "create_backup",
    "default_max_per_presentation",
    "default_retention_days",
    "list_backups",
    "prune_backups",
    "restore_backup",
]
