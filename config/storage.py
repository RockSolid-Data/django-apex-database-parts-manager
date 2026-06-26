"""Custom storage backend that creates PNG siblings for JPEG uploads."""

import logging
import os

from django.core.files.storage import FileSystemStorage

logger = logging.getLogger(__name__)


class PngSiblingStorage(FileSystemStorage):
    """
    FileSystemStorage subclass that automatically creates a .png sibling
    whenever a JPEG file is saved. This keeps JPEGs as the master format
    (stored in Django's DB) while providing PNGs for consumers that can't
    render JPEGs (e.g. the ChoreBoy Qt app).
    """

    _JPEG_EXTENSIONS = {".jpg", ".jpeg"}

    def _save(self, name, content):
        name = super()._save(name, content)

        ext = os.path.splitext(name)[1].lower()
        if ext in self._JPEG_EXTENSIONS:
            self._create_png_sibling(name)

        return name

    def _create_png_sibling(self, name):
        stem, _ = os.path.splitext(name)
        png_name = stem + ".png"
        full_path = self.path(name)
        png_path = self.path(png_name)

        try:
            from PIL import Image

            with Image.open(full_path) as img:
                img.convert("RGB").save(png_path, format="PNG", optimize=True)
        except Exception:
            logger.warning(
                "Failed to create PNG sibling for %s", name, exc_info=True
            )

    def delete(self, name):
        """Delete the file and its PNG sibling if one exists."""
        ext = os.path.splitext(name)[1].lower()
        if ext in self._JPEG_EXTENSIONS:
            stem, _ = os.path.splitext(name)
            png_name = stem + ".png"
            if super().exists(png_name):
                super().delete(png_name)

        super().delete(name)
