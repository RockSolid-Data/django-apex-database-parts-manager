"""
Parse Buyers Guide PDFs (12-13) into a staging SQLite database.

Format: Product entries each with:
  - Header: YouTech #XXXXX /J&N #YYYYY
  - PRODUCT ATTRIBUTES: key-value pairs (Manufacture, Family, Voltage, etc.)
  - INTERCHANGES: pipe-delimited "Manufacturer: number, number | ..."
  - BILL OF MATERIALS (optional)
  - POSSIBLE SUBSTITUTIONS (optional)
  - APPLICATION (optional)

Creates staging tables:
  - buyers_guide_products: one row per unique YouTech number (J&N numbers
    pipe-joined when multiple J&N numbers share the same YouTech number)
  - buyers_guide_interchanges: cross-reference data including J&N entries
  - buyers_guide_bom: BOM line items keyed by YouTech unit number
  - buyers_guide_substitutes: possible substitution pairs
  - buyers_guide_images: extracted product images keyed by YouTech number

Usage:
    python -m data_import.pdf_parsers.parse_buyers_guide <pdf_path>
"""

import argparse
import os
import re
import sqlite3
import sys
import time

import fitz  # PyMuPDF


YOUTECH_HEADER_RE = re.compile(
    r"YouTech\s+#(\S+)\s*(?:/J&N\s+#(\S+))?"
)
SECTION_HEADERS = {
    "PRODUCT ATTRIBUTES",
    "INTERCHANGES",
    "BILL OF MATERIALS",
    "APPLICATION",
    "APPLICATIONS",
    "POSSIBLE SUBSTITUTIONS",
}

# Logo watermark dimensions — skip any image at or below this size
_LOGO_MAX_PX = 200


def parse_interchanges_text(text):
    """Parse pipe-delimited interchange text into (manufacturer, number) pairs."""
    results = []
    segments = text.split("|")
    current_mfr = ""
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        if ":" in seg:
            parts = seg.split(":", 1)
            current_mfr = parts[0].strip()
            numbers_text = parts[1].strip()
        else:
            numbers_text = seg.strip()

        if current_mfr and numbers_text:
            for num in numbers_text.split(","):
                num = num.strip()
                if num:
                    results.append((current_mfr, num))
    return results


def _extract_page_images(page, doc):
    """
    Return a list of (yt_number_candidate_y, x_center, image_bytes, ext) for
    each product image on the page.  The caller resolves which YouTech entry
    each image belongs to.

    Skips the logo watermark (width <= _LOGO_MAX_PX or height <= _LOGO_MAX_PX).
    """
    results = []
    seen_xrefs = set()
    for img in page.get_images(full=True):
        xref = img[0]
        if xref in seen_xrefs:
            continue
        base_image = doc.extract_image(xref)
        if base_image["width"] <= _LOGO_MAX_PX or base_image["height"] <= _LOGO_MAX_PX:
            continue
        rects = page.get_image_rects(xref)
        if not rects:
            continue
        rect = rects[0]
        x_center = (rect.x0 + rect.x1) / 2.0
        y_top = rect.y0
        seen_xrefs.add(xref)
        results.append((y_top, x_center, base_image["image"], base_image["ext"]))
    return results


def _extract_unit_positions(page):
    """
    Return list of (y_top, x_left, yt_number) for each YouTech header block
    on the page, using the full dict-mode text extraction so we have x coords.
    Skips "(Cont.)" continuation headers.
    """
    positions = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line.get("spans", []))
            m = YOUTECH_HEADER_RE.match(text.strip())
            if m and "(Cont.)" not in text:
                yt = m.group(1)
                bbox = line["bbox"]
                positions.append((bbox[1], bbox[0], yt))  # (y_top, x_left, yt)
    return positions


def _match_images_to_units(unit_positions, page_images, page_width=612.0):
    """
    For each product image, find the closest unit entry that:
      - Is in the same horizontal column (left: x_center < page_width/2,
        right: x_center >= page_width/2)
      - Has a y_top at or above the image y_top (image is below its unit header)

    Returns dict: yt_number -> (image_bytes, ext)
    Only assigns the FIRST (topmost) image per unit.
    """
    mid = page_width / 2.0
    result = {}

    for img_y, img_x, img_bytes, img_ext in page_images:
        img_col = "left" if img_x < mid else "right"

        # Find the closest unit entry in the same column at or above the image
        best_yt = None
        best_y_diff = float("inf")
        for unit_y, unit_x, yt in unit_positions:
            unit_col = "left" if unit_x < mid else "right"
            if unit_col != img_col:
                continue
            y_diff = img_y - unit_y
            if y_diff >= -20 and y_diff < best_y_diff:  # allow 20px above
                best_y_diff = y_diff
                best_yt = yt

        if best_yt and best_yt not in result:
            result[best_yt] = (img_bytes, img_ext)

    return result


