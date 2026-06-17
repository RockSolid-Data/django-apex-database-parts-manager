"""
Import J&N Unit BOM data from a staging DB into the Django catalog.

The staging DB is produced by:
    python -m data_import.pdf_parsers.parse_jn_unit_bom <path>

It contains three tables:
    jn_unit_products   – one row per J&N unit (header info)
    jn_unit_bom_items  – BOM line items per unit
    jn_unit_references – substitutes, references, superseded-by entries

This command:
  1. For each unit in jn_unit_products:
       - Looks up an existing Unit by j_and_n_number and links it.
       - get_or_creates a BOM record (name = J&N number).
  2. For each BOM item:
       - get_or_creates a Part keyed by J&N number (or OEM number fallback).
       - Creates a BOMItem linking the BOM to that Part.
  3. For substitute and reference entries:
       - Creates CrossReference records on the linked Unit (if found).

Usage:
    python manage.py import_jn_bom --file data_import/staging_dbs/jn_unit_bom.db
    python manage.py import_jn_bom --file ... --report-only
    python manage.py import_jn_bom --file ... --clear-boms
"""

import sqlite3
import time
from pathlib import Path

from django.core.management.base import BaseCommand

from catalog.models import BOM, BOMItem, CrossReference, Part, Unit


BATCH_SIZE = 2000


