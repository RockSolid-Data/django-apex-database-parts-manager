"""
Import Transpo catalog staging data into separate source-linked Part records.

This command keeps Transpo records separate from other sources and links them
through part interchange relationships rather than merging records.
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


CATALOG_NAME = source_catalog_label("transpo")


def parse_specs(raw_json):
    if not raw_json:
        return {}
    try:
        value = json.loads(raw_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


class Command(BaseCommand):
    help = "Import Transpo catalog staging data into separate Transpo Part records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=None,
            help="Path to the transpo_catalog.db staging file",
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
        return Path(settings.BASE_DIR) / "data_import" / "staging_dbs" / "transpo_catalog.db"

    def _load_rows(self, conn):
        conn.row_factory = sqlite3.Row
        parts = conn.execute(
            """
            SELECT transpo_number, part_name, section_name, manufacturer, description,
                   features_text, attributes_json, page_number, source_pdf, has_image,
                   notes, raw_text
            FROM transpo_catalog_parts
            ORDER BY transpo_number, page_number
            """
        ).fetchall()
        refs = conn.execute(
            """
            SELECT transpo_number, ref_type, manufacturer, ref_value, notes
            FROM transpo_catalog_refs
            ORDER BY transpo_number, ref_type, manufacturer, ref_value
            """
        ).fetchall()
        images = conn.execute(
            """
            SELECT transpo_number, page_number, image_index, image_path, width, height
            FROM transpo_catalog_images
            ORDER BY transpo_number, page_number, image_index
            """
        ).fetchall()
        xrefs = conn.execute(
            """
            SELECT source_section, source_number, transpo_number, product_family, catalog_page, page_number
            FROM transpo_cross_reference
            ORDER BY transpo_number, source_number
            """
        ).fetchall()
        return parts, refs, images, xrefs

    def _report(self, db_path: Path):
        conn = sqlite3.connect(str(db_path))
        part_count = conn.execute("SELECT COUNT(*) FROM transpo_catalog_parts").fetchone()[0]
        ref_count = conn.execute("SELECT COUNT(*) FROM transpo_catalog_refs").fetchone()[0]
        image_count = conn.execute("SELECT COUNT(*) FROM transpo_catalog_images").fetchone()[0]
        xref_count = conn.execute("SELECT COUNT(*) FROM transpo_cross_reference").fetchone()[0]
        transpo_numbers = {
            row[0]
            for row in conn.execute(
                """
                SELECT DISTINCT transpo_number FROM (
                    SELECT transpo_number FROM transpo_catalog_parts
                    UNION
                    SELECT transpo_number FROM transpo_cross_reference
                )
                WHERE transpo_number != ''
                """
            )
        }
        conn.close()

        existing_parts = load_same_source_parts("transpo", transpo_numbers)
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"REPORT: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Staged detail parts:         {part_count:>10,}")
        self.stdout.write(f"  Staged detail refs:          {ref_count:>10,}")
        self.stdout.write(f"  Staged images:               {image_count:>10,}")
        self.stdout.write(f"  Staged cross refs:           {xref_count:>10,}")
        self.stdout.write(f"  Existing Transpo records:    {len(existing_parts):>10,}")
        self.stdout.write(f"  New Transpo records:         {len(transpo_numbers) - len(existing_parts):>10,}")
        self.stdout.write("")

    def _import(self, db_path: Path, skip_images=False):
        self.stdout.write(f"\nImporting: {db_path.name}")
        self.stdout.write("-" * 60)
        start = time.time()

        conn = sqlite3.connect(str(db_path))
        parts, refs, images, xrefs = self._load_rows(conn)
        conn.close()

        staged_numbers = sorted(
            {
                normalize_space(row["transpo_number"])
                for row in list(parts) + list(xrefs)
                if normalize_space(row["transpo_number"])
            }
        )
        if not staged_numbers:
            self.stdout.write("No staged Transpo part rows found.")
            return

        self.stdout.write("Step 1: Creating / updating Transpo Part records...")
        t1 = time.time()
        part_map, created_count, updated_count = self._import_parts(parts, xrefs, staged_numbers)
        self.stdout.write(
            f"  {created_count:,} parts created, {updated_count:,} updated  ({time.time() - t1:.1f}s)"
        )

        self.stdout.write("Step 2: Creating detail reference links...")
        t2 = time.time()
        detail_links = self._import_detail_refs(refs, part_map)
        self.stdout.write(
            f"  {detail_links:,} detail links created  ({time.time() - t2:.1f}s)"
        )

        self.stdout.write("Step 3: Creating cross-reference links...")
        t3 = time.time()
        xref_links = self._import_xrefs(xrefs, part_map)
        self.stdout.write(
            f"  {xref_links:,} xref links created  ({time.time() - t3:.1f}s)"
        )

        image_count = 0
        if skip_images:
            self.stdout.write("Step 4: Skipping image import (--skip-images).")
        else:
            self.stdout.write("Step 4: Importing Transpo images...")
            t4 = time.time()
            image_count = self._import_images(images, part_map)
            self.stdout.write(f"  {image_count:,} images imported  ({time.time() - t4:.1f}s)")

        elapsed = time.time() - start
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"IMPORT COMPLETE: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Parts created:              {created_count:>10,}")
        self.stdout.write(f"  Parts updated:              {updated_count:>10,}")
        self.stdout.write(f"  Detail links created:       {detail_links:>10,}")
        self.stdout.write(f"  Xref links created:         {xref_links:>10,}")
        self.stdout.write(f"  Images imported:            {image_count:>10,}")
        self.stdout.write(f"  Total time:                 {elapsed:>10.1f}s")
        self.stdout.write("")

    def _import_parts(self, part_rows, xref_rows, staged_numbers):
        part_map = load_same_source_parts("transpo", staged_numbers)

        detail_by_number = {}
        for row in part_rows:
            transpo_number = normalize_space(row["transpo_number"])
            if transpo_number and transpo_number not in detail_by_number:
                detail_by_number[transpo_number] = row

        xref_meta = defaultdict(dict)
        for row in xref_rows:
            transpo_number = normalize_space(row["transpo_number"])
            if not transpo_number:
                continue
            if row["product_family"] and not xref_meta[transpo_number].get("category"):
                xref_meta[transpo_number]["category"] = row["product_family"]
            if row["source_section"] and not xref_meta[transpo_number].get("section"):
                xref_meta[transpo_number]["section"] = row["source_section"]

        created_parts = []
        seen_new = set()
        for transpo_number in staged_numbers:
            if transpo_number in part_map or transpo_number in seen_new:
                continue
            seen_new.add(transpo_number)
            detail = detail_by_number.get(transpo_number)
            category = ""
            description = ""
            foot_notes = ""
            oem = ""
            specs = {}
            has_picture = False
            if detail:
                category = detail["section_name"] or xref_meta[transpo_number].get("category", "")
                description = detail["description"] or ""
                foot_notes = detail["notes"] or detail["features_text"] or ""
                oem = detail["manufacturer"] or ""
                specs = parse_specs(detail["attributes_json"])
                has_picture = bool(detail["has_image"])
            else:
                category = xref_meta[transpo_number].get("category") or xref_meta[transpo_number].get("section", "")

            created_parts.append(
                Part(
                    part_number=source_part_number("transpo", transpo_number),
                    manufacturer_number=transpo_number[:100],
                    part_name=((detail["part_name"] if detail else "") or transpo_number)[:255],
                    category=category[:100],
                    oem=oem[:200],
                    primary_vendor="Transpo",
                    catalog=CATALOG_NAME[:100],
                    description=description[:2000],
                    foot_notes=foot_notes[:2000],
                    specifications=specs,
                    has_picture=has_picture,
                )
            )
        if created_parts:
            Part.objects.bulk_create(created_parts, batch_size=500)
            part_map = load_same_source_parts("transpo", staged_numbers)

        updated_parts = {}
        for transpo_number in staged_numbers:
            part = part_map.get(transpo_number)
            if not part:
                continue
            detail = detail_by_number.get(transpo_number)
            changed = False
            if not part.manufacturer_number:
                part.manufacturer_number = transpo_number[:100]
                changed = True
            if not part.primary_vendor:
                part.primary_vendor = "Transpo"
                changed = True
            if not part.catalog:
                part.catalog = CATALOG_NAME[:100]
                changed = True
            if detail:
                if not part.part_name and detail["part_name"]:
                    part.part_name = detail["part_name"][:255]
                    changed = True
                if not part.category and detail["section_name"]:
                    part.category = detail["section_name"][:100]
                    changed = True
                if not part.oem and detail["manufacturer"]:
                    part.oem = detail["manufacturer"][:200]
                    changed = True
                if not part.notes and detail["description"]:
                    part.notes = detail["description"][:2000]
                    changed = True
                combined_notes = normalize_space(" | ".join(filter(None, [detail["features_text"], detail["notes"]])))
                if not part.foot_notes and combined_notes:
                    part.foot_notes = combined_notes[:2000]
                    changed = True
                staged_specs = parse_specs(detail["attributes_json"])
                if staged_specs:
                    merged_specs = dict(staged_specs)
                    merged_specs.update(part.specifications or {})
                    if merged_specs != (part.specifications or {}):
                        part.specifications = merged_specs
                        changed = True
                if detail["has_image"] and not part.has_picture:
                    part.has_picture = True
                    changed = True
            else:
                category = xref_meta[transpo_number].get("category") or xref_meta[transpo_number].get("section")
                if not part.category and category:
                    part.category = category[:100]
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

    def _import_detail_refs(self, ref_rows, part_map):
        filtered_rows = [
            row for row in ref_rows
            if normalize_space(row["ref_value"]) and normalize_space(row["ref_type"]).lower() == "original_number"
        ]
        ref_values = {normalize_space(row["ref_value"]) for row in filtered_rows}
        canonical_lookup = build_exact_part_lookup(ref_values, exclude_catalogs=[CATALOG_NAME])
        existing_interchanges = set(
            PartInterchange.objects.values_list("part_id", "interchange_number")
        )
        batch = []
        changed_parts = set()
        created = 0

        for row in filtered_rows:
            transpo_number = normalize_space(row["transpo_number"])
            ref_value = normalize_space(row["ref_value"])
            part = part_map.get(transpo_number)
            if not part or not ref_value:
                continue
            dedup_key = (part.pk, ref_value[:100])
            if dedup_key in existing_interchanges:
                continue
            existing_interchanges.add(dedup_key)

            note = "Transpo original number"
            if row["manufacturer"]:
                note += f": {normalize_space(row['manufacturer'])}"
            if row["notes"]:
                note += f" | {normalize_space(row['notes'])}"
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

    def _import_xrefs(self, xref_rows, part_map):
        source_values = {
            normalize_space(row["source_number"])
            for row in xref_rows
            if normalize_space(row["source_number"])
        }
        canonical_lookup = build_exact_part_lookup(source_values, exclude_catalogs=[CATALOG_NAME])
        existing_interchanges = set(
            PartInterchange.objects.values_list("part_id", "interchange_number")
        )
        batch = []
        changed_parts = set()
        created = 0

        for row in xref_rows:
            transpo_number = normalize_space(row["transpo_number"])
            source_number = normalize_space(row["source_number"])
            part = part_map.get(transpo_number)
            if not part or not source_number:
                continue
            dedup_key = (part.pk, source_number[:100])
            if dedup_key in existing_interchanges:
                continue
            existing_interchanges.add(dedup_key)

            note_parts = [normalize_space(row["source_section"]), normalize_space(row["product_family"]), normalize_space(row["catalog_page"])]
            note = " | ".join(value for value in note_parts if value)
            target = canonical_lookup.get(source_number)
            batch.append(
                PartInterchange(
                    part_id=part.pk,
                    interchange_part_id=target.pk if target and target.pk != part.pk else None,
                    interchange_number=source_number[:100],
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
            transpo_number = normalize_space(row["transpo_number"])
            part = part_map.get(transpo_number)
            image_path = row["image_path"]
            if not part or not image_path or not os.path.exists(image_path):
                continue

            ext = os.path.splitext(image_path)[1] or ".png"
            file_name = f"transpo_{transpo_number.replace('-', '_')}_p{int(row['page_number']):04d}_{int(row['image_index']):02d}{ext}"
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
