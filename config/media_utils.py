"""Media helpers: stable image writes and filename fallback for serving."""

import re
from pathlib import Path

from django.conf import settings
from django.http import Http404
from django.views.static import serve

# Django FileSystemStorage collision suffix: stem_<7 alnum>.ext
_DJANGO_UPLOAD_SUFFIX = re.compile(r"^(?P<stem>.+)_[A-Za-z0-9]{7}(?P<ext>\.[^.]+)$")


def write_media_file(relative_path, data):
    """Write bytes to MEDIA_ROOT using an exact relative path (overwrite if present)."""
    if hasattr(data, "read"):
        data = data.read()
    dest = Path(settings.MEDIA_ROOT) / relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return relative_path


def fallback_media_path(path):
    """If path uses a Django upload hash suffix, return the plain filename variant."""
    parent = Path(path).parent
    name = Path(path).name
    match = _DJANGO_UPLOAD_SUFFIX.match(name)
    if not match:
        return None
    alt_name = f"{match.group('stem')}{match.group('ext')}"
    if parent.parts:
        return str(parent / alt_name)
    return alt_name


def serve_media(request, path, document_root=None):
    """Serve a media file, falling back to the un-suffixed name when needed."""
    root = Path(document_root or settings.MEDIA_ROOT)
    if (root / path).is_file():
        return serve(request, path, document_root=root)

    alt_path = fallback_media_path(path)
    if alt_path and (root / alt_path).is_file():
        return serve(request, alt_path, document_root=root)

    raise Http404("Media file not found")
