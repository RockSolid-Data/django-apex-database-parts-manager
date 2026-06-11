"""
Parse "3-Our Numbers to Others.pdf" into a staging SQLite database.

PDF structure (3881 pages, multi-column):
  - Blocks grouped by YouTech number (Our No)
  - Each block: YouTech number + description (bold text), then manufacturer
    + part number pairs (regular text)
  - Font detection: bold spans = YouTech number/description;
    regular spans = manufacturer/part data

Usage:
    python -m data_import.pdf_parsers.parse_our_numbers_to_others <pdf_path> [--output <db_path>]
"""

import argparse
import os
import re
import sqlite3
import sys
import time

import fitz  # PyMuPDF


PAGE_NUMBER_RE = re.compile(r"^Pg\.\s*\d+$", re.IGNORECASE)
YOUTECH_RE = re.compile(r"^(\d[A-Za-z]-\S+|\d{5,6})\b")


def has_digit(s):
    return any(c.isdigit() for c in s)


def parse_page(page, page_num, state):
    """Parse one page using font info to distinguish descriptions from data."""
    d = page.get_text("dict")
    records = []

    our_no = state.get("our_no", "")
    description = state.get("description", "")
    manufacturer = state.get("manufacturer", "")
    prev_was_mfr_regular = state.get("prev_was_mfr_regular", False)
    pending_record = state.get("pending_record", None)

    for block in d["blocks"]:
        if "lines" not in block:
            continue
        for line in block["lines"]:
            # Combine all spans in this line into bold/regular groups
            bold_parts = []
            regular_parts = []
            for span in line["spans"]:
                text = span["text"].strip()
                if not text:
                    continue
                is_bold = bool(span["flags"] & 16) or span["size"] > 8.5
                if is_bold:
                    bold_parts.append(text)
                else:
                    regular_parts.append(text)

            bold_text = " ".join(bold_parts).strip()
            regular_text = " ".join(regular_parts).strip()

            # Skip headers and page numbers
            if bold_text == "OUR NUMBERS TO OTHERS":
                continue
            if PAGE_NUMBER_RE.match(bold_text) or PAGE_NUMBER_RE.match(regular_text):
                continue

            # Process bold text (YouTech number and/or description)
            if bold_text:
                m = YOUTECH_RE.match(bold_text)
                if m:
                    if pending_record:
                        records.append(pending_record)
                        pending_record = None
                    our_no = m.group(1)
                    rest = bold_text[len(m.group(1)):].strip()
                    description = rest
                    manufacturer = ""
                    prev_was_mfr_regular = False
                else:
                    # Bold text without YouTech pattern = description continuation
                    if our_no:
                        if description:
                            description += " " + bold_text
                        else:
                            description = bold_text

            # Process regular text (manufacturer names and part numbers)
            if regular_text and our_no:
                if regular_text == "I":
                    continue

                if pending_record:
                    if has_digit(regular_text) or len(regular_text) <= 3:
                        p_mfr, p_num, p_our, p_desc, p_page = pending_record
                        records.append((p_mfr, p_num + regular_text, p_our, p_desc, p_page))
                        pending_record = None
                        prev_was_mfr_regular = False
                        continue
                    else:
                        records.append(pending_record)
                        pending_record = None

                if has_digit(regular_text):
                    if manufacturer:
                        if regular_text.endswith("-"):
                            pending_record = (manufacturer, regular_text, our_no, description, page_num)
                        else:
                            records.append((manufacturer, regular_text, our_no, description, page_num))
                    prev_was_mfr_regular = False
                else:
                    if len(regular_text) == 1 and regular_text.isalpha():
                        if records:
                            last = records[-1]
                            records[-1] = (last[0], last[1] + regular_text, last[2], last[3], last[4])
                        elif pending_record:
                            p_mfr, p_num, p_our, p_desc, p_page = pending_record
                            pending_record = (p_mfr, p_num + regular_text, p_our, p_desc, p_page)
                    else:
                        if prev_was_mfr_regular:
                            manufacturer += " " + regular_text
                        else:
                            manufacturer = regular_text
                        prev_was_mfr_regular = True

    state = {
        "our_no": our_no,
        "description": description,
        "manufacturer": manufacturer,
        "prev_was_mfr_regular": prev_was_mfr_regular,
        "pending_record": pending_record,
    }
    return records, state


def create_staging_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS our_numbers_to_others (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manufacturer TEXT NOT NULL DEFAULT '',
            their_number TEXT NOT NULL,
            our_number TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            page_number INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_their_number ON our_numbers_to_others(their_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_our_number ON our_numbers_to_others(our_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_manufacturer ON our_numbers_to_others(manufacturer)")
    conn.commit()
    return conn


def main():
    parser = argparse.ArgumentParser(description="Parse our-numbers-to-others PDF into staging DB")
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
    state = {}
    total_records = 0
    batch = []
    batch_size = 5000
    start_time = time.time()

    for page_idx in range(total_pages):
        page = doc[page_idx]
        records, state = parse_page(page, page_idx + 1, state)
        batch.extend(records)

        if len(batch) >= batch_size:
            conn.executemany(
                "INSERT INTO our_numbers_to_others (manufacturer, their_number, our_number, description, page_number) VALUES (?, ?, ?, ?, ?)",
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

    if state.get("pending_record"):
        batch.append(state["pending_record"])

    if batch:
        conn.executemany(
            "INSERT INTO our_numbers_to_others (manufacturer, their_number, our_number, description, page_number) VALUES (?, ?, ?, ?, ?)",
            batch,
        )
        conn.commit()
        total_records += len(batch)

    elapsed = time.time() - start_time
    doc.close()

    stats = conn.execute("""
        SELECT
            COUNT(*),
            COUNT(DISTINCT manufacturer),
            COUNT(DISTINCT their_number),
            COUNT(DISTINCT our_number),
            COUNT(DISTINCT description)
        FROM our_numbers_to_others
    """).fetchone()

    mfr_sample = conn.execute("""
        SELECT manufacturer, COUNT(*) as cnt
        FROM our_numbers_to_others
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
    print(f"  Unique descriptions:   {stats[4]:>10,}")
    print(f"  Time elapsed:          {elapsed:>10.1f}s")
    print()
    print("Top 15 manufacturers by record count:")
    for mfr, cnt in mfr_sample:
        print(f"  {cnt:>8,}  {mfr}")
    print()
    print(f"Staging DB saved to: {db_path}")


if __name__ == "__main__":
    main()
