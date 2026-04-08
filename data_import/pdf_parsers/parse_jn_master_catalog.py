"""
Parse the J&N Master Catalog PDF into a staging SQLite database.

This parser handles mixed catalog layouts by:
  - classifying pages as component, unit, misc, or other
  - grouping nearby text into J&N catalog entries
  - normalizing descriptive/spec/reference lines
  - extracting embedded images and linking them to the nearest part entry

Usage:
    python -m data_import.pdf_parsers.parse_jn_master_catalog <pdf_path> [options]

Options:
    --output       Output SQLite path
                   (default: data_import/staging_dbs/jn_master_catalog.db)
    --start-page   First 1-based page to parse
    --end-page     Last 1-based page to parse
    --limit-pages  Maximum number of pages to parse after start-page
"""

import argparse
import hashlib
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


HEADER_Y_MAX = 85.0
FOOTER_Y_MIN = 760.0
COLUMN_CLUSTER_GAP = 90.0
IMAGE_MIN_WIDTH = 50.0
IMAGE_MIN_HEIGHT = 50.0
IMAGE_MAX_PAGE_SHARE = 0.70

JN_NUMBER_RE = re.compile(r"(?<![A-Z0-9])(?P<number>\d{3}-[0-9A-Z]{4,8}\*?)(?![A-Z0-9])")
SPEC_LINE_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9/&().'\- ]{1,40}):\s*(?P<value>.+)$")
TOC_LINE_RE = re.compile(r"^(?P<label>.+?)\.{2,}\s*(?P<page>\d{1,4})$")
REF_MFR_RE = re.compile(
    r"^(?P<manufacturer>[A-Za-z][A-Za-z0-9/&().'\- ]{1,40}):\s*(?P<numbers>.+)$"
)
REF_INLINE_RE = re.compile(
    r"^(?P<manufacturer>[A-Za-z][A-Za-z0-9/&().'\- ]{1,40})\s+(?P<number>[A-Z0-9][A-Z0-9\-./ ]*[0-9][A-Z0-9\-./ ]*)$"
)

TOC_UNIT_KEYWORDS = (
    "units",
    "starters",
    "alternators",
    "generators",
    "motors",
)
TOC_MISC_KEYWORDS = (
    "tools",
    "shop supplies",
    "supplies",
    "merchandise",
)
TOC_COMPONENT_KEYWORDS = (
    "components",
    "bushings",
    "brushes",
    "armatures",
    "regulators",
    "solenoids",
    "drives",
    "switches",
    "bearings",
    "repair",
)

UNIT_HEADING_HINTS = (
    "starter",
    "alternator",
    "generator",
    "motor",
    "unit",
)
MISC_HEADING_HINTS = (
    "tool",
    "shop",
    "supply",
    "merchandise",
)

REF_TYPE_HEADERS = {
    "substitutes": "substitute",
    "substitute": "substitute",
    "references": "reference",
    "reference": "reference",
    "interchanges": "reference",
    "interchange": "reference",
    "superseded by": "superseded_by",
    "superseded from": "superseded_from",
    "replaces": "superseded_from",
    "replacement": "superseded_by",
}

SPEC_KEY_HINTS = {
    "amps",
    "amp",
    "amperage",
    "voltage",
    "rotation",
    "teeth",
    "shaft",
    "od",
    "id",
    "length",
    "width",
    "height",
    "mount",
    "pulley",
    "groove",
    "clock",
    "rpm",
    "frame",
    "power",
    "kw",
    "hp",
    "weight",
    "bearing",
    "bushing",
    "solenoid",
    "regulator",
    "brush",
}


@dataclass
class TextLine:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class CatalogEntry:
    jn_number: str
    entry_type: str
    page_number: int
    heading: str
    category_code: str
    category_name: str
    lines: list = field(default_factory=list)
    bbox: tuple = None
    part_name: str = ""
    description: str = ""
    oem_family: str = ""
    specifications: dict = field(default_factory=dict)
    references: list = field(default_factory=list)
    has_image: bool = False


def normalize_space(value):
    return re.sub(r"\s+", " ", (value or "")).strip()


def slugify(value):
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "")
    return value.strip("_") or "image"


def strip_bullets(text):
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


def extract_text_lines(page):
    """Return text lines ordered by column, then by y position."""
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
                column["lines"].append(line)
                column["anchor_x"] = min(column["anchor_x"], line.x0)
                break
        else:
            columns.append({"anchor_x": line.x0, "lines": [line]})

    ordered = []
    for column in sorted(columns, key=lambda col: col["anchor_x"]):
        ordered.extend(sorted(column["lines"], key=lambda ln: (ln.y0, ln.x0)))
    return ordered


