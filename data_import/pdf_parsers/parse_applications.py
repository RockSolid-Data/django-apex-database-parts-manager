"""
Parse Application PDFs (4-8) into a staging SQLite database.

Handles the tabular application format:
  Make (bold 14pt) → Model (medium 10pt) → Engine spec (medium 10pt, with
  displacement pattern) → data rows (regular 8pt)

Column positions detected per-page from header words.

Usage:
    python -m data_import.pdf_parsers.parse_applications <pdf_path> [--unit-type Alternator]
"""

import argparse
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict

import fitz  # PyMuPDF


YEAR_RE = re.compile(r"^\d{2,4}(?:-\d{2,4})?$")
ENGINE_SPEC_RE = re.compile(
    r"^[LVH]\d\s+\d+\.\d+L|^\d+\.\d+L|^Diesel|^Turbo|^Gas",
    re.IGNORECASE,
)
HEADER_KEYS = {"Engine", "Year", "Options", "Mfr", "Amp", "KW", "Volt", "Part", "Other"}


def detect_columns(words):
    """Find header word positions to determine column boundaries."""
    header_words = [w for w in words if 70 < w[1] < 85]
    if not header_words:
        return None

    positions = {}
    for w in sorted(header_words, key=lambda w: w[0]):
        if w[4] in HEADER_KEYS:
            positions[w[4]] = w[0]

    if "Mfr" not in positions or "Part" not in positions:
        return None

    mfr_x = positions["Mfr"]
    amp_x = positions.get("Amp") or positions.get("KW") or (mfr_x + 35)
    volt_x = positions.get("Volt", amp_x + 25)
    part_x = positions["Part"]
    other_x = positions.get("Other", part_x + 43)
    year_x = positions.get("Year", mfr_x - 225)

    return {
        "model_max": year_x - 5,
        "mfr_min": mfr_x - 20,  # wider tolerance: column text is left-aligned, header may be centered
        "amp_min": amp_x - 5,
        "volt_min": volt_x - 5,
        "part_min": part_x - 8,
        "other_min": other_x - 8,
    }


def build_font_map(page_dict):
    """Build a mapping from (y_key) -> list of (x, text, is_bold, size).

    Uses span bbox top (y0) to align with word y-coordinates.
    """
    font_map = defaultdict(list)
    for block in page_dict["blocks"]:
        if "lines" not in block:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if not text:
                    continue
                bbox = span["bbox"]
                y = bbox[1]  # top of bbox, matches word y-coordinates
                x = bbox[0]
                if y < 88:
                    continue
                is_bold = bool(span["flags"] & 16)
                size = span["size"]
                y_key = round(y / 2) * 2
                font_map[y_key].append((x, text, is_bold, size))
    return font_map


