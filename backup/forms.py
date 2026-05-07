from pathlib import Path

from django import forms

from .models import BackupSettings


def _validate_backup_path(raw, *, required=False, label="path"):
    """Shared validation for a backup folder path."""
    raw = raw.strip()
    if not raw:
        if required:
            raise forms.ValidationError("A local backup folder is required.")
        return raw
    p = Path(raw)
    if not p.is_absolute():
        raise forms.ValidationError(f"Please enter a full path (e.g. E:\\ApexBackups).")
    if p.exists() and not p.is_dir():
        raise forms.ValidationError("That path exists but is not a folder.")
    if not p.exists():
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise forms.ValidationError(
                f"Cannot create folder: {exc}. "
                "Make sure the drive is plugged in and the path is correct."
            )
    try:
        test_file = p / ".apex_write_test"
        test_file.write_text("ok")
        test_file.unlink()
    except OSError:
        raise forms.ValidationError(
            "That folder is not writable. Check permissions or try a different location."
        )
    return str(p)


class BackupSettingsForm(forms.ModelForm):
    """Form for configuring backup paths and preferences."""

    class Meta:
        model = BackupSettings
        fields = [
            "local_backup_path",
            "external_backup_path",
            "auto_backup_enabled",
            "backup_interval_hours",
            "max_backups",
        ]
        widgets = {
            "local_backup_path": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": r"e.g. C:\ApexBackups",
            }),
            "external_backup_path": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": r"e.g. E:\ApexBackups (USB drive)",
            }),
            "auto_backup_enabled": forms.CheckboxInput(attrs={
                "class": "form-check-input",
            }),
            "backup_interval_hours": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 1,
                "max": 24,
            }),
            "max_backups": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 1,
                "max": 100,
            }),
        }

    def clean_local_backup_path(self):
        return _validate_backup_path(
            self.cleaned_data.get("local_backup_path", ""),
            required=False,
            label="local",
        )

    def clean_external_backup_path(self):
        return _validate_backup_path(
            self.cleaned_data.get("external_backup_path", ""),
            required=False,
            label="external",
        )

    def clean_backup_interval_hours(self):
        val = self.cleaned_data.get("backup_interval_hours")
        if val is not None:
            val = max(1, min(24, val))
        return val

    def clean_max_backups(self):
        val = self.cleaned_data.get("max_backups")
        if val is not None:
            val = max(1, min(100, val))
        return val


class RestoreForm(forms.Form):
    """Form for selecting a backup folder or .zip file to restore from."""

    backup_source = forms.CharField(
        max_length=500,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": r"e.g. C:\ApexBackups or E:\ApexBackups\apex_backup_2026-05-07.zip",
        }),
    )

    def clean_backup_source(self):
        raw = self.cleaned_data.get("backup_source", "").strip()
        if not raw:
            raise forms.ValidationError("Please enter the path to a backup folder or .zip file.")
        p = Path(raw)
        if not p.exists():
            raise forms.ValidationError("Path not found. Check the path and try again.")
        if p.is_file() and p.suffix.lower() != ".zip":
            raise forms.ValidationError("If selecting a file, it must be a .zip backup.")
        if p.is_dir() and not (p / "db.sqlite3").exists():
            raise forms.ValidationError(
                "That folder does not contain a db.sqlite3 file. "
                "Please select the backup folder that contains the database."
            )
        return str(p)
