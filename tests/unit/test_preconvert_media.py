"""Unit tests for tools/preconvert_media.py.

These tests are pure ``unittest`` (no Django) and write to a temp dir, so
they can be run directly with::

    .\\venv\\Scripts\\python.exe -u -m unittest tests.unit.test_preconvert_media -v 2>&1

They exercise the three modes (``siblings``, ``replace``, ``export-only``)
and the "do not overwrite a newer PNG" guard.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import preconvert_media  # noqa: E402


def _make_jpeg(path: Path, color=(255, 0, 0), size=(8, 8)) -> None:
    """Write a tiny valid JPEG using Pillow."""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="JPEG")


def _make_png(path: Path, color=(0, 255, 0), size=(8, 8)) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="PNG")


class SiblingsModeTest(unittest.TestCase):
    def test_writes_png_and_keeps_jpg(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            jpg = root / "parts" / "450003.jpg"
            _make_jpeg(jpg)

            converted, skipped, errors = preconvert_media.run_siblings(root)

            self.assertEqual(converted, 1)
            self.assertEqual(skipped, 0)
            self.assertEqual(errors, 0)
            self.assertTrue(jpg.exists(), "original .jpg must be kept in siblings mode")
            self.assertTrue(jpg.with_suffix(".png").is_file(), ".png sibling must be written")

    def test_skips_when_png_is_newer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            jpg = root / "parts" / "450003.jpeg"
            _make_jpeg(jpg)

            png = jpg.with_suffix(".png")
            _make_png(png, color=(0, 0, 255))

            # Force the PNG to be strictly newer than the JPEG.
            now = time.time()
            os.utime(jpg, (now - 60, now - 60))
            os.utime(png, (now, now))

            png_bytes_before = png.read_bytes()

            converted, skipped, errors = preconvert_media.run_siblings(root)

            self.assertEqual(converted, 0)
            self.assertEqual(skipped, 1)
            self.assertEqual(errors, 0)
            self.assertEqual(
                png.read_bytes(),
                png_bytes_before,
                "pre-existing newer .png must not be overwritten",
            )

    def test_ignores_already_png_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            png = root / "parts" / "ABC.png"
            _make_png(png)

            converted, skipped, errors = preconvert_media.run_siblings(root)

            self.assertEqual((converted, skipped, errors), (0, 0, 0))
            self.assertTrue(png.is_file())

    def test_handles_spaces_and_unicode_filenames(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            jpg = root / "weird folder" / "ümlaut name.jpg"
            _make_jpeg(jpg)

            converted, skipped, errors = preconvert_media.run_siblings(root)

            self.assertEqual(converted, 1)
            self.assertEqual(errors, 0)
            self.assertTrue(jpg.with_suffix(".png").is_file())


class ReplaceModeTest(unittest.TestCase):
    def test_removes_original_jpeg(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            jpg = root / "parts" / "ABC.jpg"
            _make_jpeg(jpg)

            converted, skipped, errors = preconvert_media.run_replace(root)

            self.assertEqual(converted, 1)
            self.assertEqual(skipped, 0)
            self.assertEqual(errors, 0)
            self.assertFalse(jpg.exists(), "original .jpg must be removed in replace mode")
            self.assertTrue(jpg.with_suffix(".png").is_file())


class ExportOnlyModeTest(unittest.TestCase):
    def test_writes_to_dest_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src_root = root / "src"
            dest_root = root / "dest"

            jpg = src_root / "parts" / "X.jpg"
            png_in = src_root / "parts" / "Y.png"
            other = src_root / "docs" / "readme.txt"

            _make_jpeg(jpg)
            _make_png(png_in)
            other.parent.mkdir(parents=True, exist_ok=True)
            other.write_text("hello", encoding="utf-8")

            src_inventory_before = sorted(
                p.relative_to(src_root).as_posix()
                for p in src_root.rglob("*")
                if p.is_file()
            )

            converted, skipped, errors = preconvert_media.run_export_only(
                src_root, dest_root
            )

            self.assertEqual(converted, 1)  # the JPEG
            self.assertEqual(skipped, 2)  # the PNG + the txt
            self.assertEqual(errors, 0)

            src_inventory_after = sorted(
                p.relative_to(src_root).as_posix()
                for p in src_root.rglob("*")
                if p.is_file()
            )
            self.assertEqual(
                src_inventory_before,
                src_inventory_after,
                "export-only mode must not mutate --source",
            )

            self.assertTrue((dest_root / "parts" / "X.png").is_file())
            self.assertTrue((dest_root / "parts" / "Y.png").is_file())
            self.assertTrue((dest_root / "docs" / "readme.txt").is_file())
            self.assertFalse(
                (dest_root / "parts" / "X.jpg").exists(),
                "JPEGs must not be copied verbatim under export-only",
            )


class DryRunTest(unittest.TestCase):
    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            jpg = root / "parts" / "Z.jpg"
            _make_jpeg(jpg)

            converted, skipped, errors = preconvert_media.run_siblings(root, dry_run=True)

            self.assertEqual(converted, 1)
            self.assertEqual(errors, 0)
            self.assertFalse(jpg.with_suffix(".png").exists())


if __name__ == "__main__":
    unittest.main()
