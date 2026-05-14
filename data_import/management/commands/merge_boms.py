"""
Merge multiple BOMs on the same unit into a single BOM.

For each unit with more than one BOM:
  1. Keep the BOM with the most items as the "primary".
  2. Move any unique parts from the other BOMs into the primary.
  3. Delete the now-empty secondary BOMs.

Usage:
    python manage.py merge_boms              # dry-run (default)
    python manage.py merge_boms --commit     # actually merge
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from catalog.models import BOM, BOMItem, Unit


class Command(BaseCommand):
    help = "Merge multiple BOMs per unit into a single BOM."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually perform the merge (default is dry-run).",
        )

    def handle(self, *args, **options):
        commit = options["commit"]

        units_multi = (
            Unit.objects.annotate(bom_count=Count("boms"))
            .filter(bom_count__gt=1)
        )

        total_units = units_multi.count()
        self.stdout.write(f"\nUnits with multiple BOMs: {total_units:,}")
        self.stdout.write(f"Mode: {'COMMIT' if commit else 'DRY-RUN'}\n")

        if total_units == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to merge."))
            return

        boms_deleted = 0
        items_moved = 0
        items_dropped = 0  # duplicates already in primary

        for unit in units_multi.iterator():
            boms = list(unit.boms.order_by("-pk"))
            # Pick the one with the most items as primary
            boms.sort(key=lambda b: b.items.count(), reverse=True)
            primary = boms[0]
            secondaries = boms[1:]

            # Existing part_ids in the primary BOM
            primary_part_ids = set(
                primary.items.values_list("part_id", flat=True)
            )

            for sec in secondaries:
                for item in sec.items.all():
                    if item.part_id not in primary_part_ids:
                        if commit:
                            BOMItem.objects.create(
                                bom=primary,
                                part_id=item.part_id,
                                description=item.description,
                                notes=item.notes,
                                unit_qty=item.unit_qty,
                                stock_qty=item.stock_qty,
                                bin_number=item.bin_number,
                                oem_number=item.oem_number,
                                j_and_n=item.j_and_n,
                                yt_number=item.yt_number,
                            )
                        primary_part_ids.add(item.part_id)
                        items_moved += 1
                    else:
                        items_dropped += 1

                if commit:
                    sec.delete()
                boms_deleted += 1

        self.stdout.write(f"BOMs to delete:         {boms_deleted:,}")
        self.stdout.write(f"Items moved to primary: {items_moved:,}")
        self.stdout.write(f"Duplicate items dropped:{items_dropped:,}")
        self.stdout.write("")

        if not commit:
            self.stdout.write(
                self.style.WARNING("No changes made. Pass --commit to merge.")
            )
        else:
            remaining = BOM.objects.count()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. Remaining BOMs: {remaining:,}"
                )
            )
