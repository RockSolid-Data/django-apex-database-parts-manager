"""Fill missing oem_number on Part records from PartInterchange data.

Strategy:
- For each Part with oem filled (manufacturer name) but oem_number blank,
  find PartInterchange records where source_name matches the OEM.
- Use the first matching interchange_number as the OEM number.
- Also attempts to fill oem from interchange data for parts where oem is blank.

Usage:
    python manage.py fill_oem_numbers --dry-run
    python manage.py fill_oem_numbers
"""

import time

from django.core.management.base import BaseCommand
from django.db.models import Q

from catalog.models import Part, PartInterchange


# Maps Part.oem values to the PartInterchange.source_name values that represent
# the same OEM manufacturer. Order matters: first match wins.
OEM_TO_SOURCE = {
    "Delco": ["Delco-Remy", "Delco", "ACDelco", "Delco Europe"],
    "Prestolite": ["Prestolite"],
    "Valeo": ["Valeo", "Valeo New", "Valeo Tech"],
    "Bosch": ["Bosch", "Bosch Aftermarket", "Bosch Service Europe"],
    "Letrika": ["Letrika"],
    "DENSO": ["DENSO", "Denso"],
    "Ford": ["Ford", "Motorcraft"],
    "Motorola": ["Motorola"],
    "Mitsubishi": ["Mitsubishi", "Mitsubishi Electric"],
    "Mitsubishi Electric": ["Mitsubishi Electric", "Mitsubishi"],
    "Hitachi": ["Hitachi Automotive", "Hitachi"],
    "Hitachi Automotive": ["Hitachi Automotive", "Hitachi"],
    "LUCAS": ["Lucas", "LUCAS"],
    "Lucas": ["Lucas", "LUCAS"],
    "Leece-Neville": ["Leece-Neville"],
    "Marelli": ["Marelli", "Magneti Marelli"],
    "Chrysler": ["Chrysler"],
    "Mitsuba": ["Mitsuba"],
    "MAHLE": ["MAHLE"],
    "NIKKO": ["NIKKO"],
    "Nikko": ["NIKKO"],
    "United Technologies": ["United Technologies"],
    "Litens": ["Litens"],
    "Ducellier": ["Ducellier"],
    "Mando": ["Mando"],
    "Paris Rhone": ["Paris Rhone"],
    "CAE": ["CAE"],
    "IKA": ["IKA"],
    "Briggs & Stratton": ["Briggs & Stratton"],
    "Sawafuji": ["Sawafuji", "(SAWAFUJI)"],
    "Niehoff": ["Niehoff"],
    "Nippondenso": ["DENSO", "Denso"],
}

# Source names that represent actual OEM manufacturers (not aftermarket distributors)
OEM_CLASS_SOURCES = {
    "Delco-Remy", "Delco", "ACDelco", "Delco Europe",
    "Prestolite",
    "Valeo",
    "Bosch", "Bosch Aftermarket",
    "Letrika",
    "DENSO", "Denso",
    "Ford", "Motorcraft",
    "Motorola",
    "Mitsubishi", "Mitsubishi Electric",
    "Hitachi Automotive",
    "Lucas",
    "Leece-Neville",
    "Marelli", "Magneti Marelli",
    "Chrysler",
    "Mitsuba",
    "MAHLE",
    "NIKKO",
    "United Technologies",
    "Ducellier",
    "Mando",
    "Paris Rhone",
    "Sawafuji", "(SAWAFUJI)",
    "Niehoff",
    "SEG Automotive",
    "Magneton",
}

# Reverse mapping: source_name -> canonical OEM name for Part.oem field
SOURCE_TO_OEM = {
    "Delco-Remy": "Delco",
    "Delco": "Delco",
    "ACDelco": "Delco",
    "Delco Europe": "Delco",
    "Prestolite": "Prestolite",
    "Valeo": "Valeo",
    "Bosch": "Bosch",
    "Bosch Aftermarket": "Bosch",
    "Letrika": "Letrika",
    "DENSO": "DENSO",
    "Denso": "DENSO",
    "Ford": "Ford",
    "Motorcraft": "Ford",
    "Motorola": "Motorola",
    "Mitsubishi": "Mitsubishi",
    "Mitsubishi Electric": "Mitsubishi Electric",
    "Hitachi Automotive": "Hitachi",
    "Lucas": "LUCAS",
    "Leece-Neville": "Leece-Neville",
    "Marelli": "Marelli",
    "Magneti Marelli": "Marelli",
    "Chrysler": "Chrysler",
    "Mitsuba": "Mitsuba",
    "MAHLE": "MAHLE",
    "NIKKO": "NIKKO",
    "United Technologies": "United Technologies",
    "Ducellier": "Ducellier",
    "Mando": "Mando",
    "Paris Rhone": "Paris Rhone",
    "Sawafuji": "Sawafuji",
    "(SAWAFUJI)": "Sawafuji",
    "Niehoff": "Niehoff",
    "SEG Automotive": "SEG Automotive",
    "Magneton": "Magneton",
}


