"""Five-step cleanup / normalization of catalog_application.

The catalog_application table has accumulated ~520k rows with widespread
duplication and inconsistent year/model formatting. This command repairs
the data in five ordered sub-steps (each step's output feeds the next):

    1. Year format normalize       e.g. ``00-02``        -> ``2000-2002``
    2. Pipe-soup year splitter     e.g. ``00-01 | 02-03`` -> two rows
    3. Submodel splitter           e.g. ``3.0GSM-A,B,C``  -> three rows
    4. Year direction fix          e.g. ``1964-1962``    -> ``1962-1964``
    5. Final dedup                 collapse rows that now share
                                   (make, model, engine, year).

Default behavior is a non-destructive dry-run. Pass ``--commit`` to apply
all changes inside a single ``transaction.atomic()`` block.

Usage::

    python manage.py cleanup_normalize_applications                 # dry-run
    python manage.py cleanup_normalize_applications --commit        # apply
    python manage.py cleanup_normalize_applications --limit 1000    # smoke
    python manage.py cleanup_normalize_applications --only-step 3   # debug
"""

import re
import time
from collections import defaultdict
from typing import Dict, List

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from catalog.models import Application, ApplicationUnit


# --- shared regexes ---------------------------------------------------------
YEAR_2D_RANGE_RE = re.compile(r"^(\d{2})-(\d{2})$")
YEAR_4D_RANGE_RE = re.compile(r"^(\d{4})-(\d{4})$")
SUBMODEL_RE = re.compile(r"^([\w.]+)-([A-Z](?:,[A-Z])+)$")


def _expand_2digit_year(yy: str) -> str:
    """Independent 70-cutoff: ``>=70`` -> ``19xx``, else ``20xx``."""
    n = int(yy)
    return f"19{yy}" if n >= 70 else f"20{yy}"


def _expand_2digit_range(yy1: str, yy2: str) -> tuple:
    """Apply the spec's century rule to a 2-digit ``yy-yy`` range.

    Logic chosen to match all three reference examples in the spec:

      * ``68-72`` -> ``1968-1972``  (same-century span, either >= 70 -> 19xx)
      * ``00-02`` -> ``2000-2002``  (same-century span, both <  70 -> 20xx)
      * ``99-01`` -> ``1999-2001``  (century crossover: independent cutoffs)

    The literal "if either is >= 70 prepend 19; else 20" rule alone can't
    produce ``99-01 -> 1999-2001``, so we treat the start>end case as a
    century-crossing range and fall back to per-digit cutoffs there.
    """
    n1, n2 = int(yy1), int(yy2)
    if n1 > n2:
        # Century crossover: e.g. 99-01 -> 1999-2001
        return (
            f"19{yy1}" if n1 >= 70 else f"20{yy1}",
            f"19{yy2}" if n2 >= 70 else f"20{yy2}",
        )
    # Same-century span: either >= 70 -> both 19xx; otherwise both 20xx.
    if n1 >= 70 or n2 >= 70:
        return (f"19{yy1}", f"19{yy2}")
    return (f"20{yy1}", f"20{yy2}")


def _normalize_year_segment(seg: str) -> str:
    """Convert ``00-02`` -> ``2000-2002``. Leaves other formats untouched."""
    seg = seg.strip()
    m = YEAR_2D_RANGE_RE.match(seg)
    if m:
        y1, y2 = _expand_2digit_range(m.group(1), m.group(2))
        return f"{y1}-{y2}"
    return seg


