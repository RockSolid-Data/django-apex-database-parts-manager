"""Auto-assign categories to Part records based on part_name keywords.

Usage:
    python manage.py cleanup_part_categories --dry-run   # preview only
    python manage.py cleanup_part_categories              # apply changes
    python manage.py cleanup_part_categories --create-categories  # also add to PartCategory table
"""

import re
import time

from django.core.management.base import BaseCommand
from django.db.models import Count

from catalog.models import Part, PartCategory


# ---------------------------------------------------------------------------
# Category classification rules
# ---------------------------------------------------------------------------
# Each entry: (category_name, [regex_patterns...])
# Rules are evaluated top-to-bottom; first match wins.
# Patterns are matched case-insensitively against part_name.
# More-specific patterns precede broader ones to avoid mis-classification.
# ---------------------------------------------------------------------------
CATEGORY_RULES = [
    # --- Bearings (bearing, plus model numbers like W6000-2RS) ---
    ("Bearings", [
        r"bearing",
        r"^W\d+",
    ]),

    # --- Bushings ---
    ("Bushings", [r"bushing"]),

    # --- Brush sub-categories (most specific first) ---
    ("Brush Holders & Parts", [
        r"brush holder",
        r"brush plate",
        r"brush connector",
    ]),
    ("Starter & DC Motor Brush Springs", [r"brush spring"]),
    ("Brushes", [r"brush"]),

    # --- Field Coils (includes field housings & field frames) ---
    ("Field Coils", [
        r"field coil",
        r"field housing",
        r"field frame",
        r"rotor coil",
    ]),

    # --- Gaskets, Grommets & Seals ---
    ("Gaskets, Grommets & Seals", [
        r"\bseal\b",
        r"gasket",
        r"grommet",
        r"o-ring",
        r"sealant",
    ]),

    # --- Test Equipment ---
    ("Test Equipment", [r"test lead"]),

    # --- Stators ---
    ("Stators", [r"stator"]),

    # --- Pulleys ---
    ("Pulleys", [r"pulley"]),

    # --- Kits (before solenoids so "Solenoid Repair Kit" → Kits) ---
    ("Kits", [
        r"repair kit",
        r"collar kit",
        r"terminal kit",
        r"brake kit",
    ]),

    # --- Housings (before solenoids so "Solenoid Housing" → Housings) ---
    ("Housings", [
        r"housing",
        r"frame",
        r"\bcover\b",
        r"baffle",
    ]),

    # --- Regulators & Rectifiers ---
    ("Regulators & Rectifiers", [
        r"regulator",
        r"rectifier",
        r"diode",
        r"capacitor",
        r"slip ring",
        r"\bresistor\b",
        r"transformer",
    ]),

    # --- Relays, Solenoids & Switches ---
    ("Relays, Solenoids & Switches", [
        r"solenoid",
        r"\brelay\b",
        r"ims switch",
    ]),

    # --- Shafts & Armatures ---
    ("Shafts & Armatures", [
        r"armature",
        r"rotor",
        r"commutator",
        r"\bshaft\b",
    ]),

    # --- Drives & Gears ---
    ("Drives & Gears", [
        r"\bdrive\b",
        r"\bgear\b",
        r"planetary",
        r"\bclutch\b",
        r"pinion",
    ]),

    # --- Hardware & Misc (broad catch-all, checked last) ---
    ("Hardware & Misc", [
        r"\bbolt\b",
        r"\bnut\b",
        r"\bscrew\b",
        r"washer",
        r"terminal",
        r"connector",
        r"insulator",
        r"\bboot\b",
        r"bracket",
        r"wiring",
        r"harness",
        r"\bplug\b",
        r"retainer",
        r"rivet",
        r"spacer",
        r"\bspring\b",
        r"\bstud\b",
        r"\bshim\b",
        r"\bpin\b",
        r"\bstrap\b",
        r"\blead\b",
        r"drain",
        r"\bfan\b",
        r"\bmisc\b",
        r"\bplate\b",
        r"sleeve",
        r"\bcollar\b",
        r"clamp",
        r"link-belt",
        r"alignment",
        r"expansion",
        r"magnet",
        r"thermal",
        r"\blever\b",
        r"amperage",
        r"center support",
        r"thrust",
    ]),
]

_COMPILED_RULES = [
    (cat, [re.compile(p, re.IGNORECASE) for p in patterns])
    for cat, patterns in CATEGORY_RULES
]


def classify_part_name(name: str) -> str | None:
    """Return the best category for a part name, or None if unclassifiable."""
    if not name or not name.strip():
        return None
    for category, patterns in _COMPILED_RULES:
        for pat in patterns:
            if pat.search(name):
                return category
    return None


