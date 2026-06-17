"""
Round-three cleanup for catalog_part / catalog_bom / catalog_bomitem.

Phase A (``cleanup_boms``) already removed phantom BOMItems and merged
duplicate BOMs per unit, but ``catalog_part`` itself had never been
deduped and a second BOMItem-level duplication pattern remained.  This
command finishes the job in six ordered steps inside a single atomic
transaction:

  Step 0 - Part text cleanups
           Strip leading/trailing whitespace from every text field on
           Part, repair malformed unclosed-paren artifacts in
           ``part_number`` / ``part_name`` / ``manufacturer_number`` /
           ``oem_number``, and strip cosmetic ``'Pg. NNN'`` suffixes.
           (Current scan finds zero rows in any of these patterns, so
           this step is a defensive no-op; included for parity with the
           CrossReference cleanup.)

  Step 1 - Part ``oem`` casing normalization
           Same approach as ``cleanup_normalize_manufacturers``: build a
           whitelist of all-caps acronyms, then for every Part row whose
           ``oem`` value differs from its normalized form, rewrite it.
           Layered on top is an explicit RENAME_MAP for hyphenation and
           spelling variants (Leece-Neville, Briggs & Stratton, etc.).
           Because ``Part.part_number`` is ``unique=True``, no
           collisions are possible from renaming alone -- this is purely
           cosmetic.

  Step 2 - Part exact-dupe merge by (normalized_oem, yt_number)
           Re-imports created multiple Part rows with the same
           ``part_name`` + ``yt_number`` (sometimes one had ``oem=''``
           and the others had ``oem='Delco'``).  Survivor is chosen by
           "completeness score" then lowest id.  CRITICAL: BOMItem rows
           pointing to losing Parts are re-pointed to the survivor
           BEFORE the loser Parts are deleted -- otherwise the CASCADE
           on ``BOMItem.part`` would silently destroy line items.

  Step 3 - Part brand-subset same-number dedup
           For brand pairs like (Mitsubishi, Mitsubishi Electric) and
           (Hitachi, Hitachi Automotive), where the SAME ``yt_number``
           appears under BOTH the base brand and its expanded variant,
           keep the base-brand row and merge the variant-brand row into
           it (BOMItem FKs re-pointed, then variant Part deleted).
           Identical safety pattern to Step 2.

  Step 4 - BOMItem exact-dupe collapse
           Group BOMItems by ``(bom_id, part_id, unit_qty)`` after
           applying the Step 2 / Step 3 Part renames; for every group
           with more than one row, keep the lowest id and delete the
           rest.  This is the BIG one -- the scan flagged ~44k
           deletable rows where every user-meaningful field is identical
           across the duplicates.

  Step 5 - Empty BOM cleanup
           After Step 4, sweep any BOM that ends up with zero BOMItems.
           (The Phase A scan found zero already-empty BOMs, but Step 4
           could theoretically create some.)

Usage:
    python manage.py cleanup_parts_boms                # dry-run (default)
    python manage.py cleanup_parts_boms --dry-run      # explicit
    python manage.py cleanup_parts_boms --commit       # apply changes
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from catalog.models import BOM, BOMItem, Part


# --------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------- #
EXPLICIT_WHITELIST = [
    # Reused from cleanup_normalize_manufacturers.py so behaviour is
    # consistent across the two commands.
    "WAI", "PIC", "OEM", "GM", "BMW", "MES", "EGI", "API", "TSA", "MGU",
    "BEPCO", "BBB", "ACDelco", "NAPA", "OE", "AC", "DC", "LRI", "SAE",
    "IMS", "JD", "GMC", "DRI", "SEG", "CAE",
]

# Explicit rename map applied AFTER whitelist+title-case.  Use only for
# hyphenation, ampersand quirks, or canonical spellings the title-case
# rule alone can't produce.
PART_OEM_RENAME_MAP: Dict[str, str] = {
    # Hyphenation / spelling
    "Leece Neville": "Leece-Neville",
    "Paris Rhone": "Paris-Rhone",
    "Mercedes Benz": "Mercedes-Benz",
    "Harley Davidson": "Harley-Davidson",
    "Poong Sung": "Poongsung",
    # Compound brand-name normalisations
    "Nippondenso": "Nippon Denso",
}

# Brand pairs whose same-yt_number rows are treated as a true duplicate.
# Format: (base_brand_oem, variant_brand_oem).  Variant rows lose.
# Mirrors PATTERN6_PAIRS in cleanup_remaining_duplicates.py.
BRAND_SUBSET_PAIRS: List[Tuple[str, str]] = [
    ("Mitsubishi", "Mitsubishi Electric"),
    ("Hitachi", "Hitachi Automotive"),
]


UNCLOSED_PAREN_RE = re.compile(r"\s*\([^)]*$")
PAGE_REF_RE = re.compile(r"\s+Pg\.\s*\d+\s*$", re.IGNORECASE)
DOUBLE_SPACE_RE = re.compile(r"  +")

# Text fields on Part that participate in Step 0 whitespace strip.
PART_TEXT_FIELDS = (
    "part_number", "part_name", "manufacturer_number", "yt_number",
    "j_and_n", "oem_number", "item_no", "oem", "primary_vendor",
    "category", "type", "oem_type", "item_typ", "catalog", "plug_id",
    "bin_number", "voltage",
)

# Fields scanned for paren / Pg.-suffix repair.
PART_PAREN_PG_FIELDS = (
    "part_number", "part_name", "manufacturer_number", "oem_number",
)


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #
def build_oem_whitelist() -> Dict[str, str]:
    """Return ``upper(token) -> canonical form`` for acronym preservation.

    Same algorithm as ``cleanup_normalize_manufacturers._build_whitelist``
    but scoped to ``Part.oem`` instead of ``CrossReference.interchange_type``.
    """
    whitelist: Dict[str, str] = {}
    for v in EXPLICIT_WHITELIST:
        whitelist[v.upper()] = v

    distinct = (
        Part.objects.exclude(oem="").values_list("oem", flat=True).distinct()
    )
    for raw in distinct:
        if raw is None:
            continue
        s = raw.strip().rstrip(".").strip()
        # Length cap: 3.  Round-D fix -- previously 4, which caused
        # 4-letter all-caps tokens like 'FORD' to be auto-whitelisted as
        # an acronym, preventing Step 1 from title-casing them.  The
        # real acronyms in EXPLICIT_WHITELIST are all <= 3 chars (or
        # already enumerated explicitly e.g. BEPCO, ACDelco), so a
        # length cap of 3 covers the legit dynamic discoveries.
        if not s or " " in s or len(s) > 3 or not s.isalnum():
            continue
        if not s.isupper():
            continue
        whitelist.setdefault(s.upper(), s)
    return whitelist


def normalize_oem(name: str, whitelist: Dict[str, str]) -> str:
    """Whitelist + title-case + explicit rename layered on top."""
    if not name:
        return ""
    s = name.strip().rstrip(".").strip()
    if not s:
        return ""
    out: List[str] = []
    for tok in s.split():
        canonical = whitelist.get(tok.upper())
        out.append(canonical if canonical is not None else tok.title())
    norm = " ".join(out)
    return PART_OEM_RENAME_MAP.get(norm, norm)


def completeness_score(part_dict: dict) -> int:
    """How many non-blank text + non-null pricing fields a Part has.

    Used as the primary sort key when choosing which Part survives a
    same-yt_number merge -- the row with more data wins.
    """
    score = 0
    for f in PART_TEXT_FIELDS:
        v = part_dict.get(f) or ""
        if isinstance(v, str) and v.strip():
            score += 1
    for f in ("cost_price", "price", "markup_percent", "price_updated_at"):
        if part_dict.get(f) is not None:
            score += 1
    if part_dict.get("specifications"):
        score += 1
    if part_dict.get("unit_id") is not None:
        score += 1
    return score


# --------------------------------------------------------------------- #
# Command
# --------------------------------------------------------------------- #
class Command(BaseCommand):
    help = (
        "Round-three cleanup for catalog_part / catalog_bom / "
        "catalog_bomitem: oem normalization, Part dupe merge with FK "
        "re-point, BOMItem dupe collapse, empty-BOM sweep.  Defaults to "
        "--dry-run."
    )

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--dry-run", action="store_true", dest="dry_run",
            help="Report what would change without writing (default).",
        )
        mode.add_argument(
            "--commit", action="store_true", dest="commit",
            help="Apply changes inside a single transaction.",
        )

    # ================================================================ #
    # Main entry
    # ================================================================ #
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
        self.stdout.write(f"Mode: {mode_label}")
        self.stdout.flush()

        try:
            with transaction.atomic():
                before_parts = Part.objects.count()
                before_boms = BOM.objects.count()
                before_items = BOMItem.objects.count()
                self.stdout.write(
                    f"Starting counts: Part={before_parts:,}  "
                    f"BOM={before_boms:,}  BOMItem={before_items:,}"
                )
                self.stdout.flush()

                # Build the oem-normalisation whitelist once -- both
                # Step 1 and Step 2 use the same canonical form.
                self.stdout.write("\nBuilding oem acronym whitelist...")
                self.stdout.flush()
                whitelist = build_oem_whitelist()
                self.stdout.write(
                    f"  whitelist size: {len(set(whitelist.values()))} "
                    f"canonical tokens"
                )
                self.stdout.flush()

                step0 = self._step0_part_text_cleanup(commit)
                step1 = self._step1_oem_normalize(commit, whitelist)

                # Steps 2 + 3 BOTH need: the post-Step-1 oem on every
                # Part, an FK-rename map (loser_pid -> survivor_pid) and
                # the set of losers to delete.  We accumulate across
                # both steps so Step 4 can apply them as a single
                # logical rename before grouping BOMItems.
                part_renames: Dict[int, int] = {}
                losers_to_delete: Set[int] = set()
                bomitems_repointed = 0
                bomitems_dropped_collisions = 0

                step2 = self._step2_part_dupe_merge_by_yt(
                    commit, whitelist, part_renames, losers_to_delete
                )
                bomitems_repointed += step2["bomitems_repointed"]
                bomitems_dropped_collisions += step2[
                    "bomitems_dropped_collisions"
                ]

                step3 = self._step3_brand_subset_merge(
                    commit, whitelist, part_renames, losers_to_delete
                )
                bomitems_repointed += step3["bomitems_repointed"]
                bomitems_dropped_collisions += step3[
                    "bomitems_dropped_collisions"
                ]

                step4 = self._step4_bomitem_dedup(commit, part_renames)
                step5 = self._step5_empty_bom_cleanup(
                    commit,
                    bomitems_dropped_in_step4=step4["deleted"],
                    bomitems_dropped_in_steps23=bomitems_dropped_collisions,
                )

                if not commit:
                    transaction.set_rollback(True)
                    after_parts = (
                        before_parts
                        - step2["parts_deleted"]
                        - step3["parts_deleted"]
                    )
                    after_boms = before_boms - step5["deleted"]
                    after_items = (
                        before_items
                        - step4["deleted"]
                        - bomitems_dropped_collisions
                    )
                else:
                    after_parts = Part.objects.count()
                    after_boms = BOM.objects.count()
                    after_items = BOMItem.objects.count()

        except Exception as exc:
            raise CommandError(
                f"Aborting and rolling back: "
                f"{exc.__class__.__name__}: {exc}"
            ) from exc

        # ============================================================ #
        # Summary
        # ============================================================ #
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("FINAL SUMMARY")
        self.stdout.write("=" * 70)
        self.stdout.write(
            f"Step 0  (Part text cleanup):        "
            f"{step0['stripped']:,} stripped, "
            f"{step0['paren_fixed']:,} parens, "
            f"{step0['pg_stripped']:,} Pg.-suffix"
        )
        self.stdout.write(
            f"Step 1  (oem normalization):        "
            f"{step1['renamed']:,} Parts renamed"
        )
        self.stdout.write(
            f"Step 2  (yt_number dupe merge):     "
            f"{step2['groups']:,} groups, "
            f"{step2['parts_deleted']:,} Parts deleted, "
            f"{step2['bomitems_repointed']:,} BOMItem FKs re-pointed, "
            f"{step2['bomitems_dropped_collisions']:,} colliding BOMItems dropped"
        )
        self.stdout.write(
            f"Step 3  (brand-subset same-yt):     "
            f"{step3['groups']:,} groups, "
            f"{step3['parts_deleted']:,} Parts deleted, "
            f"{step3['bomitems_repointed']:,} BOMItem FKs re-pointed, "
            f"{step3['bomitems_dropped_collisions']:,} colliding BOMItems dropped"
        )
        self.stdout.write(
            f"Step 4  (BOMItem dupe collapse):    "
            f"{step4['groups']:,} groups, "
            f"{step4['deleted']:,} BOMItems deleted"
        )
        self.stdout.write(
            f"Step 5  (empty BOM cleanup):        "
            f"{step5['deleted']:,} BOMs deleted"
        )
        self.stdout.write(
            f"\nPart:    {before_parts:,} -> {after_parts:,} "
            f"({after_parts - before_parts:+,})"
        )
        self.stdout.write(
            f"BOM:     {before_boms:,} -> {after_boms:,} "
            f"({after_boms - before_boms:+,})"
        )
        self.stdout.write(
            f"BOMItem: {before_items:,} -> {after_items:,} "
            f"({after_items - before_items:+,})"
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
        self.stdout.write(f"\nElapsed: {time.time() - start:.2f}s")
        self.stdout.flush()

    # ================================================================ #
    # Step 0 - Part text cleanups
    # ================================================================ #
    def _step0_part_text_cleanup(self, commit: bool) -> dict:
        self.stdout.write("\n--- Step 0: Part text cleanup ---")
        self.stdout.flush()

        # ---- Fast-path precheck ----
        # If no text field on any Part has leading/trailing whitespace,
        # internal double-spaces, unclosed parens, or 'Pg. NNN' suffixes
        # we can skip the full 54k-row iteration entirely.  The Round-3
        # scan confirmed all four patterns are currently empty, but we
        # re-check at runtime in case the DB has changed.
        # Build "any field matches any anomaly" filter dynamically.
        from django.db.models import Q
        anomaly_q = Q()
        for f in PART_TEXT_FIELDS:
            anomaly_q |= Q(**{f"{f}__regex": r"^ "})
            anomaly_q |= Q(**{f"{f}__regex": r" $"})
            anomaly_q |= Q(**{f"{f}__regex": r"  "})
        for f in PART_PAREN_PG_FIELDS:
            anomaly_q |= (
                Q(**{f"{f}__contains": "("})
                & ~Q(**{f"{f}__contains": ")"})
            )
            anomaly_q |= Q(**{f"{f}__iregex": r" Pg\.\s*\d"})

        any_dirty = Part.objects.filter(anomaly_q).exists()
        if not any_dirty:
            self.stdout.write(
                "  Fast-path: no whitespace / paren / Pg.-suffix "
                "anomalies in any Part text field.  Step 0 is a no-op."
            )
            self.stdout.flush()
            return {"stripped": 0, "paren_fixed": 0, "pg_stripped": 0}

        stripped = 0
        paren_fixed = 0
        pg_stripped = 0
        sample_strip: List[str] = []
        sample_paren: List[str] = []
        sample_pg: List[str] = []

        # Whitespace strip (every text field).
        # We do this with a single iterator over all Parts and bulk_update
        # only the ones that actually changed.
        to_update: List[Part] = []
        update_fields_seen: Set[str] = set()

        all_parts = (
            Part.objects.all()
            .only("id", *PART_TEXT_FIELDS)
            .iterator(chunk_size=2000)
        )
        for p in all_parts:
            changed = False
            for f in PART_TEXT_FIELDS:
                v = getattr(p, f)
                if v is None:
                    continue
                if not isinstance(v, str):
                    continue
                new = v.strip()
                if "  " in new:
                    new = DOUBLE_SPACE_RE.sub(" ", new)
                if new != v:
                    setattr(p, f, new)
                    changed = True
                    update_fields_seen.add(f)
            # Paren / Pg. repair on the eligible columns.
            for f in PART_PAREN_PG_FIELDS:
                v = getattr(p, f)
                if not v:
                    continue
                if "(" in v and ")" not in v:
                    new = UNCLOSED_PAREN_RE.sub("", v).strip()
                    if new and new != v:
                        setattr(p, f, new)
                        paren_fixed += 1
                        update_fields_seen.add(f)
                        if len(sample_paren) < 5:
                            sample_paren.append(
                                f"id={p.id} {f}: '{v}' -> '{new}'"
                            )
                        changed = True
                if PAGE_REF_RE.search(getattr(p, f) or ""):
                    cur = getattr(p, f)
                    new = PAGE_REF_RE.sub("", cur).strip()
                    if new and new != cur:
                        setattr(p, f, new)
                        pg_stripped += 1
                        update_fields_seen.add(f)
                        if len(sample_pg) < 5:
                            sample_pg.append(
                                f"id={p.id} {f}: '{cur}' -> '{new}'"
                            )
                        changed = True
            if changed:
                stripped += 1
                if len(sample_strip) < 5:
                    sample_strip.append(f"id={p.id}")
                to_update.append(p)

        self.stdout.write(
            f"  Parts with text changes: {stripped:,}  "
            f"(parens={paren_fixed}, Pg.-strip={pg_stripped})"
        )
        if sample_paren:
            self.stdout.write("  Sample paren repairs:")
            for s in sample_paren:
                self.stdout.write(f"    {s}")
        if sample_pg:
            self.stdout.write("  Sample Pg.-strips:")
            for s in sample_pg:
                self.stdout.write(f"    {s}")
        self.stdout.flush()

        if commit and to_update and update_fields_seen:
            for i in range(0, len(to_update), 500):
                batch = to_update[i:i + 500]
                Part.objects.bulk_update(
                    batch, sorted(update_fields_seen), batch_size=500
                )

        return {
            "stripped": stripped,
            "paren_fixed": paren_fixed,
            "pg_stripped": pg_stripped,
        }

    # ================================================================ #
    # Step 1 - oem casing normalization (whitelist + title-case)
    # ================================================================ #
    def _step1_oem_normalize(
        self, commit: bool, whitelist: Dict[str, str]
    ) -> dict:
        self.stdout.write("\n--- Step 1: Part oem normalization ---")
        self.stdout.flush()

        rename_count: Dict[str, str] = {}
        per_target_count: Dict[str, int] = defaultdict(int)
        renamed_ids: List[Tuple[int, str]] = []

        rows = (
            Part.objects.exclude(oem="")
            .values("id", "oem")
            .iterator(chunk_size=5000)
        )
        for r in rows:
            cur = r["oem"]
            new = normalize_oem(cur, whitelist)
            if not new or new == cur:
                continue
            renamed_ids.append((r["id"], new))
            rename_count[cur] = new
            per_target_count[new] += 1

        self.stdout.write(
            f"  Parts whose oem changes: {len(renamed_ids):,}"
        )
        self.stdout.write(
            f"  Distinct (old, new) rename keys: {len(rename_count):,}"
        )
        # Top 15 (old -> new) by row count
        ordered = sorted(
            rename_count.items(),
            key=lambda kv: -per_target_count[kv[1]],
        )[:15]
        if ordered:
            self.stdout.write("  Top 15 renames (by target row count):")
            for old, new in ordered:
                self.stdout.write(
                    f"    '{old}' -> '{new}' (target now has "
                    f"{per_target_count[new]:,} parts contributing)"
                )
        self.stdout.flush()

        if commit and renamed_ids:
            id_to_new = dict(renamed_ids)
            ids = list(id_to_new.keys())
            for i in range(0, len(ids), 2000):
                batch_ids = ids[i:i + 2000]
                objs = list(
                    Part.objects.filter(id__in=batch_ids).only("id", "oem")
                )
                for o in objs:
                    o.oem = id_to_new[o.id]
                Part.objects.bulk_update(objs, ["oem"], batch_size=2000)

        return {"renamed": len(renamed_ids)}

    # ================================================================ #
    # Step 2 - Part dupe merge by (normalized_oem, yt_number)
    # ================================================================ #
    def _step2_part_dupe_merge_by_yt(
        self,
        commit: bool,
        whitelist: Dict[str, str],
        part_renames: Dict[int, int],
        losers_to_delete: Set[int],
    ) -> dict:
        self.stdout.write(
            "\n--- Step 2: Part exact-dupe merge "
            "(normalized_oem + yt_number) ---"
        )
        self.stdout.flush()

        # Pull every Part with a non-empty yt_number.  Compute
        # normalized oem on the fly so we don't depend on Step 1 having
        # already written to the DB.
        scan_fields = list(PART_TEXT_FIELDS) + [
            "id", "unit_id", "specifications",
            "cost_price", "price", "markup_percent", "price_updated_at",
        ]
        scan_fields = list({f for f in scan_fields})

        rows = list(
            Part.objects.exclude(yt_number="").values(*scan_fields)
        )

        # Apply Step-1 normalization in-memory so the grouping matches
        # the post-Step-1 world.
        for r in rows:
            r["_norm_oem"] = normalize_oem(r.get("oem") or "", whitelist)

        # Group by (norm_oem, yt_number).  Treat oem='' as a special
        # bucket that joins with any oem -- but only when at least one
        # row in the group has a non-empty oem (so we don't accidentally
        # merge two genuinely-different blank-oem rows that happen to
        # share a yt_number).  In practice the scan showed this case is
        # the dominant pattern.
        groups: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
        for r in rows:
            key = (r["_norm_oem"], r["yt_number"].strip())
            groups[key].append(r)

        # Also build an index from yt_number alone so we can join
        # blank-oem rows into a sibling group when one exists.
        yt_index: Dict[str, List[Tuple[str, dict]]] = defaultdict(list)
        for (oem, yt), members in groups.items():
            for m in members:
                yt_index[yt].append((oem, m))

        # Reconstruct merge-clusters: for each yt_number, if at least
        # one row has non-empty norm_oem and all non-empty norm_oems
        # agree, then the cluster = every row with that yt_number
        # (including the blank-oem rows).
        merge_clusters: List[List[dict]] = []
        seen_ids: Set[int] = set()
        for yt, members in yt_index.items():
            distinct_oems = {oem for oem, _m in members if oem}
            if len(distinct_oems) > 1:
                # Two genuinely different brands share a yt_number.
                # That's not a duplicate -- leave it alone.  Step 3 may
                # still merge it if it's a known brand-subset pair.
                continue
            if not distinct_oems:
                # All blank oem.  Conservatively skip -- without a
                # brand to confirm equivalence, merging by yt alone is
                # too risky.
                continue
            cluster = [m for _oem, m in members]
            if len(cluster) < 2:
                continue
            ids = {m["id"] for m in cluster}
            if ids & seen_ids:
                continue
            seen_ids.update(ids)
            merge_clusters.append(cluster)

        self.stdout.write(
            f"  Mergeable yt_number clusters: {len(merge_clusters):,}"
        )

        # Run the merge.
        total_parts_deleted = 0
        total_bomitems_repointed = 0
        total_bomitems_dropped = 0
        sample_lines: List[str] = []

        for cluster in merge_clusters:
            # Pick survivor: highest completeness, then lowest id.
            cluster.sort(
                key=lambda r: (
                    -completeness_score(r),
                    r["id"],
                )
            )
            survivor = cluster[0]
            losers = cluster[1:]

            survivor_id = survivor["id"]
            loser_ids = [m["id"] for m in losers]

            for lid in loser_ids:
                part_renames[lid] = survivor_id
                losers_to_delete.add(lid)

            # Re-point BOMItem FKs.  Compute potential collisions
            # against existing (bom_id, part_id=survivor) rows.
            repointed, dropped = self._repoint_bomitems(
                loser_ids, survivor_id, commit
            )
            total_bomitems_repointed += repointed
            total_bomitems_dropped += dropped
            total_parts_deleted += len(loser_ids)

            if len(sample_lines) < 8:
                norm_oem = normalize_oem(
                    survivor.get("oem") or "",
                    build_oem_whitelist(),  # cheap dict
                )
                sample_lines.append(
                    f"yt='{survivor['yt_number']}' "
                    f"oem='{norm_oem}' "
                    f"KEEP id={survivor_id} (score={completeness_score(survivor)})  "
                    f"DROP {len(loser_ids)} loser(s) ids={loser_ids[:5]}"
                    + ("..." if len(loser_ids) > 5 else "")
                )

        self.stdout.write(
            f"  Parts to delete:       {total_parts_deleted:,}"
        )
        self.stdout.write(
            f"  BOMItem FKs to re-point: {total_bomitems_repointed:,}"
        )
        self.stdout.write(
            f"  BOMItem collisions to drop: {total_bomitems_dropped:,}"
        )
        if sample_lines:
            self.stdout.write("  Sample merges:")
            for s in sample_lines:
                self.stdout.write(f"    {s}")
        self.stdout.flush()

        if commit and losers_to_delete:
            # Re-pointing already happened inside the helper.
            # Deletion happens once per command run in step 3's tail.
            pass

        return {
            "groups": len(merge_clusters),
            "parts_deleted": total_parts_deleted,
            "bomitems_repointed": total_bomitems_repointed,
            "bomitems_dropped_collisions": total_bomitems_dropped,
        }

    # ================================================================ #
    # Step 3 - Brand-subset same-yt_number merge
    # ================================================================ #
    def _step3_brand_subset_merge(
        self,
        commit: bool,
        whitelist: Dict[str, str],
        part_renames: Dict[int, int],
        losers_to_delete: Set[int],
    ) -> dict:
        self.stdout.write(
            "\n--- Step 3: Brand-subset same-yt_number merge ---"
        )
        self.stdout.flush()

        total_groups = 0
        total_parts_deleted = 0
        total_bomitems_repointed = 0
        total_bomitems_dropped = 0
        sample_lines: List[str] = []

        for base_oem, variant_oem in BRAND_SUBSET_PAIRS:
            # Find variant-brand Parts that share yt_number with a
            # base-brand Part.  Apply Step-1 normalization in-memory.
            variant_rows = list(
                Part.objects.exclude(yt_number="")
                .values("id", "oem", "yt_number")
            )
            variant_rows = [
                r for r in variant_rows
                if (
                    normalize_oem(r["oem"] or "", whitelist) == variant_oem
                    and r["id"] not in losers_to_delete
                )
            ]

            # Build index of base-brand yt_numbers -> id
            base_index: Dict[str, int] = {}
            base_rows = list(
                Part.objects.exclude(yt_number="").values("id", "oem", "yt_number")
            )
            for r in base_rows:
                if r["id"] in losers_to_delete:
                    continue
                if normalize_oem(r["oem"] or "", whitelist) == base_oem:
                    base_index.setdefault(
                        r["yt_number"].strip(), r["id"]
                    )

            pair_loser_ids: List[int] = []
            pair_survivor_pairs: List[Tuple[int, int, str]] = []
            for r in variant_rows:
                yt = r["yt_number"].strip()
                base_id = base_index.get(yt)
                if base_id is None or base_id == r["id"]:
                    continue
                pair_loser_ids.append(r["id"])
                pair_survivor_pairs.append((r["id"], base_id, yt))

            if not pair_loser_ids:
                self.stdout.write(
                    f"  ({variant_oem}) -> ({base_oem}): no overlap"
                )
                continue

            for lid, sid, _yt in pair_survivor_pairs:
                part_renames[lid] = sid
                losers_to_delete.add(lid)

            repointed, dropped = self._repoint_bomitems_grouped(
                pair_survivor_pairs, commit
            )
            total_bomitems_repointed += repointed
            total_bomitems_dropped += dropped
            total_parts_deleted += len(pair_loser_ids)
            total_groups += len(pair_loser_ids)

            self.stdout.write(
                f"  ({variant_oem}) -> ({base_oem}): "
                f"{len(pair_loser_ids):,} Parts merged "
                f"(repoint={repointed}, drop_collide={dropped})"
            )
            for lid, sid, yt in pair_survivor_pairs[:5]:
                if len(sample_lines) < 8:
                    sample_lines.append(
                        f"  yt='{yt}'  DROP id={lid} ('{variant_oem}')  "
                        f"-> KEEP id={sid} ('{base_oem}')"
                    )

        if sample_lines:
            self.stdout.write("  Samples:")
            for s in sample_lines:
                self.stdout.write(f"    {s}")
        self.stdout.flush()

        if commit and losers_to_delete:
            # Final shared deletion of all losers across Steps 2+3.
            self._bulk_delete_parts(list(losers_to_delete))

        return {
            "groups": total_groups,
            "parts_deleted": total_parts_deleted,
            "bomitems_repointed": total_bomitems_repointed,
            "bomitems_dropped_collisions": total_bomitems_dropped,
        }

    # ================================================================ #
    # Step 4 - BOMItem exact-dupe collapse
    # ================================================================ #
    def _step4_bomitem_dedup(
        self, commit: bool, part_renames: Dict[int, int]
    ) -> dict:
        self.stdout.write(
            "\n--- Step 4: BOMItem exact-dupe collapse ---"
        )
        self.stdout.flush()

        def logical_pid(pid: Optional[int]) -> Optional[int]:
            seen = set()
            while pid in part_renames and pid not in seen:
                seen.add(pid)
                pid = part_renames[pid]
            return pid

        groups: Dict[Tuple[int, Optional[int], int], List[int]] = defaultdict(list)
        for bi in (
            BOMItem.objects.values(
                "id", "bom_id", "part_id", "unit_qty"
            ).iterator(chunk_size=10000)
        ):
            key = (
                bi["bom_id"],
                logical_pid(bi["part_id"]),
                bi["unit_qty"],
            )
            groups[key].append(bi["id"])

        to_delete: List[int] = []
        size_dist: Dict[int, int] = defaultdict(int)
        for key, ids in groups.items():
            if len(ids) < 2:
                continue
            size_dist[len(ids)] += 1
            ids.sort()
            to_delete.extend(ids[1:])

        self.stdout.write(
            f"  Duplicate BOMItem groups: "
            f"{sum(size_dist.values()):,}"
        )
        self.stdout.write("  Group-size distribution:")
        for n in sorted(size_dist):
            self.stdout.write(
                f"    n={n}: {size_dist[n]:,} groups  "
                f"({size_dist[n] * (n - 1):,} deletable rows)"
            )
        self.stdout.write(
            f"  Total BOMItems to delete: {len(to_delete):,}"
        )
        self.stdout.flush()

        if commit and to_delete:
            for i in range(0, len(to_delete), 1000):
                batch = to_delete[i:i + 1000]
                BOMItem.objects.filter(id__in=batch).delete()

        return {
            "groups": sum(size_dist.values()),
            "deleted": len(to_delete),
        }

    # ================================================================ #
    # Step 5 - Empty BOM cleanup
    # ================================================================ #
    def _step5_empty_bom_cleanup(
        self,
        commit: bool,
        bomitems_dropped_in_step4: int,
        bomitems_dropped_in_steps23: int,
    ) -> dict:
        self.stdout.write("\n--- Step 5: Empty BOM cleanup ---")
        self.stdout.flush()

        # In --commit mode the previous steps have already removed
        # rows, so a direct annotate(Count) works.  In --dry-run we
        # don't have a way to project this perfectly without replaying
        # every delete in memory; we approximate by simply reporting
        # the current count of empty BOMs PLUS warning that any new
        # empties created by Step 4 would only become visible at commit
        # time.
        empty_qs = BOM.objects.annotate(_n=Count("items")).filter(_n=0)
        empty_ids = list(empty_qs.values_list("id", flat=True))

        self.stdout.write(
            f"  Empty BOMs (right now, pre-Step-4 simulation): "
            f"{len(empty_ids):,}"
        )
        if bomitems_dropped_in_step4 or bomitems_dropped_in_steps23:
            self.stdout.write(
                f"  Note: Step 4 would delete {bomitems_dropped_in_step4:,} "
                f"BOMItems and Steps 2+3 would drop "
                f"{bomitems_dropped_in_steps23:,} collisions; any BOMs "
                f"that go to zero items as a result would also be "
                f"removed (only visible under --commit)."
            )
        self.stdout.flush()

        if commit and empty_ids:
            for i in range(0, len(empty_ids), 1000):
                batch = empty_ids[i:i + 1000]
                BOM.objects.filter(id__in=batch).delete()
            # Re-sweep once more in case Step 4 emptied a BOM.
            empty_qs2 = BOM.objects.annotate(_n=Count("items")).filter(_n=0)
            second_pass = list(empty_qs2.values_list("id", flat=True))
            if second_pass:
                for i in range(0, len(second_pass), 1000):
                    batch = second_pass[i:i + 1000]
                    BOM.objects.filter(id__in=batch).delete()
                empty_ids.extend(second_pass)

        return {"deleted": len(empty_ids)}

    # ================================================================ #
    # Shared helpers
    # ================================================================ #
    def _repoint_bomitems(
        self, loser_ids: List[int], survivor_id: int, commit: bool
    ) -> Tuple[int, int]:
        """Re-point all BOMItem.part_id from loser_ids -> survivor_id.

        Returns (repointed_count, dropped_collisions_count).  Drops are
        BOMItem rows whose ``(bom_id, survivor_id, unit_qty)`` already
        exists on the survivor side -- they'd just become Step-4 dupes,
        so we delete them up-front instead of letting them pile up.
        """
        if not loser_ids:
            return 0, 0

        # Look up loser BOMItems.
        loser_items = list(
            BOMItem.objects.filter(part_id__in=loser_ids)
            .values("id", "bom_id", "unit_qty")
        )
        if not loser_items:
            return 0, 0

        # Find existing survivor BOMItems for the relevant BOMs.
        relevant_bom_ids = {it["bom_id"] for it in loser_items}
        survivor_set: Set[Tuple[int, int]] = set(
            (r["bom_id"], r["unit_qty"])
            for r in BOMItem.objects.filter(
                part_id=survivor_id, bom_id__in=relevant_bom_ids
            ).values("bom_id", "unit_qty")
        )

        to_repoint: List[int] = []
        to_drop: List[int] = []
        for it in loser_items:
            key = (it["bom_id"], it["unit_qty"])
            if key in survivor_set:
                # Survivor already has this exact (bom, qty); drop the
                # loser-side row outright.
                to_drop.append(it["id"])
            else:
                # Safe to re-point; pre-register so the next loser in
                # the same loop sees it.
                survivor_set.add(key)
                to_repoint.append(it["id"])

        if commit and to_repoint:
            for i in range(0, len(to_repoint), 1000):
                batch = to_repoint[i:i + 1000]
                BOMItem.objects.filter(id__in=batch).update(
                    part_id=survivor_id
                )
        if commit and to_drop:
            for i in range(0, len(to_drop), 1000):
                batch = to_drop[i:i + 1000]
                BOMItem.objects.filter(id__in=batch).delete()

        return len(to_repoint), len(to_drop)

    def _repoint_bomitems_grouped(
        self,
        pairs: List[Tuple[int, int, str]],
        commit: bool,
    ) -> Tuple[int, int]:
        """Batched ``_repoint_bomitems`` for many (loser, survivor) pairs.

        Each pair has its own survivor, so we can't lump them all into
        a single ``update`` call.  Group by survivor first.
        """
        by_survivor: Dict[int, List[int]] = defaultdict(list)
        for lid, sid, _yt in pairs:
            by_survivor[sid].append(lid)
        total_repoint = 0
        total_drop = 0
        for sid, lids in by_survivor.items():
            r, d = self._repoint_bomitems(lids, sid, commit)
            total_repoint += r
            total_drop += d
        return total_repoint, total_drop

    def _bulk_delete_parts(self, ids: List[int]) -> None:
        for i in range(0, len(ids), 1000):
            batch = ids[i:i + 1000]
            Part.objects.filter(id__in=batch).delete()
