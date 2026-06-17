"""
Import YouTech interchange data from a staging DB into the Django catalog.

Staging DBs are produced by the PDF parsers in data_import/pdf_parsers/.
Each staging DB has a table `interchange_by_mfr` with columns:
    manufacturer, their_number, our_number, page_number

For each our_number the command resolves the target in priority order:
  1. Unit.unit_number  -> CrossReference on that Unit
  2. Part.yt_number    -> PartInterchange on that Part
  3. Unit.yt_number    -> CrossReference on the matching Unit
  4. (not found)       -> creates a new bare Unit, then CrossReference

Usage:
    python manage.py import_youtech_interchange --file "data_import/staging_dbs/1-Interchange by Mfr.db"
    python manage.py import_youtech_interchange --all
    python manage.py import_youtech_interchange --file "..." --report-only
"""

import sqlite3
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from catalog.models import CrossReference, Part, PartInterchange, Unit


BATCH_SIZE = 5000

BOGUS_MANUFACTURERS = {
    "Model Number",
}

# PDF parsers sometimes split multi-word manufacturer names across lines.
# Map known fragments to their correct full name.
MFR_NORMALIZE = {
    "United":           "United Technologies",
    "Technologies":     "United Technologies",
    "Products":         "Remy Power Products",
    "Service":          "Electric Motor Service",
    "Supplies":         "Wood Auto Supplies",
    "CARGO":            "HC CARGO",
    "CARG":             "HC CARGO",
    "Hc Cargo":         "HC CARGO",
    "America":          "Daimler Truck North America",
    "North America":    "Daimler Truck North America",
    "Agriculture":      "New Holland Agriculture",
    "Construction":     "New Holland Construction",
    "Solutions":        "NAPA Heavy Duty Solutions",
    "Remy Power":       "Remy Power Products",
    "Electric Motor":   "Electric Motor Service",
    "Electric":         "Romaine Electric",
    "Manufacturing":    "Wells Manufacturing",
    "Delco- Remy":      "Delco-Remy",
    "Leece- Neville":   "Leece-Neville",
    "Thermo- King":     "Thermo-King",
    "Atlas- Copco":     "Atlas-Copco",
    "All- Tek":         "All-Tek",
    "Tecumseh/Laus on": "Tecumseh/Lauson",
}

KNOWN_TABLES = (
    "interchange_by_mfr",
    "interchange_by_number",
    "our_numbers_to_others",
    "buyers_guide_interchanges",
)


def _find_interchange_table(conn):
    """Auto-detect the interchange table name in the staging DB."""
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for t in KNOWN_TABLES:
        if t in tables:
            return t
    if tables:
        return tables[0]
    return None


