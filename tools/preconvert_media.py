"""Pre-convert JPG/JPEG media files to PNG for the Qt (ChoreBoy) edition.

Background
----------
The Windows Django app of Apex Database serves images through Django's
FileSystemStorage and stores the on-disk filename in
``catalog.Part.image`` / ``catalog.PartImage.image`` / ``catalog.Unit.unit_image``
/ ``catalog.Unit.plug_image`` / ``catalog.UnitImage.image``. The Qt edition
that runs on ChoreBoy has a broken Qt JPEG plugin, so it can only render
PNGs. The Qt-side ``media_paths.py`` resolver looks for a ``.png`` sibling
whenever the DB row references a ``.jpg``/``.jpeg``.

This script prepares ``media/`` (or an export copy of it) so a single
``ApexDatabase_Media.zip`` works for both editions.

Three modes
-----------
* ``siblings`` (default, Option A)
    For every ``.jpg``/``.jpeg`` under ``--source``, write a ``.png`` next
    to it. Originals are kept. Safe for the Windows Django app because
    nothing on disk is removed: existing ``ImageField`` rows still point
    at a file that exists.

* ``replace`` (Option B, source-side)
    Same as ``siblings`` but the original ``.jpg``/``.jpeg`` is deleted
    after the ``.png`` is written. Smaller / faster zip but ONLY safe if
    every Django consumer that opens files by the DB-stored path goes
    through a resolver, OR a DB migration rewrites the extension columns.
    Do not use without confirming the audit.

* ``export-only``
    Walks ``--source`` and writes to ``--dest`` only. Source tree is
    never mutated. JPEGs are converted to PNG in the destination; all
    other files are copied verbatim. Use this for packaging when you do
    not want to touch the live ``media/`` folder at all.

CLI
---
::

    python -u tools/preconvert_media.py --source media --mode siblings
    python -u tools/preconvert_media.py --source media --mode replace
    python -u tools/preconvert_media.py --source media --mode export-only \\
        --dest dist\\media_png

Output is a single summary line:
``converted: N, skipped: M, errors: K, elapsed: Xs``. Per-file lines are
intentionally suppressed (the live tree is ~70k JPEGs). Exit code is
non-zero if any conversion error occurred.

See ``.cursor/rules/media-pack.mdc`` for the Option A / Option B trade-off.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Tuple


_JPEG_SUFFIXES = {".jpg", ".jpeg"}


def _is_jpeg(path: Path) -> bool:
    return path.suffix.lower() in _JPEG_SUFFIXES


def _png_is_newer(src: Path, png: Path) -> bool:
    """Return True if ``png`` exists and has mtime >= ``src``."""
    try:
        return png.stat().st_mtime >= src.stat().st_mtime
    except OSError:
        return False


def _convert_one(src: Path, dst: Path) -> None:
    """Convert one JPEG at ``src`` to PNG at ``dst``.

    Pillow is imported lazily so the rest of the module (including
    ``--dry-run`` and the test harness) can be exercised even on hosts
    that don't have Pillow installed.
    """
    from PIL import Image

    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im.convert("RGB").save(dst, format="PNG", optimize=True)


def _iter_files(source: Path):
    """Yield every regular file under ``source`` (recursive)."""
    for root, _, files in os.walk(source):
        root_p = Path(root)
        for f in files:
            yield root_p / f


def run_siblings(source: Path, dry_run: bool = False) -> Tuple[int, int, int]:
    """Option A: write .png next to every .jpg/.jpeg, keep originals."""
    converted = skipped = errors = 0
    for src in _iter_files(source):
        if not _is_jpeg(src):
            continue
        png = src.with_suffix(".png")
        if png.exists() and _png_is_newer(src, png):
            skipped += 1
            continue
        if dry_run:
            converted += 1
            continue
        try:
            _convert_one(src, png)
            converted += 1
        except Exception:
            errors += 1
    return converted, skipped, errors


def run_replace(source: Path, dry_run: bool = False) -> Tuple[int, int, int]:
    """Option B (source-side): write .png and delete the original JPEG."""
    converted = skipped = errors = 0
    for src in _iter_files(source):
        if not _is_jpeg(src):
            continue
        png = src.with_suffix(".png")

        if png.exists() and _png_is_newer(src, png):
            # PNG already up to date; just remove the JPEG.
            if dry_run:
                skipped += 1
                continue
            try:
                src.unlink()
                skipped += 1
            except OSError:
                errors += 1
            continue

        if dry_run:
            converted += 1
            continue
        try:
            _convert_one(src, png)
            src.unlink()
            converted += 1
        except Exception:
            errors += 1
    return converted, skipped, errors


def run_export_only(
    source: Path, dest: Path, dry_run: bool = False
) -> Tuple[int, int, int]:
    """Copy tree into ``dest``; JPEGs become PNGs in the destination."""
    converted = skipped = errors = 0
    source = source.resolve()
    for src in _iter_files(source):
        rel = src.relative_to(source)
        try:
            if _is_jpeg(src):
                target = dest / rel.with_suffix(".png")
                if dry_run:
                    converted += 1
                else:
                    _convert_one(src, target)
                    converted += 1
            else:
                target = dest / rel
                if dry_run:
                    skipped += 1
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, target)
                    skipped += 1
        except Exception:
            errors += 1
    return converted, skipped, errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Pre-convert JPEG media files to PNG so the same media pack "
            "works for the Windows Django app and the Qt (ChoreBoy) edition."
        )
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Root media folder to scan (e.g. 'media').",
    )
    parser.add_argument(
        "--mode",
        choices=["siblings", "replace", "export-only"],
        default="siblings",
        help=(
            "siblings (default, Option A): write .png next to every JPEG, "
            "keep originals. replace (Option B): write .png and delete the "
            "JPEG. export-only: write a converted copy into --dest without "
            "touching --source."
        ),
    )
    parser.add_argument(
        "--dest",
        help="Destination folder for --mode export-only.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report counts without writing or deleting anything.",
    )
    args = parser.parse_args(argv)

    source = Path(args.source)
    if not source.is_dir():
        print(f"error: --source not found or not a directory: {source}", file=sys.stderr)
        return 2

    started = time.monotonic()
    if args.mode == "siblings":
        converted, skipped, errors = run_siblings(source, dry_run=args.dry_run)
    elif args.mode == "replace":
        converted, skipped, errors = run_replace(source, dry_run=args.dry_run)
    else:
        if not args.dest:
            parser.error("--dest is required for --mode export-only")
        dest = Path(args.dest)
        if not args.dry_run:
            dest.mkdir(parents=True, exist_ok=True)
        converted, skipped, errors = run_export_only(source, dest, dry_run=args.dry_run)

    elapsed = time.monotonic() - started
    print(
        f"converted: {converted}, skipped: {skipped}, "
        f"errors: {errors}, elapsed: {elapsed:.1f}s"
    )
    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
