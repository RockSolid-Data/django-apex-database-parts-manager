"""
Parse J&N Unit BOM PDFs into a staging SQLite database.

Each PDF represents one unit from the J&N Auto Electric website and has:
  - Page 1: Product header with specs, substitutes, references, superseded-by
  - Optional Applications page (detected and skipped)
  - BOM page(s): columnar Bill of Materials table

Creates three staging tables:
  - jn_unit_products:  one row per unit (header info)
  - jn_unit_bom_items: BOM line items for each unit
  - jn_unit_references: substitutes, references, and superseded-by entries

Usage:
    python -m data_import.pdf_parsers.parse_jn_unit_bom <path> [options]

    <path> can be a single PDF file or a root folder (processed recursively).

Options:
    --output  Path for the output SQLite file
              (default: data_import/staging_dbs/jn_unit_bom.db)
    --limit   Stop after processing N PDF files (for testing)
"""

import argparse
import hashlib
import os
import re
import shutil
import sqlite3
import sys
import time

import fitz  # PyMuPDF


# ---------------------------------------------------------------------------
# Page layout constants
# ---------------------------------------------------------------------------

# BOM column-header row sits at roughly y=250-270 on a J&N unit page
BOM_HEADER_Y_RANGE = (230.0, 295.0)

# Ignore words below this y (footer chrome / navigation)
FOOTER_Y = 750.0
IMAGE_MIN_SIZE = 30.0

# Website chrome words to skip when parsing BOM data
CHROME_WORDS = frozenset({
    "800-366-7100", "Hello,", "Martin", "Repair", "Shop!",
    "View", "Settings", "Contact", "Logout",
    "Search", "0", "items,", "$0.00",
    "Add", "to", "list...",
    "Units", "Components", "Accessories", "Applications",
    "Lists", "Publications", "More",
    "Specifications", "Bill", "of", "Materials",
    "Notes", "Open", "Printer", "Friendly", "Page",
    "\u00a9", "Copyright", "J&N", "Auto", "Electric,", "Inc.", "2004-2017",
})

# Section headers on the product page that introduce ref/sub blocks
SECTION_HEADERS = {
    "Substitutes:":   "substitute",
    "References:":    "reference",
    "Superseded By:": "superseded_by",
    "Superseded From:": "superseded_from",
}

# Keyed fields on the product page  (key line → field name)
PRODUCT_KEYS = {
    "Description:":        "unit_type",
    "OEM(s):":             "oem",
    "Voltage:":            "voltage",
    "Power:":              "power",
    "Amps:":               "amps",
    "Rotation:":           "rotation",
    "Starter Type:":       "starter_type",
    "Number of Teeth:":    "num_teeth",
    "Motor Type:":         "unit_type",
    "Alternator Type:":    "unit_type",
    "Generator Type:":     "unit_type",
}

# Words that anchor the BOM header row
_BOM_MARKERS = {"Description", "Notes", "Qty"}
# Words that anchor an Applications header row
_APP_MARKERS = {"Make", "Model", "Engine", "Years"}

# J&N / Lester-style part numbers found on the product page.
PART_NUMBER_RE = re.compile(r"^[0-9A-Z]{1,4}(?:-[0-9A-Z]{1,5}){2,}$")
PLACEHOLDER_IMAGE_HASHES = {
    # J&N's shared "Image Unavailable" thumbnail.
    "3b92d4f0837e4596f758c318368d3e14",
}


# ---------------------------------------------------------------------------
# Product page parser
# ---------------------------------------------------------------------------

