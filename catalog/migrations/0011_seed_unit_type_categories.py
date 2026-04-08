from django.db import migrations


SEED_DATA = {
    "Starter": [
        ("starter_type", "Starter Type"),
        ("tooth_quantity", "Tooth Quantity"),
        ("nose_type", "Nose Type"),
        ("over_crank_protection", "Over Crank Protection"),
        ("solenoid_attached", "Solenoid Attached"),
    ],
    "Generator": [
        ("circuit_type", "Circuit Type"),
        ("brush_type", "Brush Type"),
        ("regulation_type", "Regulation Type"),
    ],
    "Alternator": [
        ("fan_type", "Fan Type"),
        ("regulator_type", "Regulator Type"),
        ("pulley_class", "Pulley Class"),
    ],
}


def seed_categories(apps, schema_editor):
    UnitTypeCategory = apps.get_model("catalog", "UnitTypeCategory")
    UnitTypeCategoryField = apps.get_model("catalog", "UnitTypeCategoryField")
    for cat_name, fields in SEED_DATA.items():
        cat, _ = UnitTypeCategory.objects.get_or_create(name=cat_name)
        for i, (field_name, field_label) in enumerate(fields):
            UnitTypeCategoryField.objects.get_or_create(
                category=cat,
                field_name=field_name,
                defaults={"field_label": field_label, "display_order": i},
            )


def unseed(apps, schema_editor):
    UnitTypeCategory = apps.get_model("catalog", "UnitTypeCategory")
    UnitTypeCategory.objects.filter(name__in=SEED_DATA.keys()).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0010_add_unit_type_category_models"),
    ]

    operations = [
        migrations.RunPython(seed_categories, unseed),
    ]
