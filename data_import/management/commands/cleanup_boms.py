"""
Clean up catalog_bom and catalog_bomitem tables.

Two known issues are addressed by three ordered sub-steps:
  3a — Delete phantom empty BOMItems (yt_number='' AND description=''
       AND j_and_n=''). Items with only YT missing but a real
       description are reported as warnings and kept intact.
  3b — Merge duplicate BOMs per unit. For every unit_id with more than
       one BOM row, the BOM with the most items (lowest id breaks ties)
       becomes the canonical BOM. Items from secondary BOMs are either
       reassigned to the canonical BOM or, if the canonical already has
       a matching item (by yt_number, falling back to description),
       deleted. The now-empty secondary BOM is then removed.
  3c — Delete any BOM that ends up with zero BOMItems (both unit-linked
       and orphaned).

Default mode is --dry-run (no DB writes). Use --commit to apply the
changes inside a single transaction.

Usage:
    python manage.py cleanup_boms                  # dry-run (default)
    python manage.py cleanup_boms --commit         # apply changes
    python manage.py cleanup_boms --limit 500      # restrict to first 500 BOMs
    python manage.py cleanup_boms --only-step 1    # only run step 3a
"""

import time
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Q

from catalog.models import BOM, BOMItem


PHANTOM_FILTER = Q(yt_number="", description="", j_and_n="")
WARN_FILTER = Q(yt_number="") & ~Q(description="")

STEP_LABELS = {1: "3a", 2: "3b", 3: "3c"}


