"""
Parse "1-Interchange by Mfr.pdf" into a staging SQLite database.

PDF structure (3032 pages):
  - Two-column layout per page (sometimes 3 column sections)
  - Grouped by manufacturer name (e.g. "ACCUMAX", "Bosch")
  - Each entry: manufacturer's part number ("Their No") -> YouTech number ("Our No")
  - Columns separated by lone "I" line, followed by "Their No"/"Our No" headers

Usage:
    python -m data_import.pdf_parsers.parse_interchange_by_mfr <pdf_path> [--output <db_path>]
"""

import argparse
import os
import re
import sqlite3
import sys
import time

import fitz  # PyMuPDF


HEADERS_TO_SKIP = {
    "BY MFR",
    "INTERCHANGE TO OUR NUMBERS",
    "Their No",
    "Our No",
}

PAGE_NUMBER_RE = re.compile(r"^Pg\.\s*\d+$", re.IGNORECASE)


def has_digit(s: str) -> bool:
    return any(c.isdigit() for c in s)


def parse_page(page, page_num: int, current_manufacturer: str):
    """Parse a single page and yield (manufacturer, their_no, our_no, page_num) tuples.

    Returns the manufacturer name active at the end of the page.
    """
    text = page.get_text()
    lines = text.split("\n")
    records = []
    pending_their_no = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line in HEADERS_TO_SKIP:
            continue
        if line == "I":
            continue
        if PAGE_NUMBER_RE.match(line):
            continue

        if not has_digit(line):
            # No digits -> manufacturer name
            current_manufacturer = line
            continue

        # Line contains digits -> part number
        if pending_their_no is None:
            pending_their_no = line
        else:
            records.append((current_manufacturer, pending_their_no, line, page_num))
            pending_their_no = None

    if pending_their_no is not None:
        print(f"  WARNING: Unpaired their_no '{pending_their_no}' on page {page_num}")

    return records, current_manufacturer


def create_staging_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS interchange_by_mfr (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manufacturer TEXT NOT NULL DEFAULT '',
            their_number TEXT NOT NULL,
            our_number TEXT NOT NULL,
            page_number INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_their_number ON interchange_by_mfr(their_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_our_number ON interchange_by_mfr(our_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_manufacturer ON interchange_by_mfr(manufacturer)")
    conn.commit()
    return conn


def main():
    parser = argparse.ArgumentParser(description="Parse interchange-by-manufacturer PDF into staging DB")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument("--output", help="Output DB path (default: data_import/staging_dbs/<pdf_name>.db)")
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

    # Remove existing DB to start fresh
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
    current_manufacturer = ""
    total_records = 0
    batch = []
    batch_size = 5000
    start_time = time.time()

    for page_idx in range(total_pages):
        page = doc[page_idx]
        records, current_manufacturer = parse_page(page, page_idx + 1, current_manufacturer)
        batch.extend(records)

        if len(batch) >= batch_size:
            conn.executemany(
                "INSERT INTO interchange_by_mfr (manufacturer, their_number, our_number, page_number) VALUES (?, ?, ?, ?)",
                batch,
            )
            conn.commit()
            total_records += len(batch)
            batch = []

        if (page_idx + 1) % 100 == 0 or page_idx == total_pages - 1:
            elapsed = time.time() - start_time
            rate = (page_idx + 1) / elapsed if elapsed > 0 else 0
            print(f"  Page {page_idx + 1:>5}/{total_pages}  |  records so far: {total_records + len(batch):>10,}  |  {rate:.0f} pages/sec")

    # Flush remaining
    if batch:
        conn.executemany(
            "INSERT INTO interchange_by_mfr (manufacturer, their_number, our_number, page_number) VALUES (?, ?, ?, ?)",
            batch,
        )
        conn.commit()
        total_records += len(batch)

    elapsed = time.time() - start_time
    doc.close()

    # Summary stats
    stats = conn.execute("""
        SELECT
            COUNT(*) as total_rows,
            COUNT(DISTINCT manufacturer) as unique_mfrs,
            COUNT(DISTINCT their_number) as unique_their,
            COUNT(DISTINCT our_number) as unique_our
        FROM interchange_by_mfr
    """).fetchone()

    mfr_sample = conn.execute("""
        SELECT manufacturer, COUNT(*) as cnt
        FROM interchange_by_mfr
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
