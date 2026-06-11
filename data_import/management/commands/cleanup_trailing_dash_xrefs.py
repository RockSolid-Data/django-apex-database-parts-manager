"""
Fix cross-reference numbers broken across PDF lines (trailing dash).

Interchange PDFs sometimes split OEM numbers like ``F78Z-10346-AA`` across
lines, leaving ``F78Z-10346-`` in the database with the suffix wrongly
stored in interchange_type (e.g. ``AA``, ``AARM Ford``).

This command:
  1. Deletes trailing-dash fragments when the complete number already exists.
  2. Merges suffix from interchange_type into cross_ref_number when safe.
  3. Applies the same logic to PartInterchange.interchange_number.
  4. With ``--orphans``, removes unmergeable trailing-dash parser fragments.

Orphan deletion (--orphans) is safe when:
  - Same unit/part already has a non-trailing-dash number starting with the
    orphan prefix (any interchange type / source), OR
  - The fragment is a parser artifact: whitespace or extreme length in the
    number, manufacturer label ending in ``-``, two OEM segments concatenated,
    a duplicate trailing-dash sibling on the same unit+type, or a page-tail
    with no recoverable complete number anywhere in the database.

Rows skipped for manual review (--orphans only):
  - Clean-looking single OEM prefix, no same-scope or global complete exists,
    and none of the artifact signals above fire.

Usage:
    python manage.py cleanup_trailing_dash_xrefs --dry-run
    python manage.py cleanup_trailing_dash_xrefs --orphans --dry-run
    python manage.py cleanup_trailing_dash_xrefs --orphans
"""

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import CrossReference, PartInterchange

SUFFIX_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]*$")
SPACE_RE = re.compile(r"\s")
LONG_NUM_LEN = 40


def _split_type(interchange_type: str):
    """Return (suffix, manufacturer) when type embeds a line-break suffix."""
    text = (interchange_type or "").strip()
    if not text:
        return "", ""
    if " " in text:
        first, rest = text.split(" ", 1)
        if SUFFIX_RE.match(first) and len(first) <= 8:
            return first, rest.strip()
    if SUFFIX_RE.match(text) and len(text) <= 6:
        return text, ""
    return "", text


def _is_concatenated(num: str) -> bool:
    """True when two OEM segments were glued (e.g. B-X31-60-B-X33-52-)."""
    parts = [p for p in num.rstrip("-").split("-") if p]
    for i in range(2, len(parts)):
        if len(parts[i]) == 1 and parts[i].isalpha() and i + 1 < len(parts):
            return True
    return False


def _artifact_reasons(num: str, label: str) -> list[str]:
    reasons = []
    if SPACE_RE.search(num):
        reasons.append("spaces_in_number")
    if len(num) > LONG_NUM_LEN:
        reasons.append("contaminated_long")
    if (label or "").endswith("-"):
        reasons.append("broken_label")
    if _is_concatenated(num):
        reasons.append("concatenated_parts")
    return reasons


