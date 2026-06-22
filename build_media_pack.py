"""Compress the media/ folder into dist/ApexDatabase_Media.zip.

Default behaviour is unchanged: the script walks ``media/`` as it is on
disk and zips it.

Optional ``--preconvert`` flag (off by default)
-----------------------------------------------
The Qt edition of Apex Database that runs on ChoreBoy has a broken Qt
JPEG plugin and can only render PNGs. To ship a single media pack that
works for BOTH the Windows Django app and the Qt edition, you can ask
this script to pre-convert JPEGs to PNG before zipping by delegating to
``tools/preconvert_media.py``:

* ``--preconvert siblings``  (Option A)
    Writes ``.png`` next to every ``.jpg``/``.jpeg`` in ``media/`` and
    keeps the originals. The zip ends up larger but every existing
    Django ``ImageField`` row still points at a file that exists. This
    is the safe choice and should be used unless you have audited every
    consumer.

* ``--preconvert replace``  (Option B)
    Writes ``.png`` and deletes the original JPEG from ``media/``. The
    zip is smaller and the Qt resolver does not have to fall back, but
    every Django consumer that opens files by the DB-stored path (which
    today still says ``.jpg``/``.jpeg``) will 404 unless a resolver or
    a DB migration is added. See ``.cursor/rules/media-pack.mdc``.

* ``--preconvert none`` (default)
    Skip pre-conversion entirely. Existing behaviour.

The flag can also be set via the ``MEDIA_PRECONVERT`` env var, which is
how ``build_media_pack.bat`` forwards user choice on Windows.
"""

import argparse
import os
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

APP_NAME = "ApexDatabase"
MEDIA_DIR = Path("media")
OUTPUT = Path("dist") / f"{APP_NAME}_Media.zip"
VERSION_FILE = ".media_version"
PRECONVERT_SCRIPT = Path("tools") / "preconvert_media.py"


def _parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--preconvert",
        choices=["none", "siblings", "replace"],
        default=os.environ.get("MEDIA_PRECONVERT", "none"),
        help=(
            "Pre-convert JPEGs to PNG before zipping. 'siblings' writes "
            ".png next to each JPEG and keeps the originals (Option A, "
            "safe). 'replace' writes .png and deletes the JPEG (Option "
            "B, smaller zip but requires a Django consumer audit). "
            "Default 'none' (skip pre-conversion). Can also be set via "
            "the MEDIA_PRECONVERT env var."
        ),
    )
    return parser.parse_args(argv)


def _run_preconvert(mode):
    """Invoke tools/preconvert_media.py against MEDIA_DIR. Returns its exit code."""
    if not PRECONVERT_SCRIPT.is_file():
        print(f"[ERROR] Pre-convert script not found: {PRECONVERT_SCRIPT}")
        return 1

    print(f"  Pre-converting JPEGs to PNG (mode={mode})...")
    cmd = [
        sys.executable,
        "-u",
        str(PRECONVERT_SCRIPT),
        "--source",
        str(MEDIA_DIR),
        "--mode",
        mode,
    ]
    proc = subprocess.run(cmd)
    return proc.returncode


def main(argv=None):
    args = _parse_args(argv)

    if not MEDIA_DIR.is_dir():
        print("[ERROR] media/ folder not found!")
        return 1

    if args.preconvert != "none":
        rc = _run_preconvert(args.preconvert)
        if rc != 0:
            print(f"[ERROR] Pre-conversion failed (exit {rc}); aborting before zip.")
            return rc

    OUTPUT.parent.mkdir(exist_ok=True)

    files = [
        Path(root) / f
        for root, _, filenames in os.walk(MEDIA_DIR)
        for f in filenames
        if not f.startswith(".")
    ]
    total = len(files)
    print(f"  Found {total:,} files to compress...")

    # Generate version stamp
    version_content = f"{total}\n{datetime.now():%Y-%m-%d %H:%M}\n"

    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for i, fpath in enumerate(files, 1):
            zf.write(fpath, fpath)
            if i % 100 == 0 or i == total:
                pct = i * 100 // total
                sys.stdout.write(f"\r  {i:,}/{total:,} ({pct}%)")
                sys.stdout.flush()

        # Include version file inside the zip
        zf.writestr(f"media/{VERSION_FILE}", version_content)

    # Also write version file to project root for cx_Freeze to pick up
    version_path = Path(VERSION_FILE)
    version_path.write_text(version_content, encoding="utf-8")
    print(f"\n  Media version: {total} files, {datetime.now():%Y-%m-%d %H:%M}")

    mb = OUTPUT.stat().st_size / (1024 * 1024)
    print(f"\n  Output: {OUTPUT} ({mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
