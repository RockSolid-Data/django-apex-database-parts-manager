"""
Tests for data_import.management.commands.sync_catalog.

Covers the critical business invariant: insert-only mode adds new seed
rows without touching existing catalog_part business fields.

Uses TransactionTestCase because sync_catalog uses ATTACH DATABASE,
which is incompatible with Django TestCase's transaction wrapping.
"""

import sqlite3
import tempfile
from decimal import Decimal
from pathlib import Path

from django.core.management import call_command
from django.test import TransactionTestCase

from catalog.models import Part


def _create_seed_db(path, rows):
    """Build a minimal seed.sqlite3 containing catalog_part rows.

    Each row dict must include at least ``seed_id`` and ``part_number``.
    """
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE catalog_part (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            seed_id       INTEGER,
            part_number   TEXT,
            part_name     TEXT DEFAULT '',
            yt_number     TEXT DEFAULT '',
            j_and_n       TEXT DEFAULT '',
            oem_number    TEXT DEFAULT '',
            category      TEXT DEFAULT '',
            catalog       TEXT DEFAULT '',
            cost_price    REAL,
            stock_quantity INTEGER DEFAULT 0,
            reorder_qty   INTEGER DEFAULT 0,
            bin_number    TEXT DEFAULT '',
            markup_percent REAL,
            price         REAL,
            manufacturer_number TEXT DEFAULT '',
            item_no       TEXT DEFAULT '',
            type          TEXT DEFAULT '',
            oem_type      TEXT DEFAULT '',
            item_typ      TEXT DEFAULT '',
            oem           TEXT DEFAULT '',
            primary_vendor TEXT DEFAULT '',
            plug_id       TEXT DEFAULT '',
            voltage       TEXT DEFAULT '',
            notes         TEXT DEFAULT '',
            foot_notes    TEXT DEFAULT '',
            superseding_notes TEXT DEFAULT '',
            specifications TEXT DEFAULT '[]',
            has_picture   INTEGER DEFAULT 0,
            has_interchange INTEGER DEFAULT 0,
            has_superseding INTEGER DEFAULT 0,
            is_active     INTEGER DEFAULT 1,
            track_inventory INTEGER DEFAULT 0,
            price_updated_at TEXT,
            created_at    TEXT DEFAULT '',
            updated_at    TEXT DEFAULT '',
            image         TEXT DEFAULT '',
            source_pdf    TEXT DEFAULT '',
            unit_id       INTEGER
        )
        """
    )
    for row in rows:
        cols = list(row.keys())
        placeholders = ", ".join("?" for _ in cols)
        col_names = ", ".join(cols)
        conn.execute(
            f"INSERT INTO catalog_part ({col_names}) VALUES ({placeholders})",
            [row[c] for c in cols],
        )
    conn.commit()
    conn.close()


class SyncCatalogInsertOnlyTest(TransactionTestCase):
    """Default mode (no --fill-blanks): only INSERT new records."""

    serialized_rollback = True

    def test_inserts_new_rows_from_seed(self):
        """New seed rows are inserted into the customer DB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            seed_path = Path(tmpdir) / "seed.sqlite3"
            _create_seed_db(seed_path, [
                {"seed_id": 90001, "part_number": "SEED-NEW-001", "part_name": "New Part A", "category": "Brushes"},
                {"seed_id": 90002, "part_number": "SEED-NEW-002", "part_name": "New Part B", "category": "Bearings"},
            ])
            call_command("sync_catalog", seed_db=str(seed_path))

        self.assertTrue(Part.objects.filter(part_number="SEED-NEW-001").exists())
        self.assertTrue(Part.objects.filter(part_number="SEED-NEW-002").exists())
        self.assertEqual(Part.objects.get(part_number="SEED-NEW-001").part_name, "New Part A")

    def test_insert_only_does_not_overwrite_existing(self):
        """Existing rows are untouched in default insert-only mode."""
        existing = Part.objects.create(
            seed_id=80001, part_number="EXISTING-001", part_name="Original Name",
            category="Brushes",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            seed_path = Path(tmpdir) / "seed.sqlite3"
            _create_seed_db(seed_path, [
                {"seed_id": 80001, "part_number": "EXISTING-001", "part_name": "Seed Override Name", "category": "Armatures"},
            ])
            call_command("sync_catalog", seed_db=str(seed_path))

        existing.refresh_from_db()
        self.assertEqual(existing.part_name, "Original Name")
        self.assertEqual(existing.category, "Brushes")

    def test_insert_preserves_business_fields(self):
        """BUSINESS_FIELDS (cost_price, stock_quantity, etc.) are never overwritten,
        even with --force-update."""
        part = Part.objects.create(
            seed_id=70001, part_number="BIZ-001",
            cost_price=Decimal("99.99"), stock_quantity=42, reorder_qty=10,
            bin_number="A-7",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            seed_path = Path(tmpdir) / "seed.sqlite3"
            _create_seed_db(seed_path, [
                {
                    "seed_id": 70001, "part_number": "BIZ-001",
                    "cost_price": 1.00, "stock_quantity": 0, "reorder_qty": 0,
                    "bin_number": "Z-99", "part_name": "Seed Name",
                },
            ])
            call_command("sync_catalog", seed_db=str(seed_path), force_update=True)

        part.refresh_from_db()
        self.assertEqual(part.cost_price, Decimal("99.99"))
        self.assertEqual(part.stock_quantity, 42)
        self.assertEqual(part.reorder_qty, 10)
        self.assertEqual(part.bin_number, "A-7")


class SyncCatalogDryRunTest(TransactionTestCase):
    """--dry-run reports what would change without writing."""

    def test_dry_run_does_not_insert(self):
        """No rows are inserted when --dry-run is active."""
        initial_count = Part.objects.count()
        with tempfile.TemporaryDirectory() as tmpdir:
            seed_path = Path(tmpdir) / "seed.sqlite3"
            _create_seed_db(seed_path, [
                {"seed_id": 60001, "part_number": "DRY-001", "part_name": "Should Not Appear"},
            ])
            call_command("sync_catalog", seed_db=str(seed_path), dry_run=True)

        self.assertEqual(Part.objects.count(), initial_count)
        self.assertFalse(Part.objects.filter(part_number="DRY-001").exists())


class SyncCatalogFillBlanksTest(TransactionTestCase):
    """--fill-blanks fills NULL/empty catalog fields from seed."""

    def test_fill_blanks_fills_empty_field(self):
        """Empty catalog fields are filled from seed data."""
        part = Part.objects.create(
            seed_id=50001, part_number="FILL-001", part_name="", category="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            seed_path = Path(tmpdir) / "seed.sqlite3"
            _create_seed_db(seed_path, [
                {"seed_id": 50001, "part_number": "FILL-001", "part_name": "Filled Name", "category": "Brushes"},
            ])
            call_command("sync_catalog", seed_db=str(seed_path), fill_blanks=True)

        part.refresh_from_db()
        self.assertEqual(part.part_name, "Filled Name")
        self.assertEqual(part.category, "Brushes")

    def test_fill_blanks_does_not_overwrite_existing_value(self):
        """Non-empty catalog fields are left alone in fill-blanks mode."""
        part = Part.objects.create(
            seed_id=50002, part_number="FILL-002", part_name="Customer Name",
            category="Bearings",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            seed_path = Path(tmpdir) / "seed.sqlite3"
            _create_seed_db(seed_path, [
                {"seed_id": 50002, "part_number": "FILL-002", "part_name": "Seed Name", "category": "Armatures"},
            ])
            call_command("sync_catalog", seed_db=str(seed_path), fill_blanks=True)

        part.refresh_from_db()
        self.assertEqual(part.part_name, "Customer Name")
        self.assertEqual(part.category, "Bearings")
