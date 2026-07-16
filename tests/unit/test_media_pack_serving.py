"""Unit tests for zip-backed media serving (serve images from the media pack).

The frozen app no longer extracts the 7.5 GB media pack to disk. Instead
``config.media_utils.serve_media`` serves each image on demand:

    1. from ``MEDIA_ROOT`` on disk if present (user uploads / new images), then
    2. directly out of the media pack zip (``settings.MEDIA_PACK_ZIP``).

Run with::

    .\\venv\\Scripts\\python.exe -u -m unittest tests.unit.test_media_pack_serving -v 2>&1
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django.http import Http404  # noqa: E402
from django.test import RequestFactory, SimpleTestCase, override_settings  # noqa: E402

from config.media_utils import serve_media  # noqa: E402


def _jpeg_bytes(color=(255, 0, 0)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="JPEG")
    return buf.getvalue()


def _response_body(resp):
    """Return the full body of either a FileResponse or an HttpResponse."""
    if getattr(resp, "streaming", False):
        return b"".join(resp.streaming_content)
    return resp.content


class ZipBackedServeMediaTest(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.media_root = Path(self.tmp) / "media"
        self.media_root.mkdir(parents=True, exist_ok=True)
        self.zip_path = Path(self.tmp) / "ApexDatabase_Media.zip"
        self.factory = RequestFactory()
        # Distinct payloads so we can tell disk vs pack apart.
        self.pack_bytes = _jpeg_bytes(color=(255, 0, 0))
        self.disk_bytes = _jpeg_bytes(color=(0, 0, 255))

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build_zip(self, arcname="media/parts/foo.jpg", data=None):
        with zipfile.ZipFile(self.zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(arcname, data if data is not None else self.pack_bytes)

    def _get(self, path="parts/foo.jpg"):
        request = self.factory.get("/media/" + path)
        return serve_media(request, path, document_root=str(self.media_root))

    def test_serve_media_reads_from_pack_when_not_on_disk(self):
        """Image missing from disk is served straight from the media pack zip."""
        self._build_zip()
        with override_settings(
            MEDIA_ROOT=str(self.media_root), MEDIA_PACK_ZIP=str(self.zip_path)
        ):
            resp = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_response_body(resp), self.pack_bytes)
        self.assertEqual(resp["Content-Type"], "image/jpeg")

    def test_serve_media_prefers_disk_over_pack(self):
        """A file present on disk wins over the copy inside the pack."""
        disk_file = self.media_root / "parts" / "foo.jpg"
        disk_file.parent.mkdir(parents=True, exist_ok=True)
        disk_file.write_bytes(self.disk_bytes)
        self._build_zip()  # pack has different bytes
        with override_settings(
            MEDIA_ROOT=str(self.media_root), MEDIA_PACK_ZIP=str(self.zip_path)
        ):
            resp = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_response_body(resp), self.disk_bytes)

    def test_serve_media_404_when_in_neither_disk_nor_pack(self):
        """Missing everywhere raises Http404 (broken link, but no crash)."""
        self._build_zip(arcname="media/parts/other.jpg")
        with override_settings(
            MEDIA_ROOT=str(self.media_root), MEDIA_PACK_ZIP=str(self.zip_path)
        ):
            with self.assertRaises(Http404):
                self._get("parts/foo.jpg")

    def test_serve_media_missing_zip_does_not_crash(self):
        """A configured-but-absent pack path degrades to Http404, not an error."""
        missing = Path(self.tmp) / "does_not_exist.zip"
        with override_settings(
            MEDIA_ROOT=str(self.media_root), MEDIA_PACK_ZIP=str(missing)
        ):
            with self.assertRaises(Http404):
                self._get("parts/foo.jpg")

    def test_serve_media_no_pack_configured_still_404s(self):
        """When MEDIA_PACK_ZIP is unset, behaviour falls back to disk-only 404."""
        with override_settings(MEDIA_ROOT=str(self.media_root), MEDIA_PACK_ZIP=None):
            with self.assertRaises(Http404):
                self._get("parts/foo.jpg")

    def test_serve_media_sets_cache_headers_for_pack(self):
        """Pack responses are cacheable so the browser stops re-requesting."""
        self._build_zip()
        with override_settings(
            MEDIA_ROOT=str(self.media_root), MEDIA_PACK_ZIP=str(self.zip_path)
        ):
            resp = self._get()
        self.assertIn("Cache-Control", resp)
        self.assertIn("max-age", resp["Cache-Control"])


if __name__ == "__main__":
    unittest.main()
