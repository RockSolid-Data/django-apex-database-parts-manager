"""
Import application data from staging DBs into the Django catalog.

Staging DBs are produced by parse_applications.py and contain an
`applications` table with columns:
    unit_type, make, model, year, engine, options, mfr, amp, volt,
    part_number, other_number, page_number

Grouping (v2 — June 2026):
  Each Application = one unique (make, model, engine, yt_number, mfr, transmission).
  - yt_number  = staging column ``part_number``
  - mfr        = staging column ``mfr``  (unit manufacturer, e.g. Bosch / DENSO)
  - transmission = "Automatic" | "Manual" | "" extracted from ``options``
  Each Application links to exactly ONE Unit via ApplicationUnit.
  Year ranges for the same group are combined with pipe separators.

Previous grouping (v1):
  One Application per unique (make, model, engine), linking to many Units.

Usage:
    python manage.py import_applications --file "data_import/staging_dbs/4- Applications Alts.db" --preview
    python manage.py import_applications --file "data_import/staging_dbs/4- Applications Alts.db"
    python manage.py import_applications --all
    python manage.py import_applications --file "..." --report-only
"""

import sqlite3
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from catalog.models import Application, ApplicationUnit, Unit


BATCH_SIZE = 2000
TRANSMISSION_TOKENS = {"Automatic", "Manual"}

APP_SOURCE_PDF = {
    "Alternator": "PDF 4 - Applications Alternators",
    "Generator": "PDF 5 - Applications Generators",
    "Starter": "PDF 6 - Applications Starters",
    "Motor": "PDF 7 - Applications Motors",
    "MGU": "PDF 8 - Applications MGU",
}


def extract_transmission(options_str):
    """Pull 'Automatic' or 'Manual' out of a semicolon-separated options string.

    Returns (transmission, remaining_options) where transmission is one of
    'Automatic', 'Manual', or '' and remaining_options has the token removed.
    """
    if not options_str:
        return "", ""
    parts = [p.strip() for p in options_str.split(";")]
    transmission = ""
    rest = []
    for p in parts:
        if p in TRANSMISSION_TOKENS:
            transmission = p
        else:
            rest.append(p)
    return transmission, ";".join(rest)


