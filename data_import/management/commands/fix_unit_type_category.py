"""
One-time fix: copy unit_type.name into the unit_type_category string field
for any Unit that has a unit_type FK set but an empty unit_type_category.

The unit list page tabs and filters use unit_type_category (string),
not the unit_type FK directly.
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from catalog.models import Unit


class Command(BaseCommand):
    help = "Sync unit_type_category string from unit_type FK for units where it is missing."

    def handle(self, *args, **options):
        qs = Unit.objects.filter(unit_type__isnull=False, unit_type_category="").select_related("unit_type")
        total = qs.count()
        self.stdout.write(f"Units needing fix: {total}")

        updated = 0
        for unit in qs:
            unit.unit_type_category = unit.unit_type.name
            unit.save(update_fields=["unit_type_category"])
            updated += 1

        self.stdout.write(self.style.SUCCESS(f"Updated: {updated}"))

        breakdown = (
            Unit.objects.exclude(unit_type_category="")
            .values("unit_type_category")
            .annotate(n=Count("id"))
            .order_by("unit_type_category")
        )
        self.stdout.write("\nUnit type breakdown:")
        for row in breakdown:
            self.stdout.write(f"  {row['unit_type_category']}: {row['n']}")
