"""
Sync BOM items from the Part↔Unit M2M links (linked_parts).

The Buyers Guide import created Part records and linked them to units via
the M2M relationship (Part.units / Unit.linked_parts), but did NOT create
BOM/BOMItem records. This command fills that gap by adding any linked parts
that are missing from the unit's BOM.

For units that don't have a BOM yet, one is created.

Usage:
    python manage.py sync_bom_from_links              # dry-run
    python manage.py sync_bom_from_links --commit     # actually sync
"""

from django.core.management.base import BaseCommand

from catalog.models import BOM, BOMItem, Unit


class Command(BaseCommand):
    help = "Add M2M linked_parts to unit BOMs as BOMItems."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually create BOM items (default is dry-run).",
        )

    def handle(self, *args, **options):
        commit = options["commit"]

        units_with_links = (
            Unit.objects.filter(linked_parts__isnull=False).distinct()
        )
        total = units_with_links.count()

        self.stdout.write(f"\nUnits with linked_parts: {total:,}")
        self.stdout.write(f"Mode: {'COMMIT' if commit else 'DRY-RUN'}\n")

        boms_created = 0
        items_added = 0
        items_skipped = 0

        batch = []
        BATCH_SIZE = 2000

        for unit in units_with_links.iterator():
            bom = unit.boms.first()

            linked_part_ids = set(
                unit.linked_parts.values_list("pk", flat=True)
            )
            if not linked_part_ids:
                continue

            if bom:
                existing_part_ids = set(
                    bom.items.values_list("part_id", flat=True)
                )
            else:
                existing_part_ids = set()

            missing = linked_part_ids - existing_part_ids
            if not missing:
                items_skipped += len(linked_part_ids)
                continue

            if not bom and commit:
                bom_name = f"{unit.unit_number} BOM" if unit.unit_number else f"Unit-{unit.pk} BOM"
                bom = BOM.objects.create(
                    name=bom_name,
                    unit=unit,
                )
                boms_created += 1
            elif not bom:
                boms_created += 1
                items_added += len(missing)
                continue

            for part_id in missing:
                if commit:
                    batch.append(BOMItem(bom=bom, part_id=part_id, unit_qty=1))
                items_added += 1

            items_skipped += len(linked_part_ids) - len(missing)

            if commit and len(batch) >= BATCH_SIZE:
                BOMItem.objects.bulk_create(batch, ignore_conflicts=True)
                batch = []

        if commit and batch:
            BOMItem.objects.bulk_create(batch, ignore_conflicts=True)

        self.stdout.write(f"BOMs created:          {boms_created:,}")
        self.stdout.write(f"BOM items added:       {items_added:,}")
        self.stdout.write(f"Already in BOM:        {items_skipped:,}")
        self.stdout.write("")

        if not commit:
            self.stdout.write(
                self.style.WARNING("No changes made. Pass --commit to sync.")
            )
        else:
            self.stdout.write(self.style.SUCCESS("Done."))