def classify_toc_label(label):
    lowered = normalize_space(label).lower()
    if any(keyword in lowered for keyword in TOC_MISC_KEYWORDS):
        return "misc"
    if any(keyword in lowered for keyword in TOC_UNIT_KEYWORDS):
        return "unit"
    if any(keyword in lowered for keyword in TOC_COMPONENT_KEYWORDS):
        return "component"
    return None


def extract_toc_ranges(doc, max_pages=30):
    """Best-effort TOC ranges from dotted TOC lines in the front matter."""
    anchors = []
    for page_idx in range(min(doc.page_count, max_pages)):
        page = doc[page_idx]
        for raw_line in page.get_text().splitlines():
            line = normalize_space(raw_line)
            if not line:
                continue
            match = TOC_LINE_RE.match(line)
            if not match:
                continue
            label = match.group("label")
            section = classify_toc_label(label)
            if not section:
                continue
            page_number = int(match.group("page"))
            anchors.append((page_number, section, label))

    anchors = sorted(set(anchors), key=lambda item: item[0])
    ranges = []
    for idx, (start_page, section, label) in enumerate(anchors):
        end_page = doc.page_count
        if idx + 1 < len(anchors):
            end_page = max(start_page, anchors[idx + 1][0] - 1)
        ranges.append({
            "start_page": start_page,
            "end_page": end_page,
            "section": section,
            "label": label,
        })
    return ranges


def page_type_from_toc(page_number, toc_ranges):
    for item in toc_ranges:
        if item["start_page"] <= page_number <= item["end_page"]:
            return item["section"]
    return None


def extract_page_heading(lines):
    heading_lines = []
    for line in lines:
        if line.y0 > 160:
            break
        if line.y0 < HEADER_Y_MAX:
            continue
        if JN_NUMBER_RE.search(line.text):
            break
        text = strip_bullets(line.text)
        if len(text) > 90:
            continue
        heading_lines.append(text)
        if len(heading_lines) >= 3:
            break
    return normalize_space(" | ".join(heading_lines[:2]))


def classify_page(page, toc_ranges):
    lines = extract_text_lines(page)
    heading = extract_page_heading(lines)
    page_number = page.number + 1
    toc_guess = page_type_from_toc(page_number, toc_ranges)

    matches = []
    for line in lines:
        if line.y0 < HEADER_Y_MAX or line.y0 > FOOTER_Y_MIN:
            continue
        match = JN_NUMBER_RE.search(line.text)
        if match:
            matches.append(match.group("number").rstrip("*"))

    if not matches:
        if toc_guess:
            return toc_guess, heading
        heading_lower = heading.lower()
        if any(hint in heading_lower for hint in MISC_HEADING_HINTS):
            return "misc", heading
        return "other", heading

    unit_count = sum(1 for number in matches if number.startswith("4"))
    component_count = len(matches) - unit_count

    if toc_guess == "misc":
        return "misc", heading
    if toc_guess == "unit":
        return "unit", heading
    if toc_guess == "component":
        return "component", heading

    heading_lower = heading.lower()
    if unit_count and unit_count >= component_count:
        return "unit", heading
    if any(hint in heading_lower for hint in UNIT_HEADING_HINTS) and unit_count:
        return "unit", heading
    if any(hint in heading_lower for hint in MISC_HEADING_HINTS):
        return "misc", heading
    return "component", heading


def derive_category_meta(heading, jn_number):
    heading_clean = normalize_space(heading.replace("|", " "))
    if heading_clean:
        match = re.match(r"^(?P<code>\d{2,4})\s*[-: ]\s*(?P<name>.+)$", heading_clean)
        if match:
            return match.group("code"), normalize_space(match.group("name"))
        return jn_number.split("-", 1)[0], heading_clean[:100]
    return jn_number.split("-", 1)[0], ""


def split_reference_numbers(text):
    text = normalize_space(text)
    if not text:
        return []
    chunks = []
    for piece in re.split(r"[;,]|\s{2,}", text):
        piece = normalize_space(piece)
        if piece:
            chunks.append(piece)
    if not chunks:
        return [text]
    return chunks


