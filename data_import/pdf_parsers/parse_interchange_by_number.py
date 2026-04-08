"""
Parse "2-Interchange by Number.pdf" into a staging SQLite database.

PDF structure (4026 pages):
  - Three column groups per page, each with sub-columns:
    Their No | Their Name (manufacturer) | Our No (YouTech number)
  - Odd/even pages have different margins (book layout)
  - Column positions auto-detected from header words on each page
  - Manufacturer name persists until a new one appears
  - Some values wrap across lines (handled via coordinate-based extraction)

Usage:
    python -m data_import.pdf_parsers.parse_interchange_by_number <pdf_path> [--output <db_path>]
"""

import argparse
import os
import sqlite3
import sys
import time
from collections import defaultdict

import fitz  # PyMuPDF


HEADER_Y_MAX = 72.0
FOOTER_Y_MIN = 720.0


def detect_column_layout(words):
    """Detect column groups from header words ('Their', 'Name', 'Our').

    Returns list of dicts with their_no_x, their_name_x, our_no_x boundaries.
    """
    header_words = [w for w in words if w[1] < HEADER_Y_MAX]

    their_no_xs = []
    their_name_xs = []
    our_no_xs = []

    for i, w in enumerate(header_words):
        word = w[4]
        x0 = w[0]
        if word == "Their":
            # "Their No" vs "Their Name" - check next word
            next_words = [hw for hw in header_words if abs(hw[1] - w[1]) < 3 and hw[0] > x0 and hw[0] < x0 + 40]
            if next_words and next_words[0][4] == "No":
                their_no_xs.append(x0)
            elif next_words and next_words[0][4] == "Name":
                their_name_xs.append(x0)
        elif word == "Our":
            our_no_xs.append(x0)

    if not their_no_xs or not our_no_xs:
        return []

    their_no_xs.sort()
    their_name_xs.sort()
    our_no_xs.sort()

    groups = []
    for i, tn_x in enumerate(their_no_xs):
        name_x = their_name_xs[i] if i < len(their_name_xs) else tn_x + 64
        our_x = our_no_xs[i] if i < len(our_no_xs) else name_x + 68

        # Determine the end boundary for this group
        if i + 1 < len(their_no_xs):
            end_x = their_no_xs[i + 1] - 7
        else:
            end_x = 620

        # Data x-offsets are typically ~3 below header x positions
        groups.append({
            "their_no_min": tn_x - 8,
            "their_no_max": name_x - 5,
            "their_name_min": name_x - 5,
            "their_name_max": our_x - 5,
            "our_no_min": our_x - 5,
            "end": end_x,
        })

    return groups


def parse_page(page, page_num, manufacturers):
    """Parse a single page using word-level coordinates."""
    words = page.get_text("words")
    records = []

    groups = detect_column_layout(words)
    if not groups:
        return records, manufacturers

    data_words = [w for w in words if w[1] > HEADER_Y_MAX and w[1] < FOOTER_Y_MIN]

    # Classify each data word into (group_idx, sub_col, y_key)
    row_data = defaultdict(lambda: defaultdict(list))

    for w in data_words:
        x0, y0, word = w[0], w[1], w[4]
        if word in ("I",):
            continue

        # Skip page numbers
        if word.startswith("Pg.") or (word.isdigit() and y0 > 710):
            continue

        for gi, g in enumerate(groups):
            if g["their_no_min"] <= x0 < g["end"]:
                if x0 < g["their_no_max"]:
                    sub = "their_no"
                elif x0 < g["their_name_max"]:
                    sub = "their_name"
                else:
                    sub = "our_no"
                y_key = round(y0)
                row_data[(gi, y_key)][sub].append(word)
                break

    # Process each column group independently
    for gi in range(len(groups)):
        col_rows = sorted(
            [(yk, data) for (g, yk), data in row_data.items() if g == gi],
            key=lambda x: x[0],
        )

        current_mfr = manufacturers.get(gi, "")
        pending_records = []

        for y_key, data in col_rows:
            their_no = " ".join(data.get("their_no", []))
            their_name = " ".join(data.get("their_name", []))
            our_no = " ".join(data.get("our_no", []))

            if our_no:
                if their_name:
                    current_mfr = their_name
                pending_records.append({
                    "their_no": their_no,
                    "manufacturer": current_mfr,
                    "our_no": our_no,
                })
            elif pending_records:
                if their_no:
                    pending_records[-1]["their_no"] += their_no
                if their_name:
                    pending_records[-1]["manufacturer"] += " " + their_name
                    current_mfr = pending_records[-1]["manufacturer"]

        manufacturers[gi] = current_mfr
        for rec in pending_records:
            records.append((
                rec["manufacturer"],
                rec["their_no"],
                rec["our_no"],
                page_num,
            ))

    return records, manufacturers


