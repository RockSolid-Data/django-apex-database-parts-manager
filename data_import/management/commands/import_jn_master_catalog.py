"""
Import J&N Master Catalog staging data into the Django catalog.

The staging DB is produced by:
    python -m data_import.pdf_parsers.parse_jn_master_catalog <pdf_path>

Current import scope:
  - jn_catalog_parts -> source-specific Part
  - jn_catalog_part_refs -> PartSubstitute / PartInterchange / PartSuperseding
  - jn_catalog_part_images -> PartImage (+ Part.image when empty)
  - jn_catalog_units / jn_catalog_unit_refs -> Unit / CrossReference

Usage:
    python manage.py import_jn_master_catalog --file data_import/staging_dbs/jn_master_catalog.db
    python manage.py import_jn_master_catalog --report-only
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
from django.db import models

from catalog.models import (
    CrossReference,
    Part,
    PartImage,
    PartInterchange,
    PartSubstitute,
    PartSuperseding,
    Unit,
)
from data_import.import_utils import (
    append_text,
    build_exact_part_lookup,
    load_same_source_parts,
    normalize_space,
    source_part_number,
)


CATALOG_NAME = "J&N Master Catalog"


def parse_specs(raw_json):
    if not raw_json:
        return {}
    try:
        value = json.loads(raw_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


class Command(BaseCommand):
    help = "Import J&N Master Catalog staging data into source-specific Part and Unit records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=None,
            help="Path to the jn_master_catalog.db staging file",
        )
        parser.add_argument(
            "--report-only",
            action="store_true",
            dest="report_only",
            help="Show what would be imported without making any changes",
        )
        parser.add_argument(
            "--skip-images",
            action="store_true",
            dest="skip_images",
            help="Import parts and references, but do not copy staged images",
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
        return Path(settings.BASE_DIR) / "data_import" / "staging_dbs" / "jn_master_catalog.db"

    def _report(self, db_path: Path):
        conn = sqlite3.connect(str(db_path))
        part_count = conn.execute("SELECT COUNT(*) FROM jn_catalog_parts").fetchone()[0]
        ref_count = conn.execute("SELECT COUNT(*) FROM jn_catalog_part_refs").fetchone()[0]
        image_count = conn.execute("SELECT COUNT(*) FROM jn_catalog_part_images").fetchone()[0]
        unit_count = conn.execute("SELECT COUNT(*) FROM jn_catalog_units").fetchone()[0]
        unit_ref_count = conn.execute("SELECT COUNT(*) FROM jn_catalog_unit_refs").fetchone()[0]

        jn_numbers = {
            row[0]
            for row in conn.execute("SELECT DISTINCT jn_number FROM jn_catalog_parts WHERE jn_number != ''")
        }
        staged_unit_numbers = {
            row[0]
            for row in conn.execute("SELECT DISTINCT jn_number FROM jn_catalog_units WHERE jn_number != ''")
        }
        conn.close()

        existing_parts = load_same_source_parts("jn_master", jn_numbers)
        existing_units = set(
            Unit.objects.filter(j_and_n_number__in=staged_unit_numbers).values_list("j_and_n_number", flat=True)
        )

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"REPORT: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Staged part rows:            {part_count:>10,}")
        self.stdout.write(f"  Staged part refs:            {ref_count:>10,}")
        self.stdout.write(f"  Staged part images:          {image_count:>10,}")
        self.stdout.write(f"  Staged unit rows:            {unit_count:>10,}")
        self.stdout.write(f"  Staged unit refs:            {unit_ref_count:>10,}")
        self.stdout.write(f"  Existing J&N part records:   {len(existing_parts):>10,}")
        self.stdout.write(f"  New J&N part records:        {len(jn_numbers) - len(existing_parts):>10,}")
        self.stdout.write(f"  Existing J&N unit records:   {len(existing_units):>10,}")
        self.stdout.write(f"  New J&N unit records:        {len(staged_unit_numbers) - len(existing_units):>10,}")
        self.stdout.write("")

    def _load_staging_rows(self, conn):
        conn.row_factory = sqlite3.Row
        parts = conn.execute(
            """
            SELECT jn_number, part_name, description, category_code, category_name,
                   oem_family, page_number, source_pdf, specifications_json, has_image
            FROM jn_catalog_parts
            ORDER BY jn_number, page_number
            """
        ).fetchall()
        refs = conn.execute(
            """
            SELECT jn_number, ref_type, manufacturer, ref_number, notes
            FROM jn_catalog_part_refs
            ORDER BY jn_number, ref_type, manufacturer, ref_number
            """
        ).fetchall()
        images = conn.execute(
            """
            SELECT jn_number, page_number, image_index, image_path, width, height
            FROM jn_catalog_part_images
            ORDER BY jn_number, page_number, image_index
            """
        ).fetchall()
        units = conn.execute(
            """
            SELECT jn_number, description, category_code, category_name,
                   page_number, source_pdf, specifications_json
            FROM jn_catalog_units
            ORDER BY jn_number, page_number
            """
        ).fetchall()
        unit_refs = conn.execute(
            """
            SELECT jn_number, ref_type, manufacturer, ref_number, notes
            FROM jn_catalog_unit_refs
            ORDER BY jn_number, ref_type, manufacturer, ref_number
            """
        ).fetchall()
        return parts, refs, images, units, unit_refs

    def _import(self, db_path: Path, skip_images=False):
        self.stdout.write(f"\nImporting: {db_path.name}")
        self.stdout.write("-" * 60)
        start = time.time()

        conn = sqlite3.connect(str(db_path))
        parts, refs, images, units, unit_refs = self._load_staging_rows(conn)
        conn.close()

        staged_jn_numbers = sorted(
            {normalize_space(row["jn_number"]) for row in parts if normalize_space(row["jn_number"])}
        )
        if not staged_jn_numbers:
            self.stdout.write("No staged part rows found.")
            return

        self.stdout.write("Step 1: Creating / updating Part records...")
        t1 = time.time()
        part_map, created_count, updated_count = self._import_parts(parts, staged_jn_numbers)
        self.stdout.write(
            f"  {created_count:,} parts created, {updated_count:,} updated  ({time.time() - t1:.1f}s)"
        )

        self.stdout.write("Step 2: Creating part-side reference records...")
        t2 = time.time()
        ref_counts = self._import_refs(refs, part_map)
        self.stdout.write(
            f"  {ref_counts['substitutes']:,} substitutes, "
            f"{ref_counts['interchanges']:,} interchanges, "
            f"{ref_counts['supersedings']:,} supersedings  "
            f"({time.time() - t2:.1f}s)"
        )

        image_created = 0
        if skip_images:
            self.stdout.write("Step 3: Skipping image import (--skip-images).")
        else:
            self.stdout.write("Step 3: Importing staged part images...")
            t3 = time.time()
            image_created = self._import_images(images, part_map)
            self.stdout.write(f"  {image_created:,} images imported  ({time.time() - t3:.1f}s)")

        self.stdout.write("Step 4: Creating / updating J&N Unit records...")
        t4 = time.time()
        unit_map, unit_created, unit_updated, unit_xrefs = self._import_units(units, unit_refs)
        self.stdout.write(
            f"  {unit_created:,} units created, {unit_updated:,} updated, "
            f"{unit_xrefs:,} unit refs created  ({time.time() - t4:.1f}s)"
        )

        elapsed = time.time() - start
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"IMPORT COMPLETE: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Parts created:              {created_count:>10,}")
        self.stdout.write(f"  Parts updated:              {updated_count:>10,}")
        self.stdout.write(f"  Substitutes created:        {ref_counts['substitutes']:>10,}")
        self.stdout.write(f"  Interchanges created:       {ref_counts['interchanges']:>10,}")
        self.stdout.write(f"  Supersedings created:       {ref_counts['supersedings']:>10,}")
        self.stdout.write(f"  Images imported:            {image_created:>10,}")
        self.stdout.write(f"  Units created:              {unit_created:>10,}")
        self.stdout.write(f"  Units updated:              {unit_updated:>10,}")
        self.stdout.write(f"  Unit refs created:          {unit_xrefs:>10,}")
        self.stdout.write(f"  Total time:                 {elapsed:>10.1f}s")
        self.stdout.write("")

    def _import_parts(self, part_rows, staged_jn_numbers):
        part_map = load_same_source_parts("jn_master", staged_jn_numbers)

        created_parts = []
        seen_new = set()
        for row in part_rows:
            jn_number = normalize_space(row["jn_number"])
            if not jn_number or jn_number in part_map or jn_number in seen_new:
                continue
            seen_new.add(jn_number)
            specs = parse_specs(row["specifications_json"])
            created_parts.append(
                Part(
                    part_number=source_part_number("jn_master", jn_number),
                    part_name=(row["part_name"] or jn_number)[:255],
                    j_and_n=jn_number[:100],
                    category=(row["category_name"] or row["category_code"] or "")[:100],
                    catalog=CATALOG_NAME[:100],
                    description=(row["description"] or "")[:2000],
                    specifications=specs,
                    has_picture=bool(row["has_image"]),
                )
            )
        if created_parts:
            Part.objects.bulk_create(created_parts, batch_size=1000)

        if created_parts:
            part_map = load_same_source_parts("jn_master", staged_jn_numbers)

        updated_parts = {}
        for row in part_rows:
            jn_number = normalize_space(row["jn_number"])
            part = part_map.get(jn_number)
            if not part:
                continue
            changed = False
            if not part.j_and_n:
                part.j_and_n = jn_number[:100]
                changed = True
            if not part.part_name and row["part_name"]:
                part.part_name = row["part_name"][:255]
                changed = True
            if not part.category and (row["category_name"] or row["category_code"]):
                part.category = (row["category_name"] or row["category_code"])[:100]
                changed = True
            if not part.catalog:
                part.catalog = CATALOG_NAME[:100]
                changed = True
            if not part.notes and row["description"]:
                part.notes = row["description"][:2000]
                changed = True

            staged_specs = parse_specs(row["specifications_json"])
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
                ["j_and_n", "part_name", "category", "catalog", "description", "specifications", "has_picture"],
                batch_size=500,
            )

        canonical_lookup = build_exact_part_lookup(staged_jn_numbers, exclude_catalogs=[CATALOG_NAME])
        linked = 0
        existing_interchanges = set(
            PartInterchange.objects.values_list("part_id", "interchange_number")
        )
        link_batch = []
        for jn_number, source_part in part_map.items():
            canonical_part = canonical_lookup.get(jn_number)
            if not canonical_part or canonical_part.pk == source_part.pk:
                continue
            dedup_key = (source_part.pk, canonical_part.part_number[:100])
            if dedup_key in existing_interchanges:
                continue
            existing_interchanges.add(dedup_key)
            link_batch.append(
                PartInterchange(
                    part_id=source_part.pk,
                    interchange_part_id=canonical_part.pk,
                    interchange_number=canonical_part.part_number[:100],
                    notes="Matched by J&N number",
                )
            )
            linked += 1
        if link_batch:
            PartInterchange.objects.bulk_create(link_batch, batch_size=500, ignore_conflicts=True)
            Part.objects.filter(pk__in={rel.part_id for rel in link_batch}).update(has_interchange=True)

        return part_map, len(created_parts), len(updated_parts)

    def _import_refs(self, ref_rows, part_map):
        existing_subs = set(
            PartSubstitute.objects.values_list("part_id", "substitute_number")
        )
        existing_interchanges = set(
            PartInterchange.objects.values_list("part_id", "interchange_number")
        )
        existing_supers = set(
            PartSuperseding.objects.values_list("part_id", "old_part_number")
        )

        substitute_batch = []
        interchange_batch = []
        superseding_batch = []
        part_updates = {}
        counts = {"substitutes": 0, "interchanges": 0, "supersedings": 0}

        for row in ref_rows:
            jn_number = normalize_space(row["jn_number"])
            ref_number = normalize_space(row["ref_number"])
            manufacturer = normalize_space(row["manufacturer"])
            extra_notes = normalize_space(row["notes"])
            ref_type = normalize_space(row["ref_type"]).lower() or "reference"

            part = part_map.get(jn_number)
            if not part or not ref_number:
                continue

            linked_part = part_map.get(ref_number)
            note_bits = [value for value in [manufacturer, extra_notes] if value]
            note_text = " | ".join(note_bits)[:2000]

            if ref_type == "substitute":
                dedup_key = (part.pk, ref_number[:100])
                if dedup_key in existing_subs:
                    continue
                existing_subs.add(dedup_key)
                substitute_batch.append(
                    PartSubstitute(
                        part_id=part.pk,
                        substitute_part_id=linked_part.pk if linked_part and linked_part.pk != part.pk else None,
                        substitute_number=ref_number[:100],
                        notes=note_text,
                    )
                )
                counts["substitutes"] += 1
                continue

            if ref_type in {"reference", "interchange"}:
                dedup_key = (part.pk, ref_number[:100])
                if dedup_key in existing_interchanges:
                    continue
                existing_interchanges.add(dedup_key)
                interchange_batch.append(
                    PartInterchange(
                        part_id=part.pk,
                        interchange_part_id=linked_part.pk if linked_part and linked_part.pk != part.pk else None,
                        interchange_number=ref_number[:100],
                        notes=note_text,
                    )
                )
                counts["interchanges"] += 1
                continue

            if ref_type == "superseded_from":
                dedup_key = (part.pk, ref_number[:100])
                if dedup_key in existing_supers:
                    continue
                existing_supers.add(dedup_key)
                superseding_batch.append(
                    PartSuperseding(
                        part_id=part.pk,
                        old_part_id=linked_part.pk if linked_part and linked_part.pk != part.pk else None,
                        old_part_number=ref_number[:100],
                        notes=note_text,
                    )
                )
                counts["supersedings"] += 1
                continue

            if ref_type == "superseded_by":
                if linked_part and linked_part.pk != part.pk:
                    dedup_key = (linked_part.pk, part.part_number[:100])
                    if dedup_key in existing_supers:
                        continue
                    existing_supers.add(dedup_key)
                    superseding_batch.append(
                        PartSuperseding(
                            part_id=linked_part.pk,
                            old_part_id=part.pk,
                            old_part_number=part.part_number[:100],
                            notes=note_text,
                        )
                    )
                    counts["supersedings"] += 1
                else:
                    part.superseding_notes = append_text(
                        part.superseding_notes,
                        f"Superseded by: {ref_number}" + (f" ({manufacturer})" if manufacturer else ""),
                    )
                    part_updates[part.pk] = part

        if substitute_batch:
            PartSubstitute.objects.bulk_create(
                substitute_batch,
                batch_size=500,
                ignore_conflicts=True,
            )
        if interchange_batch:
            PartInterchange.objects.bulk_create(
                interchange_batch,
                batch_size=500,
                ignore_conflicts=True,
            )
        if superseding_batch:
            PartSuperseding.objects.bulk_create(
                superseding_batch,
                batch_size=500,
                ignore_conflicts=True,
            )
        if part_updates:
            for part in part_updates.values():
                part.has_superseding = True
            Part.objects.bulk_update(
                list(part_updates.values()),
                ["superseding_notes", "has_superseding"],
                batch_size=500,
            )

        changed_parts = set()
        for relation in substitute_batch:
            changed_parts.add(relation.part_id)
        for relation in interchange_batch:
            changed_parts.add(relation.part_id)
        for relation in superseding_batch:
            changed_parts.add(relation.part_id)
        if changed_parts:
            Part.objects.filter(pk__in=changed_parts).update(
                has_interchange=True
            )
            part_ids_with_supers = {relation.part_id for relation in superseding_batch}
            if part_ids_with_supers:
                Part.objects.filter(pk__in=part_ids_with_supers).update(has_superseding=True)

        return counts

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
            jn_number = normalize_space(row["jn_number"])
            image_path = row["image_path"]
            part = part_map.get(jn_number)
            if not part or not image_path or not os.path.exists(image_path):
                continue

            ext = os.path.splitext(image_path)[1] or ".png"
            file_name = f"jn_master_{jn_number.replace('-', '_')}_p{int(row['page_number']):04d}_{int(row['image_index']):02d}{ext}"
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

    def _import_units(self, unit_rows, unit_ref_rows):
        staged_jn_numbers = sorted(
            {normalize_space(row["jn_number"]) for row in unit_rows if normalize_space(row["jn_number"])}
        )
        staged_unit_numbers = {
            jn_number: source_part_number("jn_master", jn_number)
            for jn_number in staged_jn_numbers
        }

        def load_existing_units():
            qs = Unit.objects.filter(
                models.Q(j_and_n_number__in=staged_jn_numbers)
                | models.Q(unit_number__in=staged_unit_numbers.values())
            )
            mapping = {}
            for unit in qs:
                jn_number = normalize_space(unit.j_and_n_number)
                if jn_number:
                    mapping[jn_number] = unit
                    continue
                unit_number = normalize_space(unit.unit_number)
                if unit_number.startswith("JN:"):
                    mapping[unit_number.split(":", 1)[1]] = unit
            return mapping

        existing_units = load_existing_units()

        created_units = []
        seen_new = set()
        for row in unit_rows:
            jn_number = normalize_space(row["jn_number"])
            if not jn_number or jn_number in existing_units or jn_number in seen_new:
                continue
            seen_new.add(jn_number)
            specs = parse_specs(row["specifications_json"])
            created_units.append(
                Unit(
                    unit_number=staged_unit_numbers[jn_number],
                    j_and_n_number=jn_number[:100],
                    description=(row["description"] or "")[:2000],
                    family=(row["category_name"] or row["category_code"] or "")[:100],
                    specifications=specs,
                )
            )
        if created_units:
            Unit.objects.bulk_create(created_units, batch_size=500, ignore_conflicts=True)
            existing_units = load_existing_units()

        updated_units = {}
        for row in unit_rows:
            jn_number = normalize_space(row["jn_number"])
            unit = existing_units.get(jn_number)
            if not unit:
                continue
            changed = False
            if not unit.description and row["description"]:
                unit.description = row["description"][:2000]
                changed = True
            if not unit.family and (row["category_name"] or row["category_code"]):
                unit.family = (row["category_name"] or row["category_code"])[:100]
                changed = True
            staged_specs = parse_specs(row["specifications_json"])
            if staged_specs:
                merged_specs = dict(staged_specs)
                merged_specs.update(unit.specifications or {})
                if merged_specs != (unit.specifications or {}):
                    unit.specifications = merged_specs
                    changed = True
            if changed:
                updated_units[unit.pk] = unit
        if updated_units:
            Unit.objects.bulk_update(
                list(updated_units.values()),
                ["description", "family", "specifications"],
                batch_size=500,
            )

        existing_xrefs = set(
            CrossReference.objects.values_list("unit_id", "cross_ref_number", "interchange_type")
        )
        xref_batch = []
        created_xrefs = 0
        for row in unit_ref_rows:
            jn_number = normalize_space(row["jn_number"])
            ref_number = normalize_space(row["ref_number"])
            unit = existing_units.get(jn_number)
            if not unit or not ref_number:
                continue

            manufacturer = normalize_space(row["manufacturer"])
            notes = normalize_space(row["notes"])
            ref_type = normalize_space(row["ref_type"]).lower() or "reference"
            if ref_type == "substitute":
                interchange_type = f"J&N Substitute: {manufacturer}" if manufacturer else "J&N Substitute"
            elif ref_type == "superseded_by":
                interchange_type = "J&N Superseded By"
            elif ref_type == "superseded_from":
                interchange_type = "J&N Superseded From"
            else:
                interchange_type = f"J&N Reference: {manufacturer}" if manufacturer else "J&N Reference"

            dedup_key = (unit.pk, ref_number[:100], interchange_type[:150])
            if dedup_key in existing_xrefs:
                continue
            existing_xrefs.add(dedup_key)

            xref = CrossReference(
                unit_id=unit.pk,
                cross_ref_number=ref_number[:100],
                interchange_type=interchange_type[:150],
                notes=notes[:2000],
            )
            other_unit = existing_units.get(ref_number)
            if other_unit and other_unit.pk != unit.pk:
                xref.cross_ref_unit_id = other_unit.pk
            xref_batch.append(xref)
            created_xrefs += 1

        if xref_batch:
            CrossReference.objects.bulk_create(xref_batch, batch_size=500, ignore_conflicts=True)

        return existing_units, len(created_units), len(updated_units), created_xrefs