def parse_reference_line(text, current_type):
    clean = strip_bullets(text)
    if not clean:
        return []

    match = REF_MFR_RE.match(clean)
    if match:
        manufacturer = normalize_space(match.group("manufacturer"))
        numbers = split_reference_numbers(match.group("numbers"))
        if any(any(ch.isdigit() for ch in number) for number in numbers):
            return [
                {
                    "ref_type": current_type,
                    "manufacturer": manufacturer,
                    "ref_number": number[:100],
                    "notes": "",
                }
                for number in numbers
            ]

    match = REF_INLINE_RE.match(clean)
    if match:
        number = normalize_space(match.group("number"))
        if any(ch.isdigit() for ch in number):
            return [{
                "ref_type": current_type,
                "manufacturer": normalize_space(match.group("manufacturer")),
                "ref_number": number[:100],
                "notes": "",
            }]

    if current_type != "reference" and any(ch.isdigit() for ch in clean):
        return [{
            "ref_type": current_type,
            "manufacturer": "",
            "ref_number": clean[:100],
            "notes": "",
        }]

    if JN_NUMBER_RE.fullmatch(clean):
        return [{
            "ref_type": current_type,
            "manufacturer": "",
            "ref_number": clean[:100],
            "notes": "",
        }]

    return []


def looks_like_spec(key, value):
    key_norm = normalize_space(key).lower()
    value_norm = normalize_space(value)
    if key_norm in SPEC_KEY_HINTS:
        return True
    if any(token in key_norm for token in SPEC_KEY_HINTS):
        return True
    return any(ch.isdigit() for ch in value_norm)


def build_entry_records(page, page_type, heading):
    lines = extract_text_lines(page)
    entries = []
    current = None

    for line in lines:
        if line.y0 < HEADER_Y_MAX or line.y0 > FOOTER_Y_MIN:
            continue

        match = JN_NUMBER_RE.search(line.text)
        if match:
            jn_number = match.group("number").rstrip("*")
            if current:
                entries.append(current)
            category_code, category_name = derive_category_meta(heading, jn_number)
            current = CatalogEntry(
                jn_number=jn_number,
                entry_type=page_type,
                page_number=page.number + 1,
                heading=heading,
                category_code=category_code,
                category_name=category_name,
            )

        if current:
            current.lines.append(line)
            current.bbox = merge_bbox(current.bbox, (line.x0, line.y0, line.x1, line.y1))

    if current:
        entries.append(current)

    for entry in entries:
        parse_entry_text(entry)
    return entries


def parse_entry_text(entry):
    text_lines = [normalize_space(line.text) for line in entry.lines if normalize_space(line.text)]
    if not text_lines:
        return

    first_line = text_lines[0]
    remainder = normalize_space(JN_NUMBER_RE.sub("", first_line, count=1)).strip(" -:")
    descriptive_lines = []
    if remainder:
        entry.part_name = remainder[:255]

    current_ref_type = "reference"
    for line in text_lines[1:]:
        lowered = line.rstrip(":").strip().lower()
        if lowered in REF_TYPE_HEADERS:
            current_ref_type = REF_TYPE_HEADERS[lowered]
            continue

        spec_match = SPEC_LINE_RE.match(line)
        if spec_match and looks_like_spec(spec_match.group("key"), spec_match.group("value")):
            key = normalize_space(spec_match.group("key"))[:100]
            value = normalize_space(spec_match.group("value"))[:255]
            if key and value and key not in entry.specifications:
                entry.specifications[key] = value
            continue

        ref_rows = parse_reference_line(line, current_ref_type)
        if ref_rows:
            entry.references.extend(ref_rows)
            continue

        clean = strip_bullets(line)
        if clean:
            descriptive_lines.append(clean)

    if not entry.part_name and descriptive_lines:
        entry.part_name = descriptive_lines.pop(0)[:255]
    if not entry.part_name:
        entry.part_name = entry.jn_number

    entry.description = "\n".join(descriptive_lines).strip()


def extract_entry_images(doc, page, entries, image_dir):
    """Link page images to the nearest parsed part entry."""
    if not entries:
        return []

    page_area = page.rect.width * page.rect.height
    page_number = page.number + 1
    page_results = []
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
        image_hash = hashlib.md5(image_bytes).hexdigest()
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
                if entry.entry_type == "unit":
                    continue
                entry_center = bbox_center(entry.bbox)
                distance = abs(rect_center[0] - entry_center[0]) + abs(rect_center[1] - entry_center[1])
                if best_distance is None or distance < best_distance:
                    best_entry = entry
                    best_distance = distance
            if best_entry is None:
                continue

            image_index_by_part[best_entry.jn_number] += 1
            image_index = image_index_by_part[best_entry.jn_number]
            file_name = (
                f"{slugify(best_entry.jn_number)}_p{page_number:04d}_{image_index}_{image_hash[:8]}.{ext}"
            )
            image_path = os.path.join(image_dir, file_name)
            with open(image_path, "wb") as handle:
                handle.write(image_bytes)

            best_entry.has_image = True
            page_results.append({
                "jn_number": best_entry.jn_number,
                "page_number": page_number,
                "image_index": image_index,
                "image_path": os.path.abspath(image_path),
                "width": image_info.get("width") or int(rect.width),
                "height": image_info.get("height") or int(rect.height),
            })
    return page_results


