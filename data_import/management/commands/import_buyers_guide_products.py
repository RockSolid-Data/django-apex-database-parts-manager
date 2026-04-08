"""Import buyers-guide product rows into canonical YouTech Unit records."""

import sqlite3
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from catalog.models import Unit
from data_import.import_utils import append_text, normalize_space


class Command(BaseCommand):
    help = "Import buyers-guide product rows into Unit records keyed by YouTech number."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=None,
            help="Path to the buyers guide staging DB",
        )
        parser.add_argument(
            "--report-only",
            action="store_true",
            dest="report_only",
            help="Show what would be imported without making changes",
        )

    def handle(self, *args, **options):
        db_path = self._resolve_db_path(options.get("file"))
        if not db_path.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {db_path}"))
            return

        if options["report_only"]:
            self._report(db_path)
            return

        self._import(db_path)

    def _resolve_db_path(self, explicit_path):
        if explicit_path:
            return Path(explicit_path)
        return Path(settings.BASE_DIR) / "data_import" / "staging_dbs" / "buyers_guide.db"

    def _load_rows(self, conn):
        conn.row_factory = sqlite3.Row
        return conn.execute(
            """
            SELECT youtech_number, jn_number, manufacture, oe_manufacturer,
                   family, voltage, rotation, product_notes
            FROM buyers_guide_products
            ORDER BY youtech_number
            """
        ).fetchall()

    def _report(self, db_path: Path):
        conn = sqlite3.connect(str(db_path))
        product_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_products").fetchone()[0]
        unique_units = conn.execute(
            "SELECT COUNT(DISTINCT youtech_number) FROM buyers_guide_products WHERE youtech_number != ''"
        ).fetchone()[0]
        youtech_numbers = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT youtech_number FROM buyers_guide_products WHERE youtech_number != ''"
            )
        }
        conn.close()

        existing_units = Unit.objects.filter(unit_number__in=youtech_numbers).count()
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"REPORT: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Staged product rows:         {product_count:>10,}")
        self.stdout.write(f"  Unique YouTech units:        {unique_units:>10,}")
        self.stdout.write(f"  Existing Unit records:       {existing_units:>10,}")
        self.stdout.write(f"  New Unit records:            {unique_units - existing_units:>10,}")
        self.stdout.write("")

    def _import(self, db_path: Path):
        self.stdout.write(f"\nImporting: {db_path.name}")
        self.stdout.write("-" * 60)
        start = time.time()

        conn = sqlite3.connect(str(db_path))
        rows = self._load_rows(conn)
        conn.close()

        youtech_numbers = sorted(
            {normalize_space(row["youtech_number"]) for row in rows if normalize_space(row["youtech_number"])}
        )
        if not youtech_numbers:
            self.stdout.write("No staged buyers-guide product rows found.")
            return

        existing_units = {
            normalize_space(unit.unit_number): unit
            for unit in Unit.objects.filter(unit_number__in=youtech_numbers)
        }

        created_units = []
        seen_new = set()
        for row in rows:
            youtech_number = normalize_space(row["youtech_number"])
            if not youtech_number or youtech_number in existing_units or youtech_number in seen_new:
                continue
            seen_new.add(youtech_number)
            created_units.append(
                Unit(
                    unit_number=youtech_number[:100],
                    yt_number=youtech_number[:100],
                    j_and_n_number=normalize_space(row["jn_number"])[:100],
                    manufacturer=normalize_space(row["manufacture"])[:200],
                    oem=normalize_space(row["oe_manufacturer"])[:200],
                    family=normalize_space(row["family"])[:100],
                    voltage=normalize_space(row["voltage"])[:50],
                    rotation=normalize_space(row["rotation"])[:50],
                    notes=normalize_space(row["product_notes"])[:2000],
                )
            )
        if created_units:
            Unit.objects.bulk_create(created_units, batch_size=500)
            existing_units = {
                normalize_space(unit.unit_number): unit
                for unit in Unit.objects.filter(unit_number__in=youtech_numbers)
            }

        updated_units = {}
        for row in rows:
            youtech_number = normalize_space(row["youtech_number"])
            unit = existing_units.get(youtech_number)
            if not unit:
                continue
            changed = False
            if not unit.yt_number:
                unit.yt_number = youtech_number[:100]
                changed = True
            if not unit.j_and_n_number and row["jn_number"]:
                unit.j_and_n_number = normalize_space(row["jn_number"])[:100]
                changed = True
            if not unit.manufacturer and row["manufacture"]:
                unit.manufacturer = normalize_space(row["manufacture"])[:200]
                changed = True
            if not unit.oem and row["oe_manufacturer"]:
                unit.oem = normalize_space(row["oe_manufacturer"])[:200]
                changed = True
            if not unit.family and row["family"]:
                unit.family = normalize_space(row["family"])[:100]
                changed = True
            if not unit.voltage and row["voltage"]:
                unit.voltage = normalize_space(row["voltage"])[:50]
                changed = True
            if not unit.rotation and row["rotation"]:
                unit.rotation = normalize_space(row["rotation"])[:50]
                changed = True
            if row["product_notes"]:
                merged_notes = append_text(unit.notes, row["product_notes"])
                if merged_notes != unit.notes:
                    unit.notes = merged_notes[:2000]
                    changed = True
            if changed:
                updated_units[unit.pk] = unit

        if updated_units:
            Unit.objects.bulk_update(
                list(updated_units.values()),
                ["yt_number", "j_and_n_number", "manufacturer", "oem", "family", "voltage", "rotation", "notes"],
                batch_size=500,
            )

        elapsed = time.time() - start
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"IMPORT COMPLETE: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Units created:              {len(created_units):>10,}")
        self.stdout.write(f"  Units updated:              {len(updated_units):>10,}")
        self.stdout.write(f"  Total time:                 {elapsed:>10.1f}s")
        self.stdout.write("")
