"""
Fix common staging-unit data quality issues.

Targets non-bare units (have manufacturer and/or yt_number) with:
  - blank unit_type_category
  - missing yt_number (application-import shells)
  - trailing commas in unit_number
  - test placeholder units

Usage:
    python manage.py cleanup_staging_unit_quality --dry-run
    python manage.py cleanup_staging_unit_quality
    python manage.py cleanup_staging_unit_quality --delete-test-units
"""

import re

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from catalog.models import ApplicationUnit, CrossReference, Unit

BARE_Q = Q(yt_number="") & Q(manufacturer="") & Q(unit_type_category="")

GENERATOR_MFRS = {
    "MAHLE",
    "Prestolite",
    "General Electric",
    "Hitachi",
    "Letrika",
    "United Technologies",
    "Polaris",
    "Yamaha",
    "Unknown",
}

NUMERIC_GEN_RE = re.compile(r"^[45]\d{5}$")


def _infer_category(unit: Unit) -> str:
    family = (unit.family or "").strip().upper()
    if family == "TILT&TRIM":
        return "Motor"
    if family in ("DD", "PMGR"):
        return "Starter"
    yt = (unit.yt_number or "").strip()
    if NUMERIC_GEN_RE.match(yt):
        return "Generator"
    if yt.isdigit() and len(yt) >= 6 and unit.manufacturer in GENERATOR_MFRS:
        return "Generator"
    if unit.unit_type_id and unit.unit_type:
        return unit.unit_type.name
    if unit.manufacturer == "Romaine Electric":
        return "Alternator"
    return ""


def _clean_unit_number(raw: str) -> str:
    return (raw or "").strip().rstrip(",")


def _derive_yt_number(unit: Unit) -> str:
    """Derive YouTech number from unit_number or interchange xrefs."""
    clean = _clean_unit_number(unit.unit_number)
    if not clean:
        return ""

    # Tilt/trim motors imported with numeric catalog number as unit_number.
    if unit.unit_type_category == "Motor" and re.match(r"^45\d{4}$", clean):
        return clean

    host = (
        CrossReference.objects.filter(cross_ref_number=clean)
        .exclude(unit__yt_number="")
        .select_related("unit")
        .order_by("unit_id")
        .first()
    )
    return host.unit.yt_number if host else ""


