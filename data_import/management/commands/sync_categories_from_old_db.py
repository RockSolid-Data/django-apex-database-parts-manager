"""
Sync part categories and unit type categories from the OLD database (db.sqlite3)
into the current (staging) database via Django ORM writes + direct sqlite3 reads.

Match keys:
  - Parts:  yt_number (present on all parts in both DBs)
  - Units:  unit_number (present on ~98% of units)

Modes:
  --mode=sync   (default) Copy from old → staging where old HAS a value and
                staging is empty OR different.
  --mode=strict Also CLEAR staging values where old has NO value (removes
                keyword-assigned categories that don't exist in old DB).

Usage:
  python manage.py sync_categories_from_old_db --dry-run
  python manage.py sync_categories_from_old_db --dry-run --mode=strict
  python manage.py sync_categories_from_old_db
"""

import sqlite3
from pathlib import Path

from django.core.management.base import BaseCommand

from catalog.models import Part, Unit


class Command(BaseCommand):
    help = "Sync category/unit_type_category from old db.sqlite3 into staging."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing.",
        )
        parser.add_argument(
            "--mode",
            choices=["sync", "strict"],
            default="sync",
            help=(
                "sync = only overwrite where old has data; "
                "strict = also clear staging where old is empty."
            ),
        )
        parser.add_argument(
            "--old-db",
            default="db.sqlite3",
            help="Path to the old database file (default: db.sqlite3).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        mode = options["mode"]
        old_db_path = Path(options["old_db"])

        if not old_db_path.exists():
            self.stderr.write(self.style.ERROR(f"Old DB not found: {old_db_path}"))
            return

        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write(f"{prefix}Mode: {mode}")
        self.stdout.write(f"{prefix}Old DB: {old_db_path}")
        self.stdout.write("")

        old = sqlite3.connect(str(old_db_path))

        self._sync_parts(old, mode, dry_run, prefix)
        self.stdout.write("")
        self._sync_units(old, mode, dry_run, prefix)

        old.close()

    # ------------------------------------------------------------------
    # Parts
    # ------------------------------------------------------------------
    def _sync_parts(self, old, mode, dry_run, prefix):
        self.stdout.write(self.style.MIGRATE_HEADING("--- PARTS ---"))

        old_data = {}
        for row in old.execute(
            "SELECT yt_number, category, specifications FROM catalog_part "
            "WHERE yt_number != ''"
        ):
            old_data[row[0]] = (row[1], row[2])  # (category, specs_json)

        self.stdout.write(f"Old DB parts loaded: {len(old_data)}")
        old_with_cat = sum(1 for _, (c, _) in old_data.items() if c)
        self.stdout.write(f"Old DB parts with category: {old_with_cat}")

        staging_parts = Part.objects.all().only(
            "id", "yt_number", "category", "specifications"
        )

        stats = {
            "matched": 0,
            "cat_copied": 0,
            "cat_cleared": 0,
            "specs_copied": 0,
            "specs_cleared": 0,
            "unmatched_staging": 0,
        }
        cat_breakdown = {}

        for part in staging_parts.iterator(chunk_size=2000):
            if not part.yt_number:
                stats["unmatched_staging"] += 1
                continue

            old_entry = old_data.get(part.yt_number)
            if old_entry is None:
                stats["unmatched_staging"] += 1
                continue

            stats["matched"] += 1
            old_cat, old_specs_json = old_entry
            import json
            old_specs = json.loads(old_specs_json) if old_specs_json else {}

            update_fields = []

            # Category
            if old_cat and part.category != old_cat:
                cat_breakdown[old_cat] = cat_breakdown.get(old_cat, 0) + 1
                if not dry_run:
                    part.category = old_cat
                update_fields.append("category")
                stats["cat_copied"] += 1
            elif mode == "strict" and not old_cat and part.category:
                if not dry_run:
                    part.category = ""
                update_fields.append("category")
                stats["cat_cleared"] += 1

            # Specifications
            if old_specs and part.specifications != old_specs:
                if not dry_run:
                    part.specifications = old_specs
                update_fields.append("specifications")
                stats["specs_copied"] += 1
            elif mode == "strict" and not old_specs and part.specifications:
                if not dry_run:
                    part.specifications = {}
                update_fields.append("specifications")
                stats["specs_cleared"] += 1

            if update_fields and not dry_run:
                part.save(update_fields=update_fields)

        self.stdout.write(f"\n{prefix}Parts results:")
        self.stdout.write(f"  Matched by yt_number: {stats['matched']}")
        self.stdout.write(f"  Categories copied (old->staging): {stats['cat_copied']}")
        if mode == "strict":
            self.stdout.write(f"  Categories cleared (strict): {stats['cat_cleared']}")
        self.stdout.write(f"  Specifications copied: {stats['specs_copied']}")
        if mode == "strict":
            self.stdout.write(f"  Specifications cleared: {stats['specs_cleared']}")
        self.stdout.write(f"  Unmatched staging parts: {stats['unmatched_staging']}")

        if cat_breakdown:
            self.stdout.write(f"\n{prefix}Category breakdown (would copy):")
            for cat, cnt in sorted(cat_breakdown.items(), key=lambda x: -x[1]):
                self.stdout.write(f"    {cat}: {cnt}")

    # ------------------------------------------------------------------
    # Units
    # ------------------------------------------------------------------
    def _sync_units(self, old, mode, dry_run, prefix):
        self.stdout.write(self.style.MIGRATE_HEADING("--- UNITS ---"))

        old_data = {}
        for row in old.execute(
            "SELECT unit_number, unit_type_category, unit_type_id, specifications "
            "FROM catalog_unit "
            "WHERE unit_number IS NOT NULL AND unit_number != ''"
        ):
            old_data[row[0]] = (row[1], row[2], row[3])  # (cat, type_id, specs_json)

        self.stdout.write(f"Old DB units loaded: {len(old_data)}")
        old_with_cat = sum(1 for _, (c, _, _) in old_data.items() if c)
        self.stdout.write(f"Old DB units with unit_type_category: {old_with_cat}")

        staging_units = Unit.objects.all().only(
            "id", "unit_number", "unit_type_category", "unit_type_id", "specifications"
        )

        stats = {
            "matched": 0,
            "cat_copied": 0,
            "cat_cleared": 0,
            "type_copied": 0,
            "specs_copied": 0,
            "specs_cleared": 0,
            "unmatched_staging": 0,
        }
        cat_breakdown = {}

        for unit in staging_units.iterator(chunk_size=2000):
            if not unit.unit_number:
                stats["unmatched_staging"] += 1
                continue

            old_entry = old_data.get(unit.unit_number)
            if old_entry is None:
                stats["unmatched_staging"] += 1
                continue

            stats["matched"] += 1
            old_cat, old_type_id, old_specs_json = old_entry
            import json
            old_specs = json.loads(old_specs_json) if old_specs_json else {}

            update_fields = []

            # unit_type_category
            if old_cat and unit.unit_type_category != old_cat:
                cat_breakdown[old_cat] = cat_breakdown.get(old_cat, 0) + 1
                if not dry_run:
                    unit.unit_type_category = old_cat
                update_fields.append("unit_type_category")
                stats["cat_copied"] += 1
            elif mode == "strict" and not old_cat and unit.unit_type_category:
                if not dry_run:
                    unit.unit_type_category = ""
                update_fields.append("unit_type_category")
                stats["cat_cleared"] += 1

            # unit_type FK
            if old_type_id and unit.unit_type_id != old_type_id:
                if not dry_run:
                    unit.unit_type_id = old_type_id
                update_fields.append("unit_type_id")
                stats["type_copied"] += 1

            # Specifications
            if old_specs and unit.specifications != old_specs:
                if not dry_run:
                    unit.specifications = old_specs
                update_fields.append("specifications")
                stats["specs_copied"] += 1
            elif mode == "strict" and not old_specs and unit.specifications:
                if not dry_run:
                    unit.specifications = {}
                update_fields.append("specifications")
                stats["specs_cleared"] += 1

            if update_fields and not dry_run:
                unit.save(update_fields=update_fields)

        self.stdout.write(f"\n{prefix}Units results:")
        self.stdout.write(f"  Matched by unit_number: {stats['matched']}")
        self.stdout.write(f"  unit_type_category copied: {stats['cat_copied']}")
        if mode == "strict":
            self.stdout.write(f"  unit_type_category cleared: {stats['cat_cleared']}")
        self.stdout.write(f"  unit_type FK copied: {stats['type_copied']}")
        self.stdout.write(f"  Specifications copied: {stats['specs_copied']}")
        if mode == "strict":
            self.stdout.write(f"  Specifications cleared: {stats['specs_cleared']}")
        self.stdout.write(f"  Unmatched staging units: {stats['unmatched_staging']}")

        if cat_breakdown:
            self.stdout.write(f"\n{prefix}Type category breakdown (would copy):")
            for cat, cnt in sorted(cat_breakdown.items(), key=lambda x: -x[1]):
                self.stdout.write(f"    {cat}: {cnt}")
