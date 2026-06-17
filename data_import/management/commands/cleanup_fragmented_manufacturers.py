"""
Merge fragmented manufacturer names in CrossReference and PartInterchange.

PDF parsers sometimes split multi-word manufacturer names across lines,
creating separate entries like "United" and "Technologies" instead of
"United Technologies".  This command detects and merges those fragments.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import CrossReference, PartInterchange


# ── 1:1 fragment -> correct name mappings ──────────────────────────────
#   (fragment_value, correct_full_name)
XREF_MERGES = [
    # Word-split fragments
    ("United",          "United Technologies"),
    ("Technologies",    "United Technologies"),
    ("Products",        "Remy Power Products"),
    ("Service",         "Electric Motor Service"),
    ("Supplies",        "Wood Auto Supplies"),
    ("CARGO",           "HC CARGO"),
    ("CARG",            "HC CARGO"),
    ("America",         "Daimler Truck North America"),
    ("North America",   "Daimler Truck North America"),
    ("Agriculture",     "New Holland Agriculture"),
    ("Construction",    "New Holland Construction"),
    ("Solutions",       "NAPA Heavy Duty Solutions"),
    ("Remy Power",      "Remy Power Products"),
    ("Electric Motor",  "Electric Motor Service"),
    ("Electric",        "Romaine Electric"),
    # Hyphen-space artifacts
    ("Delco- Remy",     "Delco-Remy"),
    ("Leece- Neville",  "Leece-Neville"),
    ("Thermo- King",    "Thermo-King"),
    ("Atlas- Copco",    "Atlas-Copco"),
    ("All- Tek",        "All-Tek"),
    # Broken-inside-word
    ("Tecumseh/Laus on", "Tecumseh/Lauson"),
    # Case normalization
    ("Hc Cargo",        "HC CARGO"),
]

PI_MERGES = [
    ("United",          "United Technologies"),
    ("Technologies",    "United Technologies"),
    ("Supplies",        "Wood Auto Supplies"),
    ("CARGO",           "HC CARGO"),
    ("CARG",            "HC CARGO"),
    ("Manufacturing",   "Wells Manufacturing"),
    ("Construction",    "New Holland Construction"),
    ("Agriculture",     "New Holland Agriculture"),
    ("Europe",          "Bosch Service Europe"),
    # Hyphen-space
    ("Delco- Remy",     "Delco-Remy"),
    ("Leece- Neville",  "Leece-Neville"),
    ("Thermo- King",    "Thermo-King"),
    # Broken-inside-word
    ("Tecumseh/Laus on", "Tecumseh/Lauson"),
]


class Command(BaseCommand):
    help = "Merge fragmented manufacturer names in CrossReference and PartInterchange."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be done without making changes.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN -- no changes will be saved.\n"))

        total_updated = 0
        total_deleted = 0

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== CrossReference: interchange_type merges ===\n"
        ))
        for bad, good in XREF_MERGES:
            updated, deleted = self._merge_xref(bad, good, dry_run)
            total_updated += updated
            total_deleted += deleted

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== PartInterchange: source_name merges ===\n"
        ))
        for bad, good in PI_MERGES:
            updated, deleted = self._merge_pi(bad, good, dry_run)
            total_updated += updated
            total_deleted += deleted

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== Trailing-dash report (not auto-fixed) ===\n"
        ))
        trailing = (
            CrossReference.objects
            .filter(cross_ref_number__endswith="-")
            .exclude(cross_ref_number="-")
        )
        self.stdout.write(f"  Entries with trailing dash in cross_ref_number: {trailing.count()}\n")

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Summary ===\n"))
        self.stdout.write(f"  Records updated (renamed):  {total_updated}\n")
        self.stdout.write(f"  Records deleted (dupes):    {total_deleted}\n")
        self.stdout.write(f"  Total records fixed:        {total_updated + total_deleted}\n")
        if dry_run:
            self.stdout.write(self.style.WARNING(
                "\nNo changes saved (dry run). Re-run without --dry-run to apply.\n"
            ))
        else:
            self.stdout.write(self.style.SUCCESS("\nAll changes committed.\n"))

    # ── CrossReference merge logic ─────────────────────────────────────

    def _merge_xref(self, bad_type, good_type, dry_run):
        """
        Rename interchange_type from bad_type to good_type.
        If renaming would violate unique_together (unit, cross_ref_number, interchange_type),
        delete the fragment instead (the correct entry already exists).
        """
        bad_qs = CrossReference.objects.filter(interchange_type=bad_type)
        count = bad_qs.count()
        if count == 0:
            return 0, 0

        # Find which would collide after rename
        existing_keys = set(
            CrossReference.objects
            .filter(interchange_type=good_type)
            .values_list("unit_id", "cross_ref_number", flat=False)
        )

        to_delete_pks = []
        to_update_pks = []

        for row in bad_qs.values("pk", "unit_id", "cross_ref_number"):
            key = (row["unit_id"], row["cross_ref_number"])
            if key in existing_keys:
                to_delete_pks.append(row["pk"])
            else:
                to_update_pks.append(row["pk"])
                existing_keys.add(key)

        label = f"XR '{bad_type}' -> '{good_type}'"
        self.stdout.write(f"  {label}: {len(to_update_pks)} rename, {len(to_delete_pks)} dupe-delete")

        if not dry_run:
            with transaction.atomic():
                if to_delete_pks:
                    CrossReference.objects.filter(pk__in=to_delete_pks).delete()
                if to_update_pks:
                    CrossReference.objects.filter(pk__in=to_update_pks).update(
                        interchange_type=good_type
                    )

        return len(to_update_pks), len(to_delete_pks)

    # ── PartInterchange merge logic ────────────────────────────────────

    def _merge_pi(self, bad_source, good_source, dry_run):
        """
        Rename source_name from bad_source to good_source.
        Handles unique constraints: unique_part_xref_number_source and
        unique_together on (part, interchange_part).
        """
        bad_qs = PartInterchange.objects.filter(source_name=bad_source)
        count = bad_qs.count()
        if count == 0:
            return 0, 0

        # Check unique_part_xref_number_source: (part, interchange_number, source_name)
        existing_keys = set(
            PartInterchange.objects
            .filter(source_name=good_source)
            .values_list("part_id", "interchange_number", flat=False)
        )

        to_delete_pks = []
        to_update_pks = []

        for row in bad_qs.values("pk", "part_id", "interchange_number"):
            key = (row["part_id"], row["interchange_number"])
            if key in existing_keys:
                to_delete_pks.append(row["pk"])
            else:
                to_update_pks.append(row["pk"])
                existing_keys.add(key)

        label = f"PI '{bad_source}' -> '{good_source}'"
        self.stdout.write(f"  {label}: {len(to_update_pks)} rename, {len(to_delete_pks)} dupe-delete")

        if not dry_run:
            with transaction.atomic():
                if to_delete_pks:
                    PartInterchange.objects.filter(pk__in=to_delete_pks).delete()
                if to_update_pks:
                    PartInterchange.objects.filter(pk__in=to_update_pks).update(
                        source_name=good_source
                    )

        return len(to_update_pks), len(to_delete_pks)
