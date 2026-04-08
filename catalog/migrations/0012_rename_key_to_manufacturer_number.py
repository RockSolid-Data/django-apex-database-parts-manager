from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0011_seed_unit_type_categories'),
    ]

    operations = [
        migrations.RenameField(
            model_name='part',
            old_name='key',
            new_name='manufacturer_number',
        ),
    ]