def normalize_year(year_str):
    """Convert 2-digit year ranges to 4-digit (e.g. '81-91' → '1981-1991')."""
    if not year_str:
        return year_str

    def expand(y):
        if len(y) == 2 and y.isdigit():
            val = int(y)
            return f"20{y}" if val <= 30 else f"19{y}"
        return y

    parts = year_str.split(" | ")
    normalized = []
    for part in parts:
        if "-" in part:
            segments = part.split("-")
            normalized.append("-".join(expand(s) for s in segments))
        else:
            normalized.append(expand(part))
    return " | ".join(normalized)


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
            if not r[0].rstrip(",").startswith(("400-", "410-"))
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
            if not r[0].rstrip(",").startswith(("400-", "410-"))
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

        total_rows = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]

        # ---- PASS 1: scan all rows and aggregate per new grouping key ----
        # Key = (make, model, engine, part_number, mfr, transmission)
        self.stdout.write("  Pass 1: scanning rows and building group aggregates...")

        if split:
            cursor = conn.execute(
                "SELECT unit_type, make, model, engine, options, mfr, amp, volt, "
                "part_number, other_number, year FROM applications ORDER BY id"
            )
        else:
            cursor = conn.execute(
                "SELECT unit_type, make, model, engine_options, '', mfr, amp, volt, "
                "part_number, other_number, year FROM applications ORDER BY id"
            )

        group_data = {}   # key -> dict with first-seen scalar fields
        year_map = {}     # key -> ordered list of unique year strings
        options_map = {}  # key -> ordered list of unique non-transmission option strings
        other_map = {}    # key -> ordered list of unique other_number strings
        skipped_no_part = 0
        scanned = 0

        # Inheritance state: blank year/mfr inherit from the row above
        # within the same engine group (same make + model + engine).
        prev_engine_group = None
        inherited_year = ""
        inherited_mfr = ""

        for row in cursor:
            unit_type, make, model, engine, options_raw, mfr, amp, volt, part_no, other_no, year = row
            scanned += 1

            engine_group = (make, model, engine)
            if engine_group != prev_engine_group:
                inherited_year = ""
                inherited_mfr = ""
                prev_engine_group = engine_group

            if year:
                inherited_year = year
            else:
                year = inherited_year

            if mfr:
                inherited_mfr = mfr
            else:
                mfr = inherited_mfr

            if not part_no:
                skipped_no_part += 1
                continue

            # Skip J&N cross-reference numbers erroneously in part_number
            bare_pn = part_no.rstrip(",")
            if bare_pn.startswith("400-") or bare_pn.startswith("410-"):
                skipped_no_part += 1
                continue

            transmission, remaining_opts = extract_transmission(options_raw)
            app_key = (make, model, engine, part_no, mfr, transmission)

            if app_key not in group_data:
                group_data[app_key] = {
                    "unit_type": unit_type,
                    "amp": amp,
                    "volt": volt,
                }
                year_map[app_key] = []
                options_map[app_key] = []
                other_map[app_key] = []

            if year and year not in year_map[app_key]:
                year_map[app_key].append(year)
            if other_no and other_no not in other_map[app_key]:
                other_map[app_key].append(other_no)
            if remaining_opts and remaining_opts not in options_map[app_key]:
                options_map[app_key].append(remaining_opts)

            if scanned % 50000 == 0:
                self.stdout.write(
                    f"    Scanned {scanned:,}/{total_rows:,} rows, "
                    f"{len(group_data):,} groups so far"
                )

        conn.close()
        self.stdout.write(
            f"  Pass 1 done: {len(group_data):,} unique groups from {scanned:,} rows"
        )

        # ---- PASS 2: create units, apps, and links ----
        self.stdout.write("  Pass 2: creating units, applications, and links...")

        apps_created = 0
        units_created = 0
        links_created = 0
        app_batch = []
        link_batch = []

        for app_key, info in group_data.items():
            make, model, engine, part_no, mfr, transmission = app_key
            unit_type = info["unit_type"]
            amp = info["amp"]
            volt = info["volt"]
            is_generator = unit_type.lower() == "generator"

            # Ensure Unit exists
            unit_pk = unit_map.get(part_no)
            if not unit_pk:
                unit = Unit.objects.create(
                    unit_number=part_no,
                    manufacturer=mfr[:200] if mfr else "",
                    voltage=volt[:50] if volt else "",
                    amp_rating="" if is_generator else (amp[:50] if amp else ""),
                    kw_hp=amp[:50] if (is_generator and amp) else "",
                    unit_type_category=unit_type[:100] if unit_type else "",
                    source_pdf=APP_SOURCE_PDF.get(unit_type, ""),
                )
                unit_map[part_no] = unit.pk
                unit_pk = unit.pk
                units_created += 1

            # Build application fields
            name_parts = [make, model, engine]
            if transmission:
                name_parts.append(transmission)
            app_name = " ".join(filter(None, name_parts)).strip() or f"Unknown {unit_type}"

            combined_year = normalize_year(" | ".join(year_map.get(app_key, [])))
            combined_opts_list = options_map.get(app_key, [])
            if transmission:
                combined_opts_list = [transmission] + combined_opts_list
            combined_options = " | ".join(combined_opts_list)
            combined_other = ", ".join(other_map.get(app_key, []))

            app = Application(
                name=app_name[:255],
                make=make[:150],
                model=model[:150],
                engine=engine[:150] if engine else "",
                year=combined_year[:50],
                options=combined_options,
                unit_type_name=unit_type[:100],
                mfr=mfr[:150] if mfr else "",
                amp="" if is_generator else (amp[:50] if amp else ""),
                kw=amp[:50] if (is_generator and amp) else "",
                volt=volt[:50] if volt else "",
                unit_number=part_no[:100],
                other_number=combined_other[:100],
                source_pdf=APP_SOURCE_PDF.get(unit_type, ""),
            )
            app_batch.append((app, unit_pk))

            if len(app_batch) >= BATCH_SIZE:
                objs = [a for a, _ in app_batch]
                Application.objects.bulk_create(objs)
                apps_created += len(objs)
                for a, upk in app_batch:
                    lk = (a.pk, upk)
                    if lk not in existing_app_units:
                        link_batch.append(ApplicationUnit(application_id=a.pk, unit_id=upk))
                if len(link_batch) >= BATCH_SIZE:
                    ApplicationUnit.objects.bulk_create(link_batch, ignore_conflicts=True)
                    links_created += len(link_batch)
                    link_batch = []
                app_batch = []

                if apps_created % 50000 == 0:
                    self.stdout.write(
                        f"  Progress: {apps_created:,} apps, {units_created:,} units, "
                        f"{links_created:,} links"
                    )

        # Flush remaining
        if app_batch:
            objs = [a for a, _ in app_batch]
            Application.objects.bulk_create(objs)
            apps_created += len(objs)
            for a, upk in app_batch:
                lk = (a.pk, upk)
                if lk not in existing_app_units:
                    link_batch.append(ApplicationUnit(application_id=a.pk, unit_id=upk))

        if link_batch:
            ApplicationUnit.objects.bulk_create(link_batch, ignore_conflicts=True)
            links_created += len(link_batch)

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
