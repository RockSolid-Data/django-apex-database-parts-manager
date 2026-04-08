import json
import os
import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _load_changelog() -> list[dict]:
    """Load and cache changelog.json (checks _internal/ for frozen builds)."""
    try:
        app_dir = Path(os.environ.get("APP_DIR", ""))
        from django.conf import settings
        candidates = [
            app_dir / "changelog.json",
            Path(settings.BASE_DIR) / "changelog.json",
        ]
        for p in candidates:
            if p.is_file():
                return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def app_version(request):
    """Expose APP_VERSION, CHANGELOG_DATA, IS_FROZEN, and APP_NAME to all templates."""
    try:
        from version import __version__
    except ImportError:
        __version__ = "dev"

    return {
        "APP_VERSION": __version__,
        "CHANGELOG_DATA": _load_changelog(),
        "IS_FROZEN": getattr(sys, 'frozen', False),
        "APP_NAME": os.environ.get('APP_NAME', 'Apex Database'),
    }
