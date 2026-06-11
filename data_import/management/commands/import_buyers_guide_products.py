"""Import buyers-guide product rows into canonical YouTech Unit records.

Handles ALL product attributes from the enhanced buyers guide staging DB,
writing to both model fields and specifications JSON (matching how the
Edit Unit form saves data).
"""

import os
import re
import sqlite3
import time
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from catalog.models import (
    Application,
    ApplicationUnit,
    BOM,
    BOMItem,
    CrossReference,
    Part,
    Substitute,
    Unit,
)
from data_import.import_utils import append_text, normalize_space


# Staging DB column -> (model field name, specs JSON key)
# model field is None when the attribute only goes to specs JSON.
ATTR_FIELD_MAP = {
    # -- Shared --
    "manufacture":      ("manufacturer",    "manufacturer"),
    "oe_manufacturer":  ("oem",             "oem"),
    "family":           ("family",          "family"),
    "voltage":          ("voltage",         "voltage"),
    "rotation":         ("rotation",        "rotation"),
    "mounting_type":    ("mount_type",      "mount_type"),
    # -- Alternator --
    "amperage_rating":  ("amp_rating",      "amp_rating"),
    "fan_type":         ("fan_type",        "fan_type"),
    "regulator_type":   ("regulator_type",  "regulator_type"),
    "ground_type":      ("grounding",       "grounding"),
    "plug_type":        (None,              "plug_type"),
    "plug_clocking":    (None,              "plug_clocking"),
    "belt_type":        (None,              "belt_type"),
    "pulley_grooves":   (None,              "pulley_grooves"),
    "pulley_type":      (None,              "pulley_type"),
    "pulley_od":        (None,              "pulley_od"),
    "decoupled":        (None,              "decoupled"),
    "stator_type":      (None,              "stator_type"),
    "series":           (None,              "series"),
    # -- Generator --
    "circuit_type":     ("circuit_type",    "circuit_type"),
    # -- Starter --
    "design":                ("design",                "design"),
    "power_rating":          ("power_rating",          "power_rating"),
    "tooth_quantity":        ("tooth_quantity",         "tooth_quantity"),
    "case_grounding":        ("grounding",             "grounding"),
    "nose_cone_type":        ("nose_type",             "nose_type"),
    "over_crank_protection": ("over_crank_protection", "over_crank_protection"),
    "solenoid_attached":     ("solenoid_attached",     "solenoid_attached"),
    "reclockable_flange":    ("reclockable_flange",    "reclockable_flange"),
    "bolt_holes":            ("bolt_holes",            "bolt_holes"),
    "with_hardware":         ("with_hardware",         "with_hardware"),
    "with_mounting_shims":   ("with_mounting_shims",   "with_mounting_shims"),
    "spline_quantity":       (None,                    "spline_quantity"),
    "drive_housing_position":(None,                    "drive_housing_position"),
}

ALL_MODEL_UPDATE_FIELDS = [
    "yt_number", "j_and_n_number", "manufacturer", "oem", "family",
    "voltage", "rotation", "amp_rating", "fan_type", "regulator_type",
    "grounding", "mount_type", "notes", "unit_type_category",
    "specifications",
    # Generator-specific
    "circuit_type",
    # Starter-specific
    "design", "power_rating", "tooth_quantity", "nose_type",
    "over_crank_protection", "solenoid_attached", "reclockable_flange",
    "bolt_holes", "with_hardware", "with_mounting_shims",
]


