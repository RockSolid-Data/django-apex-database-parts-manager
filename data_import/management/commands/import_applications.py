"""
Import application data from staging DBs into the Django catalog.

Staging DBs are produced by parse_applications.py and contain an
`applications` table with columns:
    unit_type, make, model, year, engine, options, mfr, amp, volt,
    part_number, other_number, page_number

This command:
  1. Creates one Application per unique (make, model, engine).
  2. Combines year ranges (e.g. "76-80 | 81-91") and options across rows.
  3. Creates Unit records (unit_number = part_number) for any part numbers
     not already in the system, tagged with the unit type (e.g. Alternator).
  4. Links Applications to Units via ApplicationUnit.

Usage:
    python manage.py import_applications --file "data_import/staging_dbs/4- Applications Alts.db" --preview
    python manage.py import_applications --file "data_import/staging_dbs/4- Applications Alts.db"
    python manage.py import_applications --all
    python manage.py import_applications --file "..." --report-only
"""

import os
import sqlite3
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from catalog.models import Application, ApplicationUnit, Unit


BATCH_SIZE = 2000


class Command(BaseCommand):
    help = "Import application staging DBs into the catalog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file", type=str, default=None,
            help="Path to a specific staging DB to import",
        )
        parser.add_argument(
            "--all", action="store_true",
            help="Import all staging DBs that have an 'applications' table",
        )
        parser.add_argument(
            "--report-only", action="store_true", dest="report_only",
            help="Show what would be imported without making changes",
        )
        parser.add_argument(
            "--preview", action="store_true",
            help="Show a summary + 10 sample rows of what would be imported, without saving",
        )

    def handle(self, *args, **options):
        staging_dir = Path(settings.BASE_DIR) / "data_import" / "staging_dbs"

        if options["file"]:
            files = [Path(options["file"])]
        elif options["all"]:
            files = sorted(staging_dir.glob("*.db"))
            files = [f for f in files if self._has_applications_table(f)]
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

        if options["preview"]:
            for f in files:
                self._preview(f)
            return

        for f in files:
            self._import_file(f)

    def _has_applications_table(self, db_path):
        try:
            conn = sqlite3.connect(str(db_path))
            tables = [
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            ]
            conn.close()
            return "applications" in tables
        except Exception:
            return False

    def _col_names(self, conn):
        """Return the column names of the applications table."""
        cur = conn.execute("PRAGMA table_info(applications)")
        return [row[1] for row in cur.fetchall()]

    def _has_split_columns(self, conn):
        """True if the staging DB has separate engine + options columns (new format)."""
        return "engine" in self._col_names(conn) and "options" in self._col_names(conn)

    def _report(self, db_path):
        conn = sqlite3.connect(str(db_path))
        total = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        unique_parts = conn.execute(
            "SELECT COUNT(DISTINCT part_number) FROM applications WHERE part_number != ''"
        ).fetchone()[0]
        unique_makes = conn.execute(
            "SELECT COUNT(DISTINCT make) FROM applications"
        ).fetchone()[0]
        unit_type = (conn.execute(
            "SELECT DISTINCT unit_type FROM applications LIMIT 1"
        ).fetchone() or ("",))[0]

        part_numbers = set(
            r[0] for r in conn.execute(
                "SELECT DISTINCT part_number FROM applications WHERE part_number != ''"
            )
        )
        existing_units = set(Unit.objects.values_list("unit_number", flat=True))
        matched = len(part_numbers & existing_units)

        conn.close()

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"REPORT: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Unit type:                   {unit_type}")
        self.stdout.write(f"  Total application records:   {total:>10,}")
        self.stdout.write(f"  Unique makes:                {unique_makes:>10,}")
        self.stdout.write(f"  Unique part numbers:         {unique_parts:>10,}")
        self.stdout.write(f"  Parts matched to units:      {matched:>10,}")
        self.stdout.write(f"  Parts not in system:         {unique_parts - matched:>10,}")
        self.stdout.write("")

    def _preview(self, db_path):
        """Show a dry-run summary and 10 sample rows without saving anything."""
        conn = sqlite3.connect(str(db_path))
        split = self._has_split_columns(conn)

        total = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        no_part = conn.execute(
            "SELECT COUNT(*) FROM applications WHERE part_number = ''"
        ).fetchone()[0]
        unit_type_val = (conn.execute(
            "SELECT DISTINCT unit_type FROM applications LIMIT 1"
        ).fetchone() or ("",))[0]

        part_numbers = set(
            r[0] for r in conn.execute(
                "SELECT DISTINCT part_number FROM applications WHERE part_number != ''"
            )
        )
        existing_units = set(
            Unit.objects.filter(unit_number__in=part_numbers).values_list("unit_number", flat=True)
        )

        if split:
            unique_app_keys = set(
                conn.execute(
                    "SELECT DISTINCT make, model, engine FROM applications WHERE part_number != ''"
                ).fetchall()
            )
        else:
            unique_app_keys = set(
                conn.execute(
                    "SELECT DISTINCT make, model FROM applications WHERE part_number != ''"
                ).fetchall()
            )

        units_new = part_numbers - existing_units
        units_matched = part_numbers & existing_units

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"PREVIEW (no changes saved): {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Unit type:                               {unit_type_val}")
        self.stdout.write(f"  Total rows in staging DB:                {total:>10,}")
        self.stdout.write(f"  Rows with no part number (skip):         {no_part:>10,}")
        key_desc = "one per make+model+engine" if split else "one per make+model"
        self.stdout.write(f"  Unique Applications to create:           {len(unique_app_keys):>10,}  ({key_desc})")
        self.stdout.write(f"  Unique part numbers:                     {len(part_numbers):>10,}")
        self.stdout.write(f"    Already in system (match only):        {len(units_matched):>10,}")
        self.stdout.write(f"    New units to create:                   {len(units_new):>10,}")
        self.stdout.write("")

        if split:
            sample = conn.execute(
                "SELECT make, model, engine, options, year, mfr, amp, volt, part_number "
                "FROM applications WHERE part_number != '' LIMIT 10"
            ).fetchall()
            self.stdout.write("Sample rows (first 10 with a part number):")
            self.stdout.write(
                f"  {'Make':<15} {'Model':<18} {'Engine':<20} {'Options':<12} "
                f"{'Year':<8} {'Mfr':<8} {'Amp':<5} {'Volt':<5} {'Part #':<10} {'Unit?'}"
            )
            self.stdout.write("  " + "-" * 120)
            for make, model, eng, opts, year, mfr, amp, volt, part_no in sample:
                exists = "YES" if part_no in existing_units else "NEW"
                self.stdout.write(
                    f"  {make:<15} {model:<18} {eng:<20} {opts:<12} "
                    f"{year:<8} {mfr:<8} {amp:<5} {volt:<5} {part_no:<10} {exists}"
                )
        else:
            sample = conn.execute(
                "SELECT make, model, year, engine_options, mfr, amp, volt, part_number "
                "FROM applications WHERE part_number != '' LIMIT 10"
            ).fetchall()
            self.stdout.write("Sample rows (first 10 with a part number):")
            self.stdout.write(
                f"  {'Make':<18} {'Model':<18} {'Year':<8} {'Engine/Options':<16} "
                f"{'Mfr':<10} {'Amp':<5} {'Volt':<5} {'Part #':<10} {'Unit?'}"
            )
            self.stdout.write("  " + "-" * 110)
            for make, model, year, eng_opts, mfr, amp, volt, part_no in sample:
                exists = "YES" if part_no in existing_units else "NEW"
                self.stdout.write(
                    f"  {make:<18} {model:<18} {year:<8} {eng_opts:<16} "
                    f"{mfr:<10} {amp:<5} {volt:<5} {part_no:<10} {exists}"
                )

        conn.close()
        self.stdout.write("")
        self.stdout.write(
            "Run without --preview to import. "
            "Run with --report-only for basic stats only."
        )
        self.stdout.write("")

    def _import_file(self, db_path):
        self.stdout.write(f"\nImporting: {db_path.name}")
        self.stdout.write("-" * 60)
        t0 = time.time()

        conn = sqlite3.connect(str(db_path))
        split = self._has_split_columns(conn)

        if not split:
            self.stderr.write(self.style.WARNING(
                "  WARNING: This staging DB uses the old schema (engine_options combined). "
                "Re-parse the PDF to get separate engine + options columns."
            ))

        # Build unit lookup
        self.stdout.write("  Building unit lookup...")
        unit_map = dict(Unit.objects.values_list("unit_number", "pk"))

        # Fetch existing ApplicationUnit links to avoid duplicates
        self.stdout.write("  Loading existing application-unit links...")
        existing_app_units = set(
            ApplicationUnit.objects.values_list("application_id", "unit_id")
        )

        # Pre-collect distinct years per app key
        self.stdout.write("  Collecting year ranges per application...")
        year_map = {}
        if split:
            for make, model, engine, year in conn.execute(
                "SELECT make, model, engine, year FROM applications "
                "WHERE year != '' GROUP BY make, model, engine, year"
            ):
                key = (make, model, engine)
                year_map.setdefault(key, [])
                if year not in year_map[key]:
                    year_map[key].append(year)
        else:
            for make, model, year in conn.execute(
                "SELECT make, model, year FROM applications WHERE year != '' "
                "GROUP BY make, model, year"
            ):
                key = (make, model)
                year_map.setdefault(key, [])
                if year not in year_map[key]:
                    year_map[key].append(year)

        # Pre-collect distinct options per app key (new schema only)
        options_map = {}
        if split:
            self.stdout.write("  Collecting options per application...")
            for make, model, engine, opts in conn.execute(
                "SELECT make, model, engine, options FROM applications "
                "WHERE options != '' GROUP BY make, model, engine, options"
            ):
                key = (make, model, engine)
                options_map.setdefault(key, [])
                if opts not in options_map[key]:
                    options_map[key].append(opts)

        if split:
            cursor = conn.execute(
                "SELECT unit_type, make, model, engine, options, mfr, amp, volt, "
                "part_number, other_number FROM applications"
            )
        else:
            cursor = conn.execute(
                "SELECT unit_type, make, model, engine_options, '', mfr, amp, volt, "
                "part_number, other_number FROM applications"
            )

        total_rows = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]

        apps_created = 0
        units_created = 0
        links_created = 0
        skipped_no_part = 0
        processed = 0
        app_batch = []
        link_batch = []

        # app_cache: app_key -> Application instance (after bulk_create has set .pk)
        app_cache = {}
        pending_links = []

        for row in cursor:
            unit_type, make, model, engine, options, mfr, amp, volt, part_no, other_no = row
            processed += 1

            if not part_no:
                skipped_no_part += 1
                continue

            # One Unit per unique part number
            # Route amp vs kw_hp depending on unit type
            is_generator = unit_type.lower() == "generator"
            unit_pk = unit_map.get(part_no)
            if not unit_pk:
                unit = Unit.objects.create(
                    unit_number=part_no,
                    manufacturer=mfr[:200] if mfr else "",
                    voltage=volt[:50] if volt else "",
                    amp_rating="" if is_generator else (amp[:50] if amp else ""),
                    kw_hp=amp[:50] if (is_generator and amp) else "",
                    unit_type_category=unit_type[:100] if unit_type else "",
                )
                unit_map[part_no] = unit.pk
                unit_pk = unit.pk
                units_created += 1

            # One Application per unique (make, model, engine)
            app_key = (make, model, engine)

            if app_key not in app_cache:
                app_name = " ".join(filter(None, [make, model, engine])).strip() or f"Unknown {unit_type}"
                combined_year = " | ".join(year_map.get(app_key, []))
                combined_options = " | ".join(options_map.get(app_key, []))
                # Populate volt/unit_number from the first unit encountered.
                # amp goes in Application.amp for alternators; kw goes in Application.kw for generators.
                app = Application(
                    name=app_name,
                    make=make[:150],
                    model=model[:150],
                    engine=engine[:150] if engine else "",
                    year=combined_year[:50],
                    options=combined_options,
                    unit_type_name=unit_type[:100],
                    amp="" if is_generator else (amp[:50] if amp else ""),
                    kw=amp[:50] if (is_generator and amp) else "",
                    volt=volt[:50] if volt else "",
                    unit_number=part_no[:100] if part_no else "",
                )
                app_batch.append(app)
                app_cache[app_key] = app

                if len(app_batch) >= BATCH_SIZE:
                    Application.objects.bulk_create(app_batch)
                    apps_created += len(app_batch)
                    app_batch = []

            pending_links.append((app_key, part_no))

            if processed % 50000 == 0:
                self.stdout.write(
                    f"  Progress: {processed:,}/{total_rows:,} rows  |  "
                    f"{apps_created:,} apps, {units_created:,} units"
                )

        # Flush remaining application batch
        if app_batch:
            Application.objects.bulk_create(app_batch)
            apps_created += len(app_batch)
            app_batch = []

        # Build ApplicationUnit links after bulk_create (apps now have PKs)
        seen_links = set()
        for app_key, part_no in pending_links:
            app = app_cache.get(app_key)
            if not app or not app.pk:
                continue
            unit_pk = unit_map.get(part_no)
            if not unit_pk:
                continue
            link_key = (app.pk, unit_pk)
            if link_key in existing_app_units or link_key in seen_links:
                continue
            seen_links.add(link_key)
            link_batch.append(ApplicationUnit(application_id=app.pk, unit_id=unit_pk))

            if len(link_batch) >= BATCH_SIZE:
                ApplicationUnit.objects.bulk_create(link_batch, ignore_conflicts=True)
                links_created += len(link_batch)
                link_batch = []

        if link_batch:
            ApplicationUnit.objects.bulk_create(link_batch, ignore_conflicts=True)
            links_created += len(link_batch)

        conn.close()
        elapsed = time.time() - t0

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"IMPORT COMPLETE: {db_path.name}")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Applications created:        {apps_created:>10,}")
        self.stdout.write(f"  Units created:               {units_created:>10,}")
        self.stdout.write(f"  App-Unit links created:      {links_created:>10,}")
        self.stdout.write(f"  Skipped (no part number):    {skipped_no_part:>10,}")
        self.stdout.write(f"  Total time:                  {elapsed:>10.1f}s")
        self.stdout.write("")

        db_app_count = Application.objects.count()
        db_link_count = ApplicationUnit.objects.count()
        self.stdout.write(
            f"  Database totals: {db_app_count:,} applications, "
            f"{db_link_count:,} app-unit links"
        )
        self.stdout.write("")
