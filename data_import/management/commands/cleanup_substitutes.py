"""
Substitute table cleanup.

Unlike `cleanup_remaining_duplicates` (which targeted CrossReference's
PDF/Lester import noise), `catalog_substitute` is a near-pristine
FK-driven table.  A scan of all 67,851 rows found that:

  - 67,770 rows (99.88%) are FK-linked (substitute_unit_id populated)
    and substitute_number always matches substitute_unit.unit_number
    exactly.  No malformed parens, no 'Pg. NNN' page refs, no annotation
    pairs, no whitespace anomalies.
  - substitute_supplier and substitute_unit_type are EMPTY for every
    row -- no spelling, corp-suffix, or brand-subset variants to clean.
  - The unique_together = (unit, substitute_unit) constraint already
    prevents duplicate FK pairs; verified zero violations.

Only three rows need cleanup:

  Step 1 - Exact text-only duplicates.  Two pairs of identical rows
           where substitute_unit_id is NULL slipped past the
           unique_together constraint (since NULL != NULL in SQLite).
           In each pair the older row (no seed_id) is the user-created
           original; the newer row carries seed_id pointing back at the
           original id, indicating it was re-imported from a seed dump.
           Delete the newer (seed-id-bearing) duplicate.

  Step 2 - Self-substitute.  One row where unit_id == substitute_unit_id
           (id=25806, unit 103203 substitutes itself).  Logically
           meaningless; delete.

  Step 3 - Bidirectional pair dedup.  23,953 unordered (A,B) pairs are
           stored in both directions (A->B AND B->A).  The catalog UI
           queries substitutes via Q(unit=u) | Q(substitute_unit=u),
           so a single directional row already surfaces in both unit
           detail pages -- the inverse row is pure redundancy.  For
           every such pair, keep the row with the lower id and delete
           the higher-id inverse row.  Both substitute_unit_id fields
           must be non-NULL (text-only rows are skipped).

Usage:
    python manage.py cleanup_substitutes              # dry-run (default)
    python manage.py cleanup_substitutes --dry-run    # explicit
    python manage.py cleanup_substitutes --commit     # apply
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import List, Tuple

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from catalog.models import Substitute


class Command(BaseCommand):
    help = (
        "Substitute cleanup: delete exact text-only duplicates, "
        "delete self-substitutes, and dedup bidirectional A<->B pairs."
    )

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Report what would change without writing anything (default).",
        )
        mode.add_argument(
            "--commit",
            action="store_true",
            dest="commit",
            help="Apply changes inside a single transaction.",
        )

    # ================================================================== #
    # Main entry
    # ================================================================== #
    def handle(self, *args, **options):
        start = time.time()
        commit: bool = options["commit"]
        dry_run: bool = options["dry_run"]

        if not commit and not dry_run:
            dry_run = True
            self.stdout.write(self.style.WARNING(
                "No mode specified -- defaulting to --dry-run."
            ))
        mode_label = "COMMIT" if commit else "DRY-RUN"
        self.stdout.write(f"Mode: {mode_label}\n")
        self.stdout.flush()

        try:
            with transaction.atomic():
                before_total = Substitute.objects.count()
                self.stdout.write(
                    f"Starting Substitute rows: {before_total:,}\n"
                )
                self.stdout.flush()

                step1 = self._step1_exact_text_only_duplicates(commit)
                step2 = self._step2_self_substitutes(commit)
                step3 = self._step3_bidirectional_dedup(commit)

                if not commit:
                    transaction.set_rollback(True)

                after_total = (
                    Substitute.objects.count()
                    if commit
                    else before_total - (
                        step1["deleted"] + step2["deleted"] + step3["deleted"]
                    )
                )

        except Exception as exc:
            raise CommandError(
                f"Aborting and rolling back: {exc.__class__.__name__}: {exc}"
            ) from exc

        # ============================================================== #
        # Summary
        # ============================================================== #
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("FINAL SUMMARY")
        self.stdout.write("=" * 70)
        self.stdout.write(
            f"Step 1 (exact text-only duplicates): "
            f"{step1['deleted']:,} deleted"
        )
        self.stdout.write(
            f"Step 2 (self-substitutes):           "
            f"{step2['deleted']:,} deleted"
        )
        self.stdout.write(
            f"Step 3 (bidirectional A<->B dedup):  "
            f"{step3['deleted']:,} deleted"
        )
        total_deleted = (
            step1["deleted"] + step2["deleted"] + step3["deleted"]
        )
        self.stdout.write(
            f"\nTOTAL rows removed: {total_deleted:,}"
        )
        self.stdout.write(
            f"Substitute: {before_total:,} -> {after_total:,} "
            f"({after_total - before_total:+,})"
        )

        if not commit:
            self.stdout.write(self.style.WARNING(
                "\nDRY-RUN: no changes were made. "
                "Re-run with --commit to apply."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                "\nCOMMIT: changes applied successfully."
            ))

        elapsed = time.time() - start
        self.stdout.write(f"\nElapsed: {elapsed:.2f}s")
        self.stdout.flush()

    # ================================================================== #
    # Step 1 - Exact duplicates among text-only rows (FK is NULL).
    # SQLite's unique_together(unit, substitute_unit) treats two NULL
    # FKs as distinct, so identical text-only rows can sneak past it.
    # Keep the older row (smaller id with seed_id=NULL); delete the
    # newer re-imported copy.
    # ================================================================== #
    def _step1_exact_text_only_duplicates(self, commit: bool) -> dict:
        self.stdout.write(
            "\n--- Step 1: Exact text-only duplicates ---"
        )
        self.stdout.flush()

        # Find (unit_id, substitute_supplier, substitute_number) groups
        # with >1 row when substitute_unit_id IS NULL.  The supplier
        # column is empty for every row in the table today, but we
        # group by it anyway in case future rows actually use it.
        groups = (
            Substitute.objects
            .filter(substitute_unit_id__isnull=True)
            .values("unit_id", "substitute_supplier", "substitute_number")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        groups = list(groups)
        self.stdout.write(f"  Duplicate groups (FK NULL): {len(groups):,}")

        to_delete: List[int] = []
        sample: List[str] = []
        for g in groups:
            members = list(
                Substitute.objects
                .filter(
                    substitute_unit_id__isnull=True,
                    unit_id=g["unit_id"],
                    substitute_supplier=g["substitute_supplier"],
                    substitute_number=g["substitute_number"],
                )
                .order_by("id")
                .values("id", "seed_id", "created_at", "notes")
            )
            # Keep the FIRST (smallest id == oldest).
            keeper = members[0]
            for m in members[1:]:
                to_delete.append(m["id"])
                if len(sample) < 10:
                    sample.append(
                        f"unit={g['unit_id']} num='{g['substitute_number']}' "
                        f"DEL id={m['id']} (seed_id={m['seed_id']}), "
                        f"KEEP id={keeper['id']} (seed_id={keeper['seed_id']})"
                    )

        self.stdout.write(f"  Plan: delete {len(to_delete):,} duplicate rows")
        for s in sample:
            self.stdout.write(f"    {s}")
        self.stdout.flush()

        if commit:
            self._bulk_delete(to_delete)

        return {"deleted": len(to_delete)}

    # ================================================================== #
    # Step 2 - Self-substitute rows (unit_id == substitute_unit_id).
    # ================================================================== #
    def _step2_self_substitutes(self, commit: bool) -> dict:
        self.stdout.write("\n--- Step 2: Self-substitute rows ---")
        self.stdout.flush()

        # SQLite has no F() shortcut needed -- raw filter on equality
        # via .extra() is overkill; iterate the (small) candidate set.
        # Use raw SQL for clarity since the count is tiny.
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute(
                "SELECT id, unit_id, substitute_unit_id "
                "FROM catalog_substitute "
                "WHERE unit_id = substitute_unit_id"
            )
            rows = cur.fetchall()

        self.stdout.write(f"  Self-substitute rows: {len(rows)}")
        for rid, uid, sid in rows:
            self.stdout.write(f"    id={rid} unit={uid} substitute_unit={sid}")
        self.stdout.flush()

        ids = [r[0] for r in rows]
        if commit:
            self._bulk_delete(ids)

        return {"deleted": len(ids)}

    # ================================================================== #
    # Step 3 - Bidirectional pair dedup.
    # When the same unordered (A, B) pair is stored as BOTH A->B and
    # B->A directed rows, the UI's Q(unit=u)|Q(substitute_unit=u) query
    # already surfaces a single directed row on both unit pages, so the
    # inverse row is pure redundancy.  Keep the lower-id row, delete
    # the higher-id inverse.  FK NULL rows are skipped (text-only).
    #
    # Algorithm: load all FK-linked rows into memory (67k+ rows is
    # cheap), bucket by unordered key (min(u, s), max(u, s)), and for
    # every bucket that contains both directed orientations, drop all
    # rows except the lowest id in the bucket.
    # ================================================================== #
    def _step3_bidirectional_dedup(self, commit: bool) -> dict:
        self.stdout.write("\n--- Step 3: Bidirectional A<->B pair dedup ---")
        self.stdout.flush()

        rows = list(
            Substitute.objects
            .exclude(substitute_unit_id__isnull=True)
            .values_list("id", "unit_id", "substitute_unit_id")
        )
        self.stdout.write(f"  Scanning {len(rows):,} FK-linked rows...")
        self.stdout.flush()

        # Bucket by unordered pair.  members = list of (id, u, s).
        buckets: dict = defaultdict(list)
        for rid, u, s in rows:
            if u == s:
                continue  # self-substitute (handled in Step 2)
            key = (min(u, s), max(u, s))
            buckets[key].append((rid, u, s))

        to_delete: List[int] = []
        sample: List[str] = []
        pairs_processed = 0
        for key, members in buckets.items():
            if len(members) < 2:
                continue
            directions = {(u, s) for _rid, u, s in members}
            # Must contain BOTH (A->B) and (B->A) orientations.
            if (key[0], key[1]) not in directions:
                continue
            if (key[1], key[0]) not in directions:
                continue
            members.sort(key=lambda t: t[0])
            keeper = members[0]
            for m in members[1:]:
                to_delete.append(m[0])
                if len(sample) < 5:
                    sample.append(
                        f"pair (units {key[0]}<->{key[1]}): "
                        f"KEEP id={keeper[0]} ({keeper[1]}->{keeper[2]}), "
                        f"DEL id={m[0]} ({m[1]}->{m[2]})"
                    )
            pairs_processed += 1

        self.stdout.write(
            f"  Bidirectional pairs found: {pairs_processed:,}"
        )
        self.stdout.write(
            f"  Plan: delete {len(to_delete):,} higher-id inverse rows"
        )
        for s in sample:
            self.stdout.write(f"    {s}")
        self.stdout.flush()

        if commit:
            self._bulk_delete(to_delete)

        return {"deleted": len(to_delete)}

    # ================================================================== #
    # Bulk helpers
    # ================================================================== #
    def _bulk_delete(self, ids: List[int]) -> None:
        for i in range(0, len(ids), 1000):
            batch = ids[i:i + 1000]
            Substitute.objects.filter(id__in=batch).delete()