def parse_page(page, page_num, state):
    """Parse one page of application data."""
    words = page.get_text("words")
    cols = detect_columns(words)
    if not cols:
        return [], state

    page_dict = page.get_text("dict")
    font_map = build_font_map(page_dict)

    records = []
    make = state.get("make", "")
    model = state.get("model", "")
    engine = state.get("engine", "")
    pending_other = state.get("pending_other", "")

    data_words = [w for w in words if w[1] > 88 and w[1] < 750]
    if not data_words:
        return records, state

    row_map = defaultdict(list)
    for w in data_words:
        y_key = round(w[1] / 2) * 2
        row_map[y_key].append(w)

    for y_key in sorted(row_map.keys()):
        row_words = sorted(row_map[y_key], key=lambda w: w[0])
        font_info = font_map.get(y_key, [])

        # Check if this row contains bold make or medium model/spec text
        is_make_row = False
        is_model_row = False
        for fx, ftext, fbold, fsize in font_info:
            if fx < cols["mfr_min"]:
                if fbold and fsize > 12:
                    is_make_row = True
                    make = ftext.title()
                    model = ""
                    engine = ""
                    pending_other = ""
                    break
                elif fsize > 8.5 and not fbold:
                    is_model_row = True

        if is_make_row:
            continue

        if is_model_row:
            # Gather all model-column words from this row
            model_words = [w[4] for w in row_words if w[0] < cols["model_max"]]
            model_text = " ".join(model_words)

            if model_text:
                if ENGINE_SPEC_RE.search(model_text):
                    engine = model_text
                else:
                    model = model_text
                    engine = ""

            # There might also be data fields on this same row (Year, Mfr, etc.)
            has_data = any(w[0] >= cols["mfr_min"] for w in row_words)
            if not has_data:
                continue
            # Fall through to data processing

        if not make:
            continue

        # Data row: classify words into columns
        model_col_parts = []
        year_engine_parts = []
        mfr_parts = []
        amp_parts = []
        volt_parts = []
        part_parts = []
        other_parts = []

        for w in row_words:
            x = w[0]
            text = w[4]
            if x < cols["model_max"]:
                model_col_parts.append(text)
            elif x < cols["mfr_min"]:
                year_engine_parts.append(text)
            elif x < cols["amp_min"]:
                mfr_parts.append(text)
            elif x < cols["volt_min"]:
                amp_parts.append(text)
            elif x < cols["part_min"]:
                volt_parts.append(text)
            elif x < cols["other_min"]:
                part_parts.append(text)
            else:
                other_parts.append(text)

        # If the model-column words on this data row form an engine spec
        # (e.g. "L4 2.2L 2156CC"), update engine state for this and future rows.
        model_col_text = " ".join(model_col_parts)
        if model_col_text and ENGINE_SPEC_RE.search(model_col_text):
            engine = model_col_text

        # Parse year from year_engine_parts
        year = ""
        options_parts = []
        for part in year_engine_parts:
            if not year and YEAR_RE.match(part):
                year = part
            else:
                options_parts.append(part)
        options_text = " ".join(options_parts)

        mfr_text = " ".join(mfr_parts)
        amp_text = " ".join(amp_parts)
        volt_text = " ".join(volt_parts)
        part_text = " ".join(part_parts)
        other_text = " ".join(other_parts)

        if " " in part_text:
            pn_parts = part_text.split(" ", 1)
            if re.match(r"\d", pn_parts[1]):
                part_text = pn_parts[0]
                extra = pn_parts[1].rstrip(",")
                other_text = (extra + ", " + other_text) if other_text else extra

        # Handle continuation lines: if row only has Other# data (no part#)
        if other_text and not part_text and not year and not mfr_text:
            pending_other += " " + other_text if pending_other else other_text
            continue

        # If we have a pending other, attach to this record
        if pending_other and part_text:
            other_text = pending_other + " " + other_text if other_text else pending_other
            pending_other = ""

        if part_text:
            # Store engine spec and options text separately.
            # engine = the technical spec from the model-column heading (e.g. "V6 3.2L 3210CC")
            # options_text = what is in the Options column (e.g. "Automatic", "F3L912")
            records.append((
                make,
                model,
                year,
                engine,
                options_text,
                mfr_text,
                amp_text,
                volt_text,
                part_text,
                other_text,
                page_num,
            ))
            if other_text and other_text.endswith(","):
                pending_other = other_text
                records[-1] = records[-1][:9] + ("",) + (records[-1][10],)
        elif other_text:
            pending_other = other_text

    state = {
        "make": make,
        "model": model,
        "engine": engine,
        "pending_other": pending_other,
    }
    return records, state


