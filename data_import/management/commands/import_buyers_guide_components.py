"""Import buyers-guide component rows into canonical Part records.

Handles component/part data from the Components Buyers Guide staging DB,
creating Part records, PartInterchange records, and linking Parts to Units.
"""

import json
import sqlite3
import time
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from catalog.models import (
    Part,
    PartInterchange,
    Unit,
)
from data_import.import_utils import normalize_space


ATTR_FIELD_MAP = {
    "manufacture": "oem",
    "oe_manufacturer": "oem",
    "voltage": "voltage",
    "rotation": None,
    "series": None,
}

ALL_MODEL_UPDATE_FIELDS = [
    "yt_number", "j_and_n", "part_name", "oem", "voltage",
    "specifications",
]


class Command(BaseCommand):
    help = "Import buyers-guide component rows into Part records keyed by YouTech number."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file", type=str, default=None,
            help="Path to the components staging DB",
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
            "--only-step", type=int, default=None, dest="only_step",
            help="Run only a specific step (1-5).",
        )

    def handle(self, *args, **options):
        import sys
        sys.stdout.reconfigure(line_buffering=True)

        db_path = self._resolve_db_path(options.get("file"))
        if not db_path.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {db_path}"))
            return

        if options["report_only"]:
            self._report(db_path)
            return

        if options["preview"]:
            self._preview(db_path, options.get("limit"))
            return

        self._import(db_path, options.get("limit"), options.get("only_step"))

    def _resolve_db_path(self, explicit_path):
        if explicit_path:
            return Path(explicit_path)
        return Path(settings.BASE_DIR) / "data_import" / "staging_dbs" / "14-Buyers Guide Components.db"

    def _load_rows(self, conn):
        conn.row_factory = sqlite3.Row
        cols = [r[1] for r in conn.execute("PRAGMA table_info(component_products)")]
        return conn.execute(
            f"SELECT {', '.join(cols)} FROM component_products ORDER BY youtech_number"
        ).fetchall()

    def _report(self, db_path: Path):
        conn = sqlite3.connect(str(db_path))
        product_count = conn.execute("SELECT COUNT(*) FROM component_products").fetchone()[0]
        unique_parts = conn.execute(
            "SELECT COUNT(DISTINCT youtech_number) FROM component_products WHERE youtech_number != ''"
        ).fetchone()[0]
        youtech_numbers = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT youtech_number FROM component_products WHERE youtech_number != ''"
            )
        }
        xref_count = conn.execute("SELECT COUNT(*) FROM component_interchanges").fetchone()[0]
        link_count = conn.execute("SELECT COUNT(*) FROM component_unit_links").fetchone()[0]

        try:
            img_count = conn.execute("SELECT COUNT(*) FROM component_images").fetchone()[0]
        except sqlite3.OperationalError:
            img_count = 0

        conn.close()

        existing_parts = Part.objects.filter(yt_number__in=youtech_numbers).count()
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"REPORT: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Staged component rows:       {product_count:>10,}")
        self.stdout.write(f"  Unique YT numbers:           {unique_parts:>10,}")
        self.stdout.write(f"  Existing Part records:       {existing_parts:>10,}")
        self.stdout.write(f"  New Part records:            {unique_parts - existing_parts:>10,}")
        self.stdout.write(f"  Interchange records:         {xref_count:>10,}")
        self.stdout.write(f"  Unit link records:           {link_count:>10,}")
        self.stdout.write(f"  Component images:            {img_count:>10,}")
        self.stdout.write("")

    def _preview(self, db_path: Path, limit=None):
        conn = sqlite3.connect(str(db_path))
        rows = self._load_rows(conn)

        # Load a few unit links for preview
        unit_links = {}
        try:
            for row in conn.execute(
                "SELECT component_yt, unit_yt FROM component_unit_links"
            ).fetchall():
                unit_links.setdefault(row[0], []).append(row[1])
        except sqlite3.OperationalError:
            pass

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

        existing_parts = {
            p.yt_number: p
            for p in Part.objects.filter(
                yt_number__in=[normalize_space(r["youtech_number"]) for r in sample]
            )
        }

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"PREVIEW (no changes saved)")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Total unique YT numbers: {len(seen):,}")
        if limit:
            self.stdout.write(f"  Limit applied: first {limit}")
        self.stdout.write("")

        for row in sample:
            yt = normalize_space(row["youtech_number"])
            part = existing_parts.get(yt)
            status = "UPDATE" if part else "CREATE"
            self.stdout.write(f"\n--- YT #{yt} [{status}] ---")
            self.stdout.write(f"  part_name:         {row['part_name']}")
            if row["jn_number"]:
                current_jn = part.j_and_n if part else ""
                action = "SKIP (has value)" if current_jn else "SET"
                self.stdout.write(f"  j_and_n:           {row['jn_number']:<30s}  [{action}]")
            if row["manufacture"]:
                self.stdout.write(f"  manufacture:       {row['manufacture']}")
            if row["oe_manufacturer"]:
                self.stdout.write(f"  oe_manufacturer:   {row['oe_manufacturer']}")
            if row["voltage"]:
                self.stdout.write(f"  voltage:           {row['voltage']}")
            if row["rotation"]:
                self.stdout.write(f"  rotation:          {row['rotation']}")
            if row["series"]:
                self.stdout.write(f"  series:            {row['series']}")
            if row["attributes_json"]:
                extra = json.loads(row["attributes_json"])
                for k, v in list(extra.items())[:5]:
                    self.stdout.write(f"  spec.{k:<14s} {v}")
                if len(extra) > 5:
                    self.stdout.write(f"  ... and {len(extra) - 5} more specs")

            links = unit_links.get(yt, [])
            if links:
                shown = links[:10]
                self.stdout.write(f"  unit links:        {', '.join(shown)}")
                if len(links) > 10:
                    self.stdout.write(f"                     ... and {len(links) - 10} more")

        self.stdout.write("")
        self.stdout.write("Run without --preview to import.")

    def _import(self, db_path: Path, limit=None, only_step=None):
        self.stdout.write(f"\nImporting: {db_path.name}")
        if only_step:
            self.stdout.write(f"  Running ONLY step {only_step}")
        self.stdout.write("-" * 60)
        start = time.time()

        conn = sqlite3.connect(str(db_path))
        rows = self._load_rows(conn)

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
            self.stdout.write("No staged component rows found.")
            conn.close()
            return

        existing_parts = {
            normalize_space(p.yt_number): p
            for p in Part.objects.filter(yt_number__in=youtech_numbers)
        }

        def should_run(step):
            return only_step is None or only_step == step

        # --- Step 1: Create new Part records ---
        created_parts = []
        if should_run(1):
            self.stdout.write("Step 1: Creating new Part records...")
            for row in unique_rows:
                yt = normalize_space(row["youtech_number"])
                if yt in existing_parts:
                    continue
                name_val = normalize_space(row["part_name"])
                if "|" in name_val:
                    name_val = ""
                part = Part(
                    yt_number=yt[:100],
                    part_name=name_val[:255],
                    notes=name_val,
                )
                created_parts.append(part)

            if created_parts:
                Part.objects.bulk_create(created_parts, batch_size=500)
                existing_parts = {
                    normalize_space(p.yt_number): p
                    for p in Part.objects.filter(yt_number__in=youtech_numbers)
                }
            self.stdout.write(f"  {len(created_parts):,} new parts created")
        else:
            self.stdout.write("Step 1: SKIPPED")

        # --- Step 2: Update attributes ---
        updated_count = 0
        if should_run(2):
            self.stdout.write("Step 2: Updating part attributes...")
            for row in unique_rows:
                yt = normalize_space(row["youtech_number"])
                part = existing_parts.get(yt)
                if not part:
                    continue

                changed = False
                specs = dict(part.specifications or {})

                if not part.yt_number:
                    part.yt_number = yt[:100]
                    changed = True

                # Part name + description
                name_val = normalize_space(row["part_name"])
                if name_val and "|" not in name_val and not part.part_name:
                    part.part_name = name_val[:255]
                    changed = True

                # J&N number
                jn_val = normalize_space(row["jn_number"])
                if jn_val and not part.j_and_n:
                    part.j_and_n = jn_val[:100]
                    changed = True

                # Manufacture → oem
                mfr_val = normalize_space(row["manufacture"])
                if mfr_val and not part.oem:
                    part.oem = mfr_val[:200]
                    changed = True

                # OE Manufacturer → oem (if manufacture didn't set it)
                oe_val = normalize_space(row["oe_manufacturer"])
                if oe_val and not part.oem:
                    part.oem = oe_val[:200]
                    changed = True

                # Voltage
                volt_val = normalize_space(row["voltage"])
                if volt_val and not part.voltage:
                    part.voltage = volt_val[:50]
                    changed = True

                # Specs from known columns
                for col in ("rotation", "series"):
                    val = normalize_space(row[col]) if col in row.keys() else ""
                    if val and not specs.get(col):
                        specs[col] = val
                        changed = True

                # Extra attributes JSON → specs
                attrs_json = row["attributes_json"]
                if attrs_json:
                    try:
                        extra = json.loads(attrs_json)
                        for k, v in extra.items():
                            if v and not specs.get(k):
                                specs[k] = v
                                changed = True
                    except (json.JSONDecodeError, TypeError):
                        pass

                if changed:
                    part.specifications = specs
                    updated_count += 1

            if updated_count:
                Part.objects.bulk_update(
                    [p for p in existing_parts.values()],
                    ALL_MODEL_UPDATE_FIELDS,
                    batch_size=500,
                )
            self.stdout.write(f"  {updated_count:,} parts updated")
        else:
            self.stdout.write("Step 2: SKIPPED")

        # --- Step 3: Import interchanges ---
        xref_created = 0
        if should_run(3):
            self.stdout.write("Step 3: Importing interchanges...")
            xref_created = self._import_interchanges(conn, existing_parts)
            self.stdout.write(f"  {xref_created:,} new part interchanges created")
        else:
            self.stdout.write("Step 3: SKIPPED")

        # --- Step 4: Link parts to units ---
        links_created = 0
        if should_run(4):
            self.stdout.write("Step 4: Linking parts to units...")
            links_created = self._import_unit_links(conn, existing_parts)
            self.stdout.write(f"  {links_created:,} part-unit links created")
        else:
            self.stdout.write("Step 4: SKIPPED")

        # --- Step 5: Import images ---
        img_saved = 0
        if should_run(5):
            self.stdout.write("Step 5: Importing images...")
            img_saved = self._import_images(conn, existing_parts)
            self.stdout.write(f"  {img_saved:,} part images saved")
        else:
            self.stdout.write("Step 5: SKIPPED")

        conn.close()
        elapsed = time.time() - start

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"IMPORT COMPLETE: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Parts created:              {len(created_parts):>10,}")
        self.stdout.write(f"  Parts updated:              {updated_count:>10,}")
        self.stdout.write(f"  Interchanges created:       {xref_created:>10,}")
        self.stdout.write(f"  Unit links created:         {links_created:>10,}")
        self.stdout.write(f"  Images saved:               {img_saved:>10,}")
        self.stdout.write(f"  Total time:                 {elapsed:>10.1f}s")
        self.stdout.write("")

    def _import_interchanges(self, conn, existing_parts):
        try:
            rows = conn.execute(
                "SELECT manufacturer, their_number, our_number "
                "FROM component_interchanges"
            ).fetchall()
        except sqlite3.OperationalError:
            return 0

        our_numbers_in_scope = set(existing_parts.keys())
        part_map = {normalize_space(p.yt_number): p.pk for p in existing_parts.values()}

        existing_xrefs = set()
        for part in existing_parts.values():
            for xi in PartInterchange.objects.filter(part=part).values_list(
                "interchange_number", "source_name"
            ):
                existing_xrefs.add((part.pk, xi[0], xi[1]))

        batch = []
        created = 0
        for mfr, their_no, our_no in rows:
            our_no = normalize_space(our_no)
            if our_no not in our_numbers_in_scope:
                continue
            part_pk = part_map.get(our_no)
            if not part_pk:
                continue

            mfr = normalize_space(mfr)[:150]
            their_no = normalize_space(their_no)[:100]
            if not their_no:
                continue

            dedup_key = (part_pk, their_no, mfr)
            if dedup_key in existing_xrefs:
                continue
            existing_xrefs.add(dedup_key)

            batch.append(PartInterchange(
                part_id=part_pk,
                interchange_number=their_no,
                source_name=mfr,
            ))

            if len(batch) >= 2000:
                PartInterchange.objects.bulk_create(batch, ignore_conflicts=True)
                created += len(batch)
                batch = []

        if batch:
            PartInterchange.objects.bulk_create(batch, ignore_conflicts=True)
            created += len(batch)

        return created

    def _import_unit_links(self, conn, existing_parts):
        try:
            rows = conn.execute(
                "SELECT component_yt, unit_yt FROM component_unit_links"
            ).fetchall()
        except sqlite3.OperationalError:
            return 0

        our_numbers_in_scope = set(existing_parts.keys())

        # Build unit lookup
        unit_numbers_needed = {normalize_space(r[1]) for r in rows}
        unit_map = {}
        chunk_size = 500
        unit_list = sorted(unit_numbers_needed)
        for i in range(0, len(unit_list), chunk_size):
            chunk = unit_list[i:i + chunk_size]
            for u in Unit.objects.filter(unit_number__in=chunk).only("pk", "unit_number"):
                unit_map[normalize_space(u.unit_number)] = u.pk

        # Pre-load existing links for parts in scope
        existing_links = set()
        for part in existing_parts.values():
            for unit_pk in part.units.values_list("pk", flat=True):
                existing_links.add((part.pk, unit_pk))

        created = 0
        # Group by component to use bulk through-model creation
        from django.db import connection as django_conn
        through_model = Part.units.through
        batch = []

        for comp_yt_raw, unit_yt_raw in rows:
            comp_yt = normalize_space(comp_yt_raw)
            unit_yt = normalize_space(unit_yt_raw)

            if comp_yt not in our_numbers_in_scope:
                continue
            part = existing_parts.get(comp_yt)
            if not part:
                continue

            unit_pk = unit_map.get(unit_yt)
            if not unit_pk:
                continue

            link_key = (part.pk, unit_pk)
            if link_key in existing_links:
                continue
            existing_links.add(link_key)

            batch.append(through_model(part_id=part.pk, unit_id=unit_pk))
            created += 1

            if len(batch) >= 2000:
                through_model.objects.bulk_create(batch, ignore_conflicts=True)
                batch = []

        if batch:
            through_model.objects.bulk_create(batch, ignore_conflicts=True)

        return created

    def _import_images(self, conn, existing_parts):
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM component_images"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            return 0

        if count == 0:
            return 0

        saved = 0
        processed = 0
        cursor = conn.execute(
            "SELECT youtech_number, image_data, image_ext FROM component_images"
        )

        for yt_raw, image_data, image_ext in cursor:
            yt = normalize_space(yt_raw)
            part = existing_parts.get(yt)
            processed += 1

            if not part:
                continue

            ext = image_ext.lower().strip(".")
            if ext == "jpeg":
                ext = "jpg"
            filename = f"{yt}.{ext}"
            part.image.save(filename, ContentFile(image_data), save=True)
            saved += 1

            if saved % 200 == 0:
                self.stdout.write(
                    f"    Image progress: {saved:,} saved ({processed:,}/{count:,} checked)"
                )

        return saved