class Command(BaseCommand):
    help = "Fill missing oem_number on Parts from PartInterchange data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", dest="dry_run",
            help="Show what would be changed without saving",
        )
        parser.add_argument(
            "--fill-oem-name", action="store_true", dest="fill_oem_name",
            help="Also fill blank Part.oem from interchange sources",
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Process at most N parts (for testing)",
        )

    def handle(self, *args, **options):
        import sys
        sys.stdout.reconfigure(line_buffering=True)

        dry_run = options["dry_run"]
        fill_oem_name = options["fill_oem_name"]
        limit = options.get("limit")
        start = time.time()

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved"))
        self.stdout.write("")

        # --- Step 1: Fill oem_number from interchange where Part.oem is known ---
        self.stdout.write("=" * 60)
        self.stdout.write("Step 1: Fill oem_number from interchange (Part.oem known)")
        self.stdout.write("=" * 60)

        parts_needing_oem_number = Part.objects.filter(
            oem_number="",
        ).exclude(oem="")

        if limit:
            parts_needing_oem_number = parts_needing_oem_number[:limit]

        oem_filled = 0
        oem_skipped_no_match = 0
        oem_skipped_no_mapping = 0
        batch_update = []

        for part in parts_needing_oem_number.iterator(chunk_size=500):
            source_names = OEM_TO_SOURCE.get(part.oem)
            if not source_names:
                oem_skipped_no_mapping += 1
                continue

            xref = (
                PartInterchange.objects
                .filter(part=part, source_name__in=source_names)
                .exclude(interchange_number="")
                .values_list("interchange_number", flat=True)
                .first()
            )

            if not xref:
                oem_skipped_no_match += 1
                continue

            part.oem_number = xref[:100]
            batch_update.append(part)
            oem_filled += 1

            if not dry_run and len(batch_update) >= 500:
                Part.objects.bulk_update(batch_update, ["oem_number"], batch_size=500)
                batch_update = []

            if oem_filled % 1000 == 0:
                self.stdout.write(f"  Progress: {oem_filled:,} filled...")

        if not dry_run and batch_update:
            Part.objects.bulk_update(batch_update, ["oem_number"], batch_size=500)

        self.stdout.write(f"  Filled oem_number:       {oem_filled:>8,}")
        self.stdout.write(f"  No mapping for OEM:      {oem_skipped_no_mapping:>8,}")
        self.stdout.write(f"  No interchange match:    {oem_skipped_no_match:>8,}")
        self.stdout.write("")

        # --- Step 2: Fill oem AND oem_number for parts with blank oem ---
        oem_name_filled = 0
        oem_number_from_blank = 0

        if fill_oem_name:
            self.stdout.write("=" * 60)
            self.stdout.write("Step 2: Fill oem + oem_number for parts with blank oem")
            self.stdout.write("=" * 60)

            parts_blank_oem = Part.objects.filter(oem="")
            if limit:
                parts_blank_oem = parts_blank_oem[:limit]

            batch_update2 = []

            for part in parts_blank_oem.iterator(chunk_size=500):
                oem_xrefs = (
                    PartInterchange.objects
                    .filter(part=part, source_name__in=OEM_CLASS_SOURCES)
                    .exclude(interchange_number="")
                    .values_list("source_name", "interchange_number")
                )

                # Find unique OEM sources for this part
                oem_sources = {}
                for src, num in oem_xrefs:
                    canonical = SOURCE_TO_OEM.get(src)
                    if canonical and canonical not in oem_sources:
                        oem_sources[canonical] = num

                if len(oem_sources) == 1:
                    oem_name, oem_num = next(iter(oem_sources.items()))
                    changed = False
                    if not part.oem:
                        part.oem = oem_name
                        oem_name_filled += 1
                        changed = True
                    if not part.oem_number:
                        part.oem_number = oem_num[:100]
                        oem_number_from_blank += 1
                        changed = True
                    if changed:
                        batch_update2.append(part)

                if not dry_run and len(batch_update2) >= 500:
                    Part.objects.bulk_update(batch_update2, ["oem", "oem_number"], batch_size=500)
                    batch_update2 = []

            if not dry_run and batch_update2:
                Part.objects.bulk_update(batch_update2, ["oem", "oem_number"], batch_size=500)

            self.stdout.write(f"  Filled oem (name):       {oem_name_filled:>8,}")
            self.stdout.write(f"  Filled oem_number:       {oem_number_from_blank:>8,}")
            self.stdout.write("")

        # --- Step 3: Fill manufacturer_number (J&N as manufacturer_number) ---
        self.stdout.write("=" * 60)
        self.stdout.write("Step 3: Fill manufacturer_number from J&N number")
        self.stdout.write("=" * 60)

        parts_blank_mfr_num = Part.objects.filter(
            manufacturer_number=""
        ).exclude(j_and_n="")

        mfr_filled = 0
        batch_update3 = []

        for part in parts_blank_mfr_num.iterator(chunk_size=500):
            jn = part.j_and_n.strip()
            if " | " in jn:
                jn = jn.split(" | ")[0].strip()
            if jn:
                part.manufacturer_number = jn[:100]
                batch_update3.append(part)
                mfr_filled += 1

            if not dry_run and len(batch_update3) >= 500:
                Part.objects.bulk_update(batch_update3, ["manufacturer_number"], batch_size=500)
                batch_update3 = []

        if not dry_run and batch_update3:
            Part.objects.bulk_update(batch_update3, ["manufacturer_number"], batch_size=500)

        self.stdout.write(f"  Filled manufacturer_number: {mfr_filled:>8,}")
        self.stdout.write("")

        # --- Step 4: Fill voltage from linked units ---
        self.stdout.write("=" * 60)
        self.stdout.write("Step 4: Fill voltage from linked units")
        self.stdout.write("=" * 60)

        voltage_filled = 0
        batch_update4 = []

        parts_blank_voltage = Part.objects.filter(voltage="").prefetch_related("units")
        if limit:
            parts_blank_voltage = parts_blank_voltage[:limit]

        for part in parts_blank_voltage.iterator(chunk_size=500):
            linked_units = part.units.exclude(voltage="").values_list("voltage", flat=True)[:1]
            voltage_val = None
            for v in linked_units:
                voltage_val = v
                break

            if not voltage_val:
                unit_fk = part.unit
                if unit_fk and unit_fk.voltage:
                    voltage_val = unit_fk.voltage

            if voltage_val:
                part.voltage = voltage_val[:50]
                batch_update4.append(part)
                voltage_filled += 1

                if not dry_run and len(batch_update4) >= 500:
                    Part.objects.bulk_update(batch_update4, ["voltage"], batch_size=500)
                    batch_update4 = []

        if not dry_run and batch_update4:
            Part.objects.bulk_update(batch_update4, ["voltage"], batch_size=500)

        self.stdout.write(f"  Filled voltage:            {voltage_filled:>8,}")
        self.stdout.write("")

        # --- Summary ---
        elapsed = time.time() - start
        self.stdout.write("=" * 60)
        self.stdout.write("SUMMARY")
        self.stdout.write("=" * 60)
        self.stdout.write(f"  oem_number filled (from known oem): {oem_filled:>8,}")
        if fill_oem_name:
            self.stdout.write(f"  oem (name) filled:                  {oem_name_filled:>8,}")
            self.stdout.write(f"  oem_number filled (from blank oem): {oem_number_from_blank:>8,}")
        self.stdout.write(f"  manufacturer_number filled (J&N):   {mfr_filled:>8,}")
        self.stdout.write(f"  voltage filled (from units):        {voltage_filled:>8,}")
        self.stdout.write(f"  Time: {elapsed:.1f}s")
        if dry_run:
            self.stdout.write(self.style.WARNING("\nDRY RUN — run without --dry-run to apply"))
        self.stdout.write("")
