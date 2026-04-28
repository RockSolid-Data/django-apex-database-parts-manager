"""
Clean up 4,049 Application records where unit_number has concatenated values
like "334718 400-52103R," — keep only the base number ("334718").
The extra number is already stored as a cross-reference on the Unit.
"""
from django.db import migrations


def clean_unit_numbers(apps, schema_editor):
    Application = apps.get_model("catalog", "Application")
    apps_with_spaces = Application.objects.filter(unit_number__contains=" ")
    count = 0
    for app in apps_with_spaces.iterator():
        base = app.unit_number.strip().split(None, 1)[0].rstrip(",")
        if base != app.unit_number:
            app.unit_number = base
            app.save(update_fields=["unit_number"])
            count += 1
    print(f"  Cleaned {count} application unit_number fields")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0033_merge_duplicate_space_units"),
    ]

    operations = [
        migrations.RunPython(clean_unit_numbers, noop),
    ]