class Command(BaseCommand):
    help = "Merge or delete trailing-dash cross-reference numbers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report changes without saving.",
        )
        parser.add_argument(
            "--orphans",
            action="store_true",
            help="Also delete unmergeable trailing-dash parser fragments.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        orphans = options["orphans"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved.\n"))

        xr_stats = self._fix_cross_references(dry_run)
        pi_stats = self._fix_part_interchanges(dry_run)

        orphan_xr = orphan_pi = None
        if orphans:
            orphan_xr = self._cleanup_cross_reference_orphans(dry_run)
            orphan_pi = self._cleanup_part_interchange_orphans(dry_run)

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Summary ===\n"))
        self.stdout.write(
            f"  CrossReference deleted:  {xr_stats['deleted']:,}\n"
            f"  CrossReference merged:   {xr_stats['merged']:,}\n"
            f"  CrossReference skipped:  {xr_stats['skipped']:,}\n"
            f"  PartInterchange deleted: {pi_stats['deleted']:,}\n"
            f"  PartInterchange merged:  {pi_stats['merged']:,}\n"
            f"  PartInterchange skipped: {pi_stats['skipped']:,}\n"
        )
        if orphans:
            self.stdout.write(
                f"  Orphan XR deleted:       {orphan_xr['deleted']:,}\n"
                f"  Orphan XR manual review: {orphan_xr['manual']:,}\n"
                f"  Orphan PI deleted:       {orphan_pi['deleted']:,}\n"
                f"  Orphan PI manual review: {orphan_pi['manual']:,}\n"
            )

        remaining_xr = (
            CrossReference.objects.filter(cross_ref_number__endswith="-")
            .exclude(cross_ref_number="-")
            .count()
        )
        remaining_pi = (
            PartInterchange.objects.filter(interchange_number__endswith="-")
            .exclude(interchange_number="-")
            .count()
        )
        self.stdout.write(f"  Remaining trailing-dash xrefs: {remaining_xr:,}\n")
        self.stdout.write(f"  Remaining trailing-dash PI:    {remaining_pi:,}\n")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nNo changes saved (dry run).\n"))
        else:
            self.stdout.write(self.style.SUCCESS("\nDone.\n"))

    def _fix_cross_references(self, dry_run):
        trailing_qs = (
            CrossReference.objects.filter(cross_ref_number__endswith="-")
            .exclude(cross_ref_number="-")
            .order_by("id")
        )
        before = trailing_qs.count()
        self.stdout.write(f"\nCrossReference trailing-dash rows: {before:,}")

        deleted = merged = skipped = 0
        to_delete = []
        to_update = []

        existing = set(
            CrossReference.objects.values_list(
                "unit_id", "cross_ref_number", "interchange_type"
            )
        )

        for xr in trailing_qs.iterator(chunk_size=2000):
            num = xr.cross_ref_number
            suffix, mfr = _split_type(xr.interchange_type)

            if suffix:
                merged_num = num + suffix
                merged_type = mfr or xr.interchange_type
            else:
                merged_num = None
                merged_type = xr.interchange_type

            # Prefer deleting when any complete variant exists on the unit.
            if merged_num:
                if CrossReference.objects.filter(
                    unit_id=xr.unit_id, cross_ref_number=merged_num
                ).exclude(pk=xr.pk).exists():
                    to_delete.append(xr.pk)
                    deleted += 1
                    continue
                key = (xr.unit_id, merged_num, merged_type)
                if key in existing:
                    to_delete.append(xr.pk)
                    deleted += 1
                    continue
                to_update.append((xr.pk, merged_num, merged_type))
                existing.add(key)
                merged += 1
                continue

            # Drop fragment when a longer same-prefix number exists on the unit
            # (any interchange type — suffix may sit on a differently labeled row).
            prefix = num[:-1]
            if CrossReference.objects.filter(
                unit_id=xr.unit_id,
                cross_ref_number__startswith=prefix,
            ).exclude(pk=xr.pk).exclude(cross_ref_number__endswith="-").exists():
                to_delete.append(xr.pk)
                deleted += 1
                continue

            skipped += 1

        self.stdout.write(
            f"  plan: delete={deleted:,} merge={merged:,} skip={skipped:,}"
        )

        if not dry_run:
            with transaction.atomic():
                if to_delete:
                    CrossReference.objects.filter(pk__in=to_delete).delete()
                for pk, merged_num, merged_type in to_update:
                    CrossReference.objects.filter(pk=pk).update(
                        cross_ref_number=merged_num,
                        interchange_type=merged_type,
                    )

        return {"deleted": deleted, "merged": merged, "skipped": skipped}

    def _fix_part_interchanges(self, dry_run):
        trailing_qs = (
            PartInterchange.objects.filter(interchange_number__endswith="-")
            .exclude(interchange_number="-")
            .order_by("id")
        )
        before = trailing_qs.count()
        self.stdout.write(f"\nPartInterchange trailing-dash rows: {before:,}")

        deleted = merged = skipped = 0
        to_delete = []
        to_update = []

        existing = set(
            PartInterchange.objects.values_list(
                "part_id", "interchange_number", "source_name"
            )
        )

        for pi in trailing_qs.iterator(chunk_size=2000):
            num = pi.interchange_number
            suffix, mfr = _split_type(pi.source_name)

            if suffix:
                merged_num = num + suffix
                merged_source = mfr or pi.source_name
            else:
                merged_num = None
                merged_source = pi.source_name

            if merged_num:
                if PartInterchange.objects.filter(
                    part_id=pi.part_id, interchange_number=merged_num
                ).exclude(pk=pi.pk).exists():
                    to_delete.append(pi.pk)
                    deleted += 1
                    continue
                key = (pi.part_id, merged_num, merged_source)
                if key in existing:
                    to_delete.append(pi.pk)
                    deleted += 1
                    continue
                to_update.append((pi.pk, merged_num, merged_source))
                existing.add(key)
                merged += 1
                continue

            prefix = num[:-1]
            if PartInterchange.objects.filter(
                part_id=pi.part_id,
                interchange_number__startswith=prefix,
            ).exclude(pk=pi.pk).exclude(interchange_number__endswith="-").exists():
                to_delete.append(pi.pk)
                deleted += 1
                continue

            skipped += 1

        self.stdout.write(
            f"  plan: delete={deleted:,} merge={merged:,} skip={skipped:,}"
        )

        if not dry_run:
            with transaction.atomic():
                if to_delete:
                    PartInterchange.objects.filter(pk__in=to_delete).delete()
                for pk, merged_num, merged_source in to_update:
                    PartInterchange.objects.filter(pk=pk).update(
                        interchange_number=merged_num,
                        source_name=merged_source,
                    )

        return {"deleted": deleted, "merged": merged, "skipped": skipped}

    def _cleanup_cross_reference_orphans(self, dry_run):
        trailing_qs = (
            CrossReference.objects.filter(cross_ref_number__endswith="-")
            .exclude(cross_ref_number="-")
            .order_by("id")
        )
        before = trailing_qs.count()
        self.stdout.write(f"\nCrossReference orphan pass: {before:,} remaining")

        deleted = manual = 0
        to_delete = []
        manual_rows = []

        for xr in trailing_qs.iterator(chunk_size=2000):
            num = xr.cross_ref_number
            prefix = num[:-1]
            label = xr.interchange_type

            scope_complete = CrossReference.objects.filter(
                unit_id=xr.unit_id,
                cross_ref_number__startswith=prefix,
            ).exclude(pk=xr.pk).exclude(cross_ref_number__endswith="-").exists()

            if scope_complete:
                to_delete.append(xr.pk)
                deleted += 1
                continue

            reasons = _artifact_reasons(num, label)
            sibling_dash = CrossReference.objects.filter(
                unit_id=xr.unit_id,
                interchange_type=label,
                cross_ref_number__endswith="-",
            ).exclude(pk=xr.pk).exclude(cross_ref_number="-").exists()
            if sibling_dash:
                reasons.append("sibling_dash_fragment")

            global_complete = CrossReference.objects.filter(
                cross_ref_number__startswith=prefix,
            ).exclude(pk=xr.pk).exclude(cross_ref_number__endswith="-").exists()

            if reasons or global_complete:
                to_delete.append(xr.pk)
                deleted += 1
                continue

            manual += 1
            manual_rows.append((xr.pk, num, label))

        self.stdout.write(
            f"  plan: delete={deleted:,} manual_review={manual:,}"
        )
        if manual_rows:
            self.stdout.write("  manual review rows (sample):")
            for pk, num, label in manual_rows[:15]:
                self.stdout.write(f"    id={pk} num={num!r} type={label!r}")
            if len(manual_rows) > 15:
                self.stdout.write(f"    ... and {len(manual_rows) - 15} more")

        if not dry_run and to_delete:
            with transaction.atomic():
                CrossReference.objects.filter(pk__in=to_delete).delete()

        return {"deleted": deleted, "manual": manual}

    def _cleanup_part_interchange_orphans(self, dry_run):
        trailing_qs = (
            PartInterchange.objects.filter(interchange_number__endswith="-")
            .exclude(interchange_number="-")
            .order_by("id")
        )
        before = trailing_qs.count()
        self.stdout.write(f"\nPartInterchange orphan pass: {before:,} remaining")

        deleted = manual = 0
        to_delete = []
        manual_rows = []

        for pi in trailing_qs.iterator(chunk_size=2000):
            num = pi.interchange_number
            prefix = num[:-1]
            label = pi.source_name

            scope_complete = PartInterchange.objects.filter(
                part_id=pi.part_id,
                interchange_number__startswith=prefix,
            ).exclude(pk=pi.pk).exclude(interchange_number__endswith="-").exists()

            if scope_complete:
                to_delete.append(pi.pk)
                deleted += 1
                continue

            reasons = _artifact_reasons(num, label)
            global_complete = PartInterchange.objects.filter(
                interchange_number__startswith=prefix,
            ).exclude(pk=pi.pk).exclude(interchange_number__endswith="-").exists()

            if reasons or global_complete:
                to_delete.append(pi.pk)
                deleted += 1
                continue

            manual += 1
            manual_rows.append((pi.pk, num, label))

        self.stdout.write(
            f"  plan: delete={deleted:,} manual_review={manual:,}"
        )
        if manual_rows:
            self.stdout.write("  manual review rows:")
            for pk, num, label in manual_rows:
                self.stdout.write(f"    id={pk} num={num!r} src={label!r}")

        if not dry_run and to_delete:
            with transaction.atomic():
                PartInterchange.objects.filter(pk__in=to_delete).delete()

        return {"deleted": deleted, "manual": manual}
