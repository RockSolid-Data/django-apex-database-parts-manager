"""
Tests for backup/utils.py helper functions.

Tests enforce_max_snapshots, get_backup_info, and get_snapshot_list
using temp directories. sync_backup integration tests are skipped
because sqlite3.backup() deadlocks with the in-memory test DB; the
backup flow is exercised by the existing e2e smoke test instead.
"""

import json
import os
import tempfile
from pathlib import Path

from django.test import TestCase

from backup.utils import enforce_max_snapshots, get_backup_info, get_snapshot_list


class EnforceMaxSnapshotsTest(TestCase):
    """enforce_max_snapshots prunes oldest snapshots beyond max_count."""

    def test_prunes_oldest_when_over_max(self):
        """Only the newest snapshots survive after enforcement."""
        with tempfile.TemporaryDirectory() as dest:
            history = Path(dest) / "history"
            history.mkdir()
            for i in range(5):
                snap = history / f"db_2026-01-0{i+1}_120000.sqlite3"
                snap.write_bytes(b"db")
                os.utime(str(snap), (1000 + i, 1000 + i))

            enforce_max_snapshots(dest, max_count=3)

            remaining = sorted(history.glob("db_*.sqlite3"))
            self.assertEqual(len(remaining), 3)
            names = [s.name for s in remaining]
            self.assertIn("db_2026-01-05_120000.sqlite3", names)
            self.assertIn("db_2026-01-04_120000.sqlite3", names)
            self.assertIn("db_2026-01-03_120000.sqlite3", names)

    def test_no_op_when_under_max(self):
        """No pruning when snapshot count is within limit."""
        with tempfile.TemporaryDirectory() as dest:
            history = Path(dest) / "history"
            history.mkdir()
            (history / "db_2026-06-01_100000.sqlite3").write_bytes(b"db")

            enforce_max_snapshots(dest, max_count=5)
            self.assertEqual(len(list(history.glob("db_*.sqlite3"))), 1)

    def test_handles_missing_history_dir(self):
        """No error when history/ doesn't exist."""
        with tempfile.TemporaryDirectory() as dest:
            enforce_max_snapshots(dest, max_count=3)


class GetBackupInfoTest(TestCase):
    """get_backup_info reads manifest data without walking media tree."""

    def test_returns_none_for_nonexistent_dir(self):
        self.assertIsNone(get_backup_info("/nonexistent/path"))

    def test_reads_manifest_data(self):
        with tempfile.TemporaryDirectory() as dest:
            db_path = Path(dest) / "db.sqlite3"
            db_path.write_bytes(b"x" * 4096)
            manifest = {
                "synced_at": "2026-07-09T12:00:00",
                "app_version": "1.0",
                "reason": "auto",
                "media_total_files": 42,
                "media_total_size_mb": 3.5,
            }
            (Path(dest) / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            info = get_backup_info(dest)
            self.assertTrue(info["has_db"])
            self.assertEqual(info["media_count"], 42)
            self.assertEqual(info["media_size_mb"], 3.5)
            self.assertEqual(info["reason"], "auto")

    def test_has_db_false_when_no_db_file(self):
        with tempfile.TemporaryDirectory() as dest:
            info = get_backup_info(dest)
            self.assertFalse(info["has_db"])

    def test_snapshot_count(self):
        with tempfile.TemporaryDirectory() as dest:
            history = Path(dest) / "history"
            history.mkdir()
            for i in range(3):
                (history / f"db_2026-01-0{i+1}_120000.sqlite3").write_bytes(b"x")

            info = get_backup_info(dest)
            self.assertEqual(info["snapshot_count"], 3)


class GetSnapshotListTest(TestCase):
    """get_snapshot_list returns snapshots sorted newest-first."""

    def test_returns_empty_for_nonexistent_dir(self):
        self.assertEqual(get_snapshot_list("/nonexistent"), [])

    def test_returns_snapshots_newest_first(self):
        with tempfile.TemporaryDirectory() as dest:
            history = Path(dest) / "history"
            history.mkdir()
            for i in range(3):
                snap = history / f"db_2026-01-0{i+1}_120000.sqlite3"
                snap.write_bytes(b"db")
                os.utime(str(snap), (1000 + i, 1000 + i))

            result = get_snapshot_list(dest)
            non_latest = [r for r in result if not r.get("is_latest")]
            self.assertEqual(len(non_latest), 3)
            self.assertEqual(non_latest[0]["filename"], "db_2026-01-03_120000.sqlite3")

    def test_includes_latest_db(self):
        with tempfile.TemporaryDirectory() as dest:
            (Path(dest) / "db.sqlite3").write_bytes(b"main_db")
            result = get_snapshot_list(dest)
            latest = [r for r in result if r.get("is_latest")]
            self.assertEqual(len(latest), 1)
            self.assertIn("latest", latest[0]["filename"])

    def test_size_mb_populated(self):
        with tempfile.TemporaryDirectory() as dest:
            history = Path(dest) / "history"
            history.mkdir()
            (history / "db_2026-07-01_100000.sqlite3").write_bytes(b"x" * 2048)
            result = get_snapshot_list(dest)
            non_latest = [r for r in result if not r.get("is_latest")]
            self.assertEqual(len(non_latest), 1)
            self.assertIn("size_mb", non_latest[0])
