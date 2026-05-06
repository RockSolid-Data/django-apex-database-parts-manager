"""
Parse Buyers Guide Components PDF (14) into a staging SQLite database.

Format: Component/Part entries each with:
  - Header: <YT#> /J&N #<JN#>/<part_name>  or  <YT#>/<part_name>
  - PRODUCT ATTRIBUTES: key-value pairs (Manufacture, Oe Manufacturer, plus
    component-specific attrs like Voltage, Rotation, Amperage, etc.)
  - INTERCHANGES: pipe-delimited "Manufacturer: number, number | ..."
  - UNIT NUMBERS - YOUTECH: comma-separated list of unit YouTech numbers

Creates staging tables:
  - component_products: one row per unique YT number (J&N numbers pipe-joined)
  - component_interchanges: cross-reference data
  - component_unit_links: maps component YT -> unit YT numbers
  - component_images: extracted product images keyed by YT number

Usage:
    python -m data_import.pdf_parsers.parse_buyers_guide_components <pdf_path>
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time

import fitz  # PyMuPDF


# Header pattern: "0A-00548 /J&N #451-56006/Rectifier Bridge" or "0A-03002/Regulator Screw"
# YT numbers follow the pattern: digits + uppercase letter + dash + digits (e.g. 0A-00548, 2D-30424, TE-10000)
# This rejects measurement lines like ".748/19" or "3.38/86" that appear in PRODUCT ATTRIBUTES.
COMPONENT_HEADER_RE = re.compile(
    r'^([0-9]{0,3}[A-Z]{1,2}-[\w-]+)\s*(?:/J&N\s+#([^/]+))?/(.+)'
)

SECTION_HEADERS = {
    "PRODUCT ATTRIBUTES",
    "INTERCHANGES",
    "UNIT NUMBERS - YOUTECH",
}

PAGE_HEADER = "COMPONENT BUYERS GUIDE BY PART NUMBER"

_LOGO_MAX_PX = 200

# Common attribute keys normalised → staging column name.
# Anything not listed here goes into the attributes_json blob.
KNOWN_ATTR_KEYS = {
    "manufacture": "manufacture",
    "oe_manufacturer": "oe_manufacturer",
    "voltage": "voltage",
    "rotation": "rotation",
    "series": "series",
}


def _clean_interchange_number(num):
    num = num.strip()
    num = re.sub(r"-\s+", "-", num)
    num = re.sub(r"\s+-", "-", num)
    return num


def parse_interchanges_text(text):
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
                num = _clean_interchange_number(num)
                if num:
                    results.append((current_mfr, num))
    return results


def _extract_page_images(page, doc):
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


def _extract_component_positions(page):
    """Return (y_top, x_left, yt_number) for each component header on the page."""
    positions = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line.get("spans", []))
            m = COMPONENT_HEADER_RE.match(text.strip())
            if m and "(Cont.)" not in text:
                yt = m.group(1)
                bbox = line["bbox"]
                positions.append((bbox[1], bbox[0], yt))
    return positions


def _column_boundary(positions, page_images, page_width=612.0):
    """Compute column split from header + image x-positions.

    Right-column headers can start left of the geometric page center
    (e.g. x=291 on a 612-wide page), so using page_width/2 misclassifies
    them.  Instead, look for a natural gap between two clusters of
    x-positions from both headers and images.
    """
    xs = [x for _, x, _ in positions]
    xs += [x for _, x, _, _ in page_images]
    if len(xs) < 2:
        return page_width / 2.0
    xs.sort()
    best_gap = 0
    best_mid = page_width / 2.0
    for i in range(len(xs) - 1):
        gap = xs[i + 1] - xs[i]
        if gap > best_gap:
            best_gap = gap
            best_mid = (xs[i] + xs[i + 1]) / 2.0
    if best_gap < 50:
        return page_width / 2.0
    return best_mid


def _match_images_to_components(positions, page_images, page_width=612.0):
    mid = _column_boundary(positions, page_images, page_width)
    result = {}
    for img_y, img_x, img_bytes, img_ext in page_images:
        img_col = "left" if img_x < mid else "right"
        best_yt = None
        best_y_diff = float("inf")
        for unit_y, unit_x, yt in positions:
            unit_col = "left" if unit_x < mid else "right"
            if unit_col != img_col:
                continue
            y_diff = img_y - unit_y
            if y_diff >= -20 and y_diff < best_y_diff:
                best_y_diff = y_diff
                best_yt = yt
        if best_yt and best_yt not in result:
            result[best_yt] = (img_bytes, img_ext)
    return result


def parse_document(doc, limit=None, image_db_conn=None, start_page=0):
    """
    Parse Components PDF into products, interchanges, unit links, and images.
    """
    product_map = {}        # yt -> {part_name, manufacture, oe_manufacturer, extra_attrs}
    jn_map = {}             # yt -> list of J&N numbers
    interchange_map = {}    # (yt, mfr, num) -> (mfr, num, yt)
    unit_link_set = set()   # (component_yt, unit_yt) pairs
    image_map = {}          # yt -> (image_bytes, ext)
    images_saved = 0

    total_pages = doc.page_count
    if limit:
        total_pages = min(total_pages, limit)
    first_page = start_page

    current_yt = ""
    current_jn = ""
    current_part_name = ""
    current_section = ""
    current_attrs = {}
    interchange_buffer = ""
    unit_numbers_buffer = ""
    name_pending = False

    def flush_unit_numbers():
        nonlocal unit_numbers_buffer
        if unit_numbers_buffer and current_yt:
            for num in re.split(r',\s*', unit_numbers_buffer):
                num = num.strip()
                if num and not re.match(r'^Pg\.\s*\d+', num):
                    unit_link_set.add((current_yt, num))
            unit_numbers_buffer = ""

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
            product_map[current_yt] = {
                "part_name": current_part_name,
                "manufacture": current_attrs.pop("manufacture", ""),
                "oe_manufacturer": current_attrs.pop("oe_manufacturer", ""),
                "voltage": current_attrs.pop("voltage", ""),
                "rotation": current_attrs.pop("rotation", ""),
                "series": current_attrs.pop("series", ""),
                "extra_attrs": dict(current_attrs),
            }
        else:
            existing = product_map[current_yt]
            if not existing["part_name"] and current_part_name:
                existing["part_name"] = current_part_name
            for key in ("manufacture", "oe_manufacturer", "voltage", "rotation", "series"):
                val = current_attrs.pop(key, "")
                if val and not existing.get(key):
                    existing[key] = val
            # Merge extra attrs
            for k, v in current_attrs.items():
                if v and k not in existing.get("extra_attrs", {}):
                    existing.setdefault("extra_attrs", {})[k] = v
        current_attrs = {}

    for page_idx in range(first_page, total_pages):
        page = doc[page_idx]
        text = page.get_text()
        lines = text.split("\n")

        # Image extraction
        comp_positions = _extract_component_positions(page)
        page_images = _extract_page_images(page, doc)
        if comp_positions and page_images:
            page_width = page.rect.width
            matched = _match_images_to_components(comp_positions, page_images, page_width)
            for yt, img_data in matched.items():
                if image_db_conn:
                    try:
                        image_db_conn.execute(
                            "INSERT OR IGNORE INTO component_images "
                            "(youtech_number, image_data, image_ext) VALUES (?, ?, ?)",
                            (yt, img_data[0], img_data[1]),
                        )
                        images_saved += 1
                    except Exception:
                        pass
                elif yt not in image_map:
                    image_map[yt] = img_data

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            if line == PAGE_HEADER:
                continue

            # Page number lines
            if re.match(r'^Pg\.\s*\d+', line):
                continue

            # Check for component header
            m = COMPONENT_HEADER_RE.match(line)
            if m:
                part_name_fragment = m.group(3).strip()

                # Check if (Cont.) is in this line
                if "(Cont.)" in line:
                    name_pending = False
                    continue

                # If we had a pending name from a previous header, finalise it
                if name_pending:
                    flush_interchanges()
                    flush_unit_numbers()
                    flush_product()
                    name_pending = False

                # Flush previous entry
                flush_interchanges()
                flush_unit_numbers()
                flush_product()

                current_yt = m.group(1)
                current_jn = (m.group(2) or "").strip()
                current_part_name = part_name_fragment
                current_section = ""
                current_attrs = {}

                if current_yt not in jn_map:
                    jn_map[current_yt] = []
                if current_jn and current_jn not in jn_map[current_yt]:
                    jn_map[current_yt].append(current_jn)

                name_pending = True
                continue

            # If awaiting part name completion
            if name_pending:
                if "(Cont.)" in line:
                    # This was a continuation header — revert to previous state
                    name_pending = False
                    continue

                clean = line.rstrip(":")
                if clean in SECTION_HEADERS:
                    name_pending = False
                    current_section = clean
                    continue

                # Otherwise, this is part of the part name (line wrap)
                current_part_name += " " + line
                name_pending = False
                continue

            # Section header detection
            clean = line.rstrip(":")
            if clean in SECTION_HEADERS:
                if current_section == "INTERCHANGES":
                    flush_interchanges()
                if current_section == "UNIT NUMBERS - YOUTECH":
                    flush_unit_numbers()
                current_section = clean
                continue

            if not current_yt:
                continue

            # --- PRODUCT ATTRIBUTES ---
            if current_section == "PRODUCT ATTRIBUTES":
                if "_pending_attr_key" in current_attrs:
                    key = current_attrs.pop("_pending_attr_key")
                    mapped = KNOWN_ATTR_KEYS.get(key, key)
                    current_attrs[mapped] = line
                else:
                    normalized = line.lower().replace(" ", "_").rstrip(".")
                    current_attrs["_pending_attr_key"] = normalized

            # --- INTERCHANGES ---
            elif current_section == "INTERCHANGES":
                interchange_buffer += " " + line if interchange_buffer else line

            # --- UNIT NUMBERS - YOUTECH ---
            elif current_section == "UNIT NUMBERS - YOUTECH":
                # Filter out page numbers embedded in unit number lists
                if not re.match(r'^Pg\.\s*\d+', line):
                    unit_numbers_buffer += " " + line if unit_numbers_buffer else line

        del page

        if (page_idx + 1) % 100 == 0 or page_idx == total_pages - 1:
            img_ct = images_saved if image_db_conn else len(image_map)
            print(
                f"  Page {page_idx + 1:>5}/{total_pages}  |  "
                f"parts: {len(product_map):>5}  |  "
                f"xrefs: {len(interchange_map):>7}  |  "
                f"unit links: {len(unit_link_set):>7}  |  "
                f"images: {img_ct:>5}",
                flush=True,
            )
            if image_db_conn and (page_idx + 1) % 500 == 0:
                image_db_conn.commit()

    # Final flush
    flush_interchanges()
    flush_unit_numbers()
    flush_product()

    # Build products list
    products = []
    for yt, attrs in product_map.items():
        attrs.pop("_pending_attr_key", None)
        extra = attrs.get("extra_attrs", {})
        extra.pop("_pending_attr_key", None)
        jns = jn_map.get(yt, [])
        jn_combined = " | ".join(jns) if jns else ""
        products.append({
            "youtech_number": yt,
            "jn_number": jn_combined,
            "part_name": attrs.get("part_name", ""),
            "manufacture": attrs.get("manufacture", ""),
            "oe_manufacturer": attrs.get("oe_manufacturer", ""),
            "voltage": attrs.get("voltage", ""),
            "rotation": attrs.get("rotation", ""),
            "series": attrs.get("series", ""),
            "attributes_json": json.dumps(extra) if extra else "",
        })

    interchanges = list(interchange_map.values())
    unit_links = list(unit_link_set)

    return products, interchanges, unit_links, image_map


def create_staging_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS component_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            youtech_number TEXT NOT NULL,
            jn_number TEXT NOT NULL DEFAULT '',
            part_name TEXT NOT NULL DEFAULT '',
            manufacture TEXT NOT NULL DEFAULT '',
            oe_manufacturer TEXT NOT NULL DEFAULT '',
            voltage TEXT NOT NULL DEFAULT '',
            rotation TEXT NOT NULL DEFAULT '',
            series TEXT NOT NULL DEFAULT '',
            attributes_json TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS component_interchanges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manufacturer TEXT NOT NULL DEFAULT '',
            their_number TEXT NOT NULL,
            our_number TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS component_unit_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            component_yt TEXT NOT NULL,
            unit_yt TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS component_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            youtech_number TEXT NOT NULL UNIQUE,
            image_data BLOB NOT NULL,
            image_ext TEXT NOT NULL DEFAULT 'jpeg'
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_cp_yt ON component_products(youtech_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ci_their ON component_interchanges(their_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ci_our ON component_interchanges(our_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cul_comp ON component_unit_links(component_yt)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cul_unit ON component_unit_links(unit_yt)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cimg_yt ON component_images(youtech_number)")
    conn.commit()
    return conn


def _write_chunk_to_db(conn, products, interchanges, unit_links, image_map):
    """Write one chunk's parsed data into the staging DB immediately."""
    _PRODUCT_COLS = (
        "youtech_number", "jn_number", "part_name", "manufacture",
        "oe_manufacturer", "voltage", "rotation", "series", "attributes_json",
    )
    _placeholders = ", ".join("?" * len(_PRODUCT_COLS))

    if products:
        conn.executemany(
            f"INSERT INTO component_products ({', '.join(_PRODUCT_COLS)}) "
            f"VALUES ({_placeholders})",
            [tuple(p[c] for c in _PRODUCT_COLS) for p in products],
        )

    if interchanges:
        conn.executemany(
            "INSERT INTO component_interchanges (manufacturer, their_number, our_number) "
            "VALUES (?, ?, ?)",
            interchanges,
        )

    if unit_links:
        conn.executemany(
            "INSERT INTO component_unit_links (component_yt, unit_yt) "
            "VALUES (?, ?)",
            unit_links,
        )

    if image_map:
        for yt, (img_bytes, img_ext) in image_map.items():
            conn.execute(
                "INSERT OR REPLACE INTO component_images (youtech_number, image_data, image_ext) "
                "VALUES (?, ?, ?)",
                (yt, img_bytes, img_ext),
            )

    conn.commit()


