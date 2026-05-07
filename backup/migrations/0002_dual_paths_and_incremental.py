"""Rename backup_path -> local_backup_path, add external_backup_path."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("backup", "0001_initial"),
    ]

    operations = [
        migrations.RenameField(
            model_name="backupsettings",
            old_name="backup_path",
            new_name="local_backup_path",
        ),
        migrations.AlterField(
            model_name="backupsettings",
            name="local_backup_path",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Local folder for fast automatic backups (e.g. C:\\ApexBackups).",
                max_length=500,
                verbose_name="Local Backup Folder",
            ),
        ),
        migrations.AddField(
            model_name="backupsettings",
            name="external_backup_path",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional external/USB drive folder for disaster recovery (e.g. E:\\ApexBackups).",
                max_length=500,
                verbose_name="External Backup Folder",
            ),
        ),
        migrations.AlterField(
            model_name="backupsettings",
            name="max_backups",
            field=models.PositiveIntegerField(
                default=10,
                help_text="Number of historical database snapshots to keep. Oldest are deleted automatically.",
                verbose_name="Max DB snapshots to keep",
            ),
        ),
    ]