def create_staging_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS interchange_by_number (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manufacturer TEXT NOT NULL DEFAULT '',
            their_number TEXT NOT NULL,
            our_number TEXT NOT NULL,
            page_number INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_their_number ON interchange_by_number(their_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_our_number ON interchange_by_number(our_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_manufacturer ON interchange_by_number(manufacturer)")
    conn.commit()
    return conn


def main():
    parser = argparse.ArgumentParser(description="Parse interchange-by-number PDF into staging DB")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument("--output", help="Output DB path")
    parser.add_argument("--limit", type=int, help="Limit to first N pages (for testing)")
    args = parser.parse_args()

    if not os.path.exists(args.pdf_path):
        print(f"ERROR: PDF not found: {args.pdf_path}")
        sys.exit(1)

    pdf_name = os.path.splitext(os.path.basename(args.pdf_path))[0]
    if args.output:
        db_path = args.output
    else:
        staging_dir = os.path.join(os.path.dirname(__file__), "..", "staging_dbs")
        os.makedirs(staging_dir, exist_ok=True)
        db_path = os.path.join(staging_dir, f"{pdf_name}.db")

    if os.path.exists(db_path):
        os.remove(db_path)

    print(f"PDF:    {args.pdf_path}")
    print(f"Output: {db_path}")
    print()

    doc = fitz.open(args.pdf_path)
    total_pages = doc.page_count
    if args.limit:
        total_pages = min(total_pages, args.limit)
    print(f"Total pages to process: {total_pages}")

    conn = create_staging_db(db_path)
    manufacturers = {}
    total_records = 0
    batch = []
    batch_size = 5000
    start_time = time.time()

    for page_idx in range(total_pages):
        page = doc[page_idx]
        records, manufacturers = parse_page(page, page_idx + 1, manufacturers)
        batch.extend(records)

        if len(batch) >= batch_size:
            conn.executemany(
                "INSERT INTO interchange_by_number (manufacturer, their_number, our_number, page_number) VALUES (?, ?, ?, ?)",
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
            "INSERT INTO interchange_by_number (manufacturer, their_number, our_number, page_number) VALUES (?, ?, ?, ?)",
            batch,
        )
        conn.commit()
        total_records += len(batch)

    elapsed = time.time() - start_time
    doc.close()

    stats = conn.execute("""
        SELECT
            COUNT(*) as total_rows,
            COUNT(DISTINCT manufacturer) as unique_mfrs,
            COUNT(DISTINCT their_number) as unique_their,
            COUNT(DISTINCT our_number) as unique_our
        FROM interchange_by_number
    """).fetchone()

    mfr_sample = conn.execute("""
        SELECT manufacturer, COUNT(*) as cnt
        FROM interchange_by_number
        GROUP BY manufacturer
        ORDER BY cnt DESC
        LIMIT 15
    """).fetchall()

    conn.close()

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Total records:         {stats[0]:>10,}")
    print(f"  Unique manufacturers:  {stats[1]:>10,}")
    print(f"  Unique 'their' numbers:{stats[2]:>10,}")
    print(f"  Unique 'our' numbers:  {stats[3]:>10,}")
    print(f"  Time elapsed:          {elapsed:>10.1f}s")
    print()
    print("Top 15 manufacturers by record count:")
    for mfr, cnt in mfr_sample:
        print(f"  {cnt:>8,}  {mfr}")
    print()
    print(f"Staging DB saved to: {db_path}")


if __name__ == "__main__":
    main()
