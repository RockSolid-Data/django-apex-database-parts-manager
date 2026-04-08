"""
Parse the Transpo 2015 catalog PDF into a staging SQLite database.

This parser handles two distinct sections in the PDF:
  - detail catalog pages with product attributes, refs, and images
  - compact cross-reference pages in the back of the catalog

Usage:
    python -m data_import.pdf_parsers.parse_transpo_catalog <pdf_path> [options]

Options:
    --output       Output SQLite path
                   (default: data_import/staging_dbs/transpo_catalog.db)
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


HEADER_Y_MAX = 90.0
FOOTER_Y_MIN = 760.0
IMAGE_MIN_WIDTH = 50.0
IMAGE_MIN_HEIGHT = 50.0
IMAGE_MAX_PAGE_SHARE = 0.55
COLUMN_CLUSTER_GAP = 90.0

DETAIL_START_PAGE = 5
UNIT_TO_TRANSPO_START_PAGE = 510
OE_TO_TRANSPO_START_PAGE = 1179
TRANSPO_TO_PAGE_START_PAGE = 1235

FAMILY_CODES = ("REG", "REC", "DIO", "DTR", "IMO")
FIELD_LINE_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9/&().# -]{1,40}):\s*(?P<value>.+)$")
TRANSPO_NUMBER_RE = re.compile(r"^(?=.*[A-Z])(?=.*\d)[A-Z0-9-]{3,20}$")
REF_VALUE_RE = re.compile(r"^(?=.*\d)[A-Z0-9./-]{2,}$")
UPPER_HEADER_RE = re.compile(r"^[A-Z][A-Z0-9 /&().-]{1,60}$")
PAGE_FOOTER_RE = re.compile(r"^\d+$")
SKIP_LINES = {
    "Buyers Guide",
}


@dataclass
class TextLine:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    column_anchor: float = 0.0


@dataclass
class DetailEntry:
    transpo_number: str
    page_number: int
    section_name: str
    manufacturer: str = ""
    part_name: str = ""
    description: str = ""
    features_text: str = ""
    attributes: dict = field(default_factory=dict)
    notes: str = ""
    raw_text: str = ""
    refs: list = field(default_factory=list)
    bbox: tuple = None
    has_image: bool = False


def normalize_space(value):
    return re.sub(r"\s+", " ", (value or "")).strip()


def slugify(value):
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "")
    return value.strip("_") or "image"


def is_all_caps_label(text):
    text = normalize_space(text)
    return bool(text) and bool(UPPER_HEADER_RE.match(text)) and not any(ch.isdigit() for ch in text)


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


def page_window(page_count, start_page=None, end_page=None, limit_pages=None):
    start_index = max(0, (start_page or 1) - 1)
    end_index = page_count - 1 if end_page is None else min(page_count - 1, end_page - 1)
    if limit_pages is not None:
        end_index = min(end_index, start_index + max(limit_pages, 0) - 1)
    if end_index < start_index:
        end_index = start_index - 1
    return start_index, end_index


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


def clean_page_lines(page):
    lines = []
    for line in extract_text_lines(page):
        if line.y0 < HEADER_Y_MAX or line.y0 > FOOTER_Y_MIN:
            continue
        text = normalize_space(line.text)
        if not text or text in SKIP_LINES:
            continue
        if text.startswith("* For additional product and unit OE numbers"):
            continue
        if text == "TABLE OF CONTENTS":
            continue
        lines.append(TextLine(text=text, x0=line.x0, y0=line.y0, x1=line.x1, y1=line.y1, column_anchor=line.column_anchor))
    return lines


def extract_detail_section_name(lines):
    footer_candidates = []
    for line in lines[-12:]:
        text = line.text
        if text in {"Buyers Guide", "TABLE OF CONTENTS"}:
            continue
        if PAGE_FOOTER_RE.match(text):
            continue
        if is_all_caps_label(text):
            footer_candidates.append(text)
    for candidate in reversed(footer_candidates):
        if candidate not in FAMILY_CODES:
            return candidate
    return ""


def extract_transpo_number(block_lines):
    for line in reversed(block_lines):
        text = line.text
        if text in {"Features", "For use on ALTERNATORS:", "FOR USE ON:"}:
            continue
        if TRANSPO_NUMBER_RE.match(text):
            return text
    return ""


def split_detail_blocks(lines):
    blocks = []
    marker_indexes = [idx for idx, line in enumerate(lines) if line.text == "Original Number *"]
    if not marker_indexes:
        return []
    marker_indexes.append(len(lines))

    for idx in range(len(marker_indexes) - 1):
        start = marker_indexes[idx]
        end = marker_indexes[idx + 1]
        block_lines = lines[start:end]
        if not block_lines:
            continue
        manufacturer = ""
        for prev_idx in range(start - 1, max(-1, start - 4), -1):
            prev_text = lines[prev_idx].text
            if is_all_caps_label(prev_text) and prev_text not in {"FEATURES", "TERMINALS"}:
                manufacturer = prev_text
                break
        blocks.append((manufacturer, block_lines))
    return blocks


def add_ref(entry, ref_type, manufacturer, ref_value, notes=""):
    ref_value = normalize_space(ref_value)
    manufacturer = normalize_space(manufacturer)
    notes = normalize_space(notes)
    if not ref_value or ref_value == "OE Part Reference Not Available":
        return
    entry.refs.append({
        "ref_type": ref_type[:30],
        "manufacturer": manufacturer[:100],
        "ref_value": ref_value[:255],
        "notes": notes[:255],
    })


def parse_ref_group(entry, ref_lines, ref_type):
    current_mfr = entry.manufacturer
    for line in ref_lines:
        text = line.text
        if not text or text in {"Original Number *", "For use on ALTERNATORS:", "FOR USE ON:", "Features"}:
            continue
        if is_all_caps_label(text) or (not any(ch.isdigit() for ch in text) and len(text) <= 40 and text == text.upper()):
            current_mfr = text
            continue
        if REF_VALUE_RE.match(text):
            add_ref(entry, ref_type, current_mfr, text)
        elif ref_type == "for_use_on":
            add_ref(entry, ref_type, current_mfr, text)


def parse_features(entry, feature_lines):
    if not feature_lines:
        entry.part_name = entry.transpo_number
        return

    free_lines = []
    notes = []
    for line in feature_lines:
        text = line.text
        if text == "Features":
            continue
        match = FIELD_LINE_RE.match(text)
        if match:
            key = normalize_space(match.group("key"))
            value = normalize_space(match.group("value"))
            if key and value:
                entry.attributes[key[:100]] = value[:500]
            continue
        if text.startswith("?"):
            notes.append(text.lstrip("? ").strip())
            continue
        free_lines.append(text)

    if free_lines:
        entry.part_name = free_lines[0][:255]
        if len(free_lines) > 1:
            entry.description = "\n".join(free_lines[1:]).strip()[:2000]
    else:
        entry.part_name = entry.transpo_number
    if notes:
        entry.features_text = "\n".join(notes)[:2000]


def parse_detail_block(page_number, section_name, manufacturer, block_lines):
    transpo_number = extract_transpo_number(block_lines)
    if not transpo_number:
        return None

    entry = DetailEntry(
        transpo_number=transpo_number,
        page_number=page_number,
        section_name=section_name,
        manufacturer=manufacturer,
    )

    raw_lines = []
    for line in block_lines:
        raw_lines.append(line.text)
        entry.bbox = merge_bbox(entry.bbox, (line.x0, line.y0, line.x1, line.y1))
    entry.raw_text = "\n".join(raw_lines)[:4000]

    original_lines = []
    use_lines = []
    feature_lines = []
    current_section = "original"

    for line in block_lines[1:]:
        text = line.text
        if text == "For use on ALTERNATORS:" or text == "FOR USE ON:":
            current_section = "use"
            continue
        if text == "Features":
            current_section = "features"
            feature_lines.append(line)
            continue
        if current_section == "original":
            original_lines.append(line)
        elif current_section == "use":
            use_lines.append(line)
        else:
            feature_lines.append(line)

    parse_ref_group(entry, original_lines, "original_number")
    parse_ref_group(entry, use_lines, "for_use_on")
    parse_features(entry, feature_lines)
    return entry


def parse_detail_page(page):
    lines = clean_page_lines(page)
    if not lines:
        return [], extract_detail_section_name(lines)

    section_name = extract_detail_section_name(lines)
    entries = []
    for manufacturer, block_lines in split_detail_blocks(lines):
        entry = parse_detail_block(page.number + 1, section_name, manufacturer, block_lines)
        if entry:
            entries.append(entry)
    return entries, section_name


def classify_crossref_section(page_number):
    if page_number >= TRANSPO_TO_PAGE_START_PAGE:
        return "Transpo-No. to Page-No"
    if page_number >= OE_TO_TRANSPO_START_PAGE:
        return "OE-No. to Transpo-No"
    return "Unit-No. to Transpo-Parts"


def split_embedded_family(token):
    parts = token.split()
    if len(parts) >= 2 and parts[-1] in FAMILY_CODES:
        return " ".join(parts[:-1]), parts[-1]
    return token, ""


def looks_like_family_token(token):
    token = normalize_space(token)
    if not token:
        return False
    if token in FAMILY_CODES:
        return True
    return any(token.startswith(prefix + " ") for prefix in FAMILY_CODES)


def parse_crossref_tokens(tokens, section_name, page_number):
    rows = []
    idx = 0
    while idx + 1 < len(tokens):
        source_number = tokens[idx]
        transpo_number = tokens[idx + 1]

        if not REF_VALUE_RE.match(source_number):
            idx += 1
            continue

        transpo_number, embedded_family = split_embedded_family(transpo_number)
        if not TRANSPO_NUMBER_RE.match(transpo_number):
            idx += 1
            continue

        product_family = embedded_family
        catalog_page = ""
        consumed = 2

        if embedded_family:
            if idx + 2 < len(tokens) and PAGE_FOOTER_RE.match(tokens[idx + 2]):
                catalog_page = tokens[idx + 2]
                consumed = 3
        elif idx + 3 < len(tokens) and looks_like_family_token(tokens[idx + 2]) and PAGE_FOOTER_RE.match(tokens[idx + 3]):
            product_family = tokens[idx + 2]
            catalog_page = tokens[idx + 3]
            consumed = 4
        elif idx + 2 < len(tokens) and looks_like_family_token(tokens[idx + 2]):
            product_family = tokens[idx + 2]
            consumed = 3

        rows.append({
            "source_section": section_name,
            "source_number": source_number[:100],
            "transpo_number": transpo_number[:100],
            "product_family": product_family[:50],
            "catalog_page": catalog_page[:20],
            "page_number": page_number,
        })
        idx += consumed

    return rows


def parse_crossref_page(page):
    section_name = classify_crossref_section(page.number + 1)
    columns = defaultdict(list)
    for line in clean_page_lines(page):
        text = line.text
        if text in {"Buyers Guide"}:
            continue
        if PAGE_FOOTER_RE.match(text):
            continue
        if is_all_caps_label(text):
            continue
        columns[round(line.column_anchor)].append(text)

    rows = []
    for anchor in sorted(columns):
        rows.extend(parse_crossref_tokens(columns[anchor], section_name, page.number + 1))
    return rows


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
                if not entry.bbox:
                    continue
                entry_center = bbox_center(entry.bbox)
                distance = abs(rect_center[0] - entry_center[0]) + abs(rect_center[1] - entry_center[1])
                if best_distance is None or distance < best_distance:
                    best_entry = entry
                    best_distance = distance
            if not best_entry:
                continue

            image_index_by_part[best_entry.transpo_number] += 1
            image_index = image_index_by_part[best_entry.transpo_number]
            file_name = f"{slugify(best_entry.transpo_number)}_p{page.number + 1:04d}_{image_index}.{ext}"
            image_path = os.path.join(image_dir, file_name)
            with open(image_path, "wb") as handle:
                handle.write(image_bytes)

            best_entry.has_image = True
            results.append({
                "transpo_number": best_entry.transpo_number,
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
        CREATE TABLE IF NOT EXISTS transpo_catalog_parts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transpo_number TEXT NOT NULL,
            part_name TEXT NOT NULL DEFAULT '',
            section_name TEXT NOT NULL DEFAULT '',
            manufacturer TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            features_text TEXT NOT NULL DEFAULT '',
            attributes_json TEXT NOT NULL DEFAULT '{}',
            page_number INTEGER NOT NULL DEFAULT 0,
            source_pdf TEXT NOT NULL DEFAULT '',
            has_image INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            raw_text TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS transpo_catalog_refs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transpo_number TEXT NOT NULL,
            ref_type TEXT NOT NULL DEFAULT '',
            manufacturer TEXT NOT NULL DEFAULT '',
            ref_value TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS transpo_catalog_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transpo_number TEXT NOT NULL,
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
        CREATE TABLE IF NOT EXISTS transpo_cross_reference (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_section TEXT NOT NULL DEFAULT '',
            source_number TEXT NOT NULL DEFAULT '',
            transpo_number TEXT NOT NULL DEFAULT '',
            product_family TEXT NOT NULL DEFAULT '',
            catalog_page TEXT NOT NULL DEFAULT '',
            page_number INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    conn.execute("CREATE INDEX IF NOT EXISTS idx_transpo_parts_number ON transpo_catalog_parts(transpo_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_transpo_parts_section ON transpo_catalog_parts(section_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_transpo_refs_number ON transpo_catalog_refs(transpo_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_transpo_refs_value ON transpo_catalog_refs(ref_value)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_transpo_images_number ON transpo_catalog_images(transpo_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_transpo_xref_source ON transpo_cross_reference(source_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_transpo_xref_transpo ON transpo_cross_reference(transpo_number)")
    conn.commit()
    return conn


def main():
    parser = argparse.ArgumentParser(description="Parse Transpo catalog PDF into staging DB")
    parser.add_argument("pdf_path", help="Path to the Transpo catalog PDF")
    parser.add_argument("--output", help="Output SQLite path")
    parser.add_argument("--start-page", type=int, default=DETAIL_START_PAGE, help="First 1-based page to parse")
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
        db_path = os.path.join(staging_dir, "transpo_catalog.db")

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
    xref_batch = []
    totals = defaultdict(int)
    start_time = time.time()
    BATCH_SIZE = 1000

    def flush():
        if part_batch:
            conn.executemany(
                """
                INSERT INTO transpo_catalog_parts
                (transpo_number, part_name, section_name, manufacturer, description,
                 features_text, attributes_json, page_number, source_pdf, has_image,
                 notes, raw_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                part_batch,
            )
            totals["parts"] += len(part_batch)
            part_batch.clear()
        if ref_batch:
            conn.executemany(
                """
                INSERT INTO transpo_catalog_refs
                (transpo_number, ref_type, manufacturer, ref_value, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                ref_batch,
            )
            totals["refs"] += len(ref_batch)
            ref_batch.clear()
        if image_batch:
            conn.executemany(
                """
                INSERT INTO transpo_catalog_images
                (transpo_number, page_number, image_index, image_path, width, height)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                image_batch,
            )
            totals["images"] += len(image_batch)
            image_batch.clear()
        if xref_batch:
            conn.executemany(
                """
                INSERT INTO transpo_cross_reference
                (source_section, source_number, transpo_number, product_family, catalog_page, page_number)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                xref_batch,
            )
            totals["xrefs"] += len(xref_batch)
            xref_batch.clear()
        conn.commit()

    try:
        for page_idx in range(start_index, end_index + 1):
            page = doc[page_idx]
            page_number = page_idx + 1

            if page_number < UNIT_TO_TRANSPO_START_PAGE:
                entries, section_name = parse_detail_page(page)
                image_rows = extract_images(doc, page, entries, image_dir)
                for entry in entries:
                    part_batch.append(
                        (
                            entry.transpo_number,
                            entry.part_name[:255],
                            entry.section_name[:150],
                            entry.manufacturer[:100],
                            entry.description[:2000],
                            entry.features_text[:2000],
                            json.dumps(entry.attributes, sort_keys=True),
                            entry.page_number,
                            os.path.basename(pdf_path),
                            1 if entry.has_image else 0,
                            entry.notes[:2000],
                            entry.raw_text[:4000],
                        )
                    )
                    for ref in entry.refs:
                        ref_batch.append(
                            (
                                entry.transpo_number,
                                ref["ref_type"][:30],
                                ref["manufacturer"][:100],
                                ref["ref_value"][:255],
                                ref["notes"][:255],
                            )
                        )
                for row in image_rows:
                    image_batch.append(
                        (
                            row["transpo_number"],
                            row["page_number"],
                            row["image_index"],
                            row["image_path"],
                            row["width"],
                            row["height"],
                        )
                    )
                if not entries:
                    totals["detail_empty_pages"] += 1
            else:
                rows = parse_crossref_page(page)
                for row in rows:
                    xref_batch.append(
                        (
                            row["source_section"],
                            row["source_number"],
                            row["transpo_number"],
                            row["product_family"],
                            row["catalog_page"],
                            row["page_number"],
                        )
                    )
                if not rows:
                    totals["xref_empty_pages"] += 1

            if (
                len(part_batch) >= BATCH_SIZE
                or len(ref_batch) >= BATCH_SIZE
                or len(image_batch) >= BATCH_SIZE
                or len(xref_batch) >= BATCH_SIZE
            ):
                flush()

            processed = page_idx - start_index + 1
            if processed % 50 == 0 or processed == total_pages:
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                print(
                    f"  Page {processed:>4,}/{total_pages:,}  |  "
                    f"parts: {totals['parts'] + len(part_batch):>6,}  "
                    f"refs: {totals['refs'] + len(ref_batch):>6,}  "
                    f"images: {totals['images'] + len(image_batch):>6,}  "
                    f"xrefs: {totals['xrefs'] + len(xref_batch):>7,}  "
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
    print(f"  Detail empty pages:   {totals['detail_empty_pages']:>10,}")
    print(f"  Xref empty pages:     {totals['xref_empty_pages']:>10,}")
    print(f"  Part rows staged:     {totals['parts']:>10,}")
    print(f"  Ref rows staged:      {totals['refs']:>10,}")
    print(f"  Image rows staged:    {totals['images']:>10,}")
    print(f"  Xref rows staged:     {totals['xrefs']:>10,}")
    print(f"  Time elapsed:         {elapsed:>10.1f}s")
    print()
    print(f"Staging DB: {db_path}")
    print(f"Image dir:   {image_dir}")


if __name__ == "__main__":
    main()