def create_staging_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jn_catalog_parts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            jn_number TEXT NOT NULL,
            part_name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            category_code TEXT NOT NULL DEFAULT '',
            category_name TEXT NOT NULL DEFAULT '',
            oem_family TEXT NOT NULL DEFAULT '',
            page_number INTEGER NOT NULL DEFAULT 0,
            source_pdf TEXT NOT NULL DEFAULT '',
            specifications_json TEXT NOT NULL DEFAULT '{}',
            has_image INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jn_catalog_part_refs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            jn_number TEXT NOT NULL,
            ref_type TEXT NOT NULL DEFAULT '',
            manufacturer TEXT NOT NULL DEFAULT '',
            ref_number TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jn_catalog_part_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            jn_number TEXT NOT NULL,
            page_number INTEGER NOT NULL DEFAULT 0,
            image_index INTEGER NOT NULL DEFAULT 0,
            image_path TEXT NOT NULL DEFAULT '',
            width INTEGER NOT NULL DEFAULT 0,
            height INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jn_catalog_units (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            jn_number TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            category_code TEXT NOT NULL DEFAULT '',
            category_name TEXT NOT NULL DEFAULT '',
            page_number INTEGER NOT NULL DEFAULT 0,
            source_pdf TEXT NOT NULL DEFAULT '',
            specifications_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jn_catalog_unit_refs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            jn_number TEXT NOT NULL,
            ref_type TEXT NOT NULL DEFAULT '',
            manufacturer TEXT NOT NULL DEFAULT '',
            ref_number TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT ''
        )
        """
    )

    conn.execute("CREATE INDEX IF NOT EXISTS idx_jn_catalog_parts_jn ON jn_catalog_parts(jn_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jn_catalog_part_refs_jn ON jn_catalog_part_refs(jn_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jn_catalog_part_images_jn ON jn_catalog_part_images(jn_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jn_catalog_units_jn ON jn_catalog_units(jn_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jn_catalog_unit_refs_jn ON jn_catalog_unit_refs(jn_number)")
    conn.commit()
    return conn


def resolve_page_window(page_count, start_page=None, end_page=None, limit_pages=None):
    start_index = max(0, (start_page or 1) - 1)
    end_index = page_count - 1 if end_page is None else min(page_count - 1, end_page - 1)
    if limit_pages is not None:
        end_index = min(end_index, start_index + max(0, limit_pages) - 1)
    if end_index < start_index:
        end_index = start_index - 1
    return start_index, end_index


def main():
    parser = argparse.ArgumentParser(description="Parse J&N Master Catalog PDF into a staging DB")
    parser.add_argument("pdf_path", help="Path to the master catalog PDF")
    parser.add_argument("--output", help="Output SQLite path")
    parser.add_argument("--start-page", type=int, default=1, help="First 1-based page to parse")
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
        db_path = os.path.join(staging_dir, "jn_master_catalog.db")

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
    start_index, end_index = resolve_page_window(
        doc.page_count,
        start_page=args.start_page,
        end_page=args.end_page,
        limit_pages=args.limit_pages,
    )
    total_pages = max(0, end_index - start_index + 1)
    toc_ranges = extract_toc_ranges(doc)

    print(f"Pages:  {doc.page_count:,} total, parsing {total_pages:,}")
    if toc_ranges:
        print(f"TOC:    {len(toc_ranges):,} classifier ranges detected")
    print()

    conn = create_staging_db(db_path)

    part_batch = []
    part_ref_batch = []
    part_image_batch = []
    unit_batch = []
    unit_ref_batch = []
    BATCH_SIZE = 1000

    totals = defaultdict(int)
    start_time = time.time()

    def flush():
        if part_batch:
            conn.executemany(
                """
                INSERT INTO jn_catalog_parts
                (jn_number, part_name, description, category_code, category_name,
                 oem_family, page_number, source_pdf, specifications_json, has_image)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                part_batch,
            )
            totals["parts"] += len(part_batch)
            part_batch.clear()
        if part_ref_batch:
            conn.executemany(
                """
                INSERT INTO jn_catalog_part_refs
                (jn_number, ref_type, manufacturer, ref_number, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                part_ref_batch,
            )
            totals["part_refs"] += len(part_ref_batch)
            part_ref_batch.clear()
        if part_image_batch:
            conn.executemany(
                """
                INSERT INTO jn_catalog_part_images
                (jn_number, page_number, image_index, image_path, width, height)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                part_image_batch,
            )
            totals["part_images"] += len(part_image_batch)
            part_image_batch.clear()
        if unit_batch:
            conn.executemany(
                """
                INSERT INTO jn_catalog_units
                (jn_number, description, category_code, category_name,
                 page_number, source_pdf, specifications_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                unit_batch,
            )
            totals["units"] += len(unit_batch)
            unit_batch.clear()
        if unit_ref_batch:
            conn.executemany(
                """
                INSERT INTO jn_catalog_unit_refs
                (jn_number, ref_type, manufacturer, ref_number, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                unit_ref_batch,
            )
            totals["unit_refs"] += len(unit_ref_batch)
            unit_ref_batch.clear()
        conn.commit()

    try:
        for page_idx in range(start_index, end_index + 1):
            page = doc[page_idx]
            page_type, heading = classify_page(page, toc_ranges)
            totals[f"pages_{page_type}"] += 1

            if page_type == "other":
                continue

            entries = build_entry_records(page, page_type, heading)
            if not entries:
                continue

            image_rows = extract_entry_images(doc, page, entries, image_dir)

            for entry in entries:
                if entry.entry_type == "unit":
                    unit_batch.append(
                        (
                            entry.jn_number,
                            (entry.description or entry.part_name or "")[:2000],
                            entry.category_code[:50],
                            entry.category_name[:100],
                            entry.page_number,
                            os.path.basename(pdf_path),
                            json.dumps(entry.specifications, sort_keys=True),
                        )
                    )
                    for ref in entry.references:
                        unit_ref_batch.append(
                            (
                                entry.jn_number,
                                ref["ref_type"][:30],
                                ref["manufacturer"][:100],
                                ref["ref_number"][:100],
                                ref["notes"][:255],
                            )
                        )
                else:
                    part_batch.append(
                        (
                            entry.jn_number,
                            entry.part_name[:255],
                            entry.description[:2000],
                            entry.category_code[:50],
                            entry.category_name[:100],
                            entry.oem_family[:100],
                            entry.page_number,
                            os.path.basename(pdf_path),
                            json.dumps(entry.specifications, sort_keys=True),
                            1 if entry.has_image else 0,
                        )
                    )
                    for ref in entry.references:
                        part_ref_batch.append(
                            (
                                entry.jn_number,
                                ref["ref_type"][:30],
                                ref["manufacturer"][:100],
                                ref["ref_number"][:100],
                                ref["notes"][:255],
                            )
                        )

            for image_row in image_rows:
                part_image_batch.append(
                    (
                        image_row["jn_number"],
                        image_row["page_number"],
                        image_row["image_index"],
                        image_row["image_path"],
                        image_row["width"],
                        image_row["height"],
                    )
                )

            if (
                len(part_batch) >= BATCH_SIZE
                or len(unit_batch) >= BATCH_SIZE
                or len(part_image_batch) >= BATCH_SIZE
            ):
                flush()

            processed_pages = page_idx - start_index + 1
            if processed_pages % 50 == 0 or processed_pages == total_pages:
                elapsed = time.time() - start_time
                rate = processed_pages / elapsed if elapsed > 0 else 0
                print(
                    f"  Page {processed_pages:>4,}/{total_pages:,}  |  "
                    f"parts: {totals['parts'] + len(part_batch):>6,}  "
                    f"units: {totals['units'] + len(unit_batch):>6,}  "
                    f"images: {totals['part_images'] + len(part_image_batch):>6,}  "
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
    print(f"  Component/misc pages: {totals['pages_component'] + totals['pages_misc']:>10,}")
    print(f"  Unit pages:           {totals['pages_unit']:>10,}")
    print(f"  Skipped pages:        {totals['pages_other']:>10,}")
    print(f"  Part rows staged:     {totals['parts']:>10,}")
    print(f"  Part refs staged:     {totals['part_refs']:>10,}")
    print(f"  Part images staged:   {totals['part_images']:>10,}")
    print(f"  Unit rows staged:     {totals['units']:>10,}")
    print(f"  Unit refs staged:     {totals['unit_refs']:>10,}")
    print(f"  Time elapsed:         {elapsed:>10.1f}s")
    print()
    print(f"Staging DB: {db_path}")
    print(f"Image dir:   {image_dir}")


if __name__ == "__main__":
    main()
