"""
Import Tilt & Trim Motors buyers-guide data from staging SQLite DB into
the live catalog.

Creates / updates:
  - Unit records (keyed by yt_number; unit_number left blank)
  - CrossReference records (all interchange entries including J&N)
  - Substitute records (possible substitutions)
  - BOM + BOMItem records
  - Stub Part records for unknown BOM parts (merged later by yt_number)
  - Unit images saved to media/units/<yt_number>.<ext>

Usage:
    python manage.py import_tilt_trim_motors
    python manage.py import_tilt_trim_motors --file path/to/staging.db
    python manage.py import_tilt_trim_motors --report-only
"""

import sqlite3
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from catalog.models import (
    BOM,
    BOMItem,
    CrossReference,
    Part,
    Substitute,
    Unit,
    UnitType,
)
from data_import.import_utils import normalize_space
from config.media_utils import write_media_file


# ---------------------------------------------------------------------------
# Family → UnitType name mapping
# Families NOT listed here (DD, TILT&TRIM, blank, unknown) → no unit_type
# ---------------------------------------------------------------------------
FAMILY_TO_UNIT_TYPE = {
    "PUMP": "Pump",
    "PLOW": "DC Motor",
    "WINCH": "DC Motor",
    "PMDD": "DC Motor",
}


# ---------------------------------------------------------------------------
# Part name → PartCategory mapping (for stub parts)
# ---------------------------------------------------------------------------
def _guess_category(part_name: str) -> str:
    name = part_name.lower()
    if "armature" in name:
        return "Shafts & Armatures"
    if "brush spring" in name:
        return "Starter & DC Motor Brush Springs"
    if "brush holder" in name:
        return "Brush Holders & Parts"
    if "brush" in name:
        return "Brushes - Starter & DC Motor"
    if "bushing" in name:
        return "Bushings"
    if "bearing" in name:
        return "Bearings"
    if "field coil" in name:
        return "Field Coils"
    if "seal" in name or "gasket" in name:
        return "Gaskets, Grommets & Seals"
    if "housing" in name or "frame" in name:
        return "Housings"
    if "drive" in name:
        return "Drives, Clutches & Drive Parts"
    if "solenoid" in name:
        return "Relays, Solenoids & Switches"
    return "Hardware & Misc"


