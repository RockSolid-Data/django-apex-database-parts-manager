from django.db import migrations


def split_jn_values(apps, schema_editor):
    Part = apps.get_model("catalog", "Part")
    PartInterchange = apps.get_model("catalog", "PartInterchange")

    parts = Part.objects.filter(j_and_n__contains=",")
    created = 0
    for part in parts:
        values = [v.strip() for v in part.j_and_n.split(",") if v.strip()]
        if len(values) <= 1:
            continue

        # Keep the first value in the j_and_n field
        part.j_and_n = values[0]
        part.save(update_fields=["j_and_n"])

        # Move additional values to PartInterchange (skip junk like "133-")
        for extra in values[1:]:
            if extra.endswith("-") and len(extra) <= 5:
                continue
            existing = PartInterchange.objects.filter(
                part=part, interchange_number=extra
            ).exists()
            if not existing:
                PartInterchange.objects.create(
                    part=part,
                    interchange_number=extra,
                    source_name="J&N",
                    notes="Split from multi-value J&N field",
                )
                created += 1

    print(f"  Split {parts.count()} parts, created {created} interchange records")


def revert(apps, schema_editor):
    PartInterchange = apps.get_model("catalog", "PartInterchange")
    PartInterchange.objects.filter(
        notes="Split from multi-value J&N field"
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0031_rename_item_number_to_part_number_labels"),
    ]

    operations = [
        migrations.RunPython(split_jn_values, revert),
    ]
