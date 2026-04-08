from django.db import migrations

DEFAULT_FIELDS = [
    ("yt_number", "YT Number"),
    ("j_and_n", "J&N"),
    ("oem_number", "OEM #"),
    ("oem", "OEM"),
    ("oem_type", "OEM Type"),
    ("item_no", "Item No"),
    ("item_typ", "Item Type"),
    ("primary_vendor", "Primary Vendor"),
    ("catalog", "Catalog"),
    ("plug_id", "Plug ID"),
]


def add_default_fields(apps, schema_editor):
    PartCategory = apps.get_model("catalog", "PartCategory")
    PartCategoryField = apps.get_model("catalog", "PartCategoryField")
    default_names = {f[0] for f in DEFAULT_FIELDS}

    for cat in PartCategory.objects.all():
        existing = set(cat.fields.values_list("field_name", flat=True))
        for f in cat.fields.exclude(field_name__in=default_names).order_by("display_order"):
            f.display_order += len(DEFAULT_FIELDS)
            f.save(update_fields=["display_order"])
        for i, (fname, flabel) in enumerate(DEFAULT_FIELDS):
            if fname not in existing:
                PartCategoryField.objects.create(
                    category=cat,
                    field_name=fname,
                    field_label=flabel,
                    display_order=i,
                )


def remove_default_fields(apps, schema_editor):
    PartCategoryField = apps.get_model("catalog", "PartCategoryField")
    default_names = [f[0] for f in DEFAULT_FIELDS]
    PartCategoryField.objects.filter(field_name__in=default_names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0014_add_default_fields_to_unit_type_categories"),
    ]

    operations = [
        migrations.RunPython(add_default_fields, remove_default_fields),
    ]