def parse_document(doc, limit=None):
    """
    Parse entire PDF document into products, interchanges, bom items,
    substitutes, and images.
    """
    # Accumulators keyed by YouTech number (de-duplicate by YT#)
    product_map = {}       # yt -> dict of attributes
    jn_map = {}            # yt -> list of J&N numbers (order-preserved, unique)
    interchange_map = {}   # (yt, mfr, num) -> True  (de-duplicate)
    bom_map = {}           # yt -> list of (part_name, yt_part, jn_part)
    sub_map = {}           # yt -> list of (sub_yt, sub_jn)
    image_map = {}         # yt -> (image_bytes, ext)

    total_pages = doc.page_count
    if limit:
        total_pages = min(total_pages, limit)

    current_yt = ""
    current_jn = ""
    current_section = ""
    current_attrs = {}
    interchange_buffer = ""

    # BOM parsing state
    bom_pending_name = ""
    bom_pending_yt = ""
    bom_in_header = False  # True while we're on the BOM/YOUTECH/J&N header row

    def flush_interchanges():
        nonlocal interchange_buffer
        if interchange_buffer and current_yt:
            pairs = parse_interchanges_text(interchange_buffer)
            for mfr, num in pairs:
                key = (current_yt, mfr, num)
                interchange_map[key] = (mfr, num, current_yt)
            interchange_buffer = ""

    def flush_product():
        nonlocal current_attrs
        if not current_yt:
            return
        if current_yt not in product_map:
            product_map[current_yt] = dict(current_attrs)
        else:
            # Merge attributes — don't overwrite existing non-empty values
            for k, v in current_attrs.items():
                if v and not product_map[current_yt].get(k):
                    product_map[current_yt][k] = v
        current_attrs = {}

    for page_idx in range(total_pages):
        page = doc[page_idx]
        text = page.get_text()
        lines = text.split("\n")

        # --- Image extraction for this page ---
        unit_positions = _extract_unit_positions(page)
        page_images = _extract_page_images(page, doc)
        if unit_positions and page_images:
            page_width = page.rect.width
            matched = _match_images_to_units(unit_positions, page_images, page_width)
            for yt, img_data in matched.items():
                if yt not in image_map:
                    image_map[yt] = img_data

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            # Skip page headers
            if line in ("BUYERS GUIDE", "TILT & TRIM MOTORS",
                        "MILD HYBRID MOTOR/GENERATORS"):
                continue

            # Check for new product header
            m = YOUTECH_HEADER_RE.match(line)
            if m:
                flush_interchanges()
                flush_product()

                current_yt = m.group(1)
                current_jn = m.group(2) or ""
                current_section = ""
                current_attrs = {}
                bom_pending_name = ""
                bom_pending_yt = ""
                bom_in_header = False

                # Track J&N numbers for this YouTech number
                if current_yt not in jn_map:
                    jn_map[current_yt] = []
                if current_jn and current_jn not in jn_map[current_yt]:
                    jn_map[current_yt].append(current_jn)

                if current_yt not in bom_map:
                    bom_map[current_yt] = []
                if current_yt not in sub_map:
                    sub_map[current_yt] = []
                continue

            # Section header detection
            clean = line.rstrip(":")
            if clean in SECTION_HEADERS:
                if current_section == "INTERCHANGES":
                    flush_interchanges()
                current_section = clean
                bom_in_header = (clean == "BILL OF MATERIALS")
                bom_pending_name = ""
                bom_pending_yt = ""
                continue

            if not current_yt:
                continue

            # --- PRODUCT ATTRIBUTES ---
            if current_section == "PRODUCT ATTRIBUTES":
                if line.startswith("Product Notes:"):
                    current_attrs["product_notes"] = line[14:].strip()
                elif "pending_attr_key" in current_attrs:
                    key = current_attrs.pop("pending_attr_key")
                    current_attrs[key] = line
                else:
                    normalized = line.lower().replace(" ", "_")
                    current_attrs["pending_attr_key"] = normalized

            # --- INTERCHANGES ---
            elif current_section == "INTERCHANGES":
                interchange_buffer += " " + line if interchange_buffer else line

            # --- BILL OF MATERIALS ---
            elif current_section == "BILL OF MATERIALS":
                # Skip the column header row "BOM / YOUTECH / J&N"
                if bom_in_header:
                    if line in ("BOM", "YOUTECH", "J&N"):
                        continue
                    else:
                        bom_in_header = False

                # Skip page numbers
                if re.match(r'^Pg\.\s*\d+', line):
                    continue

                # A line starting with a letter is a part name
                if re.match(r'^[A-Za-z]', line) and not line.startswith("YouTech"):
                    # Flush any pending BOM item first
                    if bom_pending_name and bom_pending_yt:
                        bom_map[current_yt].append(
                            (bom_pending_name, bom_pending_yt, "")
                        )
                    bom_pending_name = line
                    bom_pending_yt = ""

                # A line that looks like a YouTech part number (e.g. 2D-30424, 62-7600, TE-20000)
                elif bom_pending_name and re.match(r'^[A-Z0-9]{2}-', line):
                    bom_pending_yt = line

                # A line that looks like a J&N number (e.g. 141-21000-10)
                elif bom_pending_yt and re.match(r'^\d{3}-', line):
                    # This is the J&N for the current BOM item
                    jn_val = line.rstrip(",")
                    bom_map[current_yt].append(
                        (bom_pending_name, bom_pending_yt, jn_val)
                    )
                    bom_pending_name = ""
                    bom_pending_yt = ""

                # Continuation J&N lines (comma-separated overflow)
                elif re.match(r'^\d{3}-', line) and bom_map[current_yt]:
                    # Append to last BOM item's J&N field
                    last = bom_map[current_yt][-1]
                    merged_jn = (last[2] + ", " + line.rstrip(",")).strip(", ")
                    bom_map[current_yt][-1] = (last[0], last[1], merged_jn)

            # --- POSSIBLE SUBSTITUTIONS ---
            elif current_section == "POSSIBLE SUBSTITUTIONS":
                # Lines like: YouTech : 450001 | J&N : 430-21003
                pairs = re.findall(
                    r'YouTech\s*:\s*(\d+)(?:\s*\|\s*J&N\s*:\s*([\d-]+))?', line
                )
                for sub_yt, sub_jn in pairs:
                    entry = (sub_yt, sub_jn or "")
                    if entry not in sub_map[current_yt]:
                        sub_map[current_yt].append(entry)

            elif current_section in ("APPLICATION", "APPLICATIONS"):
                pass  # not captured for this import

        # Flush last BOM pending item if we hit end of page mid-item
        if bom_pending_name and bom_pending_yt and current_yt:
            bom_map[current_yt].append((bom_pending_name, bom_pending_yt, ""))
            bom_pending_name = ""
            bom_pending_yt = ""

        if (page_idx + 1) % 20 == 0 or page_idx == total_pages - 1:
            print(
                f"  Page {page_idx + 1:>3}/{total_pages}  |  "
                f"units: {len(product_map):>4}  |  "
                f"xrefs: {len(interchange_map):>6}  |  "
                f"images: {len(image_map):>4}"
            )

    # Final flush
    flush_interchanges()
    flush_product()

    # Build products list with combined J&N numbers
    products = []
    for yt, attrs in product_map.items():
        jns = jn_map.get(yt, [])
        jn_combined = " | ".join(jns) if jns else ""
        products.append({
            "youtech_number": yt,
            "jn_number": jn_combined,
            "manufacture": attrs.get("manufacture", ""),
            "oe_manufacturer": attrs.get("oe_manufacturer", ""),
            "family": attrs.get("family", ""),
            "voltage": attrs.get("voltage", ""),
            "rotation": attrs.get("starter_rotation", ""),
            "product_notes": attrs.get("product_notes", ""),
        })

    interchanges = list(interchange_map.values())  # (mfr, num, yt)

    bom_items = []
    for yt, items in bom_map.items():
        for part_name, yt_part, jn_part in items:
            if part_name and yt_part:
                bom_items.append((yt, part_name, yt_part, jn_part))

    substitutes = []
    for yt, subs in sub_map.items():
        for sub_yt, sub_jn in subs:
            substitutes.append((yt, sub_yt, sub_jn))

    return products, interchanges, bom_items, substitutes, image_map


