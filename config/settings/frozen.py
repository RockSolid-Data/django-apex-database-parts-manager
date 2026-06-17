"""
Settings for the cx_Freeze standalone build.

- DEBUG off
- SQLite stored in %LOCALAPPDATA%/ApexDatabase/ so data survives upgrades
- ALLOWED_HOSTS limited to loopback (Waitress serves on 127.0.0.1 only)
- Static files served by WhiteNoise from _internal/staticfiles/
"""

import os
import sys
from pathlib import Path

from .base import *  # noqa: F403, F401

DEBUG = False

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

IS_FROZEN = getattr(sys, "frozen", False)

if IS_FROZEN:
    _INSTALL_DIR = Path(sys.executable).resolve().parent
else:
    _INSTALL_DIR = BASE_DIR  # noqa: F405

_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")
if _LOCALAPPDATA:
    DATA_DIR = Path(_LOCALAPPDATA) / "ApexDatabase"
else:
    DATA_DIR = _INSTALL_DIR / "data"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# Database -- stored in DATA_DIR so it survives app upgrades
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(os.environ["DATABASE_PATH"]) if os.environ.get("DATABASE_PATH") else DATA_DIR / "db.sqlite3",
        "OPTIONS": {
            "transaction_mode": "IMMEDIATE",
        },
    }
}

# Secret key: persisted alongside the DB so sessions survive upgrades
_SECRET_KEY_FILE = DATA_DIR / ".secret_key"
if _SECRET_KEY_FILE.exists():
    SECRET_KEY = _SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
else:
    from django.core.management.utils import get_random_secret_key
    SECRET_KEY = get_random_secret_key()
    _SECRET_KEY_FILE.write_text(SECRET_KEY, encoding="utf-8")

# Static files: served from _internal/staticfiles/ in frozen builds
if IS_FROZEN:
    STATIC_ROOT = _INSTALL_DIR / "_internal" / "staticfiles"
    STATICFILES_DIRS = []  # noqa: F405
else:
    STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405

MEDIA_ROOT = DATA_DIR / "media"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": str(DATA_DIR / "cache"),
        "TIMEOUT": 1800,
    }
}

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Logging to file in DATA_DIR — daily rotation, keep 14 days
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
    },
    "handlers": {
        "file": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "filename": str(LOG_DIR / "app.log"),
            "when": "midnight",
            "backupCount": 14,
            "formatter": "standard",
            "encoding": "utf-8",
        },
    },
    "root": {
        "handlers": ["file"],
        "level": "WARNING",
    },
    "loggers": {
        "django": {
            "handlers": ["file"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["file"],
            "level": "ERROR",
            "propagate": False,
        },
        "activity": {
            "handlers": ["file"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}
