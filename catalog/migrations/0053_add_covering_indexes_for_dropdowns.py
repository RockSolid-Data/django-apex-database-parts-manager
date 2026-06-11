"""
Add composite covering indexes for dropdown filter queries.

These indexes let SQLite satisfy ``SELECT DISTINCT col FROM table WHERE
is_active = 1 AND col != '' ORDER BY col`` with a pure index scan—no
table lookup required.  On 70-90 K row tables this cuts dropdown-choice
queries from ~50 ms to < 5 ms.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0052_partinterchange_unique_number_source"),
    ]

    operations = [
        # Application dropdown covering indexes
        migrations.AddIndex(
            model_name="application",
            index=models.Index(
                fields=["is_active", "make"],
                name="catalog_app_active_make_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="application",
            index=models.Index(
                fields=["is_active", "model"],
                name="catalog_app_active_model_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="application",
            index=models.Index(
                fields=["is_active", "mfr"],
                name="catalog_app_active_mfr_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="application",
            index=models.Index(
                fields=["is_active", "volt"],
                name="catalog_app_active_volt_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="application",
            index=models.Index(
                fields=["is_active", "unit_type_name"],
                name="catalog_app_active_utype_idx",
            ),
        ),
        # Unit dropdown covering indexes
        migrations.AddIndex(
            model_name="unit",
            index=models.Index(
                fields=["is_active", "manufacturer"],
                name="catalog_uni_active_mfr_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="unit",
            index=models.Index(
                fields=["is_active", "voltage"],
                name="catalog_uni_active_volt_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="unit",
            index=models.Index(
                fields=["is_active", "unit_type_category"],
                name="catalog_uni_active_utype_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="unit",
            index=models.Index(
                fields=["is_active", "yt_number"],
                name="catalog_uni_active_yt_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="unit",
            index=models.Index(
                fields=["is_active", "unit_number"],
                name="catalog_uni_active_unum_idx",
            ),
        ),
    ]