class Command(BaseCommand):
    help = "Auto-assign categories to parts based on part_name keyword rules."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", dest="dry_run",
            help="Preview assignments without saving changes.",
        )
        parser.add_argument(
            "--overwrite", action="store_true",
            help="Overwrite existing category values (default: only fill blanks).",
        )
        parser.add_argument(
            "--create-categories", action="store_true", dest="create_categories",
            help="Also create PartCategory entries for each assigned category.",
        )

    def handle(self, *args, **options):
        import sys
        sys.stdout.reconfigure(line_buffering=True)

        dry_run = options["dry_run"]
        overwrite = options["overwrite"]
        create_cats = options["create_categories"]
        start = time.time()

        self.stdout.write(f"\n{'=' * 65}")
        self.stdout.write(f"  Part Category Cleanup  {'(DRY RUN)' if dry_run else '(LIVE)'}")
        self.stdout.write(f"{'=' * 65}")

        # ----- Current state -----
        total = Part.objects.count()
        already = Part.objects.exclude(category="").count()
        blank = Part.objects.filter(category="").count()

        self.stdout.write(f"\n  Total parts:           {total:>10,}")
        self.stdout.write(f"  Already categorized:   {already:>10,}")
        self.stdout.write(f"  Blank category:        {blank:>10,}")

        # ----- Select target parts -----
        if overwrite:
            qs = Part.objects.all()
        else:
            qs = Part.objects.filter(category="")

        # ----- Classify -----
        assignments = {}   # category → [part_pks]
        unclassified = []  # (pk, part_name)

        for pk, name in qs.values_list("pk", "part_name"):
            cat = classify_part_name(name)
            if cat:
                assignments.setdefault(cat, []).append(pk)
            else:
                unclassified.append((pk, name))

        # ----- Report planned assignments -----
        total_assigned = sum(len(pks) for pks in assignments.values())

        self.stdout.write(f"\n{'-' * 65}")
        self.stdout.write(f"  {'Category':<40s} {'Count':>10s}")
        self.stdout.write(f"{'-' * 65}")
        for cat in sorted(assignments, key=lambda c: -len(assignments[c])):
            self.stdout.write(f"  {cat:<40s} {len(assignments[cat]):>10,}")
        self.stdout.write(f"{'-' * 65}")
        self.stdout.write(f"  {'TOTAL ASSIGNABLE':<40s} {total_assigned:>10,}")
        self.stdout.write(f"  {'UNCLASSIFIABLE':<40s} {len(unclassified):>10,}")

        # ----- Show unclassified part names -----
        if unclassified:
            name_counts = {}
            for _, name in unclassified:
                name_counts[name] = name_counts.get(name, 0) + 1
            self.stdout.write(f"\n  Unclassifiable part names:")
            for name, cnt in sorted(name_counts.items(), key=lambda x: -x[1]):
                display = name if name else "(blank)"
                self.stdout.write(f"    [{cnt:>4}] {display}")

        # ----- Apply -----
        if dry_run:
            self.stdout.write(f"\n  DRY RUN -- no changes saved.")
        else:
            updated = 0
            for cat, pks in assignments.items():
                batch_size = 2000
                for i in range(0, len(pks), batch_size):
                    chunk = pks[i:i + batch_size]
                    count = Part.objects.filter(pk__in=chunk).update(category=cat)
                    updated += count
            self.stdout.write(f"\n  {updated:,} parts updated.")

            # ----- Optionally create PartCategory entries -----
            if create_cats:
                created_cats = []
                for cat_name in sorted(assignments.keys()):
                    _, created = PartCategory.objects.get_or_create(name=cat_name)
                    if created:
                        created_cats.append(cat_name)
                if created_cats:
                    self.stdout.write(f"  Created {len(created_cats)} PartCategory entries:")
                    for c in created_cats:
                        self.stdout.write(f"    + {c}")
                else:
                    self.stdout.write(f"  All PartCategory entries already exist.")

        # ----- After-state -----
        if not dry_run:
            after_blank = Part.objects.filter(category="").count()
            after_filled = Part.objects.exclude(category="").count()
            self.stdout.write(f"\n  After:")
            self.stdout.write(f"    Categorized:         {after_filled:>10,}")
            self.stdout.write(f"    Still blank:         {after_blank:>10,}")
            self.stdout.write(f"\n  Category distribution:")
            dist = (
                Part.objects.exclude(category="")
                .values("category")
                .annotate(cnt=Count("id"))
                .order_by("-cnt")
            )
            for row in dist:
                self.stdout.write(f"    {row['category']:<40s} {row['cnt']:>10,}")

        elapsed = time.time() - start
        self.stdout.write(f"\n  Elapsed: {elapsed:.1f}s")
        self.stdout.write(f"{'=' * 65}\n")
