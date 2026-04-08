"""Set seed_id = pk for all existing catalog records (one-time data migration)."""

from django.db import migrations, models

REFERENCE_MODELS = [
    "UnitType",
    "Application",
    "ApplicationSpecification",
    "Unit",
    "ApplicationUnit",
    "CrossReference",
    "Substitute",
    "GearReductionSubstitution",
    "Part",
    "PartSubstitute",
    "PartInterchange",
    "PartSuperseding",
    "BOM",
    "BOMItem",
]


def populate_seed_id(apps, schema_editor):
    for model_name in REFERENCE_MODELS:
        Model = apps.get_model("catalog", model_name)
        updated = Model.objects.filter(seed_id__isnull=True).update(
            seed_id=models.F("pk")
        )
        if updated:
            print(f"  {model_name}: set seed_id on {updated} rows")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0027_add_seed_id_to_reference_models"),
    ]

    operations = [
        migrations.RunPython(populate_seed_id, noop),
    ]
