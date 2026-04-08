"""Application version -- reads from the VERSION file (single source of truth)."""

import os
from pathlib import Path

_candidates = [
    Path(__file__).resolve().parent / "VERSION",
    Path(os.environ.get("APP_DIR", ".")) / "VERSION",
]

__version__ = "0.0.0"
for _f in _candidates:
    try:
        __version__ = _f.read_text().strip()
        break
    except Exception:
        continue