class Command(BaseCommand):
    help = (
        "Clean up phantom BOMItems and duplicate/empty BOMs in "
        "catalog_bom / catalog_bomitem. Defaults to --dry-run."
    )

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing (default).",
        )
        mode.add_argument(
            "--commit",
            action="store_true",
            help="Apply changes inside a single transaction.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Process only the first N BOMs (ordered by id). For testing.",
        )
        parser.add_argument(
            "--only-step",
            type=int,
            choices=[1, 2, 3],
            default=None,
            help="Run only the specified sub-step (1=3a, 2=3b, 3=3c).",
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        commit = bool(options["commit"])
        limit = options["limit"]
        only_step = options["only_step"]

        if limit is not None and limit <= 0:
            raise CommandError("--limit must be a positive integer")

        mode_label = "COMMIT" if commit else "DRY-RUN"

        bom_id_subset = None
        if limit is not None:
            bom_id_subset = list(
                BOM.objects.order_by("id").values_list("id", flat=True)[:limit]
            )

        starting_boms = BOM.objects.count()
        starting_items = BOMItem.objects.count()

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"cleanup_boms  mode={mode_label}"
                + (f"  only-step={STEP_LABELS[only_step]}" if only_step else "")
                + (f"  limit={limit}" if limit is not None else "")
            )
        )
        self.stdout.write(
            f"  Starting counts: BOMs={starting_boms:,}  "
            f"BOMItems={starting_items:,}"
        )
        if bom_id_subset is not None:
            self.stdout.write(
                f"  --limit applied: restricted scope to "
                f"{len(bom_id_subset):,} BOM(s) (by id)."
            )
        self.stdout.write("")

        results = {"3a": {}, "3b": {}, "3c": {}}
        grand_start = time.perf_counter()

        if commit:
            with transaction.atomic():
                self._run_steps(results, only_step, bom_id_subset, commit=True)
        else:
            self._run_steps(results, only_step, bom_id_subset, commit=False)

        grand_elapsed = time.perf_counter() - grand_start
        self._print_summary(
            results, grand_elapsed, commit,
            starting_boms=starting_boms,
            starting_items=starting_items,
        )

    # ------------------------------------------------------------------
    # Step dispatch
    # ------------------------------------------------------------------
    def _run_steps(self, results, only_step, bom_id_subset, commit):
        if only_step in (None, 1):
            results["3a"] = self._step_3a(bom_id_subset, commit)
        if only_step in (None, 2):
            results["3b"] = self._step_3b(bom_id_subset, commit)
        if only_step in (None, 3):
            # In dry-run we must exclude BOMs that step 3b would delete
            # so we don't double-count them. In --commit mode those rows
            # are already gone by the time 3c runs, so passing the set
            # is harmless.
            already_doomed = results.get("3b", {}).get(
                "secondary_ids", set()
            )
            results["3c"] = self._step_3c(
                bom_id_subset, commit, exclude_ids=already_doomed
            )

    # ------------------------------------------------------------------
    # Step 3a — Delete phantom empty BOMItems
    # ------------------------------------------------------------------
    def _step_3a(self, bom_id_subset, commit):
        start = time.perf_counter()
        self.stdout.write(
            self.style.NOTICE("--- Step 3a: Delete phantom empty BOMItems ---")
        )

        qs = BOMItem.objects.filter(PHANTOM_FILTER)
        warn_qs = BOMItem.objects.filter(WARN_FILTER)
        if bom_id_subset is not None:
            qs = qs.filter(bom_id__in=bom_id_subset)
            warn_qs = warn_qs.filter(bom_id__in=bom_id_subset)

        phantom_count = qs.count()
        warn_count = warn_qs.count()

        self.stdout.write(
            f"  Phantom items (yt='' AND desc='' AND j&n=''):   "
            f"{phantom_count:,}"
        )
        self.stdout.write(
            f"  WARN  items (yt='' but desc!='' — kept intact): "
            f"{warn_count:,}"
        )

        examples = list(
            qs.order_by("id")[:10].values(
                "id", "bom_id", "bom__name", "part_id"
            )
        )
        if examples:
            self.stdout.write("  Examples (first 10):")
            for ex in examples:
                self.stdout.write(
                    f"    BOMItem id={ex['id']}  part_id={ex['part_id']}  "
                    f"-> BOM id={ex['bom_id']}  name={ex['bom__name']!r}"
                )

        deleted = 0
        if commit and phantom_count > 0:
            self.stdout.write("  Deleting in batches of 1000...")
            while True:
                batch_ids = list(qs.values_list("id", flat=True)[:1000])
                if not batch_ids:
                    break
                n, _ = BOMItem.objects.filter(id__in=batch_ids).delete()
                deleted += n
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Deleted {deleted:,} phantom BOMItems."
                )
            )

        elapsed = time.perf_counter() - start
        self.stdout.write(f"  Step 3a elapsed: {elapsed:.2f}s")
        self.stdout.write("")
        return {
            "phantom_count": phantom_count,
            "warn_count": warn_count,
            "deleted": deleted,
            "elapsed": elapsed,
        }

    # ------------------------------------------------------------------
    # Step 3b — Merge duplicate BOMs per unit
    # ------------------------------------------------------------------
    def _step_3b(self, bom_id_subset, commit):
        start = time.perf_counter()
        self.stdout.write(
            self.style.NOTICE(
                "--- Step 3b: Merge duplicate BOMs per unit ---"
            )
        )

        bom_qs = BOM.objects.all()
        if bom_id_subset is not None:
            bom_qs = bom_qs.filter(id__in=bom_id_subset)

        dup_unit_ids = list(
            bom_qs.exclude(unit_id__isnull=True)
            .values("unit_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
            .values_list("unit_id", flat=True)
        )

        n_units = len(dup_unit_ids)
        self.stdout.write(f"  Units with duplicate BOMs: {n_units:,}")

        if n_units == 0:
            elapsed = time.perf_counter() - start
            self.stdout.write(f"  Step 3b elapsed: {elapsed:.2f}s")
            self.stdout.write("")
            return {
                "units_with_dups": 0,
                "boms_to_merge": 0,
                "items_moved": 0,
                "items_deleted": 0,
                "elapsed": elapsed,
            }

        # Load the BOMs in those duplicate groups, restricted to the subset
        # if --limit is in play. Annotate item count so we can pick canonical.
        group_qs = (
            bom_qs.filter(unit_id__in=dup_unit_ids)
            .annotate(_item_count=Count("items"))
            .order_by("unit_id", "-_item_count", "id")
        )

        groups = defaultdict(list)
        for bom in group_qs.iterator(chunk_size=2000):
            groups[bom.unit_id].append(bom)

        boms_to_merge = 0
        items_moved = 0
        items_deleted = 0
        examples_shown = 0
        processed = 0
        secondary_ids = set()

        for unit_id, boms in groups.items():
            if len(boms) < 2:
                continue

            canonical = boms[0]
            secondaries = boms[1:]

            canonical_keys = self._build_key_set(canonical.id)

            group_moved = 0
            group_deleted = 0
            for sec in secondaries:
                secondary_ids.add(sec.id)
                sec_items = list(
                    BOMItem.objects.filter(bom_id=sec.id).only(
                        "id", "yt_number", "description"
                    )
                )
                for item in sec_items:
                    key = self._item_key(item)
                    if key in canonical_keys:
                        group_deleted += 1
                        if commit:
                            BOMItem.objects.filter(id=item.id).delete()
                    else:
                        canonical_keys.add(key)
                        group_moved += 1
                        if commit:
                            BOMItem.objects.filter(id=item.id).update(
                                bom_id=canonical.id
                            )

                if commit:
                    BOM.objects.filter(id=sec.id).delete()
                boms_to_merge += 1

            items_moved += group_moved
            items_deleted += group_deleted

            if examples_shown < 5:
                self.stdout.write(
                    f"  Example: unit_id={unit_id}  canonical BOM "
                    f"id={canonical.id} (items={canonical._item_count})  "
                    f"+ {len(secondaries)} secondary(ies) "
                    f"-> moved={group_moved} deleted={group_deleted}"
                )
                examples_shown += 1

            processed += 1
            if processed % 500 == 0:
                self.stdout.write(
                    f"  ...processed {processed:,}/{n_units:,} duplicate "
                    f"unit groups"
                )
                self.stdout.flush()

        self.stdout.write(
            f"  Secondary BOMs to merge/delete: {boms_to_merge:,}"
        )
        self.stdout.write(
            f"  Items to move to canonical:     {items_moved:,}"
        )
        self.stdout.write(
            f"  Items already-dup to delete:    {items_deleted:,}"
        )

        elapsed = time.perf_counter() - start
        self.stdout.write(f"  Step 3b elapsed: {elapsed:.2f}s")
        self.stdout.write("")
        return {
            "units_with_dups": n_units,
            "boms_to_merge": boms_to_merge,
            "items_moved": items_moved,
            "items_deleted": items_deleted,
            "secondary_ids": secondary_ids,
            "elapsed": elapsed,
        }

    @staticmethod
    def _build_key_set(bom_id):
        keys = set()
        for it in BOMItem.objects.filter(bom_id=bom_id).only(
            "yt_number", "description"
        ):
            keys.add(Command._item_key(it))
        return keys

    @staticmethod
    def _item_key(item):
        yt = (item.yt_number or "").strip()
        if yt:
            return ("yt", yt.lower())
        return ("desc", (item.description or "").strip().lower())

    # ------------------------------------------------------------------
    # Step 3c — Delete BOMs with zero items
    # ------------------------------------------------------------------
    def _step_3c(self, bom_id_subset, commit, exclude_ids=None):
        start = time.perf_counter()
        self.stdout.write(
            self.style.NOTICE("--- Step 3c: Delete BOMs with zero items ---")
        )

        exclude_ids = exclude_ids or set()

        empty_qs_raw = BOM.objects.annotate(_n=Count("items")).filter(_n=0)
        if bom_id_subset is not None:
            empty_qs_raw = empty_qs_raw.filter(id__in=bom_id_subset)

        empty_count_raw = empty_qs_raw.count()

        # Deduplicate against step 3b's secondaries so we don't double-count.
        empty_qs = empty_qs_raw
        if exclude_ids:
            empty_qs = empty_qs.exclude(id__in=exclude_ids)

        empty_count = empty_qs.count()
        overlap = empty_count_raw - empty_count
        unit_linked = empty_qs.exclude(unit_id__isnull=True).count()
        orphan = empty_count - unit_linked

        self.stdout.write(
            f"  Empty BOMs found:            {empty_count_raw:,}"
        )
        if exclude_ids:
            self.stdout.write(
                f"    Already counted by 3b:     {overlap:,}"
            )
        self.stdout.write(
            f"  Additional BOMs 3c deletes:  {empty_count:,}"
        )
        self.stdout.write(f"    Unit-linked:               {unit_linked:,}")
        self.stdout.write(f"    Orphaned (no unit):        {orphan:,}")

        examples = list(
            empty_qs.order_by("id")[:5].values("id", "name", "unit_id")
        )
        if examples:
            self.stdout.write("  Examples (first 5):")
            for ex in examples:
                self.stdout.write(
                    f"    BOM id={ex['id']}  unit_id={ex['unit_id']}  "
                    f"name={ex['name']!r}"
                )

        deleted = 0
        if commit and empty_count > 0:
            # Re-evaluate after step 3b may have changed the picture.
            n, _ = empty_qs.delete()
            deleted = n
            self.stdout.write(
                self.style.SUCCESS(f"  Deleted {deleted:,} empty BOMs.")
            )

        elapsed = time.perf_counter() - start
        self.stdout.write(f"  Step 3c elapsed: {elapsed:.2f}s")
        self.stdout.write("")
        return {
            "empty_count": empty_count,
            "empty_count_raw": empty_count_raw,
            "overlap_with_3b": overlap,
            "unit_linked": unit_linked,
            "orphan": orphan,
            "deleted": deleted,
            "elapsed": elapsed,
        }

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    def _print_summary(
        self,
        results,
        grand_elapsed,
        commit,
        starting_boms,
        starting_items,
    ):
        self.stdout.write(self.style.MIGRATE_HEADING("--- Summary ---"))

        a = results.get("3a") or {}
        b = results.get("3b") or {}
        c = results.get("3c") or {}

        a_items = a.get("phantom_count", 0)
        b_boms = b.get("boms_to_merge", 0)
        b_items_moved = b.get("items_moved", 0)
        b_items_del = b.get("items_deleted", 0)
        c_boms = c.get("empty_count", 0)

        # Net change predictions (negative = rows go away).
        # BOMItems moved in 3b don't change the row count; only phantom
        # deletions (3a) and duplicate-key deletions (3b) reduce it.
        net_boms = -(b_boms + c_boms)
        net_items = -(a_items + b_items_del)

        self.stdout.write(
            f"  Step 3a: phantom BOMItems removed:        {a_items:,}"
        )
        self.stdout.write(
            f"  Step 3a: WARN partial-empty items kept:   "
            f"{a.get('warn_count', 0):,}"
        )
        self.stdout.write(
            f"  Step 3b: secondary BOMs merged/deleted:   {b_boms:,}"
        )
        self.stdout.write(
            f"  Step 3b: items moved to canonical:        {b_items_moved:,}"
        )
        self.stdout.write(
            f"  Step 3b: duplicate items deleted:         {b_items_del:,}"
        )
        self.stdout.write(
            f"  Step 3c: empty BOMs removed:              {c_boms:,}"
        )
        self.stdout.write("")
        self.stdout.write(
            f"  Predicted net BOM change:        {net_boms:+,}  "
            f"(from {starting_boms:,})"
        )
        self.stdout.write(
            f"  Predicted net BOMItem change:    {net_items:+,}  "
            f"(from {starting_items:,})"
        )
        self.stdout.write("")
        self.stdout.write(f"  Grand total elapsed: {grand_elapsed:.2f}s")
        self.stdout.write("")

        if not commit:
            self.stdout.write(
                self.style.WARNING(
                    "DRY-RUN: no changes were made. "
                    "Re-run with --commit to apply."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("COMMIT: changes applied."))
            self.stdout.write(
                f"  Final counts: BOMs={BOM.objects.count():,}  "
                f"BOMItems={BOMItem.objects.count():,}"
            )