class Command(BaseCommand):
    help = "Import Tilt & Trim Motors buyers-guide staging DB into the catalog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=None,
            help="Path to the buyers guide staging DB (default: staging_dbs/<pdf_name>.db)",
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
            self.stderr.write(self.style.ERROR(f"Staging DB not found: {db_path}"))
            self.stderr.write(
                "Run: python -m data_import.pdf_parsers.parse_buyers_guide <pdf_path>"
            )
            return

        if options["report_only"]:
            self._report(db_path)
            return

        self._import(db_path)

    # ------------------------------------------------------------------
    def _resolve_db_path(self, explicit_path):
        if explicit_path:
            return Path(explicit_path)
        staging_dir = Path(settings.BASE_DIR) / "data_import" / "staging_dbs"
        # Prefer the tilt-trim specific DB; fall back to generic buyers_guide.db
        specific = staging_dir / "12-Buyers Guide Tilt Trim Motors-001-091.db"
        if specific.exists():
            return specific
        return staging_dir / "buyers_guide.db"

    # ------------------------------------------------------------------
    def _load_conn(self, db_path: Path):
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    def _report(self, db_path: Path):
        conn = self._load_conn(db_path)
        prod_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_products").fetchone()[0]
        xref_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_interchanges").fetchone()[0]
        bom_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_bom").fetchone()[0]
        sub_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_substitutes").fetchone()[0]
        img_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_images").fetchone()[0]
        existing = Unit.objects.filter(
            yt_number__in=[
                r[0] for r in conn.execute(
                    "SELECT DISTINCT youtech_number FROM buyers_guide_products"
                )
            ]
        ).count()
        conn.close()

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"REPORT: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Staged units:              {prod_count:>10,}")
        self.stdout.write(f"  Already in catalog:        {existing:>10,}")
        self.stdout.write(f"  Interchange records:       {xref_count:>10,}")
        self.stdout.write(f"  BOM line items:            {bom_count:>10,}")
        self.stdout.write(f"  Substitute pairs:          {sub_count:>10,}")
        self.stdout.write(f"  Images available:          {img_count:>10,}")
        self.stdout.write("")

    # ------------------------------------------------------------------
    def _import(self, db_path: Path):
        self.stdout.write(f"\nImporting: {db_path.name}")
        self.stdout.write("-" * 60)
        start = time.time()

        conn = self._load_conn(db_path)

        # Pre-load unit type lookups
        unit_type_cache = {
            ut.name.upper(): ut for ut in UnitType.objects.all()
        }

        # ── 1. UNITS ──────────────────────────────────────────────────
        self.stdout.write("  [1/6] Creating / updating Unit records...")
        prod_rows = conn.execute(
            "SELECT youtech_number, jn_number, manufacture, oe_manufacturer, "
            "family, voltage, rotation, product_notes "
            "FROM buyers_guide_products ORDER BY youtech_number"
        ).fetchall()

        units_created = units_updated = 0
        unit_lookup = {}  # yt_number -> Unit pk (populated after bulk ops)

        # Existing units keyed by yt_number
        all_yt = [normalize_space(r["youtech_number"]) for r in prod_rows if r["youtech_number"]]
        existing_by_yt = {
            normalize_space(u.yt_number): u
            for u in Unit.objects.filter(yt_number__in=all_yt)
        }

        new_units = []
        update_units = []

        for row in prod_rows:
            yt = normalize_space(row["youtech_number"])
            if not yt:
                continue

            family = normalize_space(row["family"]).upper()
            type_name = FAMILY_TO_UNIT_TYPE.get(family, "")
            unit_type_obj = unit_type_cache.get(type_name.upper()) if type_name else None

            defaults = dict(
                unit_number=None,  # no distinct item/part number in this PDF
                yt_number=yt[:100],
                j_and_n_number=normalize_space(row["jn_number"])[:100],
                manufacturer=normalize_space(row["manufacture"])[:200],
                oem=normalize_space(row["oe_manufacturer"])[:200],
                family=normalize_space(row["family"])[:100],
                voltage=normalize_space(row["voltage"])[:50],
                rotation=normalize_space(row["rotation"])[:50],
                notes=normalize_space(row["product_notes"])[:2000],
            )
            if unit_type_obj:
                defaults["unit_type"] = unit_type_obj
                # unit_type_category must mirror unit_type.name so the unit
                # list tabs and filters (which use the string field) work
                defaults["unit_type_category"] = unit_type_obj.name

            if yt in existing_by_yt:
                unit = existing_by_yt[yt]
                changed = False
                for field, val in defaults.items():
                    if field == "unit_number":
                        pass  # never overwrite an existing unit_number
                    elif field == "unit_type":
                        if val and not unit.unit_type:
                            unit.unit_type = val
                            changed = True
                    elif field == "notes":
                        if val and val not in (unit.notes or ""):
                            unit.notes = ((unit.notes + "\n" + val).strip())[:2000]
                            changed = True
                    else:
                        if val and not getattr(unit, field, ""):
                            setattr(unit, field, val)
                            changed = True
                if changed:
                    update_units.append(unit)
            else:
                new_units.append(Unit(**defaults))

        if new_units:
            Unit.objects.bulk_create(new_units, batch_size=200)
            units_created = len(new_units)

        if update_units:
            Unit.objects.bulk_update(
                update_units,
                ["j_and_n_number", "manufacturer", "oem",
                 "family", "voltage", "rotation", "notes",
                 "unit_type", "unit_type_category"],
                batch_size=200,
            )
            units_updated = len(update_units)

        # Refresh lookup (includes newly created)
        unit_lookup = {
            normalize_space(u.yt_number): u
            for u in Unit.objects.filter(yt_number__in=all_yt)
        }
        self.stdout.write(
            f"     created: {units_created:,}  updated: {units_updated:,}"
        )

        # ── 2. IMAGES ─────────────────────────────────────────────────
        self.stdout.write("  [2/6] Saving unit images...")
        img_rows = conn.execute(
            "SELECT youtech_number, image_data, image_ext FROM buyers_guide_images"
        ).fetchall()
        imgs_saved = 0
        for row in img_rows:
            yt = normalize_space(row["youtech_number"])
            unit = unit_lookup.get(yt)
            if not unit:
                continue
            if unit.unit_image:
                continue  # already has an image
            ext = row["image_ext"] or "jpeg"
            filename = f"{yt}.{ext}"
            rel_path = write_media_file(f"units/{filename}", bytes(row["image_data"]))
            unit.unit_image.name = rel_path
            unit.save(update_fields=["unit_image"])
            imgs_saved += 1
        self.stdout.write(f"     saved: {imgs_saved:,}")

        # ── 3. CROSS REFERENCES ───────────────────────────────────────
        self.stdout.write("  [3/6] Creating CrossReference records...")
        xref_rows = conn.execute(
            "SELECT manufacturer, their_number, our_number "
            "FROM buyers_guide_interchanges"
        ).fetchall()

        # Build set of existing cross-refs to avoid duplicates
        existing_xrefs = set(
            CrossReference.objects.filter(
                unit__yt_number__in=all_yt
            ).values_list("unit__yt_number", "cross_ref_number", "interchange_type")
        )

        new_xrefs = []
        for row in xref_rows:
            yt = normalize_space(row["our_number"])
            unit = unit_lookup.get(yt)
            if not unit:
                continue
            mfr = normalize_space(row["manufacturer"])[:150]
            num = normalize_space(row["their_number"])[:100]
            if not num:
                continue
            key = (yt, num, mfr)
            if key in existing_xrefs:
                continue
            existing_xrefs.add(key)
            new_xrefs.append(CrossReference(
                unit=unit,
                cross_ref_number=num,
                interchange_type=mfr,
            ))

        if new_xrefs:
            CrossReference.objects.bulk_create(new_xrefs, batch_size=500, ignore_conflicts=True)
        xrefs_created = len(new_xrefs)
        self.stdout.write(f"     created: {xrefs_created:,}")

        # ── 4. SUBSTITUTES ────────────────────────────────────────────
        self.stdout.write("  [4/6] Creating Substitute records...")
        sub_rows = conn.execute(
            "SELECT youtech_number, substitute_yt, substitute_jn "
            "FROM buyers_guide_substitutes"
        ).fetchall()

        existing_subs = set(
            Substitute.objects.filter(
                unit__yt_number__in=all_yt
            ).values_list("unit__yt_number", "substitute_number")
        )

        new_subs = []
        for row in sub_rows:
            yt = normalize_space(row["youtech_number"])
            sub_yt = normalize_space(row["substitute_yt"])
            unit = unit_lookup.get(yt)
            if not unit or not sub_yt:
                continue
            key = (yt, sub_yt)
            if key in existing_subs:
                continue
            existing_subs.add(key)
            sub_unit = unit_lookup.get(sub_yt)
            new_subs.append(Substitute(
                unit=unit,
                substitute_number=sub_yt[:100],
                substitute_unit=sub_unit,
            ))

        if new_subs:
            Substitute.objects.bulk_create(new_subs, batch_size=500, ignore_conflicts=True)
        subs_created = len(new_subs)
        self.stdout.write(f"     created: {subs_created:,}")

        # ── 5. STUB PARTS ─────────────────────────────────────────────
        self.stdout.write("  [5/6] Creating stub Part records for BOM items...")
        bom_rows = conn.execute(
            "SELECT youtech_number, part_name, yt_part_number, jn_part_number "
            "FROM buyers_guide_bom"
        ).fetchall()

        # Collect all unique BOM part YT numbers
        bom_yt_nums = list({
            normalize_space(r["yt_part_number"])
            for r in bom_rows
            if normalize_space(r["yt_part_number"])
        })

        existing_parts = {
            normalize_space(p.yt_number): p
            for p in Part.objects.filter(yt_number__in=bom_yt_nums)
            if p.yt_number
        }
        existing_parts_by_pn = {
            normalize_space(p.part_number): p
            for p in Part.objects.filter(part_number__in=bom_yt_nums)
        }

        parts_created = 0
        part_lookup = {}  # yt_part_num -> Part

        # First pass: build stub parts we need to create
        stubs_to_create = {}  # yt_part_num -> Part instance
        for row in bom_rows:
            yt_part = normalize_space(row["yt_part_number"])
            if not yt_part:
                continue
            if yt_part in existing_parts:
                part_lookup[yt_part] = existing_parts[yt_part]
                continue
            if yt_part in existing_parts_by_pn:
                part_lookup[yt_part] = existing_parts_by_pn[yt_part]
                continue
            if yt_part in stubs_to_create:
                continue
            part_name = normalize_space(row["part_name"])
            jn_val = normalize_space(row["jn_part_number"])
            category = _guess_category(part_name)
            stubs_to_create[yt_part] = Part(
                part_number=yt_part[:100],
                yt_number=yt_part[:100],
                part_name=part_name[:255],
                j_and_n=jn_val[:100],
                category=category,
            )

        if stubs_to_create:
            created = Part.objects.bulk_create(
                list(stubs_to_create.values()),
                batch_size=200,
                ignore_conflicts=True,
            )
            parts_created = len(created)
            # Reload to get PKs
            fresh = {
                normalize_space(p.yt_number): p
                for p in Part.objects.filter(yt_number__in=list(stubs_to_create.keys()))
            }
            part_lookup.update(fresh)

        self.stdout.write(f"     created: {parts_created:,}")

        # ── 6. BOM + BOM ITEMS ────────────────────────────────────────
        self.stdout.write("  [6/6] Creating BOM and BOMItem records...")
        boms_created = bom_items_created = 0

        # Group BOM rows by unit YT number
        bom_by_unit = {}
        for row in bom_rows:
            yt = normalize_space(row["youtech_number"])
            if yt not in bom_by_unit:
                bom_by_unit[yt] = []
            bom_by_unit[yt].append(row)

        existing_bom_names = set(
            BOM.objects.filter(
                unit__yt_number__in=list(bom_by_unit.keys())
            ).values_list("name", flat=True)
        )

        for yt, rows in bom_by_unit.items():
            unit = unit_lookup.get(yt)
            if not unit:
                continue
            bom_name = f"{yt} BOM"
            if bom_name in existing_bom_names:
                continue

            bom_obj = BOM.objects.create(name=bom_name, unit=unit)
            boms_created += 1
            existing_bom_names.add(bom_name)

            items_to_create = []
            for row in rows:
                yt_part = normalize_space(row["yt_part_number"])
                part = part_lookup.get(yt_part)
                if not part:
                    continue
                items_to_create.append(BOMItem(
                    bom=bom_obj,
                    part=part,
                    description=normalize_space(row["part_name"])[:255],
                    yt_number=yt_part[:100],
                    j_and_n=normalize_space(row["jn_part_number"])[:100],
                    unit_qty=1,
                ))
            if items_to_create:
                BOMItem.objects.bulk_create(items_to_create, batch_size=200)
                bom_items_created += len(items_to_create)

        self.stdout.write(
            f"     BOMs: {boms_created:,}  items: {bom_items_created:,}"
        )

        conn.close()
        elapsed = time.time() - start

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(self.style.SUCCESS("IMPORT COMPLETE"))
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Units created:             {units_created:>10,}")
        self.stdout.write(f"  Units updated:             {units_updated:>10,}")
        self.stdout.write(f"  Images saved:              {imgs_saved:>10,}")
        self.stdout.write(f"  Cross references created:  {xrefs_created:>10,}")
        self.stdout.write(f"  Substitutes created:       {subs_created:>10,}")
        self.stdout.write(f"  Stub parts created:        {parts_created:>10,}")
        self.stdout.write(f"  BOMs created:              {boms_created:>10,}")
        self.stdout.write(f"  BOM items created:         {bom_items_created:>10,}")
        self.stdout.write(f"  Total time:                {elapsed:>10.1f}s")
        self.stdout.write("")
