from django.db import models


class BackupSettings(models.Model):
    """Backup configuration singleton. One row expected."""

    local_backup_path = models.CharField(
        "Local Backup Folder",
        max_length=500,
        blank=True,
        default="",
        help_text="Local folder for fast automatic backups (e.g. C:\\ApexBackups).",
    )
    external_backup_path = models.CharField(
        "External Backup Folder",
        max_length=500,
        blank=True,
        default="",
        help_text="Optional external/USB drive folder for disaster recovery (e.g. E:\\ApexBackups).",
    )
    auto_backup_enabled = models.BooleanField(
        "Auto-backup enabled",
        default=True,
        help_text="Automatically back up on app startup and periodically while running.",
    )
    backup_interval_hours = models.PositiveIntegerField(
        "Periodic backup interval (hours)",
        default=2,
        help_text="How often the app backs up while running (in addition to startup/shutdown).",
    )
    max_backups = models.PositiveIntegerField(
        "Max DB snapshots to keep",
        default=10,
        help_text="Number of historical database snapshots to keep. Oldest are deleted automatically.",
    )
    last_backup_at = models.DateTimeField(
        "Last backup time", null=True, blank=True,
    )
    last_backup_status = models.CharField(
        "Last backup status",
        max_length=500,
        blank=True,
        default="",
    )

    class Meta:
        verbose_name = "Backup Settings"
        verbose_name_plural = "Backup Settings"

    def __str__(self):
        local = self.local_backup_path or "(not set)"
        ext = self.external_backup_path or "(not set)"
        return f"Backup: local={local}, external={ext}"

    @classmethod
    def get(cls):
        """Get or create singleton settings."""
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj
