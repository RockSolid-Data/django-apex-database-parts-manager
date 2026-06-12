"""
Sync part categories, fields, and unit type categories from prod DB into staging.

Steps:
  1. Copy all 31 PartCategory records from prod (skip existing by name)
  2. Copy all 667 PartCategoryField records (replace staging fields for synced categories)
  3. Re-categorize staging parts by matching yt_number to prod
  4. For unmatched parts, map keyword category names to prod category names
  5. Rename UnitTypeCategory "Motor" → "AC Motor" and sync all UnitTypeCategoryFields

Usage:
  $env:DJANGO_DB_NAME="db.sqlite3.staging"
  python manage.py sync_prod_categories --dry-run
  python manage.py sync_prod_categories
"""

import sqlite3
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import connection

from catalog.models import (
    Part,
    PartCategory,
    PartCategoryField,
    UnitTypeCategory,
    UnitTypeCategoryField,
)

PROD_DB = r"C:\Users\kauft\AppData\Local\ApexDatabase\db.sqlite3"

KEYWORD_TO_PROD_MAP = {
    "Bearings": "Bearings",
    "Brush Holders & Parts": "Brush Holders & Parts",
    "Brushes": "Brushes",
    "Brushes - Starter & DC Motor": "Brushes - Starter & DC Motor",
    "Bushings": "Bushings",
    "Drives & Gears": "Drives, Clutches & Drive Parts",
    "Field Coils": "Field Coils",
    "Gaskets, Grommets & Seals": "Gaskets, Grommets & Seals",
    "Hardware & Misc": "Hardware",
    "Housings": "Housings",
    "Kits": "Insulators & Kits",
    "Pulleys": "Pulleys & Pulley Collars",
    "Regulators & Rectifiers": "Regulators & Regulator Parts",
    "Relays, Solenoids & Switches": "Relays, Solenoids & Switches",
    "Shafts & Armatures": "Shafts & Armatures",
    "Starter & DC Motor Brush Springs": "Starter & DC Motor Brush Springs",
    "Stators": "Stators",
    "Test Equipment": "Test Lead",
}


