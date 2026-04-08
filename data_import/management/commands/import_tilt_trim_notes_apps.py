"""
Import missing Product Notes and Application records from the Tilt & Trim
Motors Buyers Guide PDF (12-Buyers Guide Tilt Trim Motors.pdf).

The original parser only captured Product Notes that appeared *inside* the
PRODUCT ATTRIBUTES section, but in this PDF every note appears right after the
YouTech header (before any section heading), so they were all skipped.  The
APPLICATION sections were also explicitly ignored.

This command reads the PDF directly (no staging DB needed) and:
  - Appends missing Product Notes text to Unit.notes
  - Creates Application records (deduped by make + model) and links them to
    the matching Unit via ApplicationUnit

Usage:
    python manage.py import_tilt_trim_notes_apps
    python manage.py import_tilt_trim_notes_apps --preview
    python manage.py import_tilt_trim_notes_apps --file "path/to/other.pdf"
"""

import re
import time
from pathlib import Path

import fitz  # PyMuPDF
from django.conf import settings
from django.core.management.base import BaseCommand

from catalog.models import Application, ApplicationUnit, Unit


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
YOUTECH_HEADER_RE = re.compile(r"YouTech\s+#(\S+)\s*(?:/J&N\s+#(\S+))?")
SECTION_HEADERS = {
    "PRODUCT ATTRIBUTES",
    "INTERCHANGES",
    "BILL OF MATERIALS",
    "APPLICATION",
    "APPLICATIONS",
    "POSSIBLE SUBSTITUTIONS",
}
YEAR_RE = re.compile(r"\d{4}-\d{4}")
PAGE_NUM_RE = re.compile(r"^Pg\.\s*\d+")

DEFAULT_PDF = (
    Path(settings.BASE_DIR).parent
    / "Manchester Electric YouTech numbers"
    / "YouTec"
    / "Done"
    / "12-Buyers Guide Tilt Trim Motors.pdf"
)


# ---------------------------------------------------------------------------
# PDF parsing helpers
# ---------------------------------------------------------------------------
def _parse_pdf(pdf_path: Path):
    """
    Scan the PDF and return two dicts:
      notes_map  : yt_number -> notes text  (first occurrence wins)
      apps_map   : yt_number -> list of raw application lines
    """
    notes_map = {}
    apps_map = {}

    current_yt = ""
    current_section = ""
    current_app_lines = []

    def _flush_app():
        nonlocal current_app_lines
        if current_app_lines and current_yt and current_yt not in apps_map:
            apps_map[current_yt] = list(current_app_lines)
        current_app_lines = []

    doc = fitz.open(str(pdf_path))
    for page in doc:
        for raw_line in page.get_text().split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            if line in ("BUYERS GUIDE", "TILT & TRIM MOTORS", "MILD HYBRID MOTOR/GENERATORS"):
                continue

            m = YOUTECH_HEADER_RE.match(line)
            if m and "(Cont.)" not in line:
                _flush_app()
                current_yt = m.group(1)
                current_section = ""
                continue

            clean = line.rstrip(":")
            if clean in SECTION_HEADERS:
                if current_section in ("APPLICATION", "APPLICATIONS"):
                    _flush_app()
                current_section = clean
                continue

            if not current_yt:
                continue

            # Product Notes appear right after the YouTech header (section == "")
            if line.startswith("Product Notes:") and current_section == "":
                if current_yt not in notes_map:
                    notes_map[current_yt] = line[14:].strip()
                continue

            if current_section in ("APPLICATION", "APPLICATIONS"):
                if not PAGE_NUM_RE.match(line) and not YOUTECH_HEADER_RE.match(line):
                    current_app_lines.append(line)

    _flush_app()
    doc.close()
    return notes_map, apps_map


def _parse_app_lines(lines):
    """
    Parse a list of raw application section lines into
    [(make, model_description), ...] pairs.

    Terminal lines (which close an application entry) are:
      - Lines containing a year range like 1963-1979
      - The literal string "All Models"
      - Lines containing semicolons (multi-model descriptors)
      - A standalone "Various" line (common standalone model word)

    Lines before the terminal accumulate as the make name.
    """
    entries = []
    make_parts = []

    for line in lines:
        is_terminal = (
            YEAR_RE.search(line)
            or line == "All Models"
            or (line.count(";") >= 1 and len(line) > 8)
            or line.strip() in ("Various", "Salt Spreader", "All")
        )
        if is_terminal:
            make = " ".join(make_parts).strip()
            entries.append((make, line.strip()))
            make_parts = []
        else:
            make_parts.append(line.strip())

    # Flush any remaining make parts that had no terminal line
    if make_parts:
        leftover = " ".join(make_parts).strip()
        if leftover:
            entries.append((leftover, ""))

    return entries


def _app_name(make, model):
    if make and model:
        return f"{make} - {model}"
    return make or model or "Unknown Application"


