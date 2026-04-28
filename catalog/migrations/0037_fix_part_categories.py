"""
Data migration to:
1. Create missing PartCategory management entries for categories that
   exist on parts but have no management page (Brushes, Electrical,
   Hardware, Pulleys).
2. Rename "Hardware & Misc" → "Misc" in management AND on parts,
   but first move bolts/hardware items to "Hardware".
3. Fix near-duplicate: "Drive, Clutches & Drive Parts" → merge into
   existing "Drives, Clutches & Drive Parts".
4. "Pulleys" parts → merge into "Pulleys & Pulley Collars".
5. "Brushes" parts that aren't sub-typed → leave as "Brushes" with
   a new management entry.
"""
from django.db import migrations


HARDWARE_NAMES = [
    "Motor Bolt",
    "Thru Bolt",
    "Bolt",
    "Nut",
    "Screw",
    "Washer",
    "Stud",
    "Pin",
]


def forwards(apps, schema_editor):
    Part = apps.get_model("catalog", "Part")
    PartCategory = apps.get_model("catalog", "PartCategory")

    # 1. Create missing management entries
    for name in ["Brushes", "Electrical", "Hardware", "Misc", "Pulleys"]:
        PartCategory.objects.get_or_create(name=name)

    # 2. Move hardware-type items from "Hardware & Misc" → "Hardware"
    hw_misc = Part.objects.filter(category="Hardware & Misc")
    moved = 0
    for part in hw_misc:
        pname = (part.part_name or "").strip()
        if any(pname.lower().startswith(kw.lower()) for kw in HARDWARE_NAMES):
            part.category = "Hardware"
            part.save(update_fields=["category"])
            moved += 1

    # 3. Rename remaining "Hardware & Misc" parts → "Misc"
    remaining = Part.objects.filter(category="Hardware & Misc").update(category="Misc")

    # 4. Delete old "Hardware & Misc" management entry (replaced by "Misc")
    PartCategory.objects.filter(name="Hardware & Misc").delete()

    # 5. Fix "Drive, Clutches & Drive Parts" → "Drives, Clutches & Drive Parts"
    Part.objects.filter(category="Drive, Clutches & Drive Parts").update(
        category="Drives, Clutches & Drive Parts"
    )

    # 6. "Pulleys" → "Pulleys & Pulley Collars"
    Part.objects.filter(category="Pulleys").update(
        category="Pulleys & Pulley Collars"
    )

    print(
        f"  Moved {moved} bolt/hardware parts to Hardware; "
        f"{remaining} remaining -> Misc; "
        f"merged Pulleys and Drive typo"
    )


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0036_add_markup_percent_to_part"),
    ]
    operations = [
        migrations.RunPython(forwards, backwards),
    ]
