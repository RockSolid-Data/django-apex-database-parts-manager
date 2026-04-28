"""
Data migration: ensure every PartCategory has the standard default fields.
Categories created before the default-fields feature was introduced have an
empty fields table.  This migration adds the missing defaults without
touching any custom fields already stored.
"""

from django.db import migrations

DEFAULT_FIELDS = [
    ("part_number",         "Part Number"),
    ("part_name",           "Part Name"),
    ("manufacturer_number", "Manufacturer Number"),
    ("yt_number",           "YT Number"),
    ("j_and_n",             "J&N Number"),
    ("oem_number",          "OEM #"),
    ("voltage",             "Voltage"),
    ("type",                "Type"),
    ("oem",                 "OEM"),
    ("primary_vendor",      "Primary Vendor"),
]

DEFAULT_FIELD_NAMES = [fn for fn, _ in DEFAULT_FIELDS]
# Reserve orders 0-9 for the 10 default fields; custom fields start at 100
CUSTOM_START = 100


def seed_defaults(apps, schema_editor):
    PartCategory      = apps.get_model("catalog", "PartCategory")
    PartCategoryField = apps.get_model("catalog", "PartCategoryField")

    for cat in PartCategory.objects.all():
        existing = {
            f["field_name"]: f["display_order"]
            for f in cat.fields.values("field_name", "display_order")
        }

        # Bump any existing custom fields into the 100+ range so defaults
        # can claim 0-9 without colliding.
        for field in cat.fields.exclude(field_name__in=DEFAULT_FIELD_NAMES):
            if field.display_order < CUSTOM_START:
                field.display_order = CUSTOM_START + field.display_order
                field.save()

        # Insert missing defaults at positions 0-9
        for idx, (fn, fl) in enumerate(DEFAULT_FIELDS):
            if fn not in existing:
                PartCategoryField.objects.create(
                    category=cat,
                    field_name=fn,
                    field_label=fl,
                    display_order=idx,
                )
            else:
                # Keep the existing row but fix its order to match the
                # canonical default position (0-9)
                cat.fields.filter(field_name=fn).update(display_order=idx)


def reverse_seed(apps, schema_editor):
    """Remove only the fields we added whose names match the defaults."""
    PartCategoryField = apps.get_model("catalog", "PartCategoryField")
    PartCategoryField.objects.filter(field_name__in=DEFAULT_FIELD_NAMES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0038_categorize_uncategorized_parts"),
    ]

    operations = [
        migrations.RunPython(seed_defaults, reverse_code=reverse_seed),
    ]
