"""
Import YouTech interchange data from a staging DB into the Django catalog.

Staging DBs are produced by the PDF parsers in data_import/pdf_parsers/.
Each staging DB has a table `interchange_by_mfr` with columns:
    manufacturer, their_number, our_number, page_number

This command:
  1. Creates Unit records for each unique our_number (YouTech number)
     that doesn't already exist.
  2. Creates CrossReference records linking each Unit to the
     manufacturer's part number (their_number).

Usage:
    python manage.py import_youtech_interchange --file "data_import/staging_dbs/1-Interchange by Mfr.db"
    python manage.py import_youtech_interchange --all
    python manage.py import_youtech_interchange --file "..." --report-only
"""

import glob
import os
import sqlite3
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from catalog.models import CrossReference, Unit


BATCH_SIZE = 5000

KNOWN_TABLES = (
    "interchange_by_mfr",
    "interchange_by_number",
    "our_numbers_to_others",
    "buyers_guide_interchanges",
)


def _find_interchange_table(conn):
    """Auto-detect the interchange table name in the staging DB."""
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for t in KNOWN_TABLES:
        if t in tables:
            return t
    if tables:
        return tables[0]
    return None


class Command(BaseCommand):
    help = "Import YouTech interchange staging DBs into the catalog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=None,
            help="Path to a specific staging DB to import",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Import all staging DBs in data_import/staging_dbs/",
        )
        parser.add_argument(
            "--report-only",
            action="store_true",
            dest="report_only",
            help="Show what would be imported without making changes",
        )
        parser.add_argument(
            "--clear-xrefs",
            action="store_true",
            dest="clear_xrefs",
            help="Clear all existing CrossReference records before import",
        )

    def handle(self, *args, **options):
        staging_dir = Path(settings.BASE_DIR) / "data_import" / "staging_dbs"

        if options["file"]:
            files = [Path(options["file"])]
        elif options["all"]:
            files = sorted(staging_dir.glob("*.db"))
        else:
            self.stderr.write(self.style.ERROR("Specify --file <path> or --all"))
            return

        if not files:
            self.stderr.write(self.style.ERROR("No staging DB files found."))
            return

        for f in files:
            if not f.exists():
                self.stderr.write(self.style.ERROR(f"File not found: {f}"))
                return

        if options["report_only"]:
            for f in files:
                self._report(f)
            return

        if options["clear_xrefs"]:
            count = CrossReference.objects.count()
            CrossReference.objects.all().delete()
            self.stdout.write(f"Cleared {count:,} existing CrossReference records.")

        for f in files:
            self._import_file(f)

    def _report(self, db_path: Path):
        """Show summary of what the staging DB contains."""
        conn = sqlite3.connect(str(db_path))
        table = _find_interchange_table(conn)
        if not table:
            self.stderr.write(self.style.ERROR(f"No interchange table found in {db_path}"))
            conn.close()
            return

        total = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
        unique_our = conn.execute(f"SELECT COUNT(DISTINCT our_number) FROM [{table}]").fetchone()[0]
        unique_their = conn.execute(f"SELECT COUNT(DISTINCT their_number) FROM [{table}]").fetchone()[0]
        unique_mfr = conn.execute(f"SELECT COUNT(DISTINCT manufacturer) FROM [{table}]").fetchone()[0]

        our_numbers = set(
            r[0] for r in conn.execute(f"SELECT DISTINCT our_number FROM [{table}]")
        )
        existing_set = set(Unit.objects.values_list("unit_number", flat=True))
        existing_units = len(our_numbers & existing_set)
        new_units = len(our_numbers) - existing_units

        conn.close()

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"REPORT: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Total interchange records:   {total:>10,}")
        self.stdout.write(f"  Unique manufacturers:        {unique_mfr:>10,}")
        self.stdout.write(f"  Unique 'their' numbers:      {unique_their:>10,}")
        self.stdout.write(f"  Unique YouTech numbers:      {unique_our:>10,}")
        self.stdout.write(f"  Units already in system:     {existing_units:>10,}")
        self.stdout.write(f"  New units to create:         {new_units:>10,}")
        self.stdout.write("")

    def _import_file(self, db_path: Path):
        """Import one staging DB into the catalog."""
        self.stdout.write(f"\nImporting: {db_path.name}")
        self.stdout.write("-" * 60)
        t0 = time.time()

        conn = sqlite3.connect(str(db_path))
        table = _find_interchange_table(conn)
        if not table:
            self.stderr.write(self.style.ERROR(f"No interchange table found in {db_path}"))
            conn.close()
            return

        # --- Step 1: Create Unit records for new YouTech numbers ---
        self.stdout.write("Step 1: Creating Unit records for new YouTech numbers...")
        t1 = time.time()

        our_numbers = [
            r[0] for r in conn.execute(f"SELECT DISTINCT our_number FROM [{table}]")
        ]

        existing_unit_numbers = set(Unit.objects.values_list("unit_number", flat=True))

        new_units = [num for num in our_numbers if num not in existing_unit_numbers]

        if new_units:
            batch = []
            for num in new_units:
                batch.append(Unit(unit_number=num))
                if len(batch) >= BATCH_SIZE:
                    Unit.objects.bulk_create(batch, ignore_conflicts=True)
                    batch = []
            if batch:
                Unit.objects.bulk_create(batch, ignore_conflicts=True)

        self.stdout.write(
            f"  {len(new_units):,} new units created, "
            f"{len(existing_unit_numbers):,} already existed  "
            f"({time.time() - t1:.1f}s)"
        )

        # --- Build unit_number -> pk lookup ---
        self.stdout.write("  Building unit lookup...")
        unit_map = dict(Unit.objects.values_list("unit_number", "pk"))

        # --- Step 1b: Update descriptions if available ---
        has_desc = False
        try:
            conn.execute(f"SELECT description FROM [{table}] LIMIT 1")
            has_desc = True
        except sqlite3.OperationalError:
            pass

        if has_desc:
            self.stdout.write("  Updating unit descriptions from staging data...")
            desc_cursor = conn.execute(
                f"SELECT our_number, description FROM [{table}] "
                f"WHERE description IS NOT NULL AND description != '' "
                f"GROUP BY our_number"
            )
            desc_updated = 0
            for our_no, desc in desc_cursor:
                pk = unit_map.get(our_no)
                if pk and desc.strip():
                    updated = Unit.objects.filter(pk=pk, description="").update(
                        description=desc.strip()
                    )
                    desc_updated += updated
            self.stdout.write(f"  {desc_updated:,} unit descriptions updated")

        # --- Step 2: Create CrossReference records ---
        self.stdout.write("Step 2: Creating CrossReference records...")
        t2 = time.time()

        total_rows = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
        cursor = conn.execute(
            f"SELECT manufacturer, their_number, our_number FROM [{table}]"
        )

        xref_batch = []
        seen = set()
        created = 0
        skipped_dup = 0
        skipped_no_unit = 0
        processed = 0

        for mfr, their_no, our_no in cursor:
            processed += 1
            unit_pk = unit_map.get(our_no)
            if not unit_pk:
                skipped_no_unit += 1
                continue

            dedup_key = (unit_pk, their_no[:100], mfr[:150])
            if dedup_key in seen:
                skipped_dup += 1
                continue
            seen.add(dedup_key)

            other_unit_pk = unit_map.get(their_no)
            xref = CrossReference(
                unit_id=unit_pk,
                cross_ref_number=their_no[:100],
                interchange_type=mfr[:150],
            )
            if other_unit_pk and other_unit_pk != unit_pk:
                xref.cross_ref_unit_id = other_unit_pk

            xref_batch.append(xref)

            if len(xref_batch) >= BATCH_SIZE:
                CrossReference.objects.bulk_create(xref_batch, ignore_conflicts=True)
                created += len(xref_batch)
                xref_batch = []

            if processed % 200000 == 0:
                self.stdout.write(
                    f"  Progress: {processed:,}/{total_rows:,} rows  |  "
                    f"{created:,} xrefs created"
                )

        if xref_batch:
            CrossReference.objects.bulk_create(xref_batch, ignore_conflicts=True)
            created += len(xref_batch)

        conn.close()
        elapsed = time.time() - t0

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"IMPORT COMPLETE: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Cross-references created:    {created:>10,}")
        self.stdout.write(f"  Duplicates skipped:          {skipped_dup:>10,}")
        self.stdout.write(f"  No unit found (skipped):     {skipped_no_unit:>10,}")
        self.stdout.write(f"  Total time:                  {elapsed:>10.1f}s")
        self.stdout.write("")

        db_unit_count = Unit.objects.count()
        db_xref_count = CrossReference.objects.count()
        self.stdout.write(f"  Database totals: {db_unit_count:,} units, {db_xref_count:,} cross-references")
        self.stdout.write("")
