"""
Remove empty/skeleton BOMs that were superseded by richer J&N imports.

A BOM is considered "empty" if NONE of its items reference a Part with a
non-null, non-blank part_number.  An empty BOM is only deleted when the
same Unit also has at least one "real" BOM (one with actual part numbers).

Usage:
    python manage.py deduplicate_boms              # dry-run (default)
    python manage.py deduplicate_boms --commit     # actually delete
"""

from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef

from catalog.models import BOM, BOMItem


class Command(BaseCommand):
    help = "Remove empty BOMs from units that also have a BOM with real parts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually delete the empty BOMs (default is dry-run).",
        )

    def handle(self, *args, **options):
        commit = options["commit"]

        # Subquery: does this BOM have at least one item with a real part number?
        has_real_parts = Exists(
            BOMItem.objects.filter(
                bom=OuterRef("pk"),
                part__part_number__isnull=False,
            ).exclude(part__part_number="")
        )

        # All BOMs that are "empty" (no items with real part numbers)
        empty_boms = BOM.objects.annotate(has_real=has_real_parts).filter(
            has_real=False,
            unit__isnull=False,
        )

        # Only delete if the unit has at least one OTHER bom that IS real
        real_bom_for_unit = Exists(
            BOM.objects.annotate(has_real=has_real_parts)
            .filter(has_real=True, unit=OuterRef("unit"))
        )

        to_delete = empty_boms.filter(real_bom_for_unit)

        count = to_delete.count()
        item_count = BOMItem.objects.filter(bom__in=to_delete).count()

        self.stdout.write(f"\nEmpty BOMs to remove:   {count:,}")
        self.stdout.write(f"BOM items to remove:    {item_count:,}")
        self.stdout.write(f"Mode:                   {'COMMIT' if commit else 'DRY-RUN'}")
        self.stdout.write("")

        if not commit:
            self.stdout.write(
                self.style.WARNING("No changes made. Pass --commit to delete.")
            )
            # Show a few examples
            for bom in to_delete[:10]:
                self.stdout.write(
                    f"  Would delete: BOM {bom.id} '{bom.name}' "
                    f"(unit={bom.unit.unit_number}, items={bom.items.count()})"
                )
            return

        deleted_boms, details = to_delete.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDeleted {details.get('catalog.BOM', 0):,} BOMs and "
                f"{details.get('catalog.BOMItem', 0):,} BOM items."
            )
        )
        self.stdout.write(f"Remaining BOMs in DB: {BOM.objects.count():,}")