class Command(BaseCommand):
    help = (
        "Five-step cleanup of catalog_application: year normalize, "
        "pipe-split, submodel-split, year-direction, final dedup."
    )

    # Fields copied when cloning an Application row.
    # Excludes id (PK) and the auto created_at / updated_at timestamps.
    APP_COPY_FIELDS = [
        "seed_id", "name", "make", "model", "engine", "year",
        "mfr", "volt", "amp", "kw", "fuel_type", "vin",
        "alt_pulley", "unit_type_name", "part_number", "other_number",
        "unit_number", "options", "notes",
        "application_type_category", "type_specifications", "is_active",
    ]

    # ----------------------------------------------------------------- argparse
    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Report what would change; no DB writes. (Default behavior.)",
        )
        mode.add_argument(
            "--commit",
            action="store_true",
            default=False,
            help="Apply changes inside a single transaction.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Process only the first N Application rows (lowest id first).",
        )
        parser.add_argument(
            "--only-step",
            type=int,
            choices=[1, 2, 3, 4, 5],
            default=None,
            help="Run only one specific sub-step (1-5).",
        )

    # ------------------------------------------------------------------- handle
    def handle(self, *args, **options):
        self.commit = bool(options["commit"])
        self.limit = options["limit"]
        only_step = options["only_step"]

        mode_label = "COMMIT" if self.commit else "DRY-RUN"

        self.stdout.write("")
        self.stdout.write(
            f"=== cleanup_normalize_applications [{mode_label}] ==="
        )
        if self.limit:
            self.stdout.write(f"Limit:  first {self.limit:,} Application rows")
        if only_step:
            self.stdout.write(f"Only:   step {only_step}")
        self.stdout.write("")

        # Freeze the --limit scope at start so every step sees the same window.
        self.limit_max_id = None
        if self.limit:
            cap_ids = list(
                Application.objects.order_by("id")
                .values_list("id", flat=True)[: self.limit]
            )
            if cap_ids:
                self.limit_max_id = cap_ids[-1]
                self.stdout.write(
                    f"   (cap: id <= {self.limit_max_id})"
                )

        total_apps_before = Application.objects.count()
        total_links_before = ApplicationUnit.objects.count()
        self.stdout.write(f"Applications     (before): {total_apps_before:,}")
        self.stdout.write(f"ApplicationUnits (before): {total_links_before:,}")
        self.stdout.write("")

        steps = [
            (1, "Step 1 - Year format normalize", self._step1_year_normalize),
            (2, "Step 2 - Pipe-soup year splitter", self._step2_pipe_split),
            (3, "Step 3 - Submodel splitter", self._step3_submodel_split),
            (4, "Step 4 - Year direction fix", self._step4_year_direction),
            (5, "Step 5 - Final dedup", self._step5_dedup),
        ]

        grand_t0 = time.monotonic()
        results: Dict[int, dict] = {}

        def run_all():
            for step_num, label, fn in steps:
                if only_step is not None and only_step != step_num:
                    continue
                self.stdout.write(f"--- {label} ---")
                self.stdout.flush()
                t0 = time.monotonic()
                results[step_num] = fn()
                dt = time.monotonic() - t0
                self.stdout.write(f"  Step time: {dt:.2f}s")
                self.stdout.write("")

        if self.commit:
            with transaction.atomic():
                run_all()
        else:
            run_all()

        total_apps_after = Application.objects.count()
        total_links_after = ApplicationUnit.objects.count()
        grand_dt = time.monotonic() - grand_t0

        self.stdout.write("=== Summary ===")
        for step_num, _, _ in steps:
            if step_num in results:
                self.stdout.write(f"  Step {step_num}: {results[step_num]}")
        self.stdout.write("")
        self.stdout.write(
            f"Applications     (after):  {total_apps_after:,}  "
            f"(delta {total_apps_after - total_apps_before:+,})"
        )
        self.stdout.write(
            f"ApplicationUnits (after):  {total_links_after:,}  "
            f"(delta {total_links_after - total_links_before:+,})"
        )
        self.stdout.write(f"Grand total: {grand_dt:.2f}s [{mode_label}]")

        if not self.commit:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "DRY-RUN: no DB writes performed. "
                    "Re-run with --commit to apply."
                )
            )

    # ----------------------------------------------------------------- helpers
    def _scoped_apps(self):
        """Return an Application queryset honoring --limit."""
        qs = Application.objects.all()
        if self.limit_max_id is not None:
            qs = qs.filter(id__lte=self.limit_max_id)
        return qs

    def _clone_app(self, original: Application, **overrides) -> Application:
        kwargs = {f: getattr(original, f) for f in self.APP_COPY_FIELDS}
        kwargs.update(overrides)
        return Application(**kwargs)

    def _link_counts_for(self, app_ids: List[int]) -> Dict[int, int]:
        """Return ``{app_id: link_count}`` for the given app_ids in one pass.

        Chunks the IN-clause to keep SQLite happy on very large lists.
        """
        counts: Dict[int, int] = {}
        for i in range(0, len(app_ids), 5000):
            chunk = app_ids[i : i + 5000]
            for app_id, c in (
                ApplicationUnit.objects.filter(application_id__in=chunk)
                .values("application_id")
                .annotate(c=Count("id"))
                .values_list("application_id", "c")
            ):
                counts[app_id] = c
        return counts

    def _migrate_links(
        self, original_id: int, new_app_ids: List[int]
    ) -> int:
        """Create new ApplicationUnit rows for every (new_app, original_unit) pair.

        The caller deletes the original Application afterwards; CASCADE
        removes the original ApplicationUnit rows automatically.

        Returns the number of new link rows actually created.
        """
        if not new_app_ids:
            return 0
        orig_links = list(
            ApplicationUnit.objects.filter(
                application_id=original_id
            ).values("unit_id", "position", "notes", "created_at", "seed_id")
        )
        if not orig_links:
            return 0
        new_objs = []
        for new_id in new_app_ids:
            for link in orig_links:
                new_objs.append(
                    ApplicationUnit(
                        application_id=new_id,
                        unit_id=link["unit_id"],
                        position=link["position"] or "",
                        notes=link["notes"] or "",
                        created_at=link["created_at"],
                        seed_id=link["seed_id"],
                    )
                )
        # ignore_conflicts protects against the (application, unit) unique
        # constraint in the unlikely event the new app already has a link
        # to the same unit (e.g. a prior step's residue).
        ApplicationUnit.objects.bulk_create(new_objs, ignore_conflicts=True)
        return len(new_objs)

    # ------------------------------------------------------------------ step 1
    def _step1_year_normalize(self):
        qs = (
            self._scoped_apps()
            .filter(year__regex=r"^\d{2}-\d{2}$")
            .order_by("id")
        )

        examples: List[tuple] = []
        to_update: List[Application] = []
        scanned = 0
        for app in qs.iterator(chunk_size=5000):
            scanned += 1
            m = YEAR_2D_RANGE_RE.match(app.year.strip())
            if not m:
                continue
            y1, y2 = _expand_2digit_range(m.group(1), m.group(2))
            new_year = f"{y1}-{y2}"
            if new_year == app.year:
                continue
            if len(examples) < 10:
                examples.append((app.id, app.year, new_year))
            app.year = new_year
            to_update.append(app)
            if scanned % 5000 == 0:
                self.stdout.write(
                    f"    scanned {scanned:,}  "
                    f"queued {len(to_update):,} update(s)"
                )
                self.stdout.flush()

        self.stdout.write(f"  Rows to normalize: {len(to_update):,}")
        self.stdout.write("  Examples:")
        for app_id, old, new in examples:
            self.stdout.write(f"    [{app_id}]  '{old}'  ->  '{new}'")

        if self.commit and to_update:
            Application.objects.bulk_update(
                to_update, ["year"], batch_size=2000
            )

        return {"normalized": len(to_update)}

    # ------------------------------------------------------------------ step 2
    def _step2_pipe_split(self):
        qs = (
            self._scoped_apps()
            .filter(year__contains="|")
            .order_by("id")
        )
        candidates = list(qs)
        n_total = len(candidates)
        self.stdout.write(
            f"  Candidate rows with '|' in year: {n_total:,}"
        )

        # Pre-compute link counts in a single aggregate query.
        link_counts = self._link_counts_for([a.id for a in candidates])

        examples_split: List[tuple] = []
        rows_simple = 0
        rows_split = 0
        new_apps_total = 0
        new_links_total = 0
        simple_updates: List[Application] = []
        pending_deletes: List[int] = []

        for i, app in enumerate(candidates, 1):
            segments = [s.strip() for s in app.year.split("|") if s.strip()]
            normalized = [_normalize_year_segment(s) for s in segments]
            seen = set()
            unique_segs: List[str] = []
            for s in normalized:
                if s and s not in seen:
                    seen.add(s)
                    unique_segs.append(s)
            if not unique_segs:
                continue

            if len(unique_segs) == 1:
                new_year = unique_segs[0]
                if app.year != new_year:
                    rows_simple += 1
                    app.year = new_year
                    if self.commit:
                        simple_updates.append(app)
            else:
                rows_split += 1
                n_new = len(unique_segs)
                lc = link_counts.get(app.id, 0)
                new_apps_total += n_new
                new_links_total += lc * n_new

                if len(examples_split) < 5:
                    examples_split.append(
                        (app.id, app.year, list(unique_segs), lc)
                    )

                if self.commit:
                    new_apps = [
                        self._clone_app(app, year=ny) for ny in unique_segs
                    ]
                    Application.objects.bulk_create(new_apps)
                    self._migrate_links(
                        app.id, [a.id for a in new_apps]
                    )
                    pending_deletes.append(app.id)
                    if len(pending_deletes) >= 2000:
                        Application.objects.filter(
                            id__in=pending_deletes
                        ).delete()
                        pending_deletes = []

            if i % 5000 == 0:
                self.stdout.write(
                    f"    processed {i:,}/{n_total:,}"
                )
                self.stdout.flush()

        if self.commit and simple_updates:
            Application.objects.bulk_update(
                simple_updates, ["year"], batch_size=2000
            )
        if self.commit and pending_deletes:
            Application.objects.filter(id__in=pending_deletes).delete()

        self.stdout.write(
            f"  Simple-update rows (1 unique segment):     {rows_simple:,}"
        )
        self.stdout.write(
            f"  Split rows (>1 unique segments):           {rows_split:,}"
        )
        self.stdout.write(
            f"  New Application rows created:              {new_apps_total:,}"
        )
        self.stdout.write(
            f"  New ApplicationUnit rows created:          {new_links_total:,}"
        )
        self.stdout.write("  Examples (split):")
        for app_id, old, segs, lc in examples_split:
            self.stdout.write(
                f"    [{app_id}]  year='{old}'  ->  {len(segs)} new rows "
                f"{segs}  (had {lc} link{'s' if lc != 1 else ''} each)"
            )

        return {
            "candidates": n_total,
            "simple_updates": rows_simple,
            "splits": rows_split,
            "new_apps": new_apps_total,
            "new_links": new_links_total,
        }

    # ------------------------------------------------------------------ step 3
    def _step3_submodel_split(self):
        qs = (
            self._scoped_apps()
            .filter(model__regex=r"^[\w.]+-[A-Z](,[A-Z])+$")
            .order_by("id")
        )
        candidates = list(qs)
        n_total = len(candidates)
        self.stdout.write(
            f"  Candidate rows matching submodel pattern: {n_total:,}"
        )

        link_counts = self._link_counts_for([a.id for a in candidates])

        examples: List[tuple] = []
        rows_split = 0
        new_apps_total = 0
        new_links_total = 0
        pending_deletes: List[int] = []

        for i, app in enumerate(candidates, 1):
            m = SUBMODEL_RE.match(app.model.strip())
            if not m:
                continue
            base = m.group(1)
            letters = m.group(2).split(",")
            new_models = [f"{base}-{L}" for L in letters]
            n_new = len(new_models)
            lc = link_counts.get(app.id, 0)
            rows_split += 1
            new_apps_total += n_new
            new_links_total += lc * n_new

            if len(examples) < 5:
                examples.append(
                    (app.id, app.model, list(new_models), lc)
                )

            if self.commit:
                new_apps = [
                    self._clone_app(app, model=nm) for nm in new_models
                ]
                Application.objects.bulk_create(new_apps)
                self._migrate_links(app.id, [a.id for a in new_apps])
                pending_deletes.append(app.id)
                if len(pending_deletes) >= 2000:
                    Application.objects.filter(
                        id__in=pending_deletes
                    ).delete()
                    pending_deletes = []

            if i % 5000 == 0:
                self.stdout.write(f"    processed {i:,}/{n_total:,}")
                self.stdout.flush()

        if self.commit and pending_deletes:
            Application.objects.filter(id__in=pending_deletes).delete()

        self.stdout.write(
            f"  Rows to split:                    {rows_split:,}"
        )
        self.stdout.write(
            f"  New Application rows created:     {new_apps_total:,}"
        )
        self.stdout.write(
            f"  New ApplicationUnit rows created: {new_links_total:,}"
        )
        self.stdout.write("  Examples:")
        for app_id, old, news, lc in examples:
            self.stdout.write(
                f"    [{app_id}]  model='{old}'  ->  {news}  "
                f"({lc} link{'s' if lc != 1 else ''} each)"
            )

        return {
            "candidates": n_total,
            "splits": rows_split,
            "new_apps": new_apps_total,
            "new_links": new_links_total,
        }

    # ------------------------------------------------------------------ step 4
    def _step4_year_direction(self):
        qs = (
            self._scoped_apps()
            .filter(year__regex=r"^\d{4}-\d{4}$")
            .order_by("id")
        )

        examples: List[tuple] = []
        to_update: List[Application] = []
        scanned = 0
        for app in qs.iterator(chunk_size=5000):
            scanned += 1
            m = YEAR_4D_RANGE_RE.match(app.year)
            if not m:
                continue
            y1, y2 = int(m.group(1)), int(m.group(2))
            if y1 <= y2:
                continue
            new_year = f"{y2}-{y1}"
            if len(examples) < 10:
                examples.append((app.id, app.year, new_year))
            app.year = new_year
            to_update.append(app)
            if scanned % 5000 == 0:
                self.stdout.write(
                    f"    scanned {scanned:,}  "
                    f"queued {len(to_update):,} reversal(s)"
                )
                self.stdout.flush()

        self.stdout.write(
            f"  Reversed-direction rows: {len(to_update):,}"
        )
        self.stdout.write("  Examples:")
        for app_id, old, new in examples:
            self.stdout.write(f"    [{app_id}]  '{old}'  ->  '{new}'")

        if self.commit and to_update:
            Application.objects.bulk_update(
                to_update, ["year"], batch_size=2000
            )

        return {"reversed": len(to_update)}

    # ------------------------------------------------------------------ step 5
    def _step5_dedup(self):
        qs = self._scoped_apps()

        dup_groups = list(
            qs.values("make", "model", "engine", "year")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
            .order_by("make", "model", "engine", "year")
        )
        n_groups = len(dup_groups)
        self.stdout.write(
            f"  Duplicate groups (make,model,engine,year): {n_groups:,}"
        )
        if n_groups == 0:
            self.stdout.write("  Application rows to delete:        0")
            self.stdout.write("  ApplicationUnit links to repoint:  0")
            self.stdout.write("  Examples:  (none)")
            return {"groups": 0, "deleted": 0, "links_moved": 0}

        # Single sweep over Application rows to bucket ids by their group key.
        # Doing this in Python with one query is dramatically faster than
        # issuing 1 SELECT per group (was ~92k extra queries previously).
        dup_keys = {
            (g["make"], g["model"], g["engine"], g["year"])
            for g in dup_groups
        }
        groups_map: Dict[tuple, List[int]] = defaultdict(list)
        for app_id, mk, md, en, yr in qs.values_list(
            "id", "make", "model", "engine", "year"
        ).iterator(chunk_size=10000):
            key = (mk, md, en, yr)
            if key in dup_keys:
                groups_map[key].append(app_id)

        # Compute the work plan: canonical (lowest id) + dup ids per group.
        work_items: List[tuple] = []  # (canonical_id, dup_ids, key)
        for key, ids in groups_map.items():
            if len(ids) <= 1:
                continue
            ids.sort()
            work_items.append((ids[0], ids[1:], key))

        rows_deleted = sum(len(d) for _, d, _ in work_items)

        # Bulk-count the links pointing at any non-canonical app (chunked IN).
        all_dup_ids = [aid for _, dups, _ in work_items for aid in dups]
        links_repointed = 0
        for i in range(0, len(all_dup_ids), 5000):
            chunk = all_dup_ids[i : i + 5000]
            links_repointed += ApplicationUnit.objects.filter(
                application_id__in=chunk
            ).count()

        # Examples (first 5 groups).
        examples: List[tuple] = []
        for canonical, dups, key in work_items[:5]:
            lc = ApplicationUnit.objects.filter(
                application_id__in=dups
            ).count()
            examples.append((*key, canonical, list(dups), lc))

        self.stdout.write(
            f"  Application rows to delete:        {rows_deleted:,}"
        )
        self.stdout.write(
            f"  ApplicationUnit links to repoint:  {links_repointed:,}"
        )
        self.stdout.write("  Examples:")
        for make, model, engine, year, canonical, dups, lc in examples:
            self.stdout.write(
                f"    canonical id={canonical}  "
                f"key=({make!r}, {model!r}, {engine!r}, {year!r})  "
                f"duplicates={dups[:5]}{'...' if len(dups) > 5 else ''}  "
                f"links_to_move={lc}"
            )

        if self.commit:
            # Re-point each duplicate's links onto the canonical app,
            # collapsing (application, unit) collisions via
            # update_or_create. Then delete the duplicate Application rows.
            for processed_groups, (canonical_id, dup_ids, _) in enumerate(
                work_items, 1
            ):
                for link in list(
                    ApplicationUnit.objects.filter(
                        application_id__in=dup_ids
                    )
                ):
                    defaults = {}
                    if link.position:
                        defaults["position"] = link.position
                    if link.notes:
                        defaults["notes"] = link.notes
                    ApplicationUnit.objects.update_or_create(
                        application_id=canonical_id,
                        unit_id=link.unit_id,
                        defaults=defaults,
                    )
                    link.delete()
                Application.objects.filter(id__in=dup_ids).delete()
                if processed_groups % 5000 == 0:
                    self.stdout.write(
                        f"    committed {processed_groups:,}/{n_groups:,} group(s)"
                    )
                    self.stdout.flush()

        return {
            "groups": n_groups,
            "deleted": rows_deleted,
            "links_moved": links_repointed,
        }
