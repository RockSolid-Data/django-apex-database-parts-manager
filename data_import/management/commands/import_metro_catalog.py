"""
Import Metro catalog staging data into separate source-linked Part records.

This command does not merge Metro records into other catalog sources.
Instead it:
  - creates or updates Metro-specific Part rows
  - imports staged images into PartImage
  - creates part interchange links from Metro refs where safe

Usage:
    python manage.py import_metro_catalog --file data_import/staging_dbs/metro_catalog.db
    python manage.py import_metro_catalog --report-only
"""

import json
import os
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand

from catalog.models import Part, PartImage, PartInterchange
from data_import.import_utils import (
    build_exact_part_lookup,
    load_same_source_parts,
    normalize_space,
    source_catalog_label,
    source_part_number,
)


CATALOG_NAME = source_catalog_label("metro")


def parse_specs(raw_json):
    if not raw_json:
        return {}
    try:
        value = json.loads(raw_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


class Command(BaseCommand):
    help = "Import Metro catalog staging data into separate Metro Part records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=None,
            help="Path to the metro_catalog.db staging file",
        )
        parser.add_argument(
            "--report-only",
            action="store_true",
            dest="report_only",
            help="Show what would be imported without making changes",
        )
        parser.add_argument(
            "--skip-images",
            action="store_true",
            dest="skip_images",
            help="Import parts and links, but do not copy staged images",
        )

    def handle(self, *args, **options):
        db_path = self._resolve_db_path(options.get("file"))
        if not db_path.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {db_path}"))
            return

        if options["report_only"]:
            self._report(db_path)
            return

        self._import(db_path, skip_images=options["skip_images"])

    def _resolve_db_path(self, explicit_path):
        if explicit_path:
            return Path(explicit_path)
        return Path(settings.BASE_DIR) / "data_import" / "staging_dbs" / "metro_catalog.db"

    def _load_rows(self, conn):
        conn.row_factory = sqlite3.Row
        parts = conn.execute(
            """
            SELECT metro_number, part_name, description, manufacturer, section_name,
                   category_name, page_number, source_pdf, attributes_json, notes,
                   raw_text, has_image
            FROM metro_catalog_parts
            ORDER BY metro_number, page_number
            """
        ).fetchall()
        refs = conn.execute(
            """
            SELECT metro_number, ref_type, ref_value, notes
            FROM metro_catalog_refs
            ORDER BY metro_number, ref_type, ref_value
            """
        ).fetchall()
        images = conn.execute(
            """
            SELECT metro_number, page_number, image_index, image_path, width, height
            FROM metro_catalog_images
            ORDER BY metro_number, page_number, image_index
            """
        ).fetchall()
        return parts, refs, images

    def _report(self, db_path: Path):
        conn = sqlite3.connect(str(db_path))
        part_count = conn.execute("SELECT COUNT(*) FROM metro_catalog_parts").fetchone()[0]
        ref_count = conn.execute("SELECT COUNT(*) FROM metro_catalog_refs").fetchone()[0]
        image_count = conn.execute("SELECT COUNT(*) FROM metro_catalog_images").fetchone()[0]
        metro_numbers = {
            row[0]
            for row in conn.execute("SELECT DISTINCT metro_number FROM metro_catalog_parts WHERE metro_number != ''")
        }
        conn.close()

        existing_parts = load_same_source_parts("metro", metro_numbers)
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"REPORT: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Staged part rows:            {part_count:>10,}")
        self.stdout.write(f"  Staged refs:                 {ref_count:>10,}")
        self.stdout.write(f"  Staged images:               {image_count:>10,}")
        self.stdout.write(f"  Existing Metro records:      {len(existing_parts):>10,}")
        self.stdout.write(f"  New Metro records:           {len(metro_numbers) - len(existing_parts):>10,}")
        self.stdout.write("")

    def _import(self, db_path: Path, skip_images=False):
        self.stdout.write(f"\nImporting: {db_path.name}")
        self.stdout.write("-" * 60)
        start = time.time()

        conn = sqlite3.connect(str(db_path))
        parts, refs, images = self._load_rows(conn)
        conn.close()

        staged_numbers = sorted(
            {normalize_space(row["metro_number"]) for row in parts if normalize_space(row["metro_number"])}
        )
        if not staged_numbers:
            self.stdout.write("No staged Metro part rows found.")
            return

        self.stdout.write("Step 1: Creating / updating Metro Part records...")
        t1 = time.time()
        part_map, created_count, updated_count = self._import_parts(parts, staged_numbers)
        self.stdout.write(
            f"  {created_count:,} parts created, {updated_count:,} updated  ({time.time() - t1:.1f}s)"
        )

        self.stdout.write("Step 2: Creating Metro reference links...")
        t2 = time.time()
        interchange_count = self._import_refs(refs, part_map)
        self.stdout.write(
            f"  {interchange_count:,} interchange links created  ({time.time() - t2:.1f}s)"
        )

        image_count = 0
        if skip_images:
            self.stdout.write("Step 3: Skipping image import (--skip-images).")
        else:
            self.stdout.write("Step 3: Importing Metro images...")
            t3 = time.time()
            image_count = self._import_images(images, part_map)
            self.stdout.write(f"  {image_count:,} images imported  ({time.time() - t3:.1f}s)")

        elapsed = time.time() - start
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"IMPORT COMPLETE: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Parts created:              {created_count:>10,}")
        self.stdout.write(f"  Parts updated:              {updated_count:>10,}")
        self.stdout.write(f"  Interchanges created:       {interchange_count:>10,}")
        self.stdout.write(f"  Images imported:            {image_count:>10,}")
        self.stdout.write(f"  Total time:                 {elapsed:>10.1f}s")
        self.stdout.write("")

    def _import_parts(self, part_rows, staged_numbers):
        part_map = load_same_source_parts("metro", staged_numbers)

        created_parts = []
        seen_new = set()
        for row in part_rows:
            metro_number = normalize_space(row["metro_number"])
            if not metro_number or metro_number in part_map or metro_number in seen_new:
                continue
            seen_new.add(metro_number)
            created_parts.append(
                Part(
                    part_number=source_part_number("metro", metro_number),
                    manufacturer_number=metro_number[:100],
                    part_name=(row["part_name"] or metro_number)[:255],
                    category=(row["category_name"] or row["section_name"] or "")[:100],
                    oem=(row["manufacturer"] or "")[:200],
                    primary_vendor="Metro",
                    catalog=CATALOG_NAME[:100],
                    description=(row["description"] or "")[:2000],
                    foot_notes=(row["notes"] or "")[:2000],
                    specifications=parse_specs(row["attributes_json"]),
                    has_picture=bool(row["has_image"]),
                )
            )
        if created_parts:
            Part.objects.bulk_create(created_parts, batch_size=500)
            part_map = load_same_source_parts("metro", staged_numbers)

        updated_parts = {}
        for row in part_rows:
            metro_number = normalize_space(row["metro_number"])
            part = part_map.get(metro_number)
            if not part:
                continue
            changed = False
            if not part.manufacturer_number:
                part.manufacturer_number = metro_number[:100]
                changed = True
            if not part.part_name and row["part_name"]:
                part.part_name = row["part_name"][:255]
                changed = True
            if not part.category and (row["category_name"] or row["section_name"]):
                part.category = (row["category_name"] or row["section_name"])[:100]
                changed = True
            if not part.oem and row["manufacturer"]:
                part.oem = row["manufacturer"][:200]
                changed = True
            if not part.primary_vendor:
                part.primary_vendor = "Metro"
                changed = True
            if not part.catalog:
                part.catalog = CATALOG_NAME[:100]
                changed = True
            if not part.notes and row["description"]:
                part.notes = row["description"][:2000]
                changed = True
            if not part.foot_notes and row["notes"]:
                part.foot_notes = row["notes"][:2000]
                changed = True
            staged_specs = parse_specs(row["attributes_json"])
            if staged_specs:
                merged_specs = dict(staged_specs)
                merged_specs.update(part.specifications or {})
                if merged_specs != (part.specifications or {}):
                    part.specifications = merged_specs
                    changed = True
            if row["has_image"] and not part.has_picture:
                part.has_picture = True
                changed = True
            if changed:
                updated_parts[part.pk] = part

        if updated_parts:
            Part.objects.bulk_update(
                list(updated_parts.values()),
                [
                    "manufacturer_number",
                    "part_name",
                    "category",
                    "oem",
                    "primary_vendor",
                    "catalog",
                    "description",
                    "foot_notes",
                    "specifications",
                    "has_picture",
                ],
                batch_size=500,
            )

        return part_map, len(created_parts), len(updated_parts)

    def _import_refs(self, ref_rows, part_map):
        ref_values = {
            normalize_space(row["ref_value"])
            for row in ref_rows
            if normalize_space(row["ref_value"])
        }
        canonical_lookup = build_exact_part_lookup(ref_values, exclude_catalogs=[CATALOG_NAME])
        existing_interchanges = set(
            PartInterchange.objects.values_list("part_id", "interchange_number")
        )
        batch = []
        created = 0
        changed_parts = set()

        for row in ref_rows:
            metro_number = normalize_space(row["metro_number"])
            ref_value = normalize_space(row["ref_value"])
            ref_type = normalize_space(row["ref_type"]).lower() or "reference"
            part = part_map.get(metro_number)
            if not part or not ref_value:
                continue

            dedup_key = (part.pk, ref_value[:100])
            if dedup_key in existing_interchanges:
                continue
            existing_interchanges.add(dedup_key)

            note = f"Metro {ref_type}: {ref_value}"
            if row["notes"]:
                note = f"{note} | {normalize_space(row['notes'])}"
            target = canonical_lookup.get(ref_value)
            batch.append(
                PartInterchange(
                    part_id=part.pk,
                    interchange_part_id=target.pk if target and target.pk != part.pk else None,
                    interchange_number=ref_value[:100],
                    notes=note[:2000],
                )
            )
            changed_parts.add(part.pk)
            created += 1

        if batch:
            PartInterchange.objects.bulk_create(batch, batch_size=500, ignore_conflicts=True)
        if changed_parts:
            Part.objects.filter(pk__in=changed_parts).update(has_interchange=True)
        return created

    def _import_images(self, image_rows, part_map):
        if not image_rows:
            return 0

        part_ids = {part.pk for part in part_map.values()}
        existing_names = defaultdict(set)
        for part_id, image_name in PartImage.objects.filter(part_id__in=part_ids).values_list("part_id", "image"):
            existing_names[part_id].add(os.path.basename(image_name))

        created = 0
        primary_updated = set()
        for row in image_rows:
            metro_number = normalize_space(row["metro_number"])
            part = part_map.get(metro_number)
            image_path = row["image_path"]
            if not part or not image_path or not os.path.exists(image_path):
                continue

            ext = os.path.splitext(image_path)[1] or ".png"
            file_name = f"metro_{metro_number.replace('-', '_')}_p{int(row['page_number']):04d}_{int(row['image_index']):02d}{ext}"
            if file_name in existing_names[part.pk]:
                continue

            with open(image_path, "rb") as handle:
                part_image = PartImage(part=part)
                part_image.image.save(file_name, File(handle), save=True)

            existing_names[part.pk].add(file_name)
            created += 1

            if not part.image and part.pk not in primary_updated:
                part.image = part_image.image.name
                part.has_picture = True
                part.save(update_fields=["image", "has_picture"])
                primary_updated.add(part.pk)

        return created