def parse_product_page(page, expected_jn=""):
    """
    Extract unit metadata from page 1 of a J&N unit PDF.
    Returns (product_dict, references_list).
    """
    text = page.get_text()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    product = {
        "jn_number": "",
        "description": "",
        "unit_type": "",
        "oem": "",
        "voltage": "",
        "power": "",
        "amps": "",
        "rotation": "",
        "starter_type": "",
        "num_teeth": "",
        "status": "",
        "category": "",
    }

    # Detect "No Longer Available" status banner
    joined = " ".join(lines)
    if "No Longer" in joined and "Available" in joined:
        product["status"] = "No Longer Available"

    # Use the filename-derived J&N number as the source of truth when available.
    if expected_jn:
        product["jn_number"] = expected_jn.strip()

    # Locate the product-number line so we can anchor the description search.
    # Some pages insert an extra "Add" line after "$0.00", so we scan forward
    # for the first line that actually looks like a part number.
    pn_idx = -1
    start_idx = 0
    for i, ln in enumerate(lines):
        if ln == "$0.00":
            start_idx = i + 1
            break

    if expected_jn:
        expected_clean = expected_jn.strip()
        for i in range(start_idx, len(lines)):
            if lines[i].strip() == expected_clean:
                pn_idx = i
                break

    if pn_idx < 0:
        for i in range(start_idx, len(lines)):
            if PART_NUMBER_RE.match(lines[i]):
                pn_idx = i
                break

    if pn_idx < 0:
        for i, ln in enumerate(lines):
            if PART_NUMBER_RE.match(ln):
                pn_idx = i
                break

    if pn_idx < 0 and not product["jn_number"]:
        return product, []

    if pn_idx >= 0 and not product["jn_number"]:
        product["jn_number"] = lines[pn_idx].strip()

    # Description is the next non-boilerplate line after the part number
    _skip = {"Add to list...", "No Longer", "Available", "No", "Longer"}
    for offset in range(1, 5):
        idx = pn_idx + offset
        if idx >= len(lines):
            break
        candidate = lines[idx]
        if candidate in _skip or not candidate:
            continue
        # Description contains commas and does not end with ":"
        if not candidate.endswith(":"):
            product["description"] = candidate
            break

    # Parse keyed fields  (key on one line, value on the next)
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln in PRODUCT_KEYS:
            field = PRODUCT_KEYS[ln]
            if not product[field] and i + 1 < len(lines):
                product[field] = lines[i + 1]
            i += 2
            continue
        if ln.startswith("Find Other Parts in This Category:"):
            product["category"] = ln.replace(
                "Find Other Parts in This Category:", ""
            ).strip()
        i += 1

    references = _parse_ref_sections(lines)
    return product, references


def _parse_ref_sections(lines):
    """
    Extract (ref_type, manufacturer, ref_number) triples from the product page.

    Sections look like:
        Substitutes:
        Bosch
        0001501005
        Wilson
        91-28-4066
    or (no manufacturer):
        Superseded By:
        0-23000-3241
    """
    results = []
    # Any line ending in ":" that is a product attribute key (not a section
    # header) signals that we have moved past the reference sections.
    _stop = (
        {"Units", "Specifications", "Bill", "Applications",
         "Lists", "Publications", "More"}
        | set(PRODUCT_KEYS.keys())
    )
    current_section = None
    pending_mfr = ""
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln in SECTION_HEADERS:
            current_section = SECTION_HEADERS[ln]
            pending_mfr = ""
            i += 1
            continue
        if ln in _stop or ln.startswith("Find Other Parts"):
            current_section = None
            pending_mfr = ""
            i += 1
            continue
        # Skip copyright / footer lines that bleed into the section
        if "Copyright" in ln or ln.startswith("\u00a9") or ln.startswith("(c)"):
            i += 1
            continue
        if current_section:
            has_digit = any(c.isdigit() for c in ln)
            if has_digit:
                results.append((current_section, pending_mfr, ln))
                pending_mfr = ""
            else:
                pending_mfr = ln
        i += 1
    return results


# ---------------------------------------------------------------------------
# BOM page classification and parsing
# ---------------------------------------------------------------------------

def classify_page(page):
    """Return 'bom', 'applications', or 'other'."""
    words = page.get_text("words")
    header_set = {
        w[4] for w in words
        if BOM_HEADER_Y_RANGE[0] <= w[1] <= BOM_HEADER_Y_RANGE[1]
    }
    if len(_BOM_MARKERS & header_set) >= 2:
        return "bom"
    if len(_APP_MARKERS & header_set) >= 2:
        return "applications"
    return "other"


