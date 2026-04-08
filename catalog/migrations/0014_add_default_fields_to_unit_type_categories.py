from django.db import migrations

DEFAULT_FIELDS = [
    ("yt_number", "YT Number"),
    ("oem", "OEM"),
    ("j_and_n_number", "J&N Number"),
    ("model_cat_number", "Model / Cat Number"),
    ("unit_type", "Unit Type"),
    ("manufacturer", "Manufacturer"),
    ("family", "Family"),
]


def add_default_fields(apps, schema_editor):
    UnitTypeCategory = apps.get_model("catalog", "UnitTypeCategory")
    UnitTypeCategoryField = apps.get_model("catalog", "UnitTypeCategoryField")
    default_names = {f[0] for f in DEFAULT_FIELDS}

    for cat in UnitTypeCategory.objects.all():
        existing = set(cat.fields.values_list("field_name", flat=True))
        # Bump existing (non-default) fields so defaults appear first
        for f in cat.fields.exclude(field_name__in=default_names).order_by("display_order"):
            f.display_order += len(DEFAULT_FIELDS)
            f.save(update_fields=["display_order"])
        # Insert default fields at the front
        for i, (fname, flabel) in enumerate(DEFAULT_FIELDS):
            if fname not in existing:
                UnitTypeCategoryField.objects.create(
                    category=cat,
                    field_name=fname,
                    field_label=flabel,
                    display_order=i,
                )


def remove_default_fields(apps, schema_editor):
    UnitTypeCategoryField = apps.get_model("catalog", "UnitTypeCategoryField")
    default_names = [f[0] for f in DEFAULT_FIELDS]
    UnitTypeCategoryField.objects.filter(field_name__in=default_names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0013_add_part_compatibility_models"),
    ]

    operations = [
        migrations.RunPython(add_default_fields, remove_default_fields),
    ]
