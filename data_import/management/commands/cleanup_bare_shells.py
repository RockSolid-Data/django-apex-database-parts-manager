"""
Clean up bare-shell Unit records created by the interchange importer.

A "bare shell" is a Unit with no yt_number, no manufacturer, and no
unit_type_category — it was auto-created solely as an anchor for
CrossReference rows.

Three categories:
  Cat 2 — unit_number overlaps a real Unit (matches yt_number of a populated Unit)
          -> move xrefs to the real Unit, delete the shell
  Cat 1 — unit_number matches a Part.yt_number
          -> migrate xrefs to PartInterchange, delete the shell
  Cat 3 — matches nothing (pure PDF interchange numbers)
          -> left alone (they carry useful xref data)

Usage:
    python manage.py cleanup_bare_shells
    python manage.py cleanup_bare_shells --dry-run
"""

import time

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.models import Q

from catalog.models import CrossReference, Part, PartInterchange, Unit

BATCH = 2000


class Command(BaseCommand):
    help = "Clean up bare-shell Unit records from interchange imports."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen without making changes.",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        dry = options["dry_run"]
        t0 = time.time()

        self.stdout.write("\n" + "=" * 65)
        self.stdout.write("BARE-SHELL CLEANUP" + ("  [DRY RUN]" if dry else ""))
        self.stdout.write("=" * 65)

        before = self._snapshot("BEFORE")

        # ---- identify bare shells ----
        bare_q = Q(yt_number="") & Q(manufacturer="") & Q(unit_type_category="")
        bare_qs = Unit.objects.filter(bare_q)
        bare_numbers = dict(bare_qs.values_list("unit_number", "pk"))
        self.stdout.write(f"\nBare shells found: {len(bare_numbers):,}")

        # ---- build category maps ----
        part_yt_map = dict(
            Part.objects.exclude(yt_number="")
            .values_list("yt_number", "pk")
        )
        real_yt_map = dict(
            Unit.objects.exclude(bare_q)
            .exclude(yt_number="")
            .values_list("yt_number", "pk")
        )

        cat2 = {}  # bare_unit_number -> real_unit_pk
        cat1 = {}  # bare_unit_number -> part_pk
        cat3 = set()

        for num, bare_pk in bare_numbers.items():
            if num in real_yt_map:
                cat2[num] = real_yt_map[num]
            elif num in part_yt_map:
                cat1[num] = part_yt_map[num]
            else:
                cat3.add(num)

        self.stdout.write(f"  Cat 2 (overlap real Unit): {len(cat2):,}")
        self.stdout.write(f"  Cat 1 (match Part):        {len(cat1):,}")
        self.stdout.write(f"  Cat 3 (match nothing):     {len(cat3):,}")

        if not dry:
            self._step1_overlap_real_units(bare_numbers, cat2)
            self._step2_match_parts(bare_numbers, cat1)
            self._step3_match_nothing(bare_numbers, cat3)

        after = self._snapshot("AFTER" if not dry else "CURRENT (no changes)")
        self._verify(before, after, cat2, cat1, dry)

        elapsed = time.time() - t0
        self.stdout.write(f"\nTotal elapsed: {elapsed:.1f}s\n")

    # ------------------------------------------------------------------
    # Step 1  — bare shells that overlap a real Unit
    # ------------------------------------------------------------------
    def _step1_overlap_real_units(self, bare_numbers, cat2):
        self.stdout.write("\n" + "-" * 65)
        self.stdout.write("STEP 1: Move xrefs from 671 overlapping bare shells -> real Units")
        self.stdout.write("-" * 65)
        t0 = time.time()

        moved = 0
        skipped_dup = 0
        nulled_refs = 0
        deleted_shells = 0

        # Pre-load existing xref keys for all target real units to detect dupes
        real_unit_pks = set(cat2.values())
        existing_keys = set()
        for chunk_start in range(0, len(real_unit_pks), BATCH):
            chunk = list(real_unit_pks)[chunk_start : chunk_start + BATCH]
            existing_keys.update(
                CrossReference.objects.filter(unit_id__in=chunk)
                .values_list("unit_id", "cross_ref_number", "interchange_type")
            )

        for i, (num, real_pk) in enumerate(cat2.items(), 1):
            bare_pk = bare_numbers[num]

            with transaction.atomic():
                # Gather xrefs owned by the bare shell
                xrefs = list(
                    CrossReference.objects.filter(unit_id=bare_pk)
                    .values_list("id", "cross_ref_number", "interchange_type")
                )

                ids_to_move = []
                ids_to_delete = []
                for xid, crn, itype in xrefs:
                    key = (real_pk, crn, itype)
                    if key in existing_keys:
                        ids_to_delete.append(xid)
                        skipped_dup += 1
                    else:
                        ids_to_move.append(xid)
                        existing_keys.add(key)

                # Move non-duplicate xrefs
                if ids_to_move:
                    CrossReference.objects.filter(pk__in=ids_to_move).update(
                        unit_id=real_pk
                    )
                    moved += len(ids_to_move)

                # Delete xrefs that would violate unique constraint
                if ids_to_delete:
                    CrossReference.objects.filter(pk__in=ids_to_delete).delete()

                # Null out cross_ref_unit FKs from other xrefs pointing here
                n = CrossReference.objects.filter(cross_ref_unit_id=bare_pk).update(
                    cross_ref_unit_id=real_pk
                )
                nulled_refs += n

                # Delete the bare shell
                Unit.objects.filter(pk=bare_pk).delete()
                deleted_shells += 1

            if i % 100 == 0:
                self.stdout.write(f"  Progress: {i}/{len(cat2)}")

        self.stdout.write(f"  Xrefs moved:       {moved:,}")
        self.stdout.write(f"  Dup xrefs removed: {skipped_dup:,}")
        self.stdout.write(f"  cross_ref_unit redirected: {nulled_refs:,}")
        self.stdout.write(f"  Bare shells deleted: {deleted_shells:,}")
        self.stdout.write(f"  Time: {time.time() - t0:.1f}s")

    # ------------------------------------------------------------------
    # Step 2  — bare shells whose number matches a Part.yt_number
    # ------------------------------------------------------------------
    def _step2_match_parts(self, bare_numbers, cat1):
        self.stdout.write("\n" + "-" * 65)
        self.stdout.write("STEP 2: Migrate xrefs from 23K bare shells -> PartInterchange")
        self.stdout.write("-" * 65)
        t0 = time.time()

        migrated = 0
        skipped_dup = 0
        nulled_refs = 0
        deleted_shells = 0

        # Pre-load existing PartInterchange keys so we can skip duplicates
        existing_pi_keys = set(
            PartInterchange.objects.values_list(
                "part_id", "interchange_number", "source_name"
            )
        )
        self.stdout.write(f"  Pre-loaded {len(existing_pi_keys):,} existing PartInterchange keys")

        # Process in chunks of bare shells
        items = list(cat1.items())
        pi_batch = []

        for i, (num, part_pk) in enumerate(items, 1):
            bare_pk = bare_numbers[num]

            # Gather xrefs for this bare shell
            xrefs = list(
                CrossReference.objects.filter(unit_id=bare_pk)
                .values("cross_ref_number", "interchange_type", "notes")
            )

            for xr in xrefs:
                key = (part_pk, xr["cross_ref_number"][:100], xr["interchange_type"][:150])
                if key in existing_pi_keys:
                    skipped_dup += 1
                    continue
                existing_pi_keys.add(key)
                pi_batch.append(
                    PartInterchange(
                        part_id=part_pk,
                        interchange_number=xr["cross_ref_number"][:100],
                        source_name=xr["interchange_type"][:150],
                        notes=xr["notes"],
                    )
                )

            if len(pi_batch) >= BATCH:
                PartInterchange.objects.bulk_create(pi_batch, ignore_conflicts=True)
                migrated += len(pi_batch)
                pi_batch = []

            if i % 5000 == 0:
                self.stdout.write(
                    f"  Progress: {i:,}/{len(items):,}  |  "
                    f"migrated {migrated:,}  |  dupes {skipped_dup:,}"
                )

        if pi_batch:
            PartInterchange.objects.bulk_create(pi_batch, ignore_conflicts=True)
            migrated += len(pi_batch)

        self.stdout.write(f"  PartInterchanges created: {migrated:,}")
        self.stdout.write(f"  Duplicate skipped:        {skipped_dup:,}")

        # Null out cross_ref_unit FKs pointing to these bare shells, then delete
        self.stdout.write("  Nulling cross_ref_unit FKs and deleting bare shells...")
        bare_pks = [bare_numbers[num] for num in cat1]

        for chunk_start in range(0, len(bare_pks), BATCH):
            chunk = bare_pks[chunk_start : chunk_start + BATCH]
            with transaction.atomic():
                n = CrossReference.objects.filter(
                    cross_ref_unit_id__in=chunk
                ).update(cross_ref_unit=None)
                nulled_refs += n
                Unit.objects.filter(pk__in=chunk).delete()
                deleted_shells += len(chunk)

            if (chunk_start // BATCH) % 5 == 0 and chunk_start > 0:
                self.stdout.write(
                    f"  Delete progress: {chunk_start + len(chunk):,}/{len(bare_pks):,}"
                )

        self.stdout.write(f"  cross_ref_unit nulled: {nulled_refs:,}")
        self.stdout.write(f"  Bare shells deleted:   {deleted_shells:,}")
        self.stdout.write(f"  Time: {time.time() - t0:.1f}s")

    # ------------------------------------------------------------------
    # Step 3  — bare shells that match nothing  (keep them)
    # ------------------------------------------------------------------
    def _step3_match_nothing(self, bare_numbers, cat3):
        self.stdout.write("\n" + "-" * 65)
        self.stdout.write(
            f"STEP 3: {len(cat3):,} bare shells match nothing — keeping as-is"
        )
        self.stdout.write("-" * 65)
        self.stdout.write(
            "  These carry cross-reference data useful for lookups.  No action taken."
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _snapshot(self, label):
        units = Unit.objects.count()
        xrefs = CrossReference.objects.count()
        pi = PartInterchange.objects.count()
        parts = Part.objects.count()
        self.stdout.write(f"\n  {label}:")
        self.stdout.write(f"    Units:             {units:>10,}")
        self.stdout.write(f"    CrossReferences:   {xrefs:>10,}")
        self.stdout.write(f"    PartInterchanges:  {pi:>10,}")
        self.stdout.write(f"    Parts:             {parts:>10,}")
        return {"units": units, "xrefs": xrefs, "pi": pi, "parts": parts}

    def _verify(self, before, after, cat2, cat1, dry):
        self.stdout.write("\n" + "=" * 65)
        self.stdout.write("VERIFICATION")
        self.stdout.write("=" * 65)

        if dry:
            self.stdout.write("  (dry run — no changes to verify)")
            return

        shells_removed = len(cat2) + len(cat1)
        expected_units = before["units"] - shells_removed
        self.stdout.write(
            f"  Units:  {before['units']:,} -> {after['units']:,}  "
            f"(expected {expected_units:,})  "
            + ("OK" if after["units"] == expected_units else "MISMATCH")
        )

        xref_delta = before["xrefs"] - after["xrefs"]
        pi_delta = after["pi"] - before["pi"]
        self.stdout.write(
            f"  CrossRef removed:      {xref_delta:,}")
        self.stdout.write(
            f"  PartInterchange added: {pi_delta:,}")
        self.stdout.write(
            f"  Net interchange data:  {pi_delta - xref_delta:+,}  "
            "(negative = dupes consolidated, not data loss)"
        )