def _detect_col_bounds(words, header_y):
    """
    Detect BOM column x-boundaries from the header row.
    Returns a dict of boundary values.
    """
    hr = [w for w in words if abs(w[1] - header_y) <= 5]

    def _first_x(label):
        xs = sorted(w[0] for w in hr if w[4] == label)
        return xs[0] if xs else None

    def _all_x(label):
        return sorted(w[0] for w in hr if w[4] == label)

    notes_x = _first_x("Notes") or 108.0
    qty_x   = _first_x("Qty")   or 190.0

    jn_xs  = _all_x("J&N")   # [J&N Number col x, J&N Qty col x]
    oem_xs = _all_x("OEM")   # [OEM Number col x, OEM Qty col x]

    jn_num_x  = jn_xs[0]  if len(jn_xs) > 0 else 228.0
    jn_qty_x  = jn_xs[1]  if len(jn_xs) > 1 else jn_num_x + 102.0
    oem_num_x = oem_xs[0] if len(oem_xs) > 0 else 408.0
    oem_qty_x = oem_xs[1] if len(oem_xs) > 1 else oem_num_x + 102.0

    return {
        "notes_min":   notes_x  - 6,
        "qty_min":     qty_x    - 6,
        "qty_max":     qty_x    + 30,
        "jn_num_min":  jn_num_x  - 6,
        "jn_qty_min":  jn_qty_x  - 6,
        "oem_num_min": oem_num_x - 6,
        "oem_qty_min": oem_qty_x - 6,
        "header_y":    header_y,
    }


def parse_bom_page(page):
    """
    Extract BOM rows from a BOM page using column geometry.

    Strategy: each BOM item is anchored by its Qty value (always a single
    integer in the Qty column).  A y-band is defined around each Qty anchor
    using midpoints between consecutive Qty y-positions.  All words in a
    band are assigned to columns by x-position.  This handles multi-line
    Notes/Description cells that wrap above or below the Qty y.

    Returns list of dicts.
    """
    words = page.get_text("words")

    # Locate the header row by finding "Description" in column 1
    desc_hdr = [
        w for w in words
        if w[4] == "Description"
        and w[0] < 80
        and BOM_HEADER_Y_RANGE[0] <= w[1] <= BOM_HEADER_Y_RANGE[1]
    ]
    if not desc_hdr:
        return []

    header_y = desc_hdr[0][1]
    col = _detect_col_bounds(words, header_y)

    # Data words: below the header row, above footer, excluding chrome
    data = [
        w for w in words
        if w[1] > header_y + 5
        and w[1] < FOOTER_Y
        and w[4] not in CHROME_WORDS
    ]
    if not data:
        return []

    # Find Qty-column anchors (one per BOM item)
    qty_anchors = sorted(
        [
            w for w in data
            if col["qty_min"] <= w[0] <= col["qty_max"]
            and w[4].rstrip("+").isdigit()
        ],
        key=lambda w: w[1],
    )
    if not qty_anchors:
        return []

    qty_ys = [w[1] for w in qty_anchors]

    items = []
    for i, qw in enumerate(qty_anchors):
        # Band boundaries as midpoints between adjacent Qty y-values
        lo = (qty_ys[i - 1] + qty_ys[i]) / 2.0 if i > 0 else data[0][1] - 1.0
        hi = (qty_ys[i] + qty_ys[i + 1]) / 2.0 if i < len(qty_ys) - 1 else FOOTER_Y

        band = [w for w in data if lo <= w[1] < hi]

        desc_tok = []
        notes_tok = []
        jn_num_tok = []
        jn_qty_tok = []
        oem_num_tok = []
        oem_qty_tok = []

        for w in sorted(band, key=lambda x: (x[1], x[0])):
            x0, text = w[0], w[4]
            if x0 < col["notes_min"]:
                desc_tok.append(text)
            elif x0 < col["qty_min"]:
                notes_tok.append(text)
            elif x0 <= col["qty_max"]:
                pass  # qty anchor itself
            elif x0 < col["jn_qty_min"]:
                jn_num_tok.append(text)
            elif x0 < col["oem_num_min"]:
                jn_qty_tok.append(text)
            elif x0 < col["oem_qty_min"]:
                oem_num_tok.append(text)
            else:
                oem_qty_tok.append(text)

        items.append({
            "component_description": " ".join(desc_tok),
            "notes":                 " ".join(notes_tok),
            "qty":                   qw[4].rstrip("+"),
            "jn_number":             " ".join(jn_num_tok),
            "jn_qty":                " ".join(jn_qty_tok),
            "oem_number":            " ".join(oem_num_tok),
            "oem_qty":               " ".join(oem_qty_tok),
        })

    return items