class Command(BaseCommand):
    help = "Import buyers-guide product rows into Unit records keyed by YouTech number."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file", type=str, default=None,
            help="Path to the buyers guide staging DB",
        )
        parser.add_argument(
            "--report-only", action="store_true", dest="report_only",
            help="Show what would be imported without making changes",
        )
        parser.add_argument(
            "--preview", action="store_true",
            help="Show detailed preview of 10 sample rows without saving",
        )
        parser.add_argument(
            "--limit", type=int, default=None, metavar="N",
            help="Process at most the first N unique YouTech numbers",
        )
        parser.add_argument(
            "--type", type=str, default="Alternator", dest="unit_type",
            help="Unit type category: Alternator, Starter, Generator, etc. (default: Alternator)",
        )
        parser.add_argument(
            "--only-step", type=int, default=None, dest="only_step",
            help="Run only a specific step (1-7). Useful for resuming after a crash.",
        )

    def handle(self, *args, **options):
        import sys
        sys.stdout.reconfigure(line_buffering=True)

        db_path = self._resolve_db_path(options.get("file"))
        if not db_path.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {db_path}"))
            return

        unit_type = options["unit_type"]

        if options["report_only"]:
            self._report(db_path)
            return

        if options["preview"]:
            self._preview(db_path, options.get("limit"), unit_type)
            return

        self._import(db_path, options.get("limit"), unit_type, options.get("only_step"))

    def _resolve_db_path(self, explicit_path):
        if explicit_path:
            return Path(explicit_path)
        return Path(settings.BASE_DIR) / "data_import" / "staging_dbs" / "buyers_guide.db"

    def _has_column(self, conn, table, column):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        return column in cols

    def _load_rows(self, conn):
        conn.row_factory = sqlite3.Row
        cols = [r[1] for r in conn.execute("PRAGMA table_info(buyers_guide_products)")]
        return conn.execute(
            f"SELECT {', '.join(cols)} FROM buyers_guide_products ORDER BY youtech_number"
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

        xref_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_interchanges").fetchone()[0]
        bom_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_bom").fetchone()[0]
        sub_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_substitutes").fetchone()[0]

        has_images = self._has_column(conn, "buyers_guide_images", "youtech_number")
        img_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_images").fetchone()[0] if has_images else 0

        has_apps = "buyers_guide_applications" in [
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        app_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_applications").fetchone()[0] if has_apps else 0

        conn.close()

        existing_units = Unit.objects.filter(unit_number__in=youtech_numbers).count()
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"REPORT: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Staged product rows:         {product_count:>10,}")
        self.stdout.write(f"  Unique YouTech units:        {unique_units:>10,}")
        self.stdout.write(f"  Existing Unit records:       {existing_units:>10,}")
        self.stdout.write(f"  New Unit records:            {unique_units - existing_units:>10,}")
        self.stdout.write(f"  Interchange records:         {xref_count:>10,}")
        self.stdout.write(f"  BOM line items:              {bom_count:>10,}")
        self.stdout.write(f"  Substitute pairs:            {sub_count:>10,}")
        self.stdout.write(f"  Unit images:                 {img_count:>10,}")
        self.stdout.write(f"  Application entries:         {app_count:>10,}")
        self.stdout.write("")

    def _preview(self, db_path: Path, limit=None, unit_type="Alternator"):
        conn = sqlite3.connect(str(db_path))
        rows = self._load_rows(conn)
        conn.close()

        seen = set()
        unique_rows = []
        for row in rows:
            yt = normalize_space(row["youtech_number"])
            if yt and yt not in seen:
                seen.add(yt)
                unique_rows.append(row)
        if limit:
            unique_rows = unique_rows[:limit]

        sample = unique_rows[:10]

        existing_units = {
            u.unit_number: u
            for u in Unit.objects.filter(unit_number__in=[normalize_space(r["youtech_number"]) for r in sample])
        }

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"PREVIEW (no changes saved)")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Total unique YouTech numbers: {len(seen):,}")
        if limit:
            self.stdout.write(f"  Limit applied: first {limit}")
        self.stdout.write("")

        for row in sample:
            yt = normalize_space(row["youtech_number"])
            unit = existing_units.get(yt)
            status = "UPDATE" if unit else "CREATE"
            self.stdout.write(f"\n--- YouTech #{yt} [{status}] ---")
            if row["jn_number"]:
                current_jn = unit.j_and_n_number if unit else ""
                action = "SKIP (has value)" if current_jn else "SET"
                self.stdout.write(f"  j_and_n_number:    {row['jn_number']:<30s}  [{action}]")

            for staging_col, (model_field, spec_key) in ATTR_FIELD_MAP.items():
                val = normalize_space(row[staging_col]) if staging_col in row.keys() else ""
                if not val:
                    continue
                if model_field and unit:
                    current = getattr(unit, model_field, "")
                    action = "SKIP (has value)" if current else "SET"
                elif unit:
                    current = (unit.specifications or {}).get(spec_key, "")
                    action = "SKIP (has value)" if current else "SET"
                else:
                    action = "SET (new unit)"
                label = model_field or spec_key
                self.stdout.write(f"  {label:<20s} {val:<30s}  [{action}]")

            if row["product_notes"]:
                self.stdout.write(f"  notes:             {row['product_notes'][:50]}...")

        self.stdout.write("")
        self.stdout.write("Run without --preview to import.")

    def _import(self, db_path: Path, limit=None, unit_type="Alternator", only_step=None):
        self.stdout.write(f"\nImporting: {db_path.name}  (unit_type_category={unit_type})")
        if only_step:
            self.stdout.write(f"  Running ONLY step {only_step}")
        self.stdout.write("-" * 60)
        start = time.time()

        conn = sqlite3.connect(str(db_path))
        rows = self._load_rows(conn)

        # Deduplicate by youtech_number, keeping first occurrence
        seen_yt = set()
        unique_rows = []
        for row in rows:
            yt = normalize_space(row["youtech_number"])
            if yt and yt not in seen_yt:
                seen_yt.add(yt)
                unique_rows.append(row)
        if limit:
            unique_rows = unique_rows[:limit]

        youtech_numbers = [normalize_space(r["youtech_number"]) for r in unique_rows]
        if not youtech_numbers:
            self.stdout.write("No staged buyers-guide product rows found.")
            conn.close()
            return

        # Load existing units
        existing_units = {
            normalize_space(unit.unit_number): unit
            for unit in Unit.objects.filter(unit_number__in=youtech_numbers)
        }

        def should_run(step):
            return only_step is None or only_step == step

        # --- Step 1: Create new Unit records ---
        created_units = []
        if should_run(1):
            self.stdout.write("Step 1: Creating new Unit records...")
            for row in unique_rows:
                yt = normalize_space(row["youtech_number"])
                if yt in existing_units:
                    continue
                unit = Unit(
                    unit_number=yt[:100],
                    yt_number=yt[:100],
                    unit_type_category=unit_type,
                )
                created_units.append(unit)

            if created_units:
                Unit.objects.bulk_create(created_units, batch_size=500)
                existing_units = {
                    normalize_space(u.unit_number): u
                    for u in Unit.objects.filter(unit_number__in=youtech_numbers)
                }
            self.stdout.write(f"  {len(created_units):,} new units created")
        else:
            self.stdout.write("Step 1: SKIPPED")

        # --- Step 2: Update attributes ---
        updated_count = 0
        if should_run(2):
            self.stdout.write("Step 2: Updating unit attributes...")
            for row in unique_rows:
                yt = normalize_space(row["youtech_number"])
                unit = existing_units.get(yt)
                if not unit:
                    continue

                changed = False
                specs = dict(unit.specifications or {})

                if not unit.unit_type_category:
                    unit.unit_type_category = unit_type
                    changed = True

                # Ensure yt_number is set
                if not unit.yt_number:
                    unit.yt_number = yt[:100]
                    changed = True

                # J&N number
                jn_val = normalize_space(row["jn_number"])
                if jn_val and not unit.j_and_n_number:
                    unit.j_and_n_number = jn_val[:100]
                    changed = True

                # All mapped attributes
                for staging_col, (model_field, spec_key) in ATTR_FIELD_MAP.items():
                    val = normalize_space(row[staging_col]) if staging_col in row.keys() else ""
                    if not val:
                        continue

                    # Set model field if empty
                    if model_field:
                        current = getattr(unit, model_field, "")
                        if not current:
                            setattr(unit, model_field, val[:200])
                            changed = True

                    # Always set specs key if empty (mirrors how the form saves)
                    if not specs.get(spec_key):
                        specs[spec_key] = val
                        changed = True

                # Product notes
                notes_val = normalize_space(row["product_notes"])
                if notes_val:
                    merged_notes = append_text(unit.notes, notes_val)
                    if merged_notes != unit.notes:
                        unit.notes = merged_notes[:5000]
                        changed = True

                if changed:
                    unit.specifications = specs
                    updated_count += 1

            # Bulk update
            if updated_count:
                Unit.objects.bulk_update(
                    [u for u in existing_units.values()],
                    ALL_MODEL_UPDATE_FIELDS,
                    batch_size=500,
                )
            self.stdout.write(f"  {updated_count:,} units updated")
        else:
            self.stdout.write("Step 2: SKIPPED")

        # --- Step 3: Import interchanges ---
        xref_created = 0
        if should_run(3):
            self.stdout.write("Step 3: Importing interchanges...")
            xref_created = self._import_interchanges(conn, existing_units)
            self.stdout.write(f"  {xref_created:,} new cross-references created")
        else:
            self.stdout.write("Step 3: SKIPPED")

        # --- Step 4: Import BOM ---
        bom_created = bom_items_created = 0
        if should_run(4):
            self.stdout.write("Step 4: Importing BOM items...")
            bom_created, bom_items_created = self._import_bom(conn, existing_units)
            self.stdout.write(f"  {bom_created:,} BOMs created, {bom_items_created:,} BOM items")
        else:
            self.stdout.write("Step 4: SKIPPED")

        # --- Step 5: Import substitutes ---
        sub_created = 0
        if should_run(5):
            self.stdout.write("Step 5: Importing substitutes...")
            sub_created = self._import_substitutes(conn, existing_units)
            self.stdout.write(f"  {sub_created:,} substitute records created")
        else:
            self.stdout.write("Step 5: SKIPPED")

        # --- Step 6: Import images ---
        img_saved = 0
        if should_run(6):
            self.stdout.write("Step 6: Importing images...")
            img_saved = self._import_images(conn, existing_units)
            self.stdout.write(f"  {img_saved:,} unit images saved")
        else:
            self.stdout.write("Step 6: SKIPPED")

        # --- Step 7: Import applications ---
        app_created = link_created = 0
        if should_run(7):
            self.stdout.write("Step 7: Importing applications...")
            app_created, link_created = self._import_applications(conn, existing_units, unit_type)
            self.stdout.write(f"  {app_created:,} applications created, {link_created:,} unit links")
        else:
            self.stdout.write("Step 7: SKIPPED")

        conn.close()
        elapsed = time.time() - start

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"IMPORT COMPLETE: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Units created:              {len(created_units):>10,}")
        self.stdout.write(f"  Units updated:              {updated_count:>10,}")
        self.stdout.write(f"  Cross-references created:   {xref_created:>10,}")
        self.stdout.write(f"  BOMs created:               {bom_created:>10,}")
        self.stdout.write(f"  BOM items created:          {bom_items_created:>10,}")
        self.stdout.write(f"  Substitutes created:        {sub_created:>10,}")
        self.stdout.write(f"  Images saved:               {img_saved:>10,}")
        self.stdout.write(f"  Applications created:       {app_created:>10,}")
        self.stdout.write(f"  Application-Unit links:     {link_created:>10,}")
        self.stdout.write(f"  Total time:                 {elapsed:>10.1f}s")
        self.stdout.write("")

    def _import_interchanges(self, conn, existing_units):
        """Import buyers_guide_interchanges into CrossReference records.

        Model Number rule (PDF 11 family-coding fix)
        ---------------------------------------------
        PDF interchange entries with ``manufacturer == "Model Number"`` (case-
        insensitive) are *not* real cross-references — they identify the OEM
        family code (e.g. ``Model Number: 10MT`` means ``family = '10MT'``).
        For each such entry, write the value into ``Unit.family`` (only when
        the field is empty so manual edits are preserved) and DO NOT create
        a CrossReference row.  Multiple Model Number entries on the same
        unit: the first non-empty value wins; later ones are no-ops because
        ``unit.family`` is then already populated.
        """
        try:
            rows = conn.execute(
                "SELECT manufacturer, their_number, our_number "
                "FROM buyers_guide_interchanges"
            ).fetchall()
        except sqlite3.OperationalError:
            return 0

        our_numbers_in_scope = set(existing_units.keys())
        unit_map = {normalize_space(u.unit_number): u.pk for u in existing_units.values()}

        existing_xrefs = set()
        for unit in existing_units.values():
            for xr in CrossReference.objects.filter(unit=unit).values_list(
                "cross_ref_number", "interchange_type"
            ):
                existing_xrefs.add((unit.pk, xr[0], xr[1]))

        batch = []
        created = 0
        family_updates = {}   # yt -> family value (collected, applied at end)
        family_skipped = 0    # Model-Number xrefs we suppressed
        for mfr, their_no, our_no in rows:
            our_no = normalize_space(our_no)
            if our_no not in our_numbers_in_scope:
                continue
            unit_pk = unit_map.get(our_no)
            if not unit_pk:
                continue

            mfr_clean = normalize_space(mfr)
            their_no = normalize_space(their_no)[:100]
            if not their_no:
                continue

            # Model Number rule — write to Unit.family, skip CrossReference
            if mfr_clean.lower() == "model number":
                unit = existing_units[our_no]
                if not (unit.family or "").strip() and our_no not in family_updates:
                    family_updates[our_no] = their_no[:100]
                family_skipped += 1
                continue

            mfr_clean = mfr_clean[:150]
            dedup_key = (unit_pk, their_no, mfr_clean)
            if dedup_key in existing_xrefs:
                continue
            existing_xrefs.add(dedup_key)

            batch.append(CrossReference(
                unit_id=unit_pk,
                cross_ref_number=their_no,
                interchange_type=mfr_clean,
            ))

            if len(batch) >= 2000:
                CrossReference.objects.bulk_create(batch, ignore_conflicts=True)
                created += len(batch)
                batch = []

        if batch:
            CrossReference.objects.bulk_create(batch, ignore_conflicts=True)
            created += len(batch)

        # Apply Model-Number family assignments
        family_applied = 0
        if family_updates:
            units_to_save = []
            for our_no, fam in family_updates.items():
                unit = existing_units[our_no]
                if not (unit.family or "").strip():
                    unit.family = fam
                    units_to_save.append(unit)
            if units_to_save:
                Unit.objects.bulk_update(units_to_save, ["family"], batch_size=500)
                family_applied = len(units_to_save)
        self.stdout.write(
            f"    Model Number rule: {family_skipped:,} xrefs suppressed, "
            f"{family_applied:,} family fields set"
        )

        return created

    def _import_bom(self, conn, existing_units):
        """Import buyers_guide_bom into BOM + BOMItem records."""
        import gc
        from django.db import reset_queries

        try:
            rows = conn.execute(
                "SELECT youtech_number, part_name, yt_part_number, jn_part_number "
                "FROM buyers_guide_bom"
            ).fetchall()
        except sqlite3.OperationalError:
            return 0, 0

        boms_created = 0
        items_created = 0
        boms_skipped_empty = 0  # Fix N — units whose BOM would be empty

        skipped_xref_leak = 0
        by_unit = {}
        for yt, part_name, yt_part, jn_part in rows:
            yt = normalize_space(yt)
            if yt not in existing_units:
                continue
            # Fix N — only count rows with a non-empty yt_part as real items.
            if not normalize_space(yt_part):
                continue
            # Skip entries where yt_part_number contains pipe-delimited
            # interchange data leaked from an adjacent PDF section.
            if "|" in yt_part:
                skipped_xref_leak += 1
                continue
            by_unit.setdefault(yt, []).append((part_name, yt_part, jn_part))

        total_units = len(by_unit)
        processed = 0

        for yt, items in by_unit.items():
            # Fix N — defensive: never create a BOM with zero items.
            if not items:
                boms_skipped_empty += 1
                continue

            unit = existing_units[yt]
            bom = BOM.objects.filter(name=yt).first()
            if not bom:
                bom = BOM.objects.create(
                    name=yt, unit=unit, description=f"BOM for {yt}",
                )
                boms_created += 1
            elif bom.unit_id is None:
                bom.unit_id = unit.pk
                bom.save(update_fields=["unit_id"])

            existing_items = set(
                BOMItem.objects.filter(bom=bom).values_list("yt_number", flat=True)
            )

            for part_name, yt_part, jn_part in items:
                part_name = normalize_space(part_name)
                yt_part = normalize_space(yt_part)
                jn_part = normalize_space(jn_part)
                if not yt_part:
                    continue

                if yt_part in existing_items:
                    # Backfill J&N on existing BOM item / Part if missing
                    if jn_part:
                        existing_bom_item = BOMItem.objects.filter(
                            bom=bom, yt_number=yt_part[:100],
                        ).first()
                        if existing_bom_item and not existing_bom_item.j_and_n:
                            existing_bom_item.j_and_n = jn_part[:255]
                            existing_bom_item.save(update_fields=["j_and_n"])
                        if existing_bom_item and existing_bom_item.part and not existing_bom_item.part.j_and_n:
                            existing_bom_item.part.j_and_n = jn_part[:255]
                            existing_bom_item.part.save(update_fields=["j_and_n"])
                    continue

                part = Part.objects.filter(yt_number=yt_part[:100]).first()
                if not part:
                    part = Part.objects.create(
                        yt_number=yt_part[:100],
                        part_name=part_name[:255],
                        j_and_n=jn_part[:255] if jn_part else "",
                    )
                elif jn_part and not part.j_and_n:
                    part.j_and_n = jn_part[:255]
                    part.save(update_fields=["j_and_n"])

                existing_bom_item = BOMItem.objects.filter(
                    bom=bom, yt_number=yt_part[:100],
                ).first()
                if not existing_bom_item:
                    BOMItem.objects.create(
                        bom=bom,
                        part=part,
                        yt_number=yt_part[:100],
                        description=part_name[:255],
                        j_and_n=jn_part[:255] if jn_part else "",
                    )
                    items_created += 1

            processed += 1
            if processed % 500 == 0:
                self.stdout.write(
                    f"    BOM progress: {processed:,}/{total_units:,} units "
                    f"({items_created:,} items)",
                )
                reset_queries()
                gc.collect()

        if boms_skipped_empty:
            self.stdout.write(
                f"    Fix N: {boms_skipped_empty:,} empty BOM(s) skipped (no items)"
            )
        if skipped_xref_leak:
            self.stdout.write(
                f"    Xref-leak filter: {skipped_xref_leak:,} BOM row(s) skipped "
                f"(pipe-delimited interchange data in yt_part_number)"
            )

        return boms_created, items_created

    def _import_substitutes(self, conn, existing_units):
        """Import buyers_guide_substitutes into Substitute records."""
        try:
            rows = conn.execute(
                "SELECT youtech_number, substitute_yt, substitute_jn "
                "FROM buyers_guide_substitutes"
            ).fetchall()
        except sqlite3.OperationalError:
            return 0

        unit_map = dict(Unit.objects.values_list("unit_number", "pk"))
        created = 0

        for yt, sub_yt, sub_jn in rows:
            yt = normalize_space(yt)
            sub_yt = normalize_space(sub_yt)
            if yt not in existing_units or not sub_yt:
                continue

            unit = existing_units[yt]
            sub_unit_pk = unit_map.get(sub_yt)

            already = Substitute.objects.filter(
                unit=unit, substitute_number=sub_yt[:100]
            ).exists()
            if not already and sub_unit_pk:
                already = Substitute.objects.filter(
                    unit=unit, substitute_unit_id=sub_unit_pk
                ).exists()
            if already:
                continue

            if sub_unit_pk:
                Substitute.objects.create(
                    unit=unit,
                    substitute_unit_id=sub_unit_pk,
                    substitute_number=sub_yt[:100],
                )
            else:
                Substitute.objects.create(
                    unit=unit,
                    substitute_number=sub_yt[:100],
                    notes=f"J&N: {sub_jn}" if sub_jn else "",
                )
            created += 1

        return created

    def _import_images(self, conn, existing_units):
        """Import buyers_guide_images into Unit.unit_image fields."""
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM buyers_guide_images"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            return 0

        if count == 0:
            return 0

        saved = 0
        processed = 0
        cursor = conn.execute(
            "SELECT youtech_number, image_data, image_ext "
            "FROM buyers_guide_images"
        )

        for yt_raw, image_data, image_ext in cursor:
            yt = normalize_space(yt_raw)
            unit = existing_units.get(yt)
            processed += 1

            if not unit or unit.unit_image:
                continue

            ext = image_ext.lower().strip(".")
            if ext == "jpeg":
                ext = "jpg"
            filename = f"{yt}.{ext}"
            unit.unit_image.save(filename, ContentFile(image_data), save=True)
            saved += 1

            if saved % 200 == 0:
                self.stdout.write(
                    f"    Image progress: {saved:,} saved ({processed:,}/{count:,} checked)"
                )

        return saved

    # ------------------------------------------------------------------
    # Application text parsing
    # ------------------------------------------------------------------
    _YEAR_RANGE_RE = re.compile(r'\d{4}-\d{4}')
    _ENGINE_SPEC_RE = re.compile(
        r'\b(?:'
        r'[LVH]\d\s+\d+\.\d+L\b'
        r'|\d+\.\d+L\b'
        r'|Diesel\b'
        r'|Turbo\b'
        r'|Gas\b'
        r')'
    )
    # Line-level xref-leak filter: a single line that is clearly
    # pipe-delimited interchange text ("Brand: number | Brand: number")
    _XREF_LINE_RE = re.compile(
        r'^[A-Z][\w\s&.]*:\s*[\w-]+.*\|'
    )
    # Continuation of interchange text (starts with number/text, has
    # multiple pipes, no year ranges or semicolons)
    _XREF_CONTINUATION_RE = re.compile(r'.*\|.*\|')
    # Substitute-leak filter: "YouTech : NNNNNN" patterns from POSSIBLE
    # SUBSTITUTIONS section that leaked into APPLICATION
    _SUB_LEAK_RE = re.compile(r'YouTech\s*:\s*\d{5,}')
    _ATTR_KEY_NAMES = frozenset({
        "manufacture", "oe_manufacturer", "family", "voltage", "mounting_type",
        "series", "amperage_rating", "fan_type", "regulator_type",
        "rotation_direction", "ground_type", "ground_polarity",
        "mounting_ear_quantity", "plug_type", "plug_clock_rear_view",
        "plug_clock_rear_view_main_mounting_ear_at", "pulley_belt_type",
        "pulley_groove_quantity", "pulley_class", "pulley_outside_diameter",
        "outside_diameter", "decoupled", "decoupled_or_clutch_pulley",
        "stator_type", "stator_leads", "circuit_type", "generator_rotation",
        "starter_rotation", "design", "power_rating", "kw", "tooth_quantity",
        "case_grounding", "nose_cone_type", "over-crank_protection",
        "solenoid_attached", "re-clockable_flange", "spline_quantity",
        "starter_drive_housing_position", "mounting_bolt_hole_quantity",
        "mounting_hardware_included", "mounting_shims_included",
    })

    def _is_xref_leak_line(self, line):
        """Return True if line looks like leaked interchange text."""
        if self._YEAR_RANGE_RE.search(line):
            return False
        if ';' in line:
            return False
        # Primary: starts with "Brand: number ... |"
        if self._XREF_LINE_RE.match(line):
            return True
        # Continuation: has 2+ pipes and colon-number patterns
        if self._XREF_CONTINUATION_RE.match(line) and ':' in line:
            return True
        return False

    def _parse_application_text(self, raw_text):
        """
        Parse raw application text block into list of dicts:
            {make, model, engine, year}

        Format in PDF:
            MakeName
            Model1 EngineSpec Year; Model2 EngineSpec Year
            AnotherMake
            Model3 EngineSpec Year

        Safety net: filters out individual lines that match pipe-delimited
        interchange patterns or substitutes patterns (xref-leak residue
        from parser column misclassification).
        """
        # Block-level skip: pure substitutes leak (no year ranges at all)
        has_year_ranges = bool(self._YEAR_RANGE_RE.search(raw_text))
        if not has_year_ranges and self._SUB_LEAK_RE.search(raw_text):
            return []

        # Line-level filtering: remove individual interchange lines
        filtered_lines = []
        skip_next_as_attr_value = False
        for raw_line in raw_text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            # Skip lines that look like pipe-delimited interchange entries
            if self._is_xref_leak_line(line):
                continue
            # Skip substitutes lines
            if self._SUB_LEAK_RE.match(line):
                continue
            # Skip leaked attribute key names (e.g. "Fan Type", "Voltage")
            # and the value line that immediately follows them
            if line.lower().replace(" ", "_").replace("-", "_") in self._ATTR_KEY_NAMES:
                skip_next_as_attr_value = True
                continue
            if skip_next_as_attr_value:
                skip_next_as_attr_value = False
                continue
            filtered_lines.append(line)

        if not filtered_lines:
            return []

        results = []
        current_make = ""
        model_buffer = ""

        for line in filtered_lines:

            # A make line: starts with a letter, contains no semicolons,
            # no year ranges, and is relatively short
            is_make_line = (
                re.match(r'^[A-Za-z]', line)
                and ";" not in line
                and not self._YEAR_RANGE_RE.search(line)
                and not re.match(r'.*\d{2,}[A-Z]', line)  # not a model like "3.0GS"
                and len(line) < 80
            )

            # Parenthesized continuation of make name, e.g. "(Aabenraa)" after "Bukh"
            if current_make and re.match(r'^\(.+\)$', line) and not model_buffer:
                current_make = f"{current_make} {line}".title()
                continue

            # Make-continuation: when we have a make but no model data yet,
            # short non-model lines are wrapped parts of the make name
            # (e.g. "OMC Engine\n- Inboard &\nV-Drive" or "Mercruiser\nStern Drive")
            if current_make and not model_buffer:
                is_make_continuation = (
                    line.startswith("-")
                    or line.startswith("&")
                    or line.startswith("/")
                    or (
                        not self._YEAR_RANGE_RE.search(line)
                        and ";" not in line
                        and not re.search(r'\d', line)
                        and len(line) < 40
                    )
                )
                if is_make_continuation:
                    current_make = f"{current_make} {line}".strip()
                    continue

            if is_make_line:
                # Flush any pending model buffer
                if current_make and model_buffer:
                    results.extend(
                        self._split_model_entries(current_make, model_buffer)
                    )
                    model_buffer = ""
                current_make = line.title()
            else:
                # Continuation of model data
                if model_buffer:
                    model_buffer += " " + line
                else:
                    model_buffer = line

        # Flush final
        if current_make and model_buffer:
            results.extend(self._split_model_entries(current_make, model_buffer))

        return results

    def _split_model_entries(self, make, text):
        """Split semicolon-delimited model entries into individual dicts."""
        results = []
        entries = text.split(";")
        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue

            year = ""
            engine = ""

            # Extract year range — take the rightmost match so that
            # displacement-like numbers (e.g. "7277CC") are never confused
            year_matches = list(self._YEAR_RANGE_RE.finditer(entry))
            if year_matches:
                year_match = year_matches[-1]
                year = year_match.group(0)
                entry = entry[:year_match.start()].strip()

            # Extract engine spec with tightened pattern:
            #   [LVH]\d + displacement  |  bare displacement  |  Diesel/Turbo/Gas
            engine_match = self._ENGINE_SPEC_RE.search(entry)
            if engine_match:
                model = entry[:engine_match.start()].strip()
                engine = entry[engine_match.start():].strip()
            else:
                model = entry
                engine = ""

            model = model.strip().rstrip(",")
            if model:
                results.append({
                    "make": make,
                    "model": model[:150],
                    "engine": engine[:150],
                    "year": year[:50],
                })
        return results

    def _import_applications(self, conn, existing_units, unit_type=""):
        """Import buyers_guide_applications into Application + ApplicationUnit."""
        import gc
        from django.db import connection as django_conn, reset_queries

        try:
            rows = conn.execute(
                "SELECT youtech_number, application_text "
                "FROM buyers_guide_applications"
            ).fetchall()
        except sqlite3.OperationalError:
            return 0, 0

        apps_created = 0
        links_created = 0
        total = len(rows)

        # Pre-load existing app lookup to avoid repeated queries
        self.stdout.write("    Building application cache...")
        app_cache = {}
        for app in Application.objects.all().iterator(chunk_size=5000):
            key = (app.make, app.model, app.engine, app.year)
            app_cache[key] = app.pk
        self.stdout.write(f"    Cached {len(app_cache):,} existing applications")

        # Pre-load existing links
        existing_links = set()
        for au in ApplicationUnit.objects.all().values_list(
            "application_id", "unit_id"
        ).iterator(chunk_size=10000):
            existing_links.add(au)
        self.stdout.write(f"    Cached {len(existing_links):,} existing links")

        link_batch = []

        for idx, (yt, app_text) in enumerate(rows, 1):
            yt = normalize_space(yt)
            unit = existing_units.get(yt)
            if not unit:
                continue

            entries = self._parse_application_text(app_text)
            for entry in entries:
                make = entry["make"]
                model = entry["model"]
                engine = entry["engine"]
                year = entry["year"]
                cache_key = (make, model, engine, year)

                app_pk = app_cache.get(cache_key)
                if not app_pk:
                    name = f"{make} {model}"
                    if engine:
                        name += f" {engine}"
                    if year:
                        name += f" {year}"
                    app = Application.objects.create(
                        name=name[:255], make=make, model=model,
                        engine=engine, year=year,
                        unit_type_name=unit_type[:100],
                        mfr=(unit.manufacturer or "")[:150],
                        volt=(unit.voltage or "")[:50],
                        amp=(unit.amp_rating or "")[:50],
                        kw=(unit.power_rating or "")[:50],
                        unit_number=yt[:100],
                    )
                    app_pk = app.pk
                    app_cache[cache_key] = app_pk
                    apps_created += 1

                link_key = (app_pk, unit.pk)
                if link_key not in existing_links:
                    existing_links.add(link_key)
                    link_batch.append(
                        ApplicationUnit(application_id=app_pk, unit_id=unit.pk)
                    )
                    links_created += 1

            if len(link_batch) >= 2000:
                ApplicationUnit.objects.bulk_create(link_batch, ignore_conflicts=True)
                link_batch = []

            if idx % 500 == 0:
                self.stdout.write(
                    f"    App progress: {idx:,}/{total:,} units "
                    f"({apps_created:,} apps, {links_created:,} links)"
                )
                reset_queries()
                gc.collect()

        if link_batch:
            ApplicationUnit.objects.bulk_create(link_batch, ignore_conflicts=True)

        return apps_created, links_created