class Command(BaseCommand):
    help = "Sync part categories, fields, and unit type categories from prod into staging."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing.",
        )
        parser.add_argument(
            "--prod-db",
            default=PROD_DB,
            help="Path to the production database file.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        prod_path = options["prod_db"]
        prefix = "[DRY RUN] " if dry_run else ""

        self.stdout.write(f"{prefix}Prod DB: {prod_path}")
        self.stdout.write("")

        prod = sqlite3.connect(prod_path)
        prod.row_factory = sqlite3.Row

        try:
            self._sync_part_categories(prod, dry_run, prefix)
            self.stdout.write("")
            self._sync_part_category_fields(prod, dry_run, prefix)
            self.stdout.write("")
            self._recategorize_parts(prod, dry_run, prefix)
            self.stdout.write("")
            self._sync_unit_type_categories(prod, dry_run, prefix)
        finally:
            prod.close()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{prefix}Done."))

    # ------------------------------------------------------------------
    def _sync_part_categories(self, prod, dry_run, prefix):
        self.stdout.write(self.style.MIGRATE_HEADING("=== SYNC PART CATEGORIES ==="))

        prod_cats = {}
        for row in prod.execute("SELECT id, name, created_at FROM catalog_partcategory ORDER BY name"):
            prod_cats[row["name"]] = dict(row)

        staging_cats = {c.name: c for c in PartCategory.objects.all()}

        created = 0
        skipped = 0
        for name, pdata in sorted(prod_cats.items()):
            if name in staging_cats:
                skipped += 1
            else:
                created += 1
                if not dry_run:
                    PartCategory.objects.create(name=name)
                self.stdout.write(f"  {prefix}CREATE: {name}")

        self.stdout.write(f"\n{prefix}Part categories: {created} created, {skipped} already exist")
        self.stdout.write(f"{prefix}Total in prod: {len(prod_cats)}, staging after: {len(staging_cats) + created}")

    # ------------------------------------------------------------------
    def _sync_part_category_fields(self, prod, dry_run, prefix):
        self.stdout.write(self.style.MIGRATE_HEADING("=== SYNC PART CATEGORY FIELDS ==="))

        prod_cats = {}
        for row in prod.execute("SELECT id, name FROM catalog_partcategory"):
            prod_cats[row["id"]] = row["name"]

        prod_fields = defaultdict(list)
        for row in prod.execute(
            "SELECT category_id, field_name, field_label, display_order "
            "FROM catalog_partcategoryfield ORDER BY category_id, display_order"
        ):
            cat_name = prod_cats.get(row["category_id"])
            if cat_name:
                prod_fields[cat_name].append({
                    "field_name": row["field_name"],
                    "field_label": row["field_label"],
                    "display_order": row["display_order"],
                })

        # Re-read staging categories (includes newly created ones from step 1)
        staging_cat_map = {c.name: c for c in PartCategory.objects.all()}

        total_created = 0
        total_deleted = 0
        skipped_dry_run = 0
        for cat_name, fields in sorted(prod_fields.items()):
            stg_cat = staging_cat_map.get(cat_name)
            if not stg_cat:
                if dry_run:
                    # Category will be created in non-dry-run; count fields
                    skipped_dry_run += len(fields)
                    self.stdout.write(f"  {prefix}{cat_name}: would insert {len(fields)} fields (new category)")
                else:
                    self.stdout.write(f"  SKIP fields for '{cat_name}' -- category not in staging")
                continue

            existing = list(PartCategoryField.objects.filter(category=stg_cat))
            existing_set = {(f.field_name, f.field_label, f.display_order) for f in existing}
            prod_set = {(f["field_name"], f["field_label"], f["display_order"]) for f in fields}

            if existing_set == prod_set:
                continue

            if not dry_run:
                PartCategoryField.objects.filter(category=stg_cat).delete()
            deleted = len(existing)
            total_deleted += deleted

            created = 0
            for f in fields:
                if not dry_run:
                    PartCategoryField.objects.create(
                        category=stg_cat,
                        field_name=f["field_name"],
                        field_label=f["field_label"],
                        display_order=f["display_order"],
                    )
                created += 1
            total_created += created
            self.stdout.write(
                f"  {prefix}{cat_name}: replaced {deleted} fields with {created} from prod"
            )

        self.stdout.write(f"\n{prefix}Fields: {total_deleted} removed, {total_created} inserted from prod")
        if skipped_dry_run:
            self.stdout.write(f"{prefix}Fields for new categories (would insert): {skipped_dry_run}")

    # ------------------------------------------------------------------
    def _recategorize_parts(self, prod, dry_run, prefix):
        self.stdout.write(self.style.MIGRATE_HEADING("=== RE-CATEGORIZE PARTS ==="))

        prod_cat_by_yt = {}
        prod_cat_by_pn = {}
        for row in prod.execute(
            "SELECT yt_number, part_number, category FROM catalog_part "
            "WHERE category != ''"
        ):
            if row["yt_number"]:
                prod_cat_by_yt[row["yt_number"]] = row["category"]
            if row["part_number"]:
                prod_cat_by_pn[row["part_number"]] = row["category"]

        self.stdout.write(f"  Prod parts with category: {len(prod_cat_by_yt)} (by yt), {len(prod_cat_by_pn)} (by pn)")

        valid_prod_cats = set()
        for row in prod.execute("SELECT name FROM catalog_partcategory"):
            valid_prod_cats.add(row["name"])

        stats = {
            "matched_yt": 0,
            "matched_pn": 0,
            "keyword_mapped": 0,
            "already_correct": 0,
            "no_match": 0,
            "invalid_prod_cat": 0,
        }
        changes = defaultdict(lambda: defaultdict(int))

        staging_parts = Part.objects.all().only("id", "yt_number", "part_number", "category")

        batch = []
        for part in staging_parts.iterator(chunk_size=2000):
            new_cat = None

            # 1. Try matching by yt_number
            if part.yt_number and part.yt_number in prod_cat_by_yt:
                new_cat = prod_cat_by_yt[part.yt_number]
                match_type = "matched_yt"
            # 2. Try matching by part_number
            elif part.part_number and part.part_number in prod_cat_by_pn:
                new_cat = prod_cat_by_pn[part.part_number]
                match_type = "matched_pn"
            # 3. Keyword mapping for remaining
            elif part.category and part.category in KEYWORD_TO_PROD_MAP:
                new_cat = KEYWORD_TO_PROD_MAP[part.category]
                match_type = "keyword_mapped"
            else:
                stats["no_match"] += 1
                continue

            # Validate the category exists in prod's PartCategory table
            if new_cat not in valid_prod_cats:
                stats["invalid_prod_cat"] += 1
                continue

            if part.category == new_cat:
                stats["already_correct"] += 1
                continue

            stats[match_type] += 1
            changes[part.category or "(empty)"][new_cat] += 1

            if not dry_run:
                part.category = new_cat
                batch.append(part)
                if len(batch) >= 2000:
                    Part.objects.bulk_update(batch, ["category"])
                    batch = []

        if batch and not dry_run:
            Part.objects.bulk_update(batch, ["category"])

        self.stdout.write(f"\n{prefix}Part re-categorization results:")
        self.stdout.write(f"  Matched by yt_number:  {stats['matched_yt']}")
        self.stdout.write(f"  Matched by part_number: {stats['matched_pn']}")
        self.stdout.write(f"  Keyword-mapped:         {stats['keyword_mapped']}")
        self.stdout.write(f"  Already correct:        {stats['already_correct']}")
        self.stdout.write(f"  No match / no category: {stats['no_match']}")
        self.stdout.write(f"  Invalid prod category:  {stats['invalid_prod_cat']}")

        if changes:
            self.stdout.write(f"\n{prefix}Category changes:")
            for old_cat in sorted(changes.keys()):
                for new_cat, cnt in sorted(changes[old_cat].items(), key=lambda x: -x[1]):
                    self.stdout.write(f"    {old_cat} -> {new_cat}: {cnt}")

    # ------------------------------------------------------------------
    def _sync_unit_type_categories(self, prod, dry_run, prefix):
        self.stdout.write(self.style.MIGRATE_HEADING("=== SYNC UNIT TYPE CATEGORIES ==="))

        # Rename Motor → AC Motor
        try:
            motor_cat = UnitTypeCategory.objects.get(name="Motor")
            self.stdout.write(f"  {prefix}Renaming 'Motor' → 'AC Motor'")
            if not dry_run:
                motor_cat.name = "AC Motor"
                motor_cat.save(update_fields=["name"])
        except UnitTypeCategory.DoesNotExist:
            try:
                UnitTypeCategory.objects.get(name="AC Motor")
                self.stdout.write("  'AC Motor' already exists")
            except UnitTypeCategory.DoesNotExist:
                self.stdout.write(f"  {prefix}Creating 'AC Motor'")
                if not dry_run:
                    UnitTypeCategory.objects.create(name="AC Motor", sort_order=50, color="#b38234")

        # Sync sort_order and color from prod
        prod_utc = {}
        for row in prod.execute("SELECT id, name, sort_order, color FROM catalog_unittypecategory"):
            prod_utc[row["name"]] = dict(row)

        for name, pdata in prod_utc.items():
            try:
                stg = UnitTypeCategory.objects.get(name=name)
                updated = []
                if stg.sort_order != pdata["sort_order"]:
                    if not dry_run:
                        stg.sort_order = pdata["sort_order"]
                    updated.append("sort_order")
                if stg.color != pdata["color"]:
                    if not dry_run:
                        stg.color = pdata["color"]
                    updated.append("color")
                if updated:
                    if not dry_run:
                        stg.save(update_fields=updated)
                    self.stdout.write(f"  {prefix}Updated '{name}': {', '.join(updated)}")
            except UnitTypeCategory.DoesNotExist:
                pass

        # Sync UnitTypeCategoryFields from prod
        self.stdout.write(f"\n{prefix}Syncing UnitTypeCategoryFields...")

        prod_cat_ids = {}
        for row in prod.execute("SELECT id, name FROM catalog_unittypecategory"):
            prod_cat_ids[row["id"]] = row["name"]

        prod_utc_fields = defaultdict(list)
        for row in prod.execute(
            "SELECT category_id, field_name, field_label, display_order "
            "FROM catalog_unittypecategoryfield ORDER BY category_id, display_order"
        ):
            cat_name = prod_cat_ids.get(row["category_id"])
            if cat_name:
                prod_utc_fields[cat_name].append({
                    "field_name": row["field_name"],
                    "field_label": row["field_label"],
                    "display_order": row["display_order"],
                })

        stg_utc_map = {c.name: c for c in UnitTypeCategory.objects.all()}
        # In dry-run, the rename Motor→AC Motor wasn't applied, so alias it
        if dry_run and "Motor" in stg_utc_map and "AC Motor" not in stg_utc_map:
            stg_utc_map["AC Motor"] = stg_utc_map["Motor"]
        total_created = 0
        total_deleted = 0

        for cat_name, fields in sorted(prod_utc_fields.items()):
            stg_cat = stg_utc_map.get(cat_name)
            if not stg_cat:
                self.stdout.write(f"  SKIP '{cat_name}' — not in staging UnitTypeCategory")
                continue

            existing = list(UnitTypeCategoryField.objects.filter(category=stg_cat))
            existing_set = {(f.field_name, f.field_label, f.display_order) for f in existing}
            prod_set = {(f["field_name"], f["field_label"], f["display_order"]) for f in fields}

            if existing_set == prod_set:
                continue

            if not dry_run:
                UnitTypeCategoryField.objects.filter(category=stg_cat).delete()
            deleted = len(existing)
            total_deleted += deleted

            created = 0
            for f in fields:
                if not dry_run:
                    UnitTypeCategoryField.objects.create(
                        category=stg_cat,
                        field_name=f["field_name"],
                        field_label=f["field_label"],
                        display_order=f["display_order"],
                    )
                created += 1
            total_created += created
            self.stdout.write(f"  {prefix}{cat_name}: replaced {deleted} fields with {created} from prod")

        self.stdout.write(f"\n{prefix}UnitTypeCategoryFields: {total_deleted} removed, {total_created} inserted")
