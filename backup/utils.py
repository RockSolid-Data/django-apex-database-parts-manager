"""
Core backup and restore logic.

Folder-based incremental sync approach:
  - DB is copied fresh each time via sqlite3.backup() (WAL-safe, atomic).
  - Media files are synced incrementally (only new/changed files are copied).
  - Historical DB snapshots are kept in a history/ subfolder, pruned to max_backups.
  - Dual-path support: local + external, synced in parallel.

Backup folder structure:
    <backup_root>/
        db.sqlite3          -- latest DB copy (always current)
        media/              -- incrementally synced media mirror
        manifest.json       -- metadata about the latest sync
        history/            -- rolling DB-only snapshots
            db_2026-05-07_081500.sqlite3
            ...
"""

import json
import logging
import os
import shutil
import sqlite3
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

HISTORY_DIR = "history"
HISTORY_PREFIX = "db_"


def _get_db_path():
    """Resolve the active SQLite database file path."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return Path(db_path)
    return Path(settings.DATABASES["default"]["NAME"])


def _get_media_root():
    return Path(settings.MEDIA_ROOT)


def sync_backup(destination_dir, *, reason="manual"):
    """Incremental sync of DB + media to the destination folder.

    - Copies a fresh DB snapshot via sqlite3.backup()
    - Saves a timestamped copy in history/
    - Incrementally syncs media (only new/changed files, never deletes)
    - Writes a manifest.json with metadata

    Returns (destination_dir, summary_message) on success, raises on failure.
    """
    dest = Path(destination_dir)
    dest.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    db_path = _get_db_path()
    media_root = _get_media_root()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    # --- 1. Fresh DB copy via the safe backup() API ---
    dest_db = dest / "db.sqlite3"
    src_conn = sqlite3.connect(str(db_path))
    dst_conn = sqlite3.connect(str(dest_db))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    db_size_mb = dest_db.stat().st_size / (1024 * 1024)

    # --- 2. Save a timestamped copy in history/ ---
    history_dir = dest / HISTORY_DIR
    history_dir.mkdir(exist_ok=True)
    history_name = f"{HISTORY_PREFIX}{timestamp}.sqlite3"
    shutil.copy2(str(dest_db), str(history_dir / history_name))

    # --- 3. Incremental media sync (add/update, never delete) ---
    media_copied = 0
    media_skipped = 0
    if media_root.is_dir():
        dest_media = dest / "media"
        dest_media.mkdir(exist_ok=True)
        src_root_str = str(media_root)
        dst_root_str = str(dest_media)

        # Build a set of existing destination files with their stats for fast lookup.
        # os.walk + DirEntry.stat() avoids extra syscalls on Windows.
        dst_index = {}
        if dest_media.is_dir():
            for dirpath, _dirs, files in os.walk(dst_root_str):
                for fname in files:
                    full = os.path.join(dirpath, fname)
                    rel = os.path.relpath(full, dst_root_str)
                    try:
                        st = os.stat(full)
                        dst_index[rel] = (st.st_mtime, st.st_size)
                    except OSError:
                        pass

        for dirpath, _dirs, files in os.walk(src_root_str):
            for fname in files:
                src_full = os.path.join(dirpath, fname)
                rel = os.path.relpath(src_full, src_root_str)
                dst_full = os.path.join(dst_root_str, rel)

                existing = dst_index.get(rel)
                if existing is not None:
                    try:
                        src_st = os.stat(src_full)
                    except OSError:
                        continue
                    if abs(src_st.st_mtime - existing[0]) < 1 and src_st.st_size == existing[1]:
                        media_skipped += 1
                        continue

                os.makedirs(os.path.dirname(dst_full), exist_ok=True)
                shutil.copy2(src_full, dst_full)
                media_copied += 1

    # --- 4. Write manifest ---
    manifest = {
        "timestamp": timestamp,
        "synced_at": timezone.now().isoformat(),
        "reason": reason,
        "db_size_mb": round(db_size_mb, 1),
        "media_copied": media_copied,
        "media_skipped": media_skipped,
    }
    try:
        from version import __version__
        manifest["app_version"] = __version__
    except Exception:
        manifest["app_version"] = "unknown"

    manifest_path = dest / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    elapsed = time.perf_counter() - t0

    msg = (
        f"Backup synced to {dest.name}: "
        f"DB {db_size_mb:.0f} MB, "
        f"{media_copied} media files copied, "
        f"{media_skipped} unchanged "
        f"({elapsed:.1f}s)"
    )
    logger.info("[Backup] %s (reason=%s)", msg, reason)
    return str(dest), msg


def sync_to_all_paths(*, reason="manual"):
    """Sync backup to all configured paths in parallel.

    Returns a combined status message. Never raises (logs errors).
    """
    try:
        from backup.models import BackupSettings
        cfg = BackupSettings.get()
    except Exception as exc:
        logger.warning("[Backup] Could not load settings: %s", exc)
        return f"Backup failed: {exc}"

    paths = []
    if cfg.local_backup_path:
        paths.append(("Local", cfg.local_backup_path))
    if cfg.external_backup_path:
        paths.append(("External", cfg.external_backup_path))

    if not paths:
        return "No backup paths configured."

    results = {}

    def _sync(label, path):
        try:
            p = Path(path)
            if not _is_path_available(path):
                results[label] = f"{label}: drive not available ({path})"
                return
            _, msg = sync_backup(path, reason=reason)
            enforce_max_snapshots(path, cfg.max_backups)
            results[label] = f"{label}: OK - {msg}"
        except Exception as exc:
            logger.exception("[Backup] %s sync failed", label)
            results[label] = f"{label}: FAILED - {exc}"

    if len(paths) == 1:
        _sync(*paths[0])
    else:
        threads = []
        for label, path in paths:
            t = threading.Thread(target=_sync, args=(label, path), daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=300)

    combined = " | ".join(results.get(label, f"{label}: unknown") for label, _ in paths)
    _update_status(
        success=all("OK" in results.get(label, "") for label, _ in paths),
        message=combined,
    )
    return combined


def enforce_max_snapshots(backup_dir, max_count):
    """Delete oldest DB snapshots in history/ if we exceed max_count."""
    history = Path(backup_dir) / HISTORY_DIR
    if not history.is_dir():
        return
    snapshots = sorted(
        history.glob(f"{HISTORY_PREFIX}*.sqlite3"),
        key=lambda p: p.stat().st_mtime,
    )
    while len(snapshots) > max_count:
        oldest = snapshots.pop(0)
        try:
            oldest.unlink()
            logger.info("[Backup] Pruned old snapshot: %s", oldest.name)
        except OSError as exc:
            logger.warning("[Backup] Could not delete %s: %s", oldest.name, exc)


def restore_from_backup(backup_source):
    """Restore database and media from a backup folder or legacy .zip.

    Returns a message string. Raises on validation failure.
    """
    source = Path(backup_source)

    if source.is_dir():
        return _restore_from_folder(source)
    elif source.is_file() and source.suffix.lower() == ".zip":
        return _restore_from_zip(source)
    else:
        raise ValueError("Please select a backup folder or a .zip backup file.")


def _restore_from_folder(source):
    """Restore from a folder-based backup."""
    db_file = source / "db.sqlite3"
    if not db_file.exists():
        raise ValueError(f"Invalid backup folder: no db.sqlite3 found in {source}")

    db_path = _get_db_path()
    media_root = _get_media_root()

    from django.db import connections
    for conn in connections.all():
        conn.close()

    shutil.copy2(str(db_file), str(db_path))

    source_media = source / "media"
    if source_media.is_dir():
        if media_root.exists():
            shutil.rmtree(str(media_root))
        shutil.copytree(str(source_media), str(media_root))

    manifest = {}
    manifest_file = source / "manifest.json"
    if manifest_file.exists():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    synced_at = manifest.get("synced_at", "unknown time")
    version = manifest.get("app_version", "unknown")
    msg = f"Restored from folder backup (synced {synced_at}, v{version}). Please restart the application."
    logger.info("[Backup] %s", msg)
    return msg


def _restore_from_zip(zip_path):
    """Restore from a legacy .zip backup (backward compatibility)."""
    import tempfile

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        if "db.sqlite3" not in names:
            raise ValueError("Invalid backup: missing db.sqlite3")
        if "manifest.json" not in names:
            raise ValueError("Invalid backup: missing manifest.json")
        manifest_data = json.loads(zf.read("manifest.json"))

    db_path = _get_db_path()
    media_root = _get_media_root()

    from django.db import connections
    for conn in connections.all():
        conn.close()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp)

        restored_db = tmp / "db.sqlite3"
        if restored_db.exists():
            shutil.copy2(str(restored_db), str(db_path))

        restored_media = tmp / "media"
        if restored_media.is_dir():
            if media_root.exists():
                shutil.rmtree(str(media_root))
            shutil.copytree(str(restored_media), str(media_root))

    created = manifest_data.get("created_at", "unknown time")
    version = manifest_data.get("app_version", "unknown")
    msg = f"Restored from zip backup created {created} (v{version}). Please restart the application."
    logger.info("[Backup] %s", msg)
    return msg


def get_snapshot_list(backup_dir):
    """List historical DB snapshots in a backup folder.

    Returns a list of dicts sorted newest-first.
    """
    dest = Path(backup_dir)
    if not dest.is_dir():
        return []

    results = []

    main_db = dest / "db.sqlite3"
    if main_db.exists():
        stat = main_db.stat()
        results.append({
            "filename": "db.sqlite3 (latest)",
            "full_path": str(dest),
            "size_mb": round(stat.st_size / (1024 * 1024), 1),
            "modified": datetime.fromtimestamp(stat.st_mtime),
            "is_latest": True,
        })

    history = dest / HISTORY_DIR
    if history.is_dir():
        for snap in history.glob(f"{HISTORY_PREFIX}*.sqlite3"):
            stat = snap.stat()
            results.append({
                "filename": snap.name,
                "full_path": str(snap),
                "size_mb": round(stat.st_size / (1024 * 1024), 1),
                "modified": datetime.fromtimestamp(stat.st_mtime),
                "is_latest": False,
            })

    results.sort(key=lambda x: x["modified"], reverse=True)
    return results


def get_backup_info(backup_dir):
    """Get summary info about a backup folder."""
    dest = Path(backup_dir)
    if not dest.is_dir():
        return None

    info = {"path": str(dest), "has_db": False, "media_count": 0, "media_size_mb": 0}

    db_file = dest / "db.sqlite3"
    if db_file.exists():
        info["has_db"] = True
        info["db_size_mb"] = round(db_file.stat().st_size / (1024 * 1024), 1)

    media_dir = dest / "media"
    if media_dir.is_dir():
        total = 0
        count = 0
        for f in media_dir.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
                count += 1
        info["media_count"] = count
        info["media_size_mb"] = round(total / (1024 * 1024), 1)

    manifest_file = dest / "manifest.json"
    if manifest_file.exists():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            info["last_synced"] = manifest.get("synced_at")
            info["app_version"] = manifest.get("app_version")
            info["reason"] = manifest.get("reason")
        except Exception:
            pass

    snapshot_count = 0
    history = dest / HISTORY_DIR
    if history.is_dir():
        snapshot_count = sum(1 for _ in history.glob(f"{HISTORY_PREFIX}*.sqlite3"))
    info["snapshot_count"] = snapshot_count

    return info


def _is_path_available(backup_path):
    """Check whether a backup destination is reachable."""
    if not backup_path:
        return False
    return Path(backup_path).is_dir() or _can_create_path(backup_path)


def _can_create_path(backup_path):
    """Check if we can create the path (parent drive exists)."""
    try:
        p = Path(backup_path)
        if p.anchor and Path(p.anchor).exists():
            return True
    except Exception:
        pass
    return False


def is_backup_path_available(backup_path):
    """Public wrapper for path availability check."""
    return _is_path_available(backup_path)


def _update_status(*, success, message):
    """Update the BackupSettings singleton with last-backup info."""
    try:
        from backup.models import BackupSettings
        obj = BackupSettings.get()
        obj.last_backup_at = timezone.now()
        obj.last_backup_status = ("OK: " if success else "FAILED: ") + message[:490]
        obj.save(update_fields=["last_backup_at", "last_backup_status"])
    except Exception as exc:
        logger.warning("[Backup] Could not update status record: %s", exc)
