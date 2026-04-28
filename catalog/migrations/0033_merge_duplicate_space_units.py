"""
Merge 491 duplicate units whose unit_number contains a space (e.g. "334718 400-52103R,")
back into the real base unit ("334718"). For each:
  1. Copy non-empty fields from the dupe to the base (only where base is blank).
  2. Add the extra number as a CrossReference on the base.
  3. Re-parent any cross-references/BOMs from the dupe to the base.
  4. Delete the duplicate.
"""
from django.db import migrations


MERGE_FIELDS = [
    "manufacturer", "voltage", "kw_hp", "phase", "fla", "amp_rating",
    "full_load_eff", "power_rating", "rpm", "frame", "enclosure", "rotation",
    "clock_position", "mount_type", "flange_type", "housing_type", "housing",
    "weight", "bearings", "design", "type", "oem", "j_and_n_number",
    "model_cat_number", "family", "description", "notes",
]


def merge_units(apps, schema_editor):
    Unit = apps.get_model("catalog", "Unit")
    CrossReference = apps.get_model("catalog", "CrossReference")
    BOM = apps.get_model("catalog", "BOM")

    dupes = Unit.objects.filter(unit_number__contains=" ").order_by("pk")
    merged = 0
    skipped = 0

    for dupe in dupes:
        parts = dupe.unit_number.split(None, 1)
        base_num = parts[0].rstrip(",")
        extra = parts[1].rstrip(",") if len(parts) > 1 else ""

        base = Unit.objects.filter(unit_number=base_num).first()
        if not base:
            base = Unit.objects.filter(yt_number=base_num).exclude(pk=dupe.pk).first()
        if not base:
            skipped += 1
            continue

        update_fields = []
        for field in MERGE_FIELDS:
            dupe_val = getattr(dupe, field, "") or ""
            base_val = getattr(base, field, "") or ""
            if dupe_val and not base_val:
                setattr(base, field, dupe_val)
                update_fields.append(field)
        if update_fields:
            base.save(update_fields=update_fields)

        if extra:
            exists = CrossReference.objects.filter(
                unit=base, cross_ref_number=extra
            ).exists()
            if not exists:
                CrossReference.objects.create(
                    unit=base,
                    cross_ref_number=extra,
                    notes="Merged from duplicate unit import",
                )

        CrossReference.objects.filter(unit=dupe).update(unit=base)
        BOM.objects.filter(unit=dupe).update(unit=base)

        dupe.delete()
        merged += 1

    print(f"  Merged {merged} duplicate units, skipped {skipped}")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0032_split_multi_jn_to_interchanges"),
    ]

    operations = [
        migrations.RunPython(merge_units, noop),
    ]
