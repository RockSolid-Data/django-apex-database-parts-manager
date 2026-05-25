"""
Normalize manufacturer name casing in catalog_crossreference.interchange_type
and merge resulting duplicates.

The Lester import writes manufacturer names in upper case (``ALLTECH``) while
the Buyers Guide import writes them in mixed case (``Alltech``).  After the
two imports run, the same logical cross-reference exists as multiple rows
that differ only by case.  This command:

  1. Builds an "acronym whitelist" of tokens that should stay upper case
     (``WAI``, ``OEM``, ``GM`` …) by combining a hard-coded list with all
     short, all-caps single-token values found in the database.
  2. Computes a normalized form for every ``interchange_type`` value by
     splitting on whitespace, keeping whitelist tokens upper case, and
     title-casing everything else (``ALLTECH`` → ``Alltech``,
     ``ALFA ROMEO`` → ``Alfa Romeo``).
  3. Groups rows by ``(unit_id, cross_ref_number, normalized_name)`` and,
     for groups with more than one row, picks a survivor (longest
     ``notes`` field, lowest ``id`` to break ties) and marks the rest for
     deletion.
  4. In ``--commit`` mode, deletes the duplicates first (to avoid
     ``unique_together`` violations) and then bulk-updates the survivors
     to their normalized name, all inside a single ``transaction.atomic``.

Usage:
    python manage.py cleanup_normalize_manufacturers              # dry-run
    python manage.py cleanup_normalize_manufacturers --dry-run    # explicit dry-run
    python manage.py cleanup_normalize_manufacturers --commit     # apply changes
    python manage.py cleanup_normalize_manufacturers --dry-run --limit 100
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List, Tuple

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from catalog.models import CrossReference


EXPLICIT_WHITELIST = [
    "WAI", "PIC", "OEM", "GM", "BMW", "MES", "EGI", "API", "TSA", "MGU",
    "BEPCO", "BBB", "ACDelco", "NAPA", "OE", "AC", "DC", "LRI", "SAE",
    "IMS", "JD", "GMC",
]


class Command(BaseCommand):
    help = (
        "Normalize manufacturer name casing in CrossReference.interchange_type "
        "and merge duplicates that result from the normalization."
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
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Process only the first N CrossReference rows (for testing).",
        )

    # ------------------------------------------------------------------ #
    # Whitelist construction
    # ------------------------------------------------------------------ #
    def _build_whitelist(self) -> Dict[str, str]:
        """
        Return a mapping ``upper(token) -> canonical form`` of acronyms that
        must keep their original casing.  Combines the hard-coded list with
        any short, all-caps, single-token values found in the database.
        """
        whitelist: Dict[str, str] = {}
        for v in EXPLICIT_WHITELIST:
            whitelist[v.upper()] = v

        distinct_values = (
            CrossReference.objects
            .exclude(interchange_type="")
            .values_list("interchange_type", flat=True)
            .distinct()
        )
        for raw in distinct_values:
            if raw is None:
                continue
            s = raw.strip().rstrip(".").strip()
            if not s:
                continue
            if " " in s:
                continue
            if len(s) > 4:
                continue
            if not s.isalnum():
                continue
            if not s.isupper():
                continue
            whitelist.setdefault(s.upper(), s)

        return whitelist

    # ------------------------------------------------------------------ #
    # Core normalization
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalize_mfr(name: str, whitelist: Dict[str, str]) -> str:
        """
        Normalize a manufacturer name:
          - Strip whitespace and trailing periods.
          - Split on whitespace.
          - For each token: if its uppercase form is in the whitelist, use
            the whitelist's canonical form; otherwise title-case it.
          - Re-join with single spaces.
        Empty input returns an empty string.
        """
        if not name:
            return ""
        s = name.strip().rstrip(".").strip()
        if not s:
            return ""
        out: List[str] = []
        for tok in s.split():
            canonical = whitelist.get(tok.upper())
            if canonical is not None:
                out.append(canonical)
            else:
                out.append(tok.title())
        return " ".join(out)

    # ------------------------------------------------------------------ #
    # Main entry
    # ------------------------------------------------------------------ #
    def handle(self, *args, **options):
        start = time.time()
        commit: bool = options["commit"]
        dry_run: bool = options["dry_run"]
        limit = options.get("limit")

        if not commit and not dry_run:
            dry_run = True
            self.stdout.write(
                self.style.WARNING(
                    "No mode specified -- defaulting to --dry-run. "
                    "NO CHANGES WILL BE MADE."
                ),
                ending="\n",
            )
            self.stdout.flush()

        mode_label = "COMMIT" if commit else "DRY-RUN"
        self.stdout.write(f"Mode: {mode_label}", ending="\n")
        if limit:
            self.stdout.write(f"Limit: first {limit:,} rows")
        self.stdout.flush()

        # -------------------------------------------------------------- #
        # 1. Build acronym whitelist
        # -------------------------------------------------------------- #
        self.stdout.write("\nBuilding acronym whitelist...")
        self.stdout.flush()
        whitelist = self._build_whitelist()
        canonical_forms = sorted(set(whitelist.values()))
        self.stdout.write(
            f"  whitelist size: {len(canonical_forms)} canonical tokens"
        )
        self.stdout.write("  first 30 (alphabetical):")
        for tok in canonical_forms[:30]:
            self.stdout.write(f"    {tok}")
        self.stdout.flush()

        # -------------------------------------------------------------- #
        # 2. Stream rows + group by (unit_id, cross_ref_number, normalized)
        # -------------------------------------------------------------- #
        self.stdout.write("\nScanning CrossReference rows...")
        self.stdout.flush()

        qs = (
            CrossReference.objects
            .all()
            .only("id", "unit_id", "cross_ref_number", "interchange_type", "notes")
            .order_by("id")
        )
        if limit:
            qs = qs[:limit]

        # Each group entry is a list of dicts:
        #   {"id", "current", "normalized", "notes_len"}
        groups: Dict[Tuple[int, str, str], List[dict]] = defaultdict(list)
        rows_seen = 0
        rows_already_normal = 0

        for row in qs.iterator(chunk_size=5000):
            rows_seen += 1
            current = row.interchange_type or ""
            normalized = self._normalize_mfr(current, whitelist)
            if current == normalized:
                rows_already_normal += 1
            key = (row.unit_id, row.cross_ref_number or "", normalized)
            groups[key].append({
                "id": row.id,
                "current": current,
                "normalized": normalized,
                "notes_len": len(row.notes or ""),
            })
            if rows_seen % 50000 == 0:
                self.stdout.write(f"  scanned {rows_seen:,} rows...")
                self.stdout.flush()

        self.stdout.write(f"  total scanned: {rows_seen:,} rows")
        self.stdout.write(f"  already normalized: {rows_already_normal:,}")
        self.stdout.flush()

        # -------------------------------------------------------------- #
        # 3. Decide actions
        # -------------------------------------------------------------- #
        rows_to_update: List[Tuple[int, str]] = []   # (id, normalized)
        rows_to_delete: List[int] = []
        duplicate_groups = 0

        rename_examples: List[Tuple[str, str]] = []
        rename_examples_by_target: Dict[str, List[str]] = defaultdict(list)
        merge_examples: List[dict] = []

        for (unit_id, crn, normalized), members in groups.items():
            if len(members) > 1:
                duplicate_groups += 1
                # Survivor: longest notes, then lowest id (deterministic).
                members.sort(key=lambda m: (-m["notes_len"], m["id"]))
                survivor = members[0]
                losers = members[1:]

                for loser in losers:
                    rows_to_delete.append(loser["id"])
                    if len(merge_examples) < 10:
                        merge_examples.append({
                            "unit_id": unit_id,
                            "crn": crn,
                            "normalized": normalized,
                            "survivor_id": survivor["id"],
                            "survivor_current": survivor["current"],
                            "loser_id": loser["id"],
                            "loser_current": loser["current"],
                        })

                if survivor["current"] != normalized:
                    rows_to_update.append((survivor["id"], normalized))
                    if (
                        len(rename_examples_by_target[normalized]) < 3
                        and len(rename_examples) < 20
                    ):
                        rename_examples.append((survivor["current"], normalized))
                        rename_examples_by_target[normalized].append(
                            survivor["current"]
                        )
            else:
                m = members[0]
                if m["current"] != normalized:
                    rows_to_update.append((m["id"], normalized))
                    if (
                        len(rename_examples_by_target[normalized]) < 3
                        and len(rename_examples) < 20
                    ):
                        rename_examples.append((m["current"], normalized))
                        rename_examples_by_target[normalized].append(m["current"])

        # -------------------------------------------------------------- #
        # 4. Report planned actions
        # -------------------------------------------------------------- #
        self.stdout.write("\n--- Planned actions ---")
        self.stdout.write(f"Rows to rename:   {len(rows_to_update):,}")
        self.stdout.write(f"Duplicate groups: {duplicate_groups:,}")
        self.stdout.write(f"Rows to delete:   {len(rows_to_delete):,}")
        self.stdout.flush()

        if rename_examples:
            self.stdout.write("\nExample renames (grouped by target):")
            for before, after in rename_examples:
                self.stdout.write(f"  {before!r:<35} -> {after!r}")
        if merge_examples:
            self.stdout.write("\nExample duplicate merges:")
            for ex in merge_examples:
                self.stdout.write(
                    f"  unit={ex['unit_id']} crn={ex['crn']!r} "
                    f"keep id={ex['survivor_id']} ({ex['survivor_current']!r}) "
                    f"drop id={ex['loser_id']} ({ex['loser_current']!r}) "
                    f"-> {ex['normalized']!r}"
                )
        self.stdout.flush()

        # -------------------------------------------------------------- #
        # 5. Apply (commit mode) or simulate (dry-run)
        # -------------------------------------------------------------- #
        before_total = (
            CrossReference.objects.count() if not limit else rows_seen
        )

        if commit:
            self._apply_changes(rows_to_update, rows_to_delete)
            after_total = CrossReference.objects.count()
        else:
            after_total = before_total - len(rows_to_delete)

        # -------------------------------------------------------------- #
        # 6. Final report
        # -------------------------------------------------------------- #
        self.stdout.write("\n--- Final report ---")
        self.stdout.write(
            f"Total CrossReferences: {before_total:,} -> {after_total:,}"
        )

        top10 = self._top_mfr_counts(groups, commit=commit, limit=limit)
        self.stdout.write("\nTop 10 manufacturer names by row count after cleanup:")
        for name, count in top10:
            self.stdout.write(f"  {count:>7,}  {name!r}")

        if not commit:
            self.stdout.write(
                self.style.WARNING(
                    "\nDRY-RUN: no changes were made. "
                    "Re-run with --commit to apply."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("\nCOMMIT: changes applied successfully.")
            )

        elapsed = time.time() - start
        self.stdout.write(f"Elapsed: {elapsed:.2f}s")
        self.stdout.flush()

    # ------------------------------------------------------------------ #
    # Commit-mode helper
    # ------------------------------------------------------------------ #
    def _apply_changes(
        self,
        rows_to_update: List[Tuple[int, str]],
        rows_to_delete: List[int],
    ) -> None:
        """
        Apply deletes first (to avoid unique_together collisions on
        ``(unit, cross_ref_number, interchange_type)``) and then bulk-update
        the survivors.  Wrapped in a single transaction.
        """
        try:
            with transaction.atomic():
                # Deletes first.
                deleted_total = 0
                for i in range(0, len(rows_to_delete), 1000):
                    batch = rows_to_delete[i:i + 1000]
                    cnt, _ = (
                        CrossReference.objects
                        .filter(id__in=batch)
                        .delete()
                    )
                    deleted_total += cnt
                    self.stdout.write(
                        f"  deleted batch {i // 1000 + 1}: "
                        f"{cnt} rows (running total {deleted_total:,})"
                    )
                    self.stdout.flush()

                # Updates next.
                update_map = dict(rows_to_update)
                ids = list(update_map.keys())
                updated_total = 0
                for i in range(0, len(ids), 2000):
                    batch_ids = ids[i:i + 2000]
                    objs = list(
                        CrossReference.objects
                        .filter(id__in=batch_ids)
                        .only("id", "interchange_type")
                    )
                    for o in objs:
                        o.interchange_type = update_map[o.id]
                    CrossReference.objects.bulk_update(
                        objs, ["interchange_type"], batch_size=2000
                    )
                    updated_total += len(objs)
                    self.stdout.write(
                        f"  updated batch {i // 2000 + 1}: "
                        f"{len(objs)} rows (running total {updated_total:,})"
                    )
                    self.stdout.flush()
        except Exception as exc:
            raise CommandError(
                f"Aborting and rolling back: {exc.__class__.__name__}: {exc}"
            ) from exc

    # ------------------------------------------------------------------ #
    # Reporting helpers
    # ------------------------------------------------------------------ #
    def _top_mfr_counts(
        self,
        groups: Dict[Tuple[int, str, str], List[dict]],
        commit: bool,
        limit,
    ) -> List[Tuple[str, int]]:
        """
        Return [(name, count)] of the top 10 normalized manufacturer names.

        After commit we ask the DB directly.  In dry-run we derive the
        count from the in-memory groups dict so the numbers reflect the
        post-cleanup state without touching the database.
        """
        if commit:
            rows = (
                CrossReference.objects
                .values("interchange_type")
                .annotate(c=Count("id"))
                .order_by("-c")[:10]
            )
            return [(r["interchange_type"], r["c"]) for r in rows]

        counts: Dict[str, int] = defaultdict(int)
        for (_unit_id, _crn, normalized), members in groups.items():
            # After dedup the group contributes exactly 1 row.
            counts[normalized] += 1

        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
        return top