def create_staging_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS buyers_guide_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            youtech_number TEXT NOT NULL,
            jn_number TEXT NOT NULL DEFAULT '',
            manufacture TEXT NOT NULL DEFAULT '',
            oe_manufacturer TEXT NOT NULL DEFAULT '',
            family TEXT NOT NULL DEFAULT '',
            voltage TEXT NOT NULL DEFAULT '',
            rotation TEXT NOT NULL DEFAULT '',
            product_notes TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS buyers_guide_interchanges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manufacturer TEXT NOT NULL DEFAULT '',
            their_number TEXT NOT NULL,
            our_number TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS buyers_guide_bom (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            youtech_number TEXT NOT NULL,
            part_name TEXT NOT NULL DEFAULT '',
            yt_part_number TEXT NOT NULL DEFAULT '',
            jn_part_number TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS buyers_guide_substitutes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            youtech_number TEXT NOT NULL,
            substitute_yt TEXT NOT NULL DEFAULT '',
            substitute_jn TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS buyers_guide_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            youtech_number TEXT NOT NULL UNIQUE,
            image_data BLOB NOT NULL,
            image_ext TEXT NOT NULL DEFAULT 'jpeg'
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_bg_yt ON buyers_guide_products(youtech_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bg_their ON buyers_guide_interchanges(their_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bg_our ON buyers_guide_interchanges(our_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bg_bom_yt ON buyers_guide_bom(youtech_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bg_sub_yt ON buyers_guide_substitutes(youtech_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bg_img_yt ON buyers_guide_images(youtech_number)")
    conn.commit()
    return conn


def main():
    parser = argparse.ArgumentParser(description="Parse buyers guide PDF into staging DB")
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
    start_time = time.time()

    products, interchanges, bom_items, substitutes, image_map = parse_document(
        doc, limit=args.limit
    )
    doc.close()

    conn = create_staging_db(db_path)

    conn.executemany(
        "INSERT INTO buyers_guide_products "
        "(youtech_number, jn_number, manufacture, oe_manufacturer, family, voltage, rotation, product_notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                p["youtech_number"], p["jn_number"], p["manufacture"],
                p["oe_manufacturer"], p["family"], p["voltage"],
                p["rotation"], p["product_notes"],
            )
            for p in products
        ],
    )

    if interchanges:
        conn.executemany(
            "INSERT INTO buyers_guide_interchanges (manufacturer, their_number, our_number) "
            "VALUES (?, ?, ?)",
            interchanges,
        )

    if bom_items:
        conn.executemany(
            "INSERT INTO buyers_guide_bom (youtech_number, part_name, yt_part_number, jn_part_number) "
            "VALUES (?, ?, ?, ?)",
            bom_items,
        )

    if substitutes:
        conn.executemany(
            "INSERT INTO buyers_guide_substitutes (youtech_number, substitute_yt, substitute_jn) "
            "VALUES (?, ?, ?)",
            substitutes,
        )

    for yt, (img_bytes, img_ext) in image_map.items():
        conn.execute(
            "INSERT OR REPLACE INTO buyers_guide_images (youtech_number, image_data, image_ext) "
            "VALUES (?, ?, ?)",
            (yt, img_bytes, img_ext),
        )

    conn.commit()

    elapsed = time.time() - start_time

    prod_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_products").fetchone()[0]
    xref_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_interchanges").fetchone()[0]
    bom_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_bom").fetchone()[0]
    sub_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_substitutes").fetchone()[0]
    img_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_images").fetchone()[0]
    conn.close()

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Products (unique YT#):     {prod_count:>10,}")
    print(f"  Interchange records:       {xref_count:>10,}")
    print(f"  BOM line items:            {bom_count:>10,}")
    print(f"  Substitute pairs:          {sub_count:>10,}")
    print(f"  Unit images extracted:     {img_count:>10,}")
    print(f"  Time elapsed:              {elapsed:>10.1f}s")
    print()
    print(f"Staging DB saved to: {db_path}")


if __name__ == "__main__":
    main()