class Command(BaseCommand):
    help = "Import J&N Unit BOM staging DB into the catalog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            required=True,
            help="Path to the jn_unit_bom.db staging file",
        )
        parser.add_argument(
            "--report-only",
            action="store_true",
            dest="report_only",
            help="Show what would be imported without making any changes",
        )
        parser.add_argument(
            "--clear-boms",
            action="store_true",
            dest="clear_boms",
            help="Delete all existing BOM and BOMItem records before importing",
        )

    def handle(self, *args, **options):
        db_path = Path(options["file"])
        if not db_path.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {db_path}"))
            return

        if options["report_only"]:
            self._report(db_path)
            return

        if options["clear_boms"]:
            bom_count = BOM.objects.count()
            item_count = BOMItem.objects.count()
            BOM.objects.all().delete()   # cascades to BOMItem
            self.stdout.write(
                f"Cleared {bom_count:,} BOMs and {item_count:,} BOM items."
            )

        self._import(db_path)

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def _report(self, db_path: Path):
        conn = sqlite3.connect(str(db_path))
        p_count = conn.execute("SELECT COUNT(*) FROM jn_unit_products").fetchone()[0]
        b_count = conn.execute("SELECT COUNT(*) FROM jn_unit_bom_items").fetchone()[0]
        r_count = conn.execute("SELECT COUNT(*) FROM jn_unit_references").fetchone()[0]
        u_count = conn.execute(
            "SELECT COUNT(DISTINCT jn_unit_number) FROM jn_unit_bom_items"
        ).fetchone()[0]

        jn_numbers = set(
            r[0] for r in conn.execute("SELECT DISTINCT jn_number FROM jn_unit_products")
        )
        conn.close()

        existing_units = set(Unit.objects.values_list("j_and_n_number", flat=True))
        matched = len(jn_numbers & existing_units)

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"REPORT: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Unit products in staging:    {p_count:>10,}")
        self.stdout.write(f"  BOM line items:              {b_count:>10,}")
        self.stdout.write(f"  Units with BOM data:         {u_count:>10,}")
        self.stdout.write(f"  Reference entries:           {r_count:>10,}")
        self.stdout.write(f"  Units already in system:     {matched:>10,}")
        self.stdout.write(f"  Units not yet in system:     {len(jn_numbers) - matched:>10,}")
        self.stdout.write(f"  Existing BOMs in DB:         {BOM.objects.count():>10,}")
        self.stdout.write("")

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def _import(self, db_path: Path):
        self.stdout.write(f"\nImporting: {db_path.name}")
        self.stdout.write("-" * 60)
        t0 = time.time()

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # ----------------------------------------------------------------
        # Step 1: Build a BOM for every unit product
        # ----------------------------------------------------------------
        self.stdout.write("Step 1: Creating / updating BOM records...")
        t1 = time.time()

        # Build lookup of Unit by j_and_n_number
        unit_map = dict(
            Unit.objects.exclude(j_and_n_number="")
            .values_list("j_and_n_number", "pk")
        )

        products = conn.execute(
            "SELECT jn_number, description, unit_type, oem, voltage, power, "
            "amps, rotation, starter_type, num_teeth, status, category "
            "FROM jn_unit_products"
        ).fetchall()

        bom_created = 0
        bom_updated = 0
        # jn_number → BOM pk
        bom_map = {}

        for row in products:
            jn = row["jn_number"]
            unit_pk = unit_map.get(jn)
            desc = row["description"] or ""

            bom, created = BOM.objects.get_or_create(
                name=jn,
                defaults={
                    "description": desc,
                    "unit_id": unit_pk,
                },
            )
            # Update description / unit link if missing on an existing BOM
            if not created:
                changed = False
                if not bom.description and desc:
                    bom.description = desc
                    changed = True
                if bom.unit_id is None and unit_pk:
                    bom.unit_id = unit_pk
                    changed = True
                if changed:
                    bom.save(update_fields=["description", "unit_id"])
                    bom_updated += 1
            else:
                bom_created += 1

            bom_map[jn] = bom.pk

        self.stdout.write(
            f"  {bom_created:,} BOMs created, {bom_updated:,} updated  "
            f"({time.time() - t1:.1f}s)"
        )

        # ----------------------------------------------------------------
        # Step 2: Create Part + BOMItem records
        # ----------------------------------------------------------------
        self.stdout.write("Step 2: Creating Parts and BOM items...")
        t2 = time.time()

        total_bom_rows = conn.execute(
            "SELECT COUNT(*) FROM jn_unit_bom_items"
        ).fetchone()[0]

        # Pre-load existing Part numbers to minimise DB round-trips
        # Key: (j_and_n or oem_number) → Part pk
        existing_parts_jn = dict(
            Part.objects.exclude(j_and_n="").values_list("j_and_n", "pk")
        )
        existing_parts_oem = dict(
            Part.objects.exclude(oem_number="").values_list("oem_number", "pk")
        )

        cursor = conn.execute(
            "SELECT jn_unit_number, component_description, notes, qty, "
            "jn_number, jn_qty, oem_number, oem_qty, sort_order "
            "FROM jn_unit_bom_items "
            "ORDER BY jn_unit_number, sort_order"
        )

        bom_item_batch = []
        items_created = 0
        items_skipped = 0
        processed = 0

        for row in cursor:
            processed += 1
            jn_unit = row["jn_unit_number"]
            bom_pk = bom_map.get(jn_unit)
            if not bom_pk:
                items_skipped += 1
                continue

            part_jn  = (row["jn_number"]  or "").strip()
            part_oem = (row["oem_number"] or "").strip()
            comp_desc = (row["component_description"] or "").strip()

            # Determine the Part lookup key: J&N number preferred, OEM fallback
            if part_jn:
                part_key = part_jn
                lookup_field = "j_and_n"
                part_pk = existing_parts_jn.get(part_key)
            elif part_oem:
                part_key = part_oem
                lookup_field = "oem_number"
                part_pk = existing_parts_oem.get(part_key)
            else:
                items_skipped += 1
                continue

            # Create Part if it doesn't exist yet
            if part_pk is None:
                kwargs = {
                    "part_number": part_key,
                    "part_name": comp_desc,
                    lookup_field: part_key,
                }
                if lookup_field == "j_and_n" and part_oem:
                    kwargs["oem_number"] = part_oem
                if lookup_field == "oem_number" and part_jn:
                    kwargs["j_and_n"] = part_jn
                part, _ = Part.objects.get_or_create(
                    part_number=part_key,
                    defaults=kwargs,
                )
                part_pk = part.pk
                existing_parts_jn[part_jn] = part_pk if part_jn else None
                existing_parts_oem[part_oem] = part_pk if part_oem else None

            try:
                qty_int = int(row["qty"])
            except (TypeError, ValueError):
                qty_int = 1

            bom_item_batch.append(
                BOMItem(
                    bom_id=bom_pk,
                    part_id=part_pk,
                    description=comp_desc[:255],
                    notes=(row["notes"] or ""),
                    unit_qty=qty_int,
                    j_and_n=part_jn[:100],
                    oem_number=part_oem[:100],
                )
            )

            if len(bom_item_batch) >= BATCH_SIZE:
                BOMItem.objects.bulk_create(bom_item_batch, ignore_conflicts=True)
                items_created += len(bom_item_batch)
                bom_item_batch = []

            if processed % 50000 == 0:
                self.stdout.write(
                    f"  Progress: {processed:,}/{total_bom_rows:,} rows  |  "
                    f"{items_created:,} items created"
                )

        if bom_item_batch:
            BOMItem.objects.bulk_create(bom_item_batch, ignore_conflicts=True)
            items_created += len(bom_item_batch)

        self.stdout.write(
            f"  {items_created:,} BOM items created, {items_skipped:,} skipped  "
            f"({time.time() - t2:.1f}s)"
        )

        # ----------------------------------------------------------------
        # Step 3: CrossReferences from substitute / reference entries
        # ----------------------------------------------------------------
        self.stdout.write("Step 3: Creating CrossReference records...")
        t3 = time.time()

        # Full unit map for cross-ref linking
        all_unit_map = dict(Unit.objects.values_list("j_and_n_number", "pk"))

        ref_rows = conn.execute(
            "SELECT jn_unit_number, ref_type, manufacturer, ref_number "
            "FROM jn_unit_references"
        ).fetchall()

        xref_batch = []
        seen_xrefs = set()
        xrefs_created = 0
        xrefs_skipped = 0

        for row in ref_rows:
            jn_unit  = row["jn_unit_number"]
            ref_type = row["ref_type"]
            mfr      = (row["manufacturer"] or "").strip()
            ref_num  = (row["ref_number"]   or "").strip()

            if not ref_num:
                xrefs_skipped += 1
                continue

            unit_pk = all_unit_map.get(jn_unit)
            if not unit_pk:
                xrefs_skipped += 1
                continue

            # Map ref_type to a readable interchange_type label
            if ref_type == "substitute":
                itype = f"Substitute: {mfr}" if mfr else "Substitute"
            elif ref_type == "superseded_by":
                itype = "Superseded By"
            else:
                itype = f"Reference: {mfr}" if mfr else "Reference"

            dedup_key = (unit_pk, ref_num[:100], itype[:150])
            if dedup_key in seen_xrefs:
                xrefs_skipped += 1
                continue
            seen_xrefs.add(dedup_key)

            xref = CrossReference(
                unit_id=unit_pk,
                cross_ref_number=ref_num[:100],
                interchange_type=itype[:150],
            )
            # Link to another Unit if the ref_number matches one
            other_pk = all_unit_map.get(ref_num)
            if other_pk and other_pk != unit_pk:
                xref.cross_ref_unit_id = other_pk

            xref_batch.append(xref)

            if len(xref_batch) >= BATCH_SIZE:
                CrossReference.objects.bulk_create(xref_batch, ignore_conflicts=True)
                xrefs_created += len(xref_batch)
                xref_batch = []

        if xref_batch:
            CrossReference.objects.bulk_create(xref_batch, ignore_conflicts=True)
            xrefs_created += len(xref_batch)

        self.stdout.write(
            f"  {xrefs_created:,} cross-references created, "
            f"{xrefs_skipped:,} skipped  ({time.time() - t3:.1f}s)"
        )

        conn.close()
        elapsed = time.time() - t0

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"IMPORT COMPLETE: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  BOMs created:                {bom_created:>10,}")
        self.stdout.write(f"  BOM items created:           {items_created:>10,}")
        self.stdout.write(f"  Cross-references created:    {xrefs_created:>10,}")
        self.stdout.write(f"  Total time:                  {elapsed:>10.1f}s")
        self.stdout.write("")
        self.stdout.write(
            f"  DB totals: {BOM.objects.count():,} BOMs, "
            f"{BOMItem.objects.count():,} BOM items, "
            f"{CrossReference.objects.count():,} cross-references"
        )
        self.stdout.write("")