def create_staging_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_type TEXT NOT NULL DEFAULT '',
            make TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            year TEXT NOT NULL DEFAULT '',
            engine TEXT NOT NULL DEFAULT '',
            options TEXT NOT NULL DEFAULT '',
            mfr TEXT NOT NULL DEFAULT '',
            amp TEXT NOT NULL DEFAULT '',
            volt TEXT NOT NULL DEFAULT '',
            part_number TEXT NOT NULL DEFAULT '',
            other_number TEXT NOT NULL DEFAULT '',
            page_number INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_part_number ON applications(part_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_make ON applications(make)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_model ON applications(model)")
    conn.commit()
    return conn


def main():
    parser = argparse.ArgumentParser(description="Parse application PDF into staging DB")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument("--unit-type", default="", help="Unit type (e.g. Alternator, Starter)")
    parser.add_argument("--output", help="Output DB path")
    parser.add_argument("--limit", type=int, help="Limit to first N pages (for testing)")
    args = parser.parse_args()

    if not os.path.exists(args.pdf_path):
        print(f"ERROR: PDF not found: {args.pdf_path}")
        sys.exit(1)

    unit_type = args.unit_type
    if not unit_type:
        fname = os.path.basename(args.pdf_path).lower()
        if "alt" in fname:
            unit_type = "Alternator"
        elif "gen" in fname:
            unit_type = "Generator"
        elif "starter" in fname:
            unit_type = "Starter"
        elif "motor" in fname:
            unit_type = "Motor"
        elif "mgu" in fname:
            unit_type = "MGU"

    pdf_name = os.path.splitext(os.path.basename(args.pdf_path))[0]
    if args.output:
        db_path = args.output
    else:
        staging_dir = os.path.join(os.path.dirname(__file__), "..", "staging_dbs")
        os.makedirs(staging_dir, exist_ok=True)
        db_path = os.path.join(staging_dir, f"{pdf_name}.db")

    if os.path.exists(db_path):
        os.remove(db_path)

    print(f"PDF:       {args.pdf_path}")
    print(f"Unit type: {unit_type}")
    print(f"Output:    {db_path}")
    print()

    doc = fitz.open(args.pdf_path)
    total_pages = doc.page_count
    if args.limit:
        total_pages = min(total_pages, args.limit)
    print(f"Total pages to process: {total_pages}")

    conn = create_staging_db(db_path)
    state = {}
    total_records = 0
    batch = []
    batch_size = 5000
    start_time = time.time()

    for page_idx in range(total_pages):
        page = doc[page_idx]
        records, state = parse_page(page, page_idx + 1, state)
        for rec in records:
            batch.append((unit_type,) + rec[0:10] + (rec[10],))

        if len(batch) >= batch_size:
            conn.executemany(
                "INSERT INTO applications (unit_type, make, model, year, engine, options, mfr, amp, volt, part_number, other_number, page_number) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                batch,
            )
            conn.commit()
            total_records += len(batch)
            batch = []

        if (page_idx + 1) % 100 == 0 or page_idx == total_pages - 1:
            elapsed = time.time() - start_time
            rate = (page_idx + 1) / elapsed if elapsed > 0 else 0
            print(
                f"  Page {page_idx + 1:>5}/{total_pages}  |  "
                f"records so far: {total_records + len(batch):>10,}  |  "
                f"{rate:.0f} pages/sec"
            )

    if batch:
        conn.executemany(
            "INSERT INTO applications (unit_type, make, model, year, engine, options, mfr, amp, volt, part_number, other_number, page_number) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            batch,
        )
        conn.commit()
        total_records += len(batch)

    elapsed = time.time() - start_time
    doc.close()

    stats = conn.execute("""
        SELECT
            COUNT(*),
            COUNT(DISTINCT make),
            COUNT(DISTINCT model),
            COUNT(DISTINCT part_number)
        FROM applications
    """).fetchone()

    make_sample = conn.execute("""
        SELECT make, COUNT(*) as cnt
        FROM applications
        GROUP BY make
        ORDER BY cnt DESC
        LIMIT 15
    """).fetchall()

    conn.close()

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Total records:         {stats[0]:>10,}")
    print(f"  Unique makes:          {stats[1]:>10,}")
    print(f"  Unique models:         {stats[2]:>10,}")
    print(f"  Unique part numbers:   {stats[3]:>10,}")
    print(f"  Time elapsed:          {elapsed:>10.1f}s")
    print()
    print("Top 15 makes by record count:")
    for make, cnt in make_sample:
        print(f"  {cnt:>8,}  {make}")
    print()
    print(f"Staging DB saved to: {db_path}")


if __name__ == "__main__":
    main()
