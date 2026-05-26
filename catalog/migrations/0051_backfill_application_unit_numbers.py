"""
Backfill Application.unit_number for records imported from the buyers guide
(PDF 11) that have linked units via ApplicationUnit but no unit_number set.
"""
from django.db import migrations


def backfill_unit_numbers(apps, schema_editor):
    Application = apps.get_model("catalog", "Application")
    ApplicationUnit = apps.get_model("catalog", "ApplicationUnit")

    empty_apps = Application.objects.filter(unit_number="")
    updated = 0

    for app in empty_apps.iterator(chunk_size=1000):
        first_link = (
            ApplicationUnit.objects.filter(application=app)
            .select_related("unit")
            .order_by("unit__unit_number")
            .first()
        )
        if first_link and first_link.unit and first_link.unit.unit_number:
            app.unit_number = first_link.unit.unit_number[:100]
            app.save(update_fields=["unit_number"])
            updated += 1

    print(f"  Backfilled unit_number on {updated} applications")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0050_application_composite_index"),
    ]

    operations = [
        migrations.RunPython(backfill_unit_numbers, noop),
    ]