# ---------------------------------------------------------------------------
# Image extraction
# ---------------------------------------------------------------------------

def extract_main_product_image(doc, image_dir, jn_number):
    """
    Extract the main unit image from page 1.

    The J&N pages contain many embedded UI assets, so choose the largest image
    that sits in the main product-content area rather than in the top chrome.
    Returns a dict or None.
    """
    if doc.page_count == 0:
        return None

    page = doc[0]
    page_width = page.rect.width
    page_height = page.rect.height
    best = None

    for img in page.get_images(full=True):
        xref = img[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            continue

        for rect in rects:
            if rect.width < IMAGE_MIN_SIZE or rect.height < IMAGE_MIN_SIZE:
                continue

            score = rect.width * rect.height

            # Penalize top-header chrome and far-right UI elements heavily.
            if rect.y0 < 80:
                score *= 0.2
            if rect.y0 > page_height * 0.55:
                score *= 0.2
            if rect.x0 > page_width * 0.45:
                score *= 0.3

            candidate = {
                "score": score,
                "xref": xref,
                "rect": rect,
                "page_number": 1,
            }
            if best is None or candidate["score"] > best["score"]:
                best = candidate

    if best is None:
        return None

    try:
        image_info = doc.extract_image(best["xref"])
    except Exception:
        return None

    image_bytes = image_info.get("image")
    if not image_bytes:
        return None
    image_hash = hashlib.md5(image_bytes).hexdigest()
    if image_hash in PLACEHOLDER_IMAGE_HASHES:
        return None

    ext = (image_info.get("ext") or "png").lower()
    image_path = os.path.join(image_dir, f"{jn_number}.{ext}")

    with open(image_path, "wb") as fh:
        fh.write(image_bytes)

    return {
        "jn_unit_number": jn_number,
        "page_number": best["page_number"],
        "image_path": os.path.abspath(image_path),
        "width": image_info.get("width") or int(best["rect"].width),
        "height": image_info.get("height") or int(best["rect"].height),
        "xref": best["xref"],
    }


# ---------------------------------------------------------------------------
# Staging database
# ---------------------------------------------------------------------------

def create_staging_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jn_unit_products (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            jn_number     TEXT NOT NULL,
            description   TEXT NOT NULL DEFAULT '',
            unit_type     TEXT NOT NULL DEFAULT '',
            oem           TEXT NOT NULL DEFAULT '',
            voltage       TEXT NOT NULL DEFAULT '',
            power         TEXT NOT NULL DEFAULT '',
            amps          TEXT NOT NULL DEFAULT '',
            rotation      TEXT NOT NULL DEFAULT '',
            starter_type  TEXT NOT NULL DEFAULT '',
            num_teeth     TEXT NOT NULL DEFAULT '',
            status        TEXT NOT NULL DEFAULT '',
            category      TEXT NOT NULL DEFAULT '',
            source_file   TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jn_unit_bom_items (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            jn_unit_number        TEXT NOT NULL,
            component_description TEXT NOT NULL DEFAULT '',
            notes                 TEXT NOT NULL DEFAULT '',
            qty                   TEXT NOT NULL DEFAULT '',
            jn_number             TEXT NOT NULL DEFAULT '',
            jn_qty                TEXT NOT NULL DEFAULT '',
            oem_number            TEXT NOT NULL DEFAULT '',
            oem_qty               TEXT NOT NULL DEFAULT '',
            sort_order            INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jn_unit_references (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            jn_unit_number TEXT NOT NULL,
            ref_type       TEXT NOT NULL DEFAULT '',
            manufacturer   TEXT NOT NULL DEFAULT '',
            ref_number     TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jn_unit_images (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            jn_unit_number TEXT NOT NULL,
            page_number    INTEGER NOT NULL DEFAULT 1,
            image_path     TEXT NOT NULL DEFAULT '',
            width          INTEGER NOT NULL DEFAULT 0,
            height         INTEGER NOT NULL DEFAULT 0,
            xref           INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prod_jn   ON jn_unit_products(jn_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bom_unit  ON jn_unit_bom_items(jn_unit_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bom_jn    ON jn_unit_bom_items(jn_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ref_unit  ON jn_unit_references(jn_unit_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_img_unit  ON jn_unit_images(jn_unit_number)")
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------

def process_pdf(pdf_path, image_dir):
    """
    Parse one PDF.
    Returns (product_dict, bom_items_list, references_list, image_dict), or None on error.
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        print(f"  WARN: cannot open {os.path.basename(pdf_path)}: {exc}",
              file=sys.stderr)
        return None

    try:
        if doc.page_count == 0:
            return None

        expected_jn = os.path.splitext(os.path.basename(pdf_path))[0].strip()
        product, references = parse_product_page(doc[0], expected_jn=expected_jn)
        if not product["jn_number"]:
            return None

        image = extract_main_product_image(doc, image_dir, product["jn_number"])
        bom_items = []
        for page_idx in range(1, doc.page_count):
            ptype = classify_page(doc[page_idx])
            if ptype == "bom":
                bom_items.extend(parse_bom_page(doc[page_idx]))
            # "applications" and "other" pages are skipped intentionally
    finally:
        doc.close()

    return product, bom_items, references, image


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def collect_pdfs(path):
    """Return sorted list of all PDF paths under path (recurses into dirs)."""
    path = os.path.abspath(path)
    if os.path.isfile(path):
        return [path]
    pdfs = []
    for dirpath, _, filenames in os.walk(path):
        for fn in sorted(filenames):
            if fn.lower().endswith(".pdf"):
                pdfs.append(os.path.join(dirpath, fn))
    return pdfs


def main():
    parser = argparse.ArgumentParser(
        description="Parse J&N Unit BOM PDFs into a staging SQLite DB"
    )
    parser.add_argument(
        "path",
        help="A single PDF file or a root folder to scan recursively",
    )
    parser.add_argument("--output", help="Output SQLite DB path")
    parser.add_argument(
        "--limit",
        type=int,
        help="Stop after processing N PDF files (useful for testing)",
    )
    args = parser.parse_args()

    pdfs = collect_pdfs(args.path)
    if not pdfs:
        print(f"ERROR: no PDF files found at {args.path}", file=sys.stderr)
        sys.exit(1)

    if args.limit:
        pdfs = pdfs[: args.limit]

    if args.output:
        db_path = args.output
    else:
        staging_dir = os.path.join(os.path.dirname(__file__), "..", "staging_dbs")
        os.makedirs(staging_dir, exist_ok=True)
        db_path = os.path.join(staging_dir, "jn_unit_bom.db")

    db_path = os.path.abspath(db_path)
    image_dir = os.path.splitext(db_path)[0] + "_images"

    if os.path.exists(db_path):
        os.remove(db_path)
    if os.path.exists(image_dir):
        shutil.rmtree(image_dir)
    os.makedirs(image_dir, exist_ok=True)

    print(f"Input:  {args.path}")
    print(f"PDFs:   {len(pdfs):,}")
    print(f"Output: {db_path}")
    print(f"Images: {image_dir}")
    print()

    conn = create_staging_db(db_path)

    total_products  = 0
    total_bom_items = 0
    total_refs      = 0
    total_images    = 0
    errors          = 0
    start           = time.time()

    prod_batch = []
    bom_batch  = []
    ref_batch  = []
    img_batch  = []
    BATCH_SIZE = 2000

    def flush():
        nonlocal total_products, total_bom_items, total_refs, total_images
        if prod_batch:
            conn.executemany(
                "INSERT INTO jn_unit_products "
                "(jn_number,description,unit_type,oem,voltage,power,amps,"
                "rotation,starter_type,num_teeth,status,category,source_file) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                prod_batch,
            )
            total_products += len(prod_batch)
            prod_batch.clear()
        if bom_batch:
            conn.executemany(
                "INSERT INTO jn_unit_bom_items "
                "(jn_unit_number,component_description,notes,qty,"
                "jn_number,jn_qty,oem_number,oem_qty,sort_order) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                bom_batch,
            )
            total_bom_items += len(bom_batch)
            bom_batch.clear()
        if ref_batch:
            conn.executemany(
                "INSERT INTO jn_unit_references "
                "(jn_unit_number,ref_type,manufacturer,ref_number) "
                "VALUES (?,?,?,?)",
                ref_batch,
            )
            total_refs += len(ref_batch)
            ref_batch.clear()
        if img_batch:
            conn.executemany(
                "INSERT INTO jn_unit_images "
                "(jn_unit_number,page_number,image_path,width,height,xref) "
                "VALUES (?,?,?,?,?,?)",
                img_batch,
            )
            total_images += len(img_batch)
            img_batch.clear()
        conn.commit()

    for file_idx, pdf_path in enumerate(pdfs, 1):
        result = process_pdf(pdf_path, image_dir)
        if result is None:
            errors += 1
        else:
            product, bom_items, references, image = result
            jn_num = product["jn_number"]

            prod_batch.append((
                jn_num,
                product["description"],
                product["unit_type"],
                product["oem"],
                product["voltage"],
                product["power"],
                product["amps"],
                product["rotation"],
                product["starter_type"],
                product["num_teeth"],
                product["status"],
                product["category"],
                os.path.basename(pdf_path),
            ))

            for order, item in enumerate(bom_items):
                bom_batch.append((
                    jn_num,
                    item["component_description"],
                    item["notes"],
                    item["qty"],
                    item["jn_number"],
                    item["jn_qty"],
                    item["oem_number"],
                    item["oem_qty"],
                    order,
                ))

            for ref_type, mfr, ref_num in references:
                ref_batch.append((jn_num, ref_type, mfr, ref_num))
            if image:
                img_batch.append((
                    image["jn_unit_number"],
                    image["page_number"],
                    image["image_path"],
                    image["width"],
                    image["height"],
                    image["xref"],
                ))

        if len(prod_batch) >= BATCH_SIZE:
            flush()

        if file_idx % 250 == 0 or file_idx == len(pdfs):
            elapsed = time.time() - start
            rate = file_idx / elapsed if elapsed > 0 else 0
            eta = (len(pdfs) - file_idx) / rate if rate > 0 else 0
            print(
                f"  {file_idx:>6,}/{len(pdfs):,}  |  "
                f"products: {total_products + len(prod_batch):>7,}  "
                f"BOM rows: {total_bom_items + len(bom_batch):>8,}  "
                f"refs: {total_refs + len(ref_batch):>6,}  "
                f"images: {total_images + len(img_batch):>6,}  |  "
                f"{rate:.1f} files/sec  ETA {eta:.0f}s"
            )

    flush()

    elapsed = time.time() - start

    p_count = conn.execute("SELECT COUNT(*) FROM jn_unit_products").fetchone()[0]
    b_count = conn.execute("SELECT COUNT(*) FROM jn_unit_bom_items").fetchone()[0]
    r_count = conn.execute("SELECT COUNT(*) FROM jn_unit_references").fetchone()[0]
    i_count = conn.execute("SELECT COUNT(*) FROM jn_unit_images").fetchone()[0]
    u_count = conn.execute(
        "SELECT COUNT(DISTINCT jn_unit_number) FROM jn_unit_bom_items"
    ).fetchone()[0]

    conn.close()

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  PDFs processed:    {len(pdfs) - errors:>10,}  ({errors} errors)")
    print(f"  Unit products:     {p_count:>10,}")
    print(f"  BOM line items:    {b_count:>10,}")
    print(f"  Units with BOM:    {u_count:>10,}")
    print(f"  Reference entries: {r_count:>10,}")
    print(f"  Image rows:        {i_count:>10,}")
    print(f"  Time elapsed:      {elapsed:>10.1f}s")
    print()
    print(f"Staging DB: {db_path}")
    print(f"Image dir:   {image_dir}")


if __name__ == "__main__":
    main()