# ---------------------------------------------------------------------------
# Management command
# ---------------------------------------------------------------------------
class Command(BaseCommand):
    help = "Import missing Product Notes and Application links from the Tilt & Trim Buyers Guide PDF."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=None,
            help="Path to the PDF (default: auto-detected)",
        )
        parser.add_argument(
            "--preview",
            action="store_true",
            help="Print a full report of what would change without writing anything.",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        pdf_path = Path(options["file"]) if options.get("file") else DEFAULT_PDF

        if not pdf_path.exists():
            self.stderr.write(self.style.ERROR(f"PDF not found: {pdf_path}"))
            self.stderr.write("Pass the correct path with --file")
            return

        self.stdout.write(f"Reading: {pdf_path.name}")
        notes_map, apps_map = _parse_pdf(pdf_path)
        self.stdout.write(
            f"  Found {len(notes_map)} YT numbers with notes, "
            f"{len(apps_map)} with application sections.\n"
        )

        if options["preview"]:
            self._preview(notes_map, apps_map)
        else:
            self._import(notes_map, apps_map)

    # ------------------------------------------------------------------
    def _preview(self, notes_map, apps_map):
        all_yts = sorted(set(notes_map) | set(apps_map))
        unit_lookup = {
            u.yt_number: u
            for u in Unit.objects.filter(yt_number__in=all_yts)
        }

        W = 72
        self.stdout.write("=" * W)
        self.stdout.write("PREVIEW -- NOTES")
        self.stdout.write("=" * W)
        notes_needed = 0
        for yt in sorted(notes_map):
            note = notes_map[yt]
            unit = unit_lookup.get(yt)
            if not unit:
                self.stdout.write(f"  YT={yt:<10}  NOT IN SYSTEM -- skip")
                continue
            already = unit.notes and note in unit.notes
            if already:
                self.stdout.write(f"  YT={yt:<10}  (already has note)  {note[:60]}")
            else:
                self.stdout.write(f"  YT={yt:<10}  ** ADD NOTE **  {note[:60]}")
                notes_needed += 1

        self.stdout.write(f"\n  -> {notes_needed} unit(s) will have notes added.\n")

        self.stdout.write("=" * W)
        self.stdout.write("PREVIEW -- APPLICATIONS")
        self.stdout.write("=" * W)
        total_links = 0
        total_new_apps = 0
        existing_apps = {
            (a.make, a.model): a
            for a in Application.objects.all()
        }
        existing_links = set(
            ApplicationUnit.objects.filter(
                unit__yt_number__in=list(apps_map.keys())
            ).values_list("unit__yt_number", "application__make", "application__model")
        )

        for yt in sorted(apps_map):
            unit = unit_lookup.get(yt)
            lines = apps_map[yt]
            parsed = _parse_app_lines(lines)
            if not parsed:
                continue
            self.stdout.write(f"  YT={yt}:")
            for make, model in parsed:
                if not make and not model:
                    continue
                key = (make, model)
                app_exists = key in existing_apps
                link_exists = (yt, make, model) in existing_links
                app_status = "(app exists)" if app_exists else "** CREATE APP **"
                link_status = "(link exists)" if link_exists else "** LINK **"
                self.stdout.write(
                    f"    make={make!r:<30} model={model!r:<35} {app_status} {link_status}"
                )
                if not link_exists:
                    total_links += 1
                if not app_exists:
                    # Count unique new apps only once
                    existing_apps[key] = True  # mark as seen
                    total_new_apps += 1

        self.stdout.write(f"\n  -> {total_new_apps} new Application record(s) will be created.")
        self.stdout.write(f"  -> {total_links} new ApplicationUnit link(s) will be created.")
        self.stdout.write("\nRun without --preview to apply these changes.")

    # ------------------------------------------------------------------
    def _import(self, notes_map, apps_map):
        start = time.time()
        all_yts = sorted(set(notes_map) | set(apps_map))
        unit_lookup = {
            u.yt_number: u
            for u in Unit.objects.filter(yt_number__in=all_yts)
        }

        # ── 1. NOTES ──────────────────────────────────────────────────
        self.stdout.write("  [1/2] Adding notes to Unit records...")
        notes_added = 0
        units_to_update = []
        for yt, note in notes_map.items():
            unit = unit_lookup.get(yt)
            if not unit:
                continue
            if unit.notes and note in unit.notes:
                continue
            unit.notes = (unit.notes + "\n" + note).strip() if unit.notes else note
            units_to_update.append(unit)
            notes_added += 1

        if units_to_update:
            Unit.objects.bulk_update(units_to_update, ["notes"], batch_size=200)
        self.stdout.write(f"     added: {notes_added:,}  skipped: {len(notes_map) - notes_added:,}")

        # ── 2. APPLICATIONS ───────────────────────────────────────────
        self.stdout.write("  [2/2] Creating Application records and links...")
        apps_created = links_created = links_skipped = 0

        # Cache existing apps keyed by (make, model)
        app_cache = {
            (a.make, a.model): a
            for a in Application.objects.all()
        }
        # Cache existing links to avoid duplicates
        existing_links = set(
            ApplicationUnit.objects.filter(
                unit__yt_number__in=list(apps_map.keys())
            ).values_list("unit_id", "application_id")
        )

        new_links = []
        for yt, lines in apps_map.items():
            unit = unit_lookup.get(yt)
            if not unit:
                continue
            parsed = _parse_app_lines(lines)
            for make, model in parsed:
                if not make and not model:
                    continue
                key = (make, model)
                app = app_cache.get(key)
                if not app:
                    app = Application.objects.create(
                        name=_app_name(make, model),
                        make=make,
                        model=model,
                    )
                    app_cache[key] = app
                    apps_created += 1

                link_key = (unit.pk, app.pk)
                if link_key in existing_links:
                    links_skipped += 1
                    continue
                existing_links.add(link_key)
                new_links.append(ApplicationUnit(unit=unit, application=app))
                links_created += 1

        if new_links:
            ApplicationUnit.objects.bulk_create(new_links, batch_size=200, ignore_conflicts=True)

        elapsed = time.time() - start
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(self.style.SUCCESS("IMPORT COMPLETE"))
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Notes added:               {notes_added:>10,}")
        self.stdout.write(f"  Application records created:{apps_created:>10,}")
        self.stdout.write(f"  Application links created:  {links_created:>10,}")
        self.stdout.write(f"  Application links skipped:  {links_skipped:>10,}")
        self.stdout.write(f"  Total time:                {elapsed:>10.1f}s")
        self.stdout.write("")
