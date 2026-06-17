from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0054_add_source_pdf"),
    ]

    operations = [
        migrations.AddField(
            model_name="partimage",
            name="seed_id",
            field=models.IntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="unitimage",
            name="seed_id",
            field=models.IntegerField(blank=True, db_index=True, null=True),
        ),
    ]
