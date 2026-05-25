"""
Round-two CrossReference cleanup that finds the duplicate patterns Phase A
missed.

Runs four passes in a single transaction:

  Step 0 - Repair malformed-paren cross_ref_numbers (parser line-wrap
           artifacts like '400-12003 (12V').  If a clean counterpart already
           exists on the same unit+brand, delete the malformed row; else
           strip the partial annotation in-place.

  Step 1 - Annotation merge.  For every pair (unit, brand, base_num) and
           (unit, brand, base_num + ' (' + label + ')') on the same unit
           and the same brand, keep the annotated row and delete the bare
           one.  The annotation describes the part's condition or source
           (e.g. '(New Aftermarket)', '(Remanufactured)') and is the
           PDF-authoritative form; the bare row came from the Lester import
           for the same physical SKU.

  Step 2 - Manufacturer-name rename map.  Collapses formatting / spelling
           variants of the same brand to a single canonical spelling
           (e.g. 'WAI (Old)' -> 'WAI Old', 'AC Delco' -> 'ACDelco',
           'API Marine' -> 'API Marine Inc', 'Industry Old' -> 'Industry').
           After renames, dedupes any (unit, number, interchange_type)
           collisions that result.

  Step 3 - Pattern-6 same-number overlaps.  For NAPA/NAPA New, PIC/PIC (Old),
           J&N/J&N (Old), where the SAME number appears on the same unit
           under BOTH the base brand and its New/Old variant, delete the
           variant-brand row and keep the base-brand row (since 97%+ of the
           variant rows are legitimately different numbers).

Usage:
    python manage.py cleanup_remaining_duplicates              # dry-run
    python manage.py cleanup_remaining_duplicates --dry-run    # explicit
    python manage.py cleanup_remaining_duplicates --commit     # apply
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Dict, List, Tuple

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import CrossReference


RENAME_MAP: Dict[str, str] = {
    # Pattern 2: parenthesis vs no-parenthesis (same word, formatting only)
    "WAI (Old)": "WAI Old",
    "Lester (Old)": "Lester Old",
    "Delco (Europe)": "Delco Europe",
    "China (Made)": "China Made",
    # Pattern 3: corporate-suffix variants (PDF-authoritative when known)
    "API Marine": "API Marine Inc",
    "Anthony": "Anthony Co",
    "Eaton": "Eaton Corporation",
    "Motor Coach": "Motor Coach Industries",
    "Schaeff": "Schaeff Inc",
    # Pattern 5: spelling / punctuation / stray-space variants
    "AC Delco": "ACDelco",
    "J & N": "J&N",
    "Delco- REMY": "Delco-Remy",
    "Leece Neville": "Leece-Neville",
    "Leece- Neville": "Leece-Neville",
    "Mercedes Benz": "Mercedes-Benz",
    "Mercedes- Benz": "Mercedes-Benz",
    "Beck/Arnley": "Beck Arnley",
    "Landrover": "Land Rover",
    "Bluebird": "Blue Bird",
    "Chris-Craft": "Chris Craft",
    "Sea Doo": "Sea-Doo",
    "Atlas Copco": "Atlas-Copco",
    "Atlas- Copco": "Atlas-Copco",
    "All- Tek": "All-Tek",
    "Aquapower": "Aqua Power",
    "Autocrane": "Auto Crane",
    "Auto-Union": "Auto Union",
    "Ez Go": "E-Z-Go",
    "Ez-Go": "E-Z-Go",
    "Electrodyne": "Electro-Dyne",
    "FIAT Allis": "Fiatallis",
    "P.C.M": "PCM",
    "Regitar Usa": "Regitar-Usa",
    "Rolls Royce": "Rolls-Royce",
    "Skytrak": "Sky Trak",
    "Ssang Yong": "Ssangyong",
    "Tecumseh/Laus On": "Tecumseh/Lauson",
    "Thermo King": "Thermo-King",
    "Thermo- King": "Thermo-King",
    "U.S.Marine": "US Marine",
    # Pattern 6 partial: Industry Old is 10 rows, all 5 overlapping cases
    # share the same number with Industry -- safe to fold in.
    "Industry Old": "Industry",
    # Romaine is an abbreviation of Romaine Electric used by Lester.
    # (Romaine High Performance stays separate -- different product line.)
    "Romaine": "Romaine Electric",
}


# Brand pairs where same-number overlap on same unit is treated as a true
# duplicate.  Format: (base_brand, variant_brand).  Variant-brand rows lose
# (i.e., we keep the base_brand row and delete the variant_brand row).
PATTERN6_PAIRS: List[Tuple[str, str]] = [
    # Old/New product line variants (rare, already handled)
    ("NAPA", "NAPA New"),
    ("PIC", "PIC (Old)"),
    ("J&N", "J&N (Old)"),
    # Brand-subset duplicates (same brand, just abbreviated by Lester import
    # vs the PDF using the full company name).  User-approved 2026-05-25.
    ("SEG Automotive", "SEG"),
    ("Dixie Electric Ltd", "Dixie"),
    ("Hitachi", "Hitachi Automotive"),
    ("DRI", "DRI Dk"),
    ("Dubois", "Dubois Usa"),
    ("Wood Auto", "Wood Auto Supplies"),
    ("MES Motorcycle & Marine", "MES"),
]


UNCLOSED_PAREN_RE = re.compile(r"\s*\([^)]*$")
PAGE_REF_RE = re.compile(r"\s+Pg\.\s*\d+\s*$", re.IGNORECASE)


class Command(BaseCommand):
    help = (
        "Round-two CrossReference cleanup: malformed-paren repair, "
        "annotation merge, mfr-name rename map, and Pattern-6 same-number "
        "overlap dedup."
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
                before_total = CrossReference.objects.count()
                self.stdout.write(
                    f"Starting CrossReference rows: {before_total:,}\n"
                )
                self.stdout.flush()

                # Order: parser repair + page-ref strip, rename mfrs FIRST
                # (so annotation merge can see all variants under the same
                # brand), then annotation merge, then Pattern-6.
                step0 = self._step0_repair_malformed_parens(commit)
                step0b = self._step0b_strip_page_refs(commit)
                step0c = self._step0c_delete_pageref_only(commit)
                step2 = self._step2_rename_mfr_names(commit)
                step1 = self._step1_annotation_merge(commit)
                step3 = self._step3_pattern6_same_number(commit)

                if not commit:
                    transaction.set_rollback(True)

                after_total = (
                    CrossReference.objects.count()
                    if commit
                    else before_total - (
                        step0["deleted"] + step0b["deleted"]
                        + step0c["deleted"] + step1["deleted"]
                        + step2["deleted"] + step3["deleted"]
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
            f"Step 0  (malformed-paren repair): "
            f"{step0['deleted']:,} deleted, {step0['updated']:,} repaired"
        )
        self.stdout.write(
            f"Step 0b (Pg. page-ref strip):     "
            f"{step0b['deleted']:,} deleted, {step0b['updated']:,} stripped"
        )
        self.stdout.write(
            f"Step 0c (Pg.-only garbage del):   "
            f"{step0c['deleted']:,} deleted"
        )
        self.stdout.write(
            f"Step 1  (annotation merge):       "
            f"{step1['deleted']:,} deleted"
        )
        self.stdout.write(
            f"Step 2  (mfr-name rename):        "
            f"{step2['renamed']:,} renamed, {step2['deleted']:,} merged"
        )
        self.stdout.write(
            f"Step 3  (Pattern-6 same-number):  "
            f"{step3['deleted']:,} deleted"
        )
        total_deleted = (
            step0["deleted"] + step0b["deleted"]
            + step0c["deleted"] + step1["deleted"]
            + step2["deleted"] + step3["deleted"]
        )
        self.stdout.write(
            f"\nTOTAL rows removed: {total_deleted:,}"
        )
        self.stdout.write(
            f"CrossReference: {before_total:,} -> {after_total:,} "
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
    # Step 0 - Repair malformed-paren cross_ref_numbers
    # ================================================================== #
    def _step0_repair_malformed_parens(self, commit: bool) -> dict:
        self.stdout.write("\n--- Step 0: Repair malformed parens ---")
        self.stdout.flush()

        rows = list(
            CrossReference.objects
            .filter(cross_ref_number__contains="(")
            .exclude(cross_ref_number__contains=")")
            .values("id", "unit_id", "interchange_type", "cross_ref_number")
        )
        self.stdout.write(f"  Rows with unclosed parens: {len(rows):,}")
        self.stdout.flush()

        to_delete: List[int] = []
        to_update: List[Tuple[int, str]] = []
        sample_delete: List[str] = []
        sample_update: List[Tuple[str, str]] = []

        for r in rows:
            cleaned = UNCLOSED_PAREN_RE.sub("", r["cross_ref_number"]).strip()
            if not cleaned:
                # Pathological case: nothing left after strip; skip.
                continue
            existing = (
                CrossReference.objects
                .filter(
                    unit_id=r["unit_id"],
                    interchange_type=r["interchange_type"],
                    cross_ref_number=cleaned,
                )
                .exclude(id=r["id"])
                .values_list("id", flat=True)
                .first()
            )
            if existing:
                to_delete.append(r["id"])
                if len(sample_delete) < 5:
                    sample_delete.append(
                        f"id={r['id']} '{r['cross_ref_number']}' "
                        f"(clean='{cleaned}' kept as id={existing})"
                    )
            else:
                to_update.append((r["id"], cleaned))
                if len(sample_update) < 5:
                    sample_update.append((r["cross_ref_number"], cleaned))

        self.stdout.write(
            f"  Plan: delete {len(to_delete):,}, "
            f"in-place repair {len(to_update):,}"
        )
        if sample_delete:
            self.stdout.write("  Sample deletes (counterpart exists):")
            for s in sample_delete:
                self.stdout.write(f"    {s}")
        if sample_update:
            self.stdout.write("  Sample in-place repairs:")
            for before, after in sample_update:
                self.stdout.write(f"    '{before}' -> '{after}'")
        self.stdout.flush()

        if commit:
            self._bulk_delete(to_delete)
            self._bulk_update_crn(to_update)

        return {"deleted": len(to_delete), "updated": len(to_update)}

    # ================================================================== #
    # Step 0b - Strip 'Pg. NNN' page references from cross_ref_number
    # ================================================================== #
    def _step0b_strip_page_refs(self, commit: bool) -> dict:
        self.stdout.write("\n--- Step 0b: Strip 'Pg. NNN' page refs ---")
        self.stdout.flush()

        rows = list(
            CrossReference.objects
            .filter(cross_ref_number__iregex=r" Pg\.\s*\d")
            .values("id", "unit_id", "interchange_type", "cross_ref_number")
        )
        self.stdout.write(f"  Rows with 'Pg. NNN' suffix: {len(rows):,}")
        self.stdout.flush()

        to_delete: List[int] = []
        to_update: List[Tuple[int, str]] = []
        sample_delete: List[str] = []
        sample_update: List[Tuple[str, str]] = []

        for r in rows:
            cleaned = PAGE_REF_RE.sub("", r["cross_ref_number"]).strip()
            if not cleaned or cleaned == r["cross_ref_number"]:
                continue
            existing = (
                CrossReference.objects
                .filter(
                    unit_id=r["unit_id"],
                    interchange_type=r["interchange_type"],
                    cross_ref_number=cleaned,
                )
                .exclude(id=r["id"])
                .values_list("id", flat=True)
                .first()
            )
            if existing:
                to_delete.append(r["id"])
                if len(sample_delete) < 5:
                    sample_delete.append(
                        f"id={r['id']} '{r['cross_ref_number']}' "
                        f"(clean='{cleaned}' kept as id={existing})"
                    )
            else:
                to_update.append((r["id"], cleaned))
                if len(sample_update) < 5:
                    sample_update.append((r["cross_ref_number"], cleaned))

        self.stdout.write(
            f"  Plan: delete {len(to_delete):,}, "
            f"in-place strip {len(to_update):,}"
        )
        if sample_delete:
            self.stdout.write("  Sample deletes (counterpart exists):")
            for s in sample_delete:
                self.stdout.write(f"    {s}")
        if sample_update:
            self.stdout.write("  Sample in-place strips:")
            for before, after in sample_update:
                self.stdout.write(f"    '{before}' -> '{after}'")
        self.stdout.flush()

        if commit:
            self._bulk_delete(to_delete)
            self._bulk_update_crn(to_update)

        return {"deleted": len(to_delete), "updated": len(to_update)}

    # ================================================================== #
    # Step 0c - Delete garbage rows where cross_ref_number is *only* a
    #           page reference (e.g., 'Pg. 17810') with no real number.
    # ================================================================== #
    def _step0c_delete_pageref_only(self, commit: bool) -> dict:
        self.stdout.write("\n--- Step 0c: Delete 'Pg.-only' garbage rows ---")
        self.stdout.flush()

        ids = list(
            CrossReference.objects
            .filter(cross_ref_number__iregex=r"^Pg\.\s*\d+\s*$")
            .values_list("id", flat=True)
        )
        self.stdout.write(f"  Rows where cross_ref_number is 'Pg. NNN' only: {len(ids):,}")

        # Sample a few to show
        samples = list(
            CrossReference.objects
            .filter(id__in=ids[:8])
            .values("id", "unit_id", "interchange_type", "cross_ref_number")
        )
        for s in samples:
            self.stdout.write(
                f"    id={s['id']} unit={s['unit_id']} brand='{s['interchange_type']}'"
                f"  num='{s['cross_ref_number']}'"
            )
        self.stdout.flush()

        if commit:
            self._bulk_delete(ids)

        return {"deleted": len(ids)}

    # ================================================================== #
    # Step 1 - Annotation merge
    # ================================================================== #
    def _step1_annotation_merge(self, commit: bool) -> dict:
        self.stdout.write("\n--- Step 1: Annotation merge ---")
        self.stdout.flush()

        # Index every (unit_id, brand_lower) -> list of (id, crn)
        groups: Dict[Tuple[int, str], List[Tuple[int, str]]] = defaultdict(list)
        qs = (
            CrossReference.objects
            .all()
            .only("id", "unit_id", "interchange_type", "cross_ref_number")
            .iterator(chunk_size=5000)
        )
        for r in qs:
            crn = r.cross_ref_number or ""
            if not crn:
                continue
            brand_l = (r.interchange_type or "").lower()
            groups[(r.unit_id, brand_l)].append((r.id, crn))

        to_delete_set: set = set()
        sample: List[str] = []
        annot_label_count: Dict[str, int] = defaultdict(int)

        for (unit_id, brand_l), members in groups.items():
            if len(members) < 2:
                continue
            # Build map of bare number -> list of ids (multiple possible)
            num_to_ids: Dict[str, List[int]] = defaultdict(list)
            for rid, crn in members:
                num_to_ids[crn].append(rid)
            for rid, crn in members:
                # Does this number begin with "base (annotation) ..." where
                # (annotation) is a fully closed paren group?  The trailing
                # text is allowed (e.g. "8201154A (Aftermarket) Pg. 36748").
                m = re.match(r"^(.+?)\s+\(([^)]+)\)(.*)$", crn)
                if not m:
                    continue
                base = m.group(1).strip()
                label = m.group(2).strip()
                bare_ids = num_to_ids.get(base, [])
                if not bare_ids:
                    continue
                # Delete every bare row (could be more than one).
                for bid in bare_ids:
                    if bid == rid or bid in to_delete_set:
                        continue
                    to_delete_set.add(bid)
                    annot_label_count[label] += 1
                    if len(sample) < 10:
                        sample.append(
                            f"unit={unit_id} brand='{brand_l}' "
                            f"DEL '{base}' (id={bid}), "
                            f"KEEP '{crn}' (id={rid})"
                        )

        to_delete = list(to_delete_set)

        self.stdout.write(f"  Plan: delete {len(to_delete):,} bare rows")
        if annot_label_count:
            self.stdout.write("  Top 10 annotation labels driving these merges:")
            top = sorted(
                annot_label_count.items(), key=lambda kv: -kv[1]
            )[:10]
            for label, n in top:
                self.stdout.write(f"    {n:>6,}  '({label})'")
        if sample:
            self.stdout.write("  Sample merges:")
            for s in sample:
                self.stdout.write(f"    {s}")
        self.stdout.flush()

        if commit:
            self._bulk_delete(to_delete)

        return {"deleted": len(to_delete)}

    # ================================================================== #
    # Step 2 - Manufacturer-name rename + dedup
    # ================================================================== #
    def _step2_rename_mfr_names(self, commit: bool) -> dict:
        self.stdout.write("\n--- Step 2: Mfr-name rename + dedup ---")
        self.stdout.flush()

        total_renamed = 0
        total_deleted = 0

        for src, dst in RENAME_MAP.items():
            n_src = CrossReference.objects.filter(interchange_type=src).count()
            if n_src == 0:
                continue
            n_dst_before = (
                CrossReference.objects.filter(interchange_type=dst).count()
            )

            # Find rows that would collide with an existing dst row
            # on (unit_id, cross_ref_number).
            src_rows = list(
                CrossReference.objects
                .filter(interchange_type=src)
                .values("id", "unit_id", "cross_ref_number")
            )
            collide_delete: List[int] = []
            rename_ids: List[int] = []
            for r in src_rows:
                dst_existing = (
                    CrossReference.objects
                    .filter(
                        unit_id=r["unit_id"],
                        cross_ref_number=r["cross_ref_number"],
                        interchange_type=dst,
                    )
                    .values_list("id", flat=True)
                    .first()
                )
                if dst_existing:
                    collide_delete.append(r["id"])
                else:
                    rename_ids.append(r["id"])

            self.stdout.write(
                f"  '{src}' ({n_src}) -> '{dst}' ({n_dst_before}): "
                f"rename {len(rename_ids)}, delete-collide {len(collide_delete)}"
            )
            self.stdout.flush()

            if commit:
                self._bulk_delete(collide_delete)
                for i in range(0, len(rename_ids), 2000):
                    batch = rename_ids[i:i + 2000]
                    CrossReference.objects.filter(id__in=batch).update(
                        interchange_type=dst
                    )

            total_renamed += len(rename_ids)
            total_deleted += len(collide_delete)

        self.stdout.write(
            f"  Total: renamed {total_renamed:,}, "
            f"deleted (collide) {total_deleted:,}"
        )
        self.stdout.flush()

        return {"renamed": total_renamed, "deleted": total_deleted}

    # ================================================================== #
    # Step 3 - Pattern-6 same-number overlap dedup
    # ================================================================== #
    def _step3_pattern6_same_number(self, commit: bool) -> dict:
        self.stdout.write("\n--- Step 3: Pattern-6 same-number dedup ---")
        self.stdout.flush()

        total_deleted = 0
        for base, variant in PATTERN6_PAIRS:
            # Find rows under `variant` whose (unit_id, cross_ref_number) also
            # exists under `base`.  Delete the variant row.
            variant_rows = list(
                CrossReference.objects
                .filter(interchange_type=variant)
                .values("id", "unit_id", "cross_ref_number")
            )
            to_delete: List[int] = []
            for r in variant_rows:
                if (
                    CrossReference.objects
                    .filter(
                        interchange_type=base,
                        unit_id=r["unit_id"],
                        cross_ref_number=r["cross_ref_number"],
                    )
                    .exists()
                ):
                    to_delete.append(r["id"])

            self.stdout.write(
                f"  '{variant}' -> overlaps with '{base}': "
                f"delete {len(to_delete):,}"
            )
            self.stdout.flush()

            if commit:
                self._bulk_delete(to_delete)
            total_deleted += len(to_delete)

        self.stdout.write(f"  Total: deleted {total_deleted:,}")
        self.stdout.flush()

        return {"deleted": total_deleted}

    # ================================================================== #
    # Bulk helpers
    # ================================================================== #
    def _bulk_delete(self, ids: List[int]) -> None:
        for i in range(0, len(ids), 1000):
            batch = ids[i:i + 1000]
            CrossReference.objects.filter(id__in=batch).delete()

    def _bulk_update_crn(self, pairs: List[Tuple[int, str]]) -> None:
        for i in range(0, len(pairs), 500):
            batch = pairs[i:i + 500]
            objs = list(
                CrossReference.objects
                .filter(id__in=[p[0] for p in batch])
                .only("id", "cross_ref_number")
            )
            crn_map = dict(batch)
            for o in objs:
                o.cross_ref_number = crn_map[o.id]
            CrossReference.objects.bulk_update(
                objs, ["cross_ref_number"], batch_size=500
            )