class Command(BaseCommand):
    help = "Fix blank categories, missing yt_numbers, and test units in staging."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report changes without saving.",
        )
        parser.add_argument(
            "--delete-test-units",
            action="store_true",
            help="Delete test placeholder units (unit_number or yt_number is 'test').",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        delete_test = options["delete_test_units"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved.\n"))

        comma_fixed = self._fix_trailing_commas(dry_run)
        cat_fixed = self._fix_blank_categories(dry_run)
        yt_fixed = self._fix_missing_yt_numbers(dry_run)
        test_deleted = self._delete_test_units(dry_run, delete_test)

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Summary ===\n"))
        self.stdout.write(f"  unit_number commas stripped: {comma_fixed:,}\n")
        self.stdout.write(f"  unit_type_category assigned: {cat_fixed:,}\n")
        self.stdout.write(f"  yt_number derived:           {yt_fixed:,}\n")
        self.stdout.write(f"  test units deleted:          {test_deleted:,}\n")

        bare_excluded = Unit.objects.exclude(BARE_Q)
        remaining_blank_cat = bare_excluded.filter(unit_type_category="").count()
        remaining_no_yt = bare_excluded.filter(yt_number="").count()
        remaining_test = Unit.objects.filter(
            Q(unit_number__iexact="test") | Q(yt_number__iexact="test")
        ).count()

        self.stdout.write(f"\n  Remaining blank category (non-bare): {remaining_blank_cat:,}\n")
        self.stdout.write(f"  Remaining missing yt_number (non-bare): {remaining_no_yt:,}\n")
        self.stdout.write(f"  Remaining test placeholders: {remaining_test:,}\n")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nNo changes saved (dry run).\n"))
        else:
            self.stdout.write(self.style.SUCCESS("\nDone.\n"))

    def _fix_trailing_commas(self, dry_run):
        qs = Unit.objects.filter(unit_number__endswith=",").exclude(BARE_Q)
        count = qs.count()
        self.stdout.write(f"\nunit_number trailing commas: {count:,}")

        stripped = merged = 0
        for unit in qs.iterator(chunk_size=500):
            clean = _clean_unit_number(unit.unit_number)
            if clean == unit.unit_number:
                continue

            keeper = (
                Unit.objects.filter(unit_number=clean)
                .exclude(pk=unit.pk)
                .first()
            )
            if keeper:
                merged += 1
                if not dry_run:
                    with transaction.atomic():
                        keeper_apps = set(
                            ApplicationUnit.objects.filter(unit_id=keeper.pk)
                            .values_list("application_id", flat=True)
                        )
                        for link in ApplicationUnit.objects.filter(unit_id=unit.pk):
                            if link.application_id in keeper_apps:
                                link.delete()
                            else:
                                link.unit_id = keeper.pk
                                link.save(update_fields=["unit_id"])
                                keeper_apps.add(link.application_id)
                        unit.delete()
            else:
                stripped += 1
                if not dry_run:
                    unit.unit_number = clean
                    unit.save(update_fields=["unit_number"])

        self.stdout.write(f"  strip comma: {stripped:,}  merge into twin: {merged:,}")
        return stripped + merged

    def _fix_blank_categories(self, dry_run):
        qs = (
            Unit.objects.filter(unit_type_category="")
            .exclude(BARE_Q)
            .select_related("unit_type")
        )
        count = qs.count()
        self.stdout.write(f"\nblank unit_type_category (non-bare): {count:,}")

        planned = []
        for unit in qs.iterator(chunk_size=500):
            cat = _infer_category(unit)
            if cat:
                planned.append((unit.pk, cat))

        self.stdout.write(f"  assignable: {len(planned):,}")
        if dry_run or not planned:
            return len(planned)

        with transaction.atomic():
            for pk, cat in planned:
                Unit.objects.filter(pk=pk).update(unit_type_category=cat)
        return len(planned)

    def _fix_missing_yt_numbers(self, dry_run):
        qs = Unit.objects.filter(yt_number="").exclude(BARE_Q).exclude(unit_number="")
        count = qs.count()
        self.stdout.write(f"\nmissing yt_number (non-bare): {count:,}")

        planned = []
        for unit in qs.iterator(chunk_size=500):
            yt = _derive_yt_number(unit)
            if yt:
                planned.append((unit.pk, yt))

        self.stdout.write(f"  derivable from xref lookup: {len(planned):,}")
        if dry_run or not planned:
            return len(planned)

        with transaction.atomic():
            for pk, yt in planned:
                Unit.objects.filter(pk=pk).update(yt_number=yt[:100])
        return len(planned)

    def _delete_test_units(self, dry_run, enabled):
        qs = Unit.objects.filter(
            Q(unit_number__iexact="test") | Q(yt_number__iexact="test")
        )
        count = qs.count()
        self.stdout.write(f"\ntest placeholder units: {count:,}")

        if not enabled:
            self.stdout.write("  (skipped — pass --delete-test-units to remove)")
            return 0

        if dry_run:
            for u in qs:
                self.stdout.write(
                    f"  would delete pk={u.pk} cat={u.unit_type_category!r} "
                    f"xrefs={u.cross_references.count()}"
                )
            return count

        deleted = 0
        with transaction.atomic():
            for unit in qs:
                ApplicationUnit.objects.filter(unit_id=unit.pk).delete()
                CrossReference.objects.filter(unit_id=unit.pk).delete()
                unit.delete()
                deleted += 1
        return deleted
