import json
import os
from pathlib import Path

from django.http import JsonResponse

_NOT_EXTRACTING = {"extracting": False}


def media_status(request):
    """Return the current media-extraction progress as JSON."""
    data_dir = os.environ.get("APP_DATA_DIR", "")
    if not data_dir:
        return JsonResponse(_NOT_EXTRACTING)

    status_path = Path(data_dir) / ".media_status.json"
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
        return JsonResponse(data)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return JsonResponse(_NOT_EXTRACTING)
