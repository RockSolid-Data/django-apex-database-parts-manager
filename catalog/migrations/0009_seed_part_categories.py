from django.db import migrations


SEED_DATA = {
    "Bearings": [
        ("id_dimension", "ID"),
        ("od_dimension", "OD"),
        ("width", "W"),
        ("side_type", "Side Type"),
        ("extended_inner_race", "Extended Inner Race"),
        ("snap_ring", "Snap Ring"),
        ("style", "Style"),
        ("which_end", "Which End"),
        ("family", "Family"),
    ],
    "Bearing Retainers": [
        ("id_dimension", "ID"),
        ("od_dimension", "OD"),
        ("width", "W"),
        ("family", "Family"),
        ("style", "Style"),
    ],
    "Bushings": [
        ("id_dimension", "ID"),
        ("od_dimension", "OD"),
        ("width", "W"),
        ("bushing_type", "Type"),
        ("style", "Style"),
        ("where_used", "Where Used"),
        ("family", "Family"),
        ("flange", "Flange"),
    ],
}


def seed_categories(apps, schema_editor):
    PartCategory = apps.get_model("catalog", "PartCategory")
    PartCategoryField = apps.get_model("catalog", "PartCategoryField")
    for cat_name, fields in SEED_DATA.items():
        cat, _ = PartCategory.objects.get_or_create(name=cat_name)
        for i, (field_name, field_label) in enumerate(fields):
            PartCategoryField.objects.get_or_create(
                category=cat,
                field_name=field_name,
                defaults={"field_label": field_label, "display_order": i},
            )


def unseed(apps, schema_editor):
    PartCategory = apps.get_model("catalog", "PartCategory")
    PartCategory.objects.filter(name__in=SEED_DATA.keys()).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0008_add_part_category_models"),
    ]

    operations = [
        migrations.RunPython(seed_categories, unseed),
    ]
