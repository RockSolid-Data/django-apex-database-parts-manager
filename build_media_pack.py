"""Compress the media/ folder into dist/ApexDatabase_Media.zip."""

import os
import sys
import zipfile
from pathlib import Path

APP_NAME = "ApexDatabase"
MEDIA_DIR = Path("media")
OUTPUT = Path("dist") / f"{APP_NAME}_Media.zip"


def main():
    if not MEDIA_DIR.is_dir():
        print("[ERROR] media/ folder not found!")
        return 1

    OUTPUT.parent.mkdir(exist_ok=True)

    files = [
        Path(root) / f
        for root, _, filenames in os.walk(MEDIA_DIR)
        for f in filenames
        if not f.startswith(".")
    ]
    total = len(files)
    print(f"  Found {total:,} files to compress...")

    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for i, fpath in enumerate(files, 1):
            zf.write(fpath, fpath)
            if i % 100 == 0 or i == total:
                pct = i * 100 // total
                sys.stdout.write(f"\r  {i:,}/{total:,} ({pct}%)")
                sys.stdout.flush()

    mb = OUTPUT.stat().st_size / (1024 * 1024)
    print(f"\n\n  Output: {OUTPUT} ({mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
