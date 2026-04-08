"""
Development settings -- used by manage.py runserver.
"""

from .base import *  # noqa: F403, F401

DEBUG = True
SECRET_KEY = "django-insecure-dev-only-m4nch3st3r-3l3ctr1c"
ALLOWED_HOSTS = []

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "activity": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}