def main():
    import gc

    parser = argparse.ArgumentParser(description="Parse Buyers Guide Components PDF into staging DB")
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

    print(f"PDF:    {args.pdf_path}", flush=True)
    print(f"Output: {db_path}", flush=True)
    print(flush=True)

    conn = create_staging_db(db_path)

    doc = fitz.open(args.pdf_path)
    total_pages = doc.page_count
    if args.limit:
        total_pages = min(total_pages, args.limit)
    print(f"Total pages: {total_pages:,}", flush=True)

    start_time = time.time()

    CHUNK = 200

    for chunk_start in range(0, total_pages, CHUNK):
        chunk_end = min(chunk_start + CHUNK, total_pages)
        print(f"\n--- Processing pages {chunk_start + 1}-{chunk_end} ---", flush=True)

        if chunk_start > 0:
            doc.close()
            gc.collect()
            doc = fitz.open(args.pdf_path)

        products, interchanges, unit_links, image_map = parse_document(
            doc, limit=chunk_end, image_db_conn=conn,
            start_page=chunk_start,
        )

        _write_chunk_to_db(conn, products, interchanges, unit_links, image_map)
        del products, interchanges, unit_links, image_map
        gc.collect()

    doc.close()
    gc.collect()

    elapsed = time.time() - start_time

    prod_count = conn.execute("SELECT COUNT(*) FROM component_products").fetchone()[0]
    xref_count = conn.execute("SELECT COUNT(*) FROM component_interchanges").fetchone()[0]
    link_count = conn.execute("SELECT COUNT(*) FROM component_unit_links").fetchone()[0]
    img_count = conn.execute("SELECT COUNT(*) FROM component_images").fetchone()[0]
    conn.close()

    print(flush=True)
    print("=" * 60, flush=True)
    print("SUMMARY", flush=True)
    print("=" * 60, flush=True)
    print(f"  Components (unique YT#):   {prod_count:>10,}", flush=True)
    print(f"  Interchange records:       {xref_count:>10,}", flush=True)
    print(f"  Unit link records:         {link_count:>10,}", flush=True)
    print(f"  Component images:          {img_count:>10,}", flush=True)
    print(f"  Time elapsed:              {elapsed:>10.1f}s", flush=True)
    print(flush=True)
    print(f"Staging DB saved to: {db_path}", flush=True)


if __name__ == "__main__":
    main()
