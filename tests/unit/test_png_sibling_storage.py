"""Unit tests for config.storage.PngSiblingStorage.

Run with::

    .\\venv\\Scripts\\python.exe -u -m unittest tests.unit.test_png_sibling_storage -v 2>&1
"""

from __future__ import annotations

import io
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django.core.files.base import ContentFile  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402

from config.storage import PngSiblingStorage  # noqa: E402


def _jpeg_bytes(size=(4, 4), color=(255, 0, 0)):
    """Return minimal valid JPEG bytes."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def _png_bytes(size=(4, 4), color=(0, 255, 0)):
    """Return minimal valid PNG bytes."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class TestPngSiblingStorage(unittest.TestCase):
    """Tests for the automatic PNG sibling creation on JPEG upload."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.storage = PngSiblingStorage(location=self.tmp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_jpeg_upload_creates_png_sibling(self):
        """A .jpg upload should produce both .jpg and .png on disk."""
        content = ContentFile(_jpeg_bytes(), name="test_image.jpg")
        saved_name = self.storage.save("parts/test_image.jpg", content)

        jpg_path = Path(self.tmp_dir) / saved_name
        stem = os.path.splitext(saved_name)[0]
        png_path = Path(self.tmp_dir) / (stem + ".png")

        self.assertTrue(jpg_path.exists(), f"JPEG not found: {jpg_path}")
        self.assertTrue(png_path.exists(), f"PNG sibling not found: {png_path}")

    def test_jpeg_uppercase_extension(self):
        """A .JPEG upload (uppercase) should also produce a PNG sibling."""
        content = ContentFile(_jpeg_bytes(), name="upper.JPEG")
        saved_name = self.storage.save("parts/upper.JPEG", content)

        stem = os.path.splitext(saved_name)[0]
        png_path = Path(self.tmp_dir) / (stem + ".png")
        self.assertTrue(png_path.exists(), "PNG sibling not created for .JPEG")

    def test_png_upload_no_double_conversion(self):
        """A .png upload should NOT produce a second .png file."""
        content = ContentFile(_png_bytes(), name="already.png")
        saved_name = self.storage.save("parts/already.png", content)

        parent = Path(self.tmp_dir) / "parts"
        png_files = list(parent.glob("already*.png"))
        self.assertEqual(len(png_files), 1, "Should have exactly one PNG file")

    def test_non_image_upload_ignored(self):
        """A .txt upload should not trigger any PNG conversion."""
        content = ContentFile(b"hello world", name="readme.txt")
        saved_name = self.storage.save("docs/readme.txt", content)

        parent = Path(self.tmp_dir) / "docs"
        png_files = list(parent.glob("*.png"))
        self.assertEqual(len(png_files), 0, "No PNGs should be created for .txt")

    def test_delete_removes_png_sibling(self):
        """Deleting a JPEG via storage should also remove its PNG sibling."""
        content = ContentFile(_jpeg_bytes(), name="del_test.jpg")
        saved_name = self.storage.save("parts/del_test.jpg", content)

        stem = os.path.splitext(saved_name)[0]
        png_name = stem + ".png"

        self.assertTrue(self.storage.exists(saved_name))
        self.assertTrue(self.storage.exists(png_name))

        self.storage.delete(saved_name)

        self.assertFalse(self.storage.exists(saved_name))
        self.assertFalse(self.storage.exists(png_name))

    def test_conversion_failure_doesnt_block_upload(self):
        """If PIL.Image.open raises, the JPEG upload still succeeds."""
        content = ContentFile(_jpeg_bytes(), name="fail.jpg")

        with patch("PIL.Image.open", side_effect=RuntimeError("Simulated Pillow failure")):
            with self.assertLogs("config.storage", level="WARNING") as cm:
                saved_name = self.storage.save("parts/fail.jpg", content)

        jpg_path = Path(self.tmp_dir) / saved_name
        self.assertTrue(jpg_path.exists(), "JPEG should still be saved")

        stem = os.path.splitext(saved_name)[0]
        png_path = Path(self.tmp_dir) / (stem + ".png")
        self.assertFalse(png_path.exists(), "PNG should NOT be created on failure")

        self.assertTrue(any("Failed to create PNG sibling" in msg for msg in cm.output))

    def test_delete_signal_removes_sibling(self):
        """Deleting a PartImage model instance removes both .jpg and .png."""
        from catalog.models import Part, PartImage

        content = ContentFile(_jpeg_bytes(), name="signal_test.jpg")
        saved_name = self.storage.save("parts/signal_test.jpg", content)

        stem = os.path.splitext(saved_name)[0]
        png_name = stem + ".png"

        self.assertTrue(self.storage.exists(saved_name))
        self.assertTrue(self.storage.exists(png_name))

        # Create a Part and PartImage using this storage path
        with patch("django.conf.settings.MEDIA_ROOT", self.tmp_dir):
            part = Part.objects.create(part_number="TEST-SIGNAL-001")
            part_image = PartImage.objects.create(part=part, image=saved_name)

            # Override the image field's storage to use our temp storage
            part_image.image.storage = self.storage

            # Trigger the delete signal
            part_image.delete()

        self.assertFalse(self.storage.exists(saved_name), "JPEG should be deleted")
        self.assertFalse(self.storage.exists(png_name), "PNG sibling should be deleted")

        # Cleanup the Part
        Part.objects.filter(part_number="TEST-SIGNAL-001").delete()


if __name__ == "__main__":
    unittest.main()
