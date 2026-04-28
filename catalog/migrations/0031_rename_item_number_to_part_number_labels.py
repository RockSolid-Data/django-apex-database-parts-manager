from django.db import migrations


def rename_item_number_labels(apps, schema_editor):
    PartCategoryField = apps.get_model("catalog", "PartCategoryField")
    PartCategoryField.objects.filter(field_label="Item Number").update(
        field_label="Part Number"
    )


def revert(apps, schema_editor):
    PartCategoryField = apps.get_model("catalog", "PartCategoryField")
    PartCategoryField.objects.filter(
        field_label="Part Number", field_name="part_number"
    ).update(field_label="Item Number")


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0030_set_unit_type_category_order_and_colors"),
    ]

    operations = [
        migrations.RunPython(rename_item_number_labels, revert),
    ]