class Command(BaseCommand):
    help = "Import YouTech interchange staging DBs into the catalog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=None,
            help="Path to a specific staging DB to import",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Import all staging DBs in data_import/staging_dbs/",
        )
        parser.add_argument(
            "--report-only",
            action="store_true",
            dest="report_only",
            help="Show what would be imported without making changes",
        )
        parser.add_argument(
            "--clear-xrefs",
            action="store_true",
            dest="clear_xrefs",
            help="Clear all existing CrossReference records before import",
        )

    def handle(self, *args, **options):
        staging_dir = Path(settings.BASE_DIR) / "data_import" / "staging_dbs"

        if options["file"]:
            files = [Path(options["file"])]
        elif options["all"]:
            files = sorted(staging_dir.glob("*.db"))
        else:
            self.stderr.write(self.style.ERROR("Specify --file <path> or --all"))
            return

        if not files:
            self.stderr.write(self.style.ERROR("No staging DB files found."))
            return

        for f in files:
            if not f.exists():
                self.stderr.write(self.style.ERROR(f"File not found: {f}"))
                return

        if options["report_only"]:
            for f in files:
                self._report(f)
            return

        if options["clear_xrefs"]:
            count = CrossReference.objects.count()
            CrossReference.objects.all().delete()
            self.stdout.write(f"Cleared {count:,} existing CrossReference records.")

        for f in files:
            self._import_file(f)

    def _report(self, db_path: Path):
        """Show summary of what the staging DB contains."""
        conn = sqlite3.connect(str(db_path))
        table = _find_interchange_table(conn)
        if not table:
            self.stderr.write(self.style.ERROR(f"No interchange table found in {db_path}"))
            conn.close()
            return

        total = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
        unique_our = conn.execute(f"SELECT COUNT(DISTINCT our_number) FROM [{table}]").fetchone()[0]
        unique_their = conn.execute(f"SELECT COUNT(DISTINCT their_number) FROM [{table}]").fetchone()[0]
        unique_mfr = conn.execute(f"SELECT COUNT(DISTINCT manufacturer) FROM [{table}]").fetchone()[0]

        our_numbers = set(
            r[0] for r in conn.execute(f"SELECT DISTINCT our_number FROM [{table}]")
        )
        existing_set = set(Unit.objects.values_list("unit_number", flat=True))
        part_yt_set = set(
            Part.objects.exclude(yt_number="").values_list("yt_number", flat=True)
        )
        unit_yt_set = set(
            Unit.objects.exclude(yt_number="").values_list("yt_number", flat=True)
        )
        remaining = our_numbers - existing_set
        existing_units = len(our_numbers & existing_set)
        routed_to_parts = len(remaining & part_yt_set)
        remaining -= part_yt_set
        matched_unit_yt = len(remaining & unit_yt_set)
        remaining -= unit_yt_set
        new_units = len(remaining)

        conn.close()

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"REPORT: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Total interchange records:   {total:>10,}")
        self.stdout.write(f"  Unique manufacturers:        {unique_mfr:>10,}")
        self.stdout.write(f"  Unique 'their' numbers:      {unique_their:>10,}")
        self.stdout.write(f"  Unique YouTech numbers:      {unique_our:>10,}")
        self.stdout.write(f"  Units already in system:     {existing_units:>10,}")
        self.stdout.write(f"  Routed to Parts:             {routed_to_parts:>10,}")
        self.stdout.write(f"  Matched Unit (by YT#):       {matched_unit_yt:>10,}")
        self.stdout.write(f"  New units to create:         {new_units:>10,}")
        self.stdout.write("")

    def _import_file(self, db_path: Path):
        """Import one staging DB into the catalog."""
        self.stdout.write(f"\nImporting: {db_path.name}")
        self.stdout.write("-" * 60)
        t0 = time.time()

        conn = sqlite3.connect(str(db_path))
        table = _find_interchange_table(conn)
        if not table:
            self.stderr.write(self.style.ERROR(f"No interchange table found in {db_path}"))
            conn.close()
            return

        # --- Step 1: Resolve our_numbers to Units or Parts ---
        self.stdout.write("Step 1: Resolving our_numbers to Units / Parts...")
        t1 = time.time()

        our_numbers = [
            r[0] for r in conn.execute(f"SELECT DISTINCT our_number FROM [{table}]")
        ]

        existing_unit_numbers = set(Unit.objects.values_list("unit_number", flat=True))
        part_yt_map = dict(
            Part.objects.exclude(yt_number="").values_list("yt_number", "pk")
        )
        unit_yt_map = dict(
            Unit.objects.exclude(yt_number="").values_list("yt_number", "pk")
        )

        unmatched = []
        routed_to_part = []
        routed_to_unit_yt = []
        for num in our_numbers:
            if num in existing_unit_numbers:
                continue
            if num in part_yt_map:
                routed_to_part.append(num)
            elif num in unit_yt_map:
                routed_to_unit_yt.append(num)
            else:
                unmatched.append(num)

        self.stdout.write(
            f"  Already a Unit:     {len(existing_unit_numbers & set(our_numbers)):,}\n"
            f"  Routed to Part:     {len(routed_to_part):,}\n"
            f"  Matched Unit (YT):  {len(routed_to_unit_yt):,}\n"
            f"  Unmatched (skip):   {len(unmatched):,}  "
            f"({time.time() - t1:.1f}s)"
        )

        # --- Build unit_number -> pk lookup ---
        self.stdout.write("  Building lookups...")
        unit_map = dict(Unit.objects.values_list("unit_number", "pk"))

        # --- Step 1b: Update descriptions if available ---
        has_desc = False
        try:
            conn.execute(f"SELECT description FROM [{table}] LIMIT 1")
            has_desc = True
        except sqlite3.OperationalError:
            pass

        if has_desc:
            self.stdout.write("  Updating unit descriptions from staging data...")
            desc_cursor = conn.execute(
                f"SELECT our_number, description FROM [{table}] "
                f"WHERE description IS NOT NULL AND description != '' "
                f"GROUP BY our_number"
            )
            desc_updated = 0
            for our_no, desc in desc_cursor:
                pk = unit_map.get(our_no)
                if pk and desc.strip():
                    updated = Unit.objects.filter(pk=pk, description="").update(
                        description=desc.strip()
                    )
                    desc_updated += updated
            self.stdout.write(f"  {desc_updated:,} unit descriptions updated")

        # --- Step 2: Create CrossReference + PartInterchange records ---
        self.stdout.write("Step 2: Creating interchange records...")
        total_rows = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
        cursor = conn.execute(
            f"SELECT manufacturer, their_number, our_number FROM [{table}]"
        )

        # Dedup sets for CrossReference and PartInterchange
        xref_batch = []
        xref_seen = set(
            CrossReference.objects.values_list(
                "unit_id", "cross_ref_number", "interchange_type"
            )
        )

        pi_batch = []
        pi_seen = set(
            PartInterchange.objects.values_list(
                "part_id", "interchange_number", "source_name"
            )
        )

        part_route_set = set(routed_to_part)
        unit_yt_route_set = set(routed_to_unit_yt)

        self.stdout.write(
            f"  Pre-loaded {len(xref_seen):,} existing xrefs, "
            f"{len(pi_seen):,} existing part-interchanges"
        )
        xref_created = 0
        pi_created = 0
        skipped_dup = 0
        skipped_no_target = 0
        skipped_bogus_mfr = 0
        processed = 0

        for mfr, their_no, our_no in cursor:
            processed += 1
            mfr = MFR_NORMALIZE.get(mfr, mfr)

            if mfr in BOGUS_MANUFACTURERS:
                skipped_bogus_mfr += 1
                continue

            if our_no in part_route_set:
                # Route to PartInterchange
                part_pk = part_yt_map[our_no]
                key = (part_pk, their_no[:100], mfr[:150])
                if key in pi_seen:
                    skipped_dup += 1
                    continue
                pi_seen.add(key)
                pi_batch.append(
                    PartInterchange(
                        part_id=part_pk,
                        interchange_number=their_no[:100],
                        source_name=mfr[:150],
                    )
                )
                if len(pi_batch) >= BATCH_SIZE:
                    PartInterchange.objects.bulk_create(
                        pi_batch, ignore_conflicts=True
                    )
                    pi_created += len(pi_batch)
                    pi_batch = []
            else:
                # Route to CrossReference on the Unit (by unit_number or yt_number)
                unit_pk = unit_map.get(our_no)
                if not unit_pk and our_no in unit_yt_route_set:
                    unit_pk = unit_yt_map.get(our_no)
                if not unit_pk:
                    skipped_no_target += 1
                    continue

                key = (unit_pk, their_no[:100], mfr[:150])
                if key in xref_seen:
                    skipped_dup += 1
                    continue
                xref_seen.add(key)

                other_unit_pk = unit_map.get(their_no)
                xref = CrossReference(
                    unit_id=unit_pk,
                    cross_ref_number=their_no[:100],
                    interchange_type=mfr[:150],
                )
                if other_unit_pk and other_unit_pk != unit_pk:
                    xref.cross_ref_unit_id = other_unit_pk

                xref_batch.append(xref)
                if len(xref_batch) >= BATCH_SIZE:
                    CrossReference.objects.bulk_create(
                        xref_batch, ignore_conflicts=True
                    )
                    xref_created += len(xref_batch)
                    xref_batch = []

            if processed % 200000 == 0:
                self.stdout.write(
                    f"  Progress: {processed:,}/{total_rows:,} rows  |  "
                    f"xrefs {xref_created:,}  |  part-ix {pi_created:,}"
                )

        if xref_batch:
            CrossReference.objects.bulk_create(xref_batch, ignore_conflicts=True)
            xref_created += len(xref_batch)
        if pi_batch:
            PartInterchange.objects.bulk_create(pi_batch, ignore_conflicts=True)
            pi_created += len(pi_batch)

        conn.close()
        elapsed = time.time() - t0

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"IMPORT COMPLETE: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  CrossReferences created:     {xref_created:>10,}")
        self.stdout.write(f"  PartInterchanges created:    {pi_created:>10,}")
        self.stdout.write(f"  Duplicates skipped:          {skipped_dup:>10,}")
        self.stdout.write(f"  Bogus manufacturer skipped:  {skipped_bogus_mfr:>10,}")
        self.stdout.write(f"  No target found (skipped):   {skipped_no_target:>10,}")
        self.stdout.write(f"  Total time:                  {elapsed:>10.1f}s")
        self.stdout.write("")

        db_unit_count = Unit.objects.count()
        db_xref_count = CrossReference.objects.count()
        db_pi_count = PartInterchange.objects.count()
        self.stdout.write(
            f"  Database totals: {db_unit_count:,} units, "
            f"{db_xref_count:,} cross-refs, "
            f"{db_pi_count:,} part-interchanges"
        )
        self.stdout.write("")
