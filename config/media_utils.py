"""Media helpers: stable image writes, and on-demand serving from disk or the media pack zip.

The frozen desktop app ships part images inside a single ``ApexDatabase_Media.zip``
(7.5 GB uncompressed / 35k+ files). Rather than extracting that pack to disk on
first launch -- which is slow and, if interrupted, leaves truncated files that
break images permanently -- images are served on demand:

    1. from ``MEDIA_ROOT`` on disk if the file is present (user uploads / new
       images always win), otherwise
    2. straight out of the media pack zip (``settings.MEDIA_PACK_ZIP``), reading
       just the one entry that was requested.

Reading a single entry from a zip is a direct seek + decompress (milliseconds on
localhost), so there is no upfront extraction wait and no partial-extraction
corruption to heal.
"""

import mimetypes
import re
import threading
import zipfile
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse
from django.views.static import serve

# Django FileSystemStorage collision suffix: stem_<7 alnum>.ext
_DJANGO_UPLOAD_SUFFIX = re.compile(r"^(?P<stem>.+)_[A-Za-z0-9]{7}(?P<ext>\.[^.]+)$")

# Media pack entries are stored relative to the project root, i.e. prefixed with
# the media directory name and using forward slashes (e.g. "media/parts/x.jpg").
_PACK_MEMBER_PREFIX = "media/"

# Long cache lifetime -- pack images are immutable for the life of an install.
_PACK_CACHE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


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


class _MediaPack:
    """Thread-safe reader over a media pack zip, cached open across requests.

    Opening a ZipFile parses its central directory (a few ms even for 35k
    entries); caching the open handle avoids repeating that on every image
    request. Reads are serialised with a lock because ``zipfile`` is not safe
    for concurrent reads on a single handle -- fine for a single-user desktop
    app on localhost.
    """

    def __init__(self, zip_path):
        self.zip_path = Path(zip_path)
        self._zf = None
        self._names = None
        self._lock = threading.Lock()

    def _ensure_open(self):
        if self._zf is None:
            self._zf = zipfile.ZipFile(self.zip_path, "r")
            self._names = set(self._zf.namelist())

    def read(self, member):
        """Return the bytes of ``member`` or ``None`` if it is not in the pack."""
        with self._lock:
            self._ensure_open()
            if member not in self._names:
                return None
            return self._zf.read(member)


_pack_cache = {}
_pack_cache_lock = threading.Lock()


def _get_media_pack():
    """Return a cached _MediaPack for the configured zip, or None if unavailable."""
    zip_path = getattr(settings, "MEDIA_PACK_ZIP", None)
    if not zip_path:
        return None
    zip_path = Path(zip_path)
    try:
        mtime = zip_path.stat().st_mtime
    except OSError:
        return None  # missing / unreadable -- fall through to Http404
    key = (str(zip_path), mtime)
    with _pack_cache_lock:
        pack = _pack_cache.get(key)
        if pack is None:
            _pack_cache.clear()  # a new/rebuilt zip supersedes any stale handle
            pack = _MediaPack(zip_path)
            _pack_cache[key] = pack
    return pack


def _pack_members_for(path):
    """Candidate zip member names to try for a requested media path."""
    candidates = [_PACK_MEMBER_PREFIX + path, path]
    alt = fallback_media_path(path)
    if alt:
        candidates.append(_PACK_MEMBER_PREFIX + alt)
        candidates.append(alt)
    return candidates


def _serve_from_pack(path):
    """Serve a media file from the pack zip, or return None if not present there."""
    pack = _get_media_pack()
    if pack is None:
        return None

    for member in _pack_members_for(path):
        try:
            data = pack.read(member)
        except (OSError, zipfile.BadZipFile):
            return None
        if data is not None:
            content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
            response = HttpResponse(data, content_type=content_type)
            response["Content-Length"] = str(len(data))
            response["Cache-Control"] = f"public, max-age={_PACK_CACHE_MAX_AGE}"
            return response
    return None


def serve_media(request, path, document_root=None):
    """Serve a media file: disk first (uploads/new images), then the media pack zip."""
    root = Path(document_root or settings.MEDIA_ROOT)

    if (root / path).is_file():
        return serve(request, path, document_root=root)

    alt_path = fallback_media_path(path)
    if alt_path and (root / alt_path).is_file():
        return serve(request, alt_path, document_root=root)

    pack_response = _serve_from_pack(path)
    if pack_response is not None:
        return pack_response

    raise Http404("Media file not found")
