from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0025_add_kw_to_application"),
    ]

    operations = [
        migrations.AlterField(
            model_name="part",
            name="part_number",
            field=models.CharField(
                blank=True,
                default=None,
                max_length=100,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name="partinterchange",
            name="source_name",
            field=models.CharField(
                blank=True,
                default="",
                max_length=150,
                verbose_name="Source / Name",
            ),
        ),
    ]
