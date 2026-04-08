"""
Parse the Metro E-Catalog PDF into a staging SQLite database.

This parser stages Metro catalog entries as parts plus related references/images.
It supports both:
  - compact list/table pages
  - detail pages with fields like Replace, OE, Lester, and Note

Usage:
    python -m data_import.pdf_parsers.parse_metro_catalog <pdf_path> [options]

Options:
    --output       Output SQLite path
                   (default: data_import/staging_dbs/metro_catalog.db)
    --start-page   First 1-based page to parse
    --end-page     Last 1-based page to parse
    --limit-pages  Maximum number of pages to parse after start-page
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field

import fitz  # PyMuPDF


HEADER_Y_MAX = 95.0
FOOTER_Y_MIN = 760.0
IMAGE_MIN_WIDTH = 40.0
IMAGE_MIN_HEIGHT = 40.0
IMAGE_MAX_PAGE_SHARE = 0.60
COLUMN_CLUSTER_GAP = 90.0

METRO_NUMBER_RE = re.compile(
    r"(?<![A-Z0-9])(?P<number>\d{2}-(?=[0-9A-Z-]*\d)[0-9A-Z]{3,}(?:-[0-9A-Z]+)*\*?)(?![A-Z0-9])"
)
FIELD_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9/&().+# -]{1,40}):\s*(?P<value>.*)$")
PURE_NUMBER_LIST_RE = re.compile(r"^[0-9 ,./-]+$")
OEM_TOKEN_RE = re.compile(r"^(?=.*[A-Z])[A-Z0-9][A-Z0-9./-]{3,}$")
METRO_CATALOG_START_PAGE = 24

HEADER_SKIP_RE = re.compile(
    r"^(?:\d+\s+of\s+\d+|manufacturers? and supplier names|metro auto industrial|catalog cover|photo|metro#|lester|oem|description|amp|shaft|stator|rotor|od|length)$",
    re.IGNORECASE,
)


@dataclass
class TextLine:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    column_anchor: float = 0.0


@dataclass
class MetroEntry:
    metro_number: str
    page_number: int
    section_name: str
    category_name: str
    lines: list = field(default_factory=list)
    bbox: tuple = None
    part_name: str = ""
    description: str = ""
    manufacturer: str = ""
    notes: str = ""
    attributes: dict = field(default_factory=dict)
    references: list = field(default_factory=list)
    has_image: bool = False


def normalize_space(value):
    return re.sub(r"\s+", " ", (value or "")).strip()


def slugify(value):
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "")
    return value.strip("_") or "image"


def strip_bullet(text):
    return text.lstrip(" -*\u2022\u25aa\t").strip()


def merge_bbox(current, bbox):
    if current is None:
        return bbox
    return (
        min(current[0], bbox[0]),
        min(current[1], bbox[1]),
        max(current[2], bbox[2]),
        max(current[3], bbox[3]),
    )


def bbox_center(bbox):
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def looks_like_header_line(text):
    text = normalize_space(text)
    if not text:
        return True
    if HEADER_SKIP_RE.match(text):
        return True
    if text.isdigit() and len(text) <= 3:
        return True
    return False


def split_ref_values(text):
    values = []
    for piece in re.split(r"[;,]|\s{2,}", normalize_space(text)):
        piece = normalize_space(piece)
        if piece:
            values.append(piece)
    return values


def extract_text_lines(page):
    raw_lines = []
    text_dict = page.get_text("dict")
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = normalize_space("".join(span.get("text", "") for span in spans))
            if not text:
                continue
            x0, y0, x1, y1 = line["bbox"]
            raw_lines.append(TextLine(text=text, x0=x0, y0=y0, x1=x1, y1=y1))
    if not raw_lines:
        return []

    columns = []
    for line in sorted(raw_lines, key=lambda ln: (ln.x0, ln.y0)):
        for column in columns:
            if abs(line.x0 - column["anchor_x"]) <= COLUMN_CLUSTER_GAP:
                line.column_anchor = column["anchor_x"]
                column["lines"].append(line)
                column["anchor_x"] = min(column["anchor_x"], line.x0)
                break
        else:
            line.column_anchor = line.x0
            columns.append({"anchor_x": line.x0, "lines": [line]})

    ordered = []
    for column in sorted(columns, key=lambda col: col["anchor_x"]):
        ordered.extend(sorted(column["lines"], key=lambda ln: (ln.y0, ln.x0)))
    return ordered


def build_section_map(doc):
    section_map = {}
    toc = doc.get_toc(simple=True)
    anchors = [
        (level, normalize_space(title), page)
        for level, title, page in toc
        if page and page > 0
    ]
    current_major = ""
    current_minor = ""
    for page_num in range(1, doc.page_count + 1):
        for level, title, anchor_page in anchors:
            if anchor_page == page_num:
                if level <= 2:
                    current_major = title
                    current_minor = ""
                elif level == 3:
                    current_minor = title
        section_map[page_num] = {
            "section_name": current_major,
            "category_name": current_minor or current_major,
        }
    return section_map


def page_window(page_count, start_page=None, end_page=None, limit_pages=None):
    start_index = max(0, (start_page or 1) - 1)
    end_index = page_count - 1 if end_page is None else min(page_count - 1, end_page - 1)
    if limit_pages is not None:
        end_index = min(end_index, start_index + max(limit_pages, 0) - 1)
    if end_index < start_index:
        end_index = start_index - 1
    return start_index, end_index


def build_entries(page, section_info):
    entries = []
    current = None
    for line in extract_text_lines(page):
        if line.y0 < HEADER_Y_MAX or line.y0 > FOOTER_Y_MIN:
            continue
        if looks_like_header_line(line.text):
            continue

        match = METRO_NUMBER_RE.search(line.text)
        if match and (line.x0 - line.column_anchor) <= 20:
            metro_number = match.group("number").rstrip("*")
            if current:
                entries.append(current)
            current = MetroEntry(
                metro_number=metro_number,
                page_number=page.number + 1,
                section_name=section_info.get("section_name", ""),
                category_name=section_info.get("category_name", ""),
            )
        if current:
            current.lines.append(line)
            current.bbox = merge_bbox(current.bbox, (line.x0, line.y0, line.x1, line.y1))
    if current:
        entries.append(current)

    for entry in entries:
        parse_entry(entry)
    return entries


def add_reference(entry, ref_type, value, notes=""):
    value = normalize_space(value)
    notes = normalize_space(notes)
    if not value:
        return
    entry.references.append({
        "ref_type": ref_type[:30],
        "ref_value": value[:255],
        "notes": notes[:255],
    })


def parse_table_style(entry, content_lines):
    if not content_lines:
        entry.part_name = entry.metro_number
        return

    ref_consumed = set()
    if content_lines and PURE_NUMBER_LIST_RE.match(content_lines[0]):
        for ref in split_ref_values(content_lines[0]):
            add_reference(entry, "lester", ref)
        ref_consumed.add(0)

    if len(content_lines) > 1 and OEM_TOKEN_RE.match(content_lines[1]) and " " not in content_lines[1]:
        add_reference(entry, "oem", content_lines[1])
        ref_consumed.add(1)

    remaining = [line for idx, line in enumerate(content_lines) if idx not in ref_consumed]
    if remaining:
        entry.part_name = remaining[0][:255]
        if len(remaining) > 1:
            entry.description = "\n".join(remaining[1:]).strip()[:2000]
    else:
        entry.part_name = entry.metro_number

    if remaining:
        manufacturer_candidates = [line for line in remaining[:3] if line and not any(ch.isdigit() for ch in line)]
        if manufacturer_candidates:
            entry.manufacturer = manufacturer_candidates[0][:100]


def parse_detail_style(entry, content_lines):
    current_field = None
    field_values = defaultdict(list)
    free_lines = []

    for raw_line in content_lines:
        line = normalize_space(raw_line)
        if not line:
            continue
        match = FIELD_RE.match(line)
        if match:
            key = normalize_space(match.group("key")).lower()
            current_field = key
            value = normalize_space(match.group("value"))
            if value:
                field_values[key].append(value)
            continue

        if current_field:
            field_values[current_field].append(line)
        else:
            free_lines.append(line)

    if free_lines:
        entry.part_name = free_lines[0][:255]
        if len(free_lines) > 1:
            entry.description = "\n".join(free_lines[1:]).strip()[:2000]
    else:
        entry.part_name = entry.metro_number

    if "for" in field_values:
        values = [normalize_space(v) for v in field_values["for"] if normalize_space(v)]
        if values:
            entry.attributes["for"] = " ".join(values)
    if "dim" in field_values:
        entry.attributes["dim"] = " | ".join(field_values["dim"])[:500]
    if "dimensions" in field_values:
        entry.attributes["dimensions"] = " | ".join(field_values["dimensions"])[:500]
    if "note" in field_values:
        entry.notes = "\n".join(field_values["note"]).strip()[:2000]

    for key in ("replace", "oe", "lester"):
        for value in field_values.get(key, []):
            for ref in split_ref_values(value):
                add_reference(entry, key, ref)

    # Preserve any other keyed values as structured attributes.
    for key, values in field_values.items():
        if key in {"replace", "oe", "lester", "note", "for", "dim", "dimensions"}:
            continue
        text = " | ".join(values).strip()
        if text:
            entry.attributes[key[:100]] = text[:500]


def parse_entry(entry):
    text_lines = [normalize_space(line.text) for line in entry.lines if normalize_space(line.text)]
    if not text_lines:
        entry.part_name = entry.metro_number
        return

    first_line = normalize_space(METRO_NUMBER_RE.sub("", text_lines[0], count=1)).strip(" -:")
    content_lines = [strip_bullet(line) for line in text_lines[1:] if strip_bullet(line)]
    if first_line:
        content_lines.insert(0, first_line)

    has_fields = any(FIELD_RE.match(line) for line in content_lines)
    if has_fields:
        parse_detail_style(entry, content_lines)
    else:
        parse_table_style(entry, content_lines)

    if not entry.part_name:
        entry.part_name = entry.metro_number


def extract_images(doc, page, entries, image_dir):
    if not entries:
        return []

    page_area = page.rect.width * page.rect.height
    results = []
    seen_rects = set()
    xref_cache = {}
    image_index_by_part = defaultdict(int)

    for image in page.get_images(full=True):
        xref = image[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            continue

        if xref not in xref_cache:
            try:
                xref_cache[xref] = doc.extract_image(xref)
            except Exception:
                xref_cache[xref] = None
        image_info = xref_cache[xref]
        if not image_info:
            continue

        image_bytes = image_info.get("image")
        if not image_bytes:
            continue
        ext = (image_info.get("ext") or "png").lower()

        for rect in rects:
            rect_key = (xref, round(rect.x0, 1), round(rect.y0, 1), round(rect.x1, 1), round(rect.y1, 1))
            if rect_key in seen_rects:
                continue
            seen_rects.add(rect_key)

            if rect.width < IMAGE_MIN_WIDTH or rect.height < IMAGE_MIN_HEIGHT:
                continue
            if rect.y0 < HEADER_Y_MAX or rect.y1 > FOOTER_Y_MIN:
                continue
            if (rect.width * rect.height) / page_area > IMAGE_MAX_PAGE_SHARE:
                continue

            rect_center = ((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0)
            best_entry = None
            best_distance = None
            for entry in entries:
                entry_center = bbox_center(entry.bbox)
                distance = abs(rect_center[0] - entry_center[0]) + abs(rect_center[1] - entry_center[1])
                if best_distance is None or distance < best_distance:
                    best_entry = entry
                    best_distance = distance
            if not best_entry:
                continue

            image_index_by_part[best_entry.metro_number] += 1
            image_index = image_index_by_part[best_entry.metro_number]
            file_name = f"{slugify(best_entry.metro_number)}_p{page.number + 1:04d}_{image_index}.{ext}"
            image_path = os.path.join(image_dir, file_name)
            with open(image_path, "wb") as handle:
                handle.write(image_bytes)

            best_entry.has_image = True
            results.append({
                "metro_number": best_entry.metro_number,
                "page_number": page.number + 1,
                "image_index": image_index,
                "image_path": os.path.abspath(image_path),
                "width": image_info.get("width") or int(rect.width),
                "height": image_info.get("height") or int(rect.height),
            })
    return results


def create_staging_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metro_catalog_parts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metro_number TEXT NOT NULL,
            part_name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            manufacturer TEXT NOT NULL DEFAULT '',
            section_name TEXT NOT NULL DEFAULT '',
            category_name TEXT NOT NULL DEFAULT '',
            page_number INTEGER NOT NULL DEFAULT 0,
            source_pdf TEXT NOT NULL DEFAULT '',
            attributes_json TEXT NOT NULL DEFAULT '{}',
            notes TEXT NOT NULL DEFAULT '',
            raw_text TEXT NOT NULL DEFAULT '',
            has_image INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metro_catalog_refs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metro_number TEXT NOT NULL,
            ref_type TEXT NOT NULL DEFAULT '',
            ref_value TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metro_catalog_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metro_number TEXT NOT NULL,
            page_number INTEGER NOT NULL DEFAULT 0,
            image_index INTEGER NOT NULL DEFAULT 0,
            image_path TEXT NOT NULL DEFAULT '',
            width INTEGER NOT NULL DEFAULT 0,
            height INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_metro_parts_number ON metro_catalog_parts(metro_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_metro_parts_category ON metro_catalog_parts(category_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_metro_refs_number ON metro_catalog_refs(metro_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_metro_refs_value ON metro_catalog_refs(ref_value)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_metro_images_number ON metro_catalog_images(metro_number)")
    conn.commit()
    return conn


def main():
    parser = argparse.ArgumentParser(description="Parse Metro catalog PDF into staging DB")
    parser.add_argument("pdf_path", help="Path to the Metro catalog PDF")
    parser.add_argument("--output", help="Output SQLite path")
    parser.add_argument("--start-page", type=int, default=METRO_CATALOG_START_PAGE, help="First 1-based page to parse")
    parser.add_argument("--end-page", type=int, help="Last 1-based page to parse")
    parser.add_argument("--limit-pages", type=int, help="Maximum number of pages to parse")
    args = parser.parse_args()

    pdf_path = os.path.abspath(args.pdf_path)
    if not os.path.exists(pdf_path):
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        db_path = os.path.abspath(args.output)
    else:
        staging_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "staging_dbs"))
        os.makedirs(staging_dir, exist_ok=True)
        db_path = os.path.join(staging_dir, "metro_catalog.db")

    image_dir = os.path.splitext(db_path)[0] + "_images"
    if os.path.exists(db_path):
        os.remove(db_path)
    if os.path.exists(image_dir):
        shutil.rmtree(image_dir)
    os.makedirs(image_dir, exist_ok=True)

    print(f"PDF:    {pdf_path}")
    print(f"Output: {db_path}")
    print(f"Images: {image_dir}")
    print()

    doc = fitz.open(pdf_path)
    section_map = build_section_map(doc)
    start_index, end_index = page_window(
        doc.page_count,
        start_page=args.start_page,
        end_page=args.end_page,
        limit_pages=args.limit_pages,
    )
    total_pages = max(0, end_index - start_index + 1)
    print(f"Pages:  {doc.page_count:,} total, parsing {total_pages:,}")
    print()

    conn = create_staging_db(db_path)
    part_batch = []
    ref_batch = []
    image_batch = []
    totals = defaultdict(int)
    start_time = time.time()
    BATCH_SIZE = 1000

    def flush():
        if part_batch:
            conn.executemany(
                """
                INSERT INTO metro_catalog_parts
                (metro_number, part_name, description, manufacturer, section_name,
                 category_name, page_number, source_pdf, attributes_json, notes,
                 raw_text, has_image)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                part_batch,
            )
            totals["parts"] += len(part_batch)
            part_batch.clear()
        if ref_batch:
            conn.executemany(
                """
                INSERT INTO metro_catalog_refs
                (metro_number, ref_type, ref_value, notes)
                VALUES (?, ?, ?, ?)
                """,
                ref_batch,
            )
            totals["refs"] += len(ref_batch)
            ref_batch.clear()
        if image_batch:
            conn.executemany(
                """
                INSERT INTO metro_catalog_images
                (metro_number, page_number, image_index, image_path, width, height)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                image_batch,
            )
            totals["images"] += len(image_batch)
            image_batch.clear()
        conn.commit()

    try:
        for page_idx in range(start_index, end_index + 1):
            page = doc[page_idx]
            page_num = page_idx + 1
            section_info = section_map.get(page_num, {"section_name": "", "category_name": ""})
            entries = build_entries(page, section_info)
            if not entries:
                totals["empty_pages"] += 1
                continue

            image_rows = extract_images(doc, page, entries, image_dir)
            for entry in entries:
                raw_text = "\n".join(normalize_space(line.text) for line in entry.lines if normalize_space(line.text))
                part_batch.append(
                    (
                        entry.metro_number,
                        entry.part_name[:255],
                        entry.description[:2000],
                        entry.manufacturer[:100],
                        entry.section_name[:150],
                        entry.category_name[:150],
                        entry.page_number,
                        os.path.basename(pdf_path),
                        json.dumps(entry.attributes, sort_keys=True),
                        entry.notes[:2000],
                        raw_text[:4000],
                        1 if entry.has_image else 0,
                    )
                )
                for ref in entry.references:
                    ref_batch.append(
                        (
                            entry.metro_number,
                            ref["ref_type"][:30],
                            ref["ref_value"][:255],
                            ref["notes"][:255],
                        )
                    )
            for row in image_rows:
                image_batch.append(
                    (
                        row["metro_number"],
                        row["page_number"],
                        row["image_index"],
                        row["image_path"],
                        row["width"],
                        row["height"],
                    )
                )

            if len(part_batch) >= BATCH_SIZE or len(image_batch) >= BATCH_SIZE:
                flush()

            processed = page_idx - start_index + 1
            if processed % 50 == 0 or processed == total_pages:
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                print(
                    f"  Page {processed:>4,}/{total_pages:,}  |  "
                    f"parts: {totals['parts'] + len(part_batch):>7,}  "
                    f"refs: {totals['refs'] + len(ref_batch):>7,}  "
                    f"images: {totals['images'] + len(image_batch):>6,}  "
                    f"| {rate:.1f} pages/sec"
                )

        flush()
    finally:
        doc.close()
        conn.close()

    elapsed = time.time() - start_time
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Pages parsed:         {total_pages:>10,}")
    print(f"  Pages without parts:  {totals['empty_pages']:>10,}")
    print(f"  Part rows staged:     {totals['parts']:>10,}")
    print(f"  Reference rows:       {totals['refs']:>10,}")
    print(f"  Image rows:           {totals['images']:>10,}")
    print(f"  Time elapsed:         {elapsed:>10.1f}s")
    print()
    print(f"Staging DB: {db_path}")
    print(f"Image dir:   {image_dir}")


if __name__ == "__main__":
    main()
