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

# Map normalized attribute keys (from PDF) to our staging column names.
# PyMuPDF extracts attribute names and values on alternate lines; the name
# line is lowercased and spaces replaced with underscores.
ATTR_KEY_MAP = {
    # -- Shared --
    "manufacture": "manufacture",
    "oe_manufacturer": "oe_manufacturer",
    "family": "family",
    "voltage": "voltage",
    "mounting_type": "mounting_type",
    "series": "series",
    # -- Alternator --
    "amperage_rating": "amperage_rating",
    "fan_type": "fan_type",
    "regulator_type": "regulator_type",
    "rotation_direction": "rotation",
    "ground_type": "ground_type",
    "ground_polarity": "ground_type",
    "mounting_ear_quantity": "mounting_ear_quantity",
    "plug_type": "plug_type",
    "plug_clock_rear_view": "plug_clocking",
    "plug_clock_rear_view_main_mounting_ear_at": "plug_clocking",
    "pulley_belt_type": "belt_type",
    "pulley_groove_quantity": "pulley_grooves",
    "pulley_class": "pulley_type",
    "pulley_outside_diameter": "pulley_od",
    "outside_diameter": "pulley_od",
    "decoupled": "decoupled",
    "decoupled_or_clutch_pulley": "decoupled",
    "stator_type": "stator_type",
    "stator_leads": "stator_type",
    # -- Generator --
    "circuit_type": "circuit_type",
    "generator_rotation": "rotation",
    # -- Starter --
    "starter_rotation": "rotation",
    "design": "design",
    "power_rating": "power_rating",
    "kw": "power_rating",
    "tooth_quantity": "tooth_quantity",
    "case_grounding": "case_grounding",
    "nose_cone_type": "nose_cone_type",
    "over-crank_protection": "over_crank_protection",
    "solenoid_attached": "solenoid_attached",
    "re-clockable_flange": "reclockable_flange",
    "spline_quantity": "spline_quantity",
    "starter_drive_housing_position": "drive_housing_position",
    "mounting_bolt_hole_quantity": "bolt_holes",
    "mounting_hardware_included": "with_hardware",
    "mounting_shims_included": "with_mounting_shims",
}


def _clean_interchange_number(num):
    """Fix line-wrap artifacts in interchange numbers (e.g. '240- 025' -> '240-025')."""
    num = num.strip()
    num = re.sub(r"-\s+", "-", num)
    num = re.sub(r"\s+-", "-", num)
    return num


# ---------------------------------------------------------------------------
# Fix R1 — Per-page column midpoint from block geometry
# ---------------------------------------------------------------------------

def compute_page_midpoint(page) -> float:
    """Pick a column-split x using block geometry; fall back to page_width/2.

    Buyers Guide pages are two-column.  Some pages have shifted margins
    (left column at x0~27 instead of ~87), which moves the gutter left.

    Two-pass approach:
      1. Find the column gap via the largest horizontal gap between block
         x0 values (ignoring full-width header blocks).
      2. Refine using the right edges of left-column blocks and left edges
         of right-column blocks for a precise gutter midpoint.
    """
    width = page.rect.width
    naive = width / 2.0
    blocks = page.get_text("blocks") or []
    if not blocks:
        return naive

    # Exclude full-width blocks (page headers) and page-number blocks
    # ("Pg. NNN") whose far-right x0 creates false column gaps.
    narrow = [b for b in blocks
              if (b[2] - b[0]) < width * 0.6
              and not re.match(r"Pg\.\s*\d", (b[4] or "").strip())]
    if len(narrow) < 2:
        return naive

    # Pass 1: find the largest gap between sorted x0 values
    x0s = sorted(b[0] for b in narrow)
    max_gap = 0
    gap_idx = 0
    for i in range(len(x0s) - 1):
        gap = x0s[i + 1] - x0s[i]
        if gap > max_gap:
            max_gap = gap
            gap_idx = i

    if max_gap < 40:
        return naive

    rough_mid = (x0s[gap_idx] + x0s[gap_idx + 1]) / 2.0

    # Pass 2: refine using column edges
    left_x1s = [b[2] for b in narrow if b[0] < rough_mid]
    right_x0s = [b[0] for b in narrow if b[0] >= rough_mid]
    if left_x1s and right_x0s:
        refined = (max(left_x1s) + min(right_x0s)) / 2.0
        if width * 0.2 < refined < width * 0.8:
            return refined

    if width * 0.2 < rough_mid < width * 0.8:
        return rough_mid

    return naive


def _classify_block_column(block, mid: float) -> str:
    """Classify a text block as LEFT or RIGHT using hybrid gutter logic.

    Default: center-based classification ((x0+x1)/2 vs mid).
    Gutter guard: blocks whose center falls within a narrow band around mid
    (mid-40 to mid+10) are classified by their *majority side* — if more
    than half the block's width lies to the right of mid, it goes RIGHT.

    This correctly handles:
      - Section labels that straddle the gutter (x0~292, x1~351, width=59,
        majority right of mid~338) → RIGHT
      - Normal left-column content (x1 well below mid) → LEFT
      - Normal right-column content (x0 well above mid) → RIGHT
      - Regression cases from pure right-edge logic → back to LEFT
    """
    x0, x1 = block[0], block[2]
    center = (x0 + x1) / 2.0
    width = x1 - x0

    # Gutter zone: center is within [mid-40, mid+10]
    if (mid - 40) < center < (mid + 10) and width > 0:
        # Use majority-side: how much of the block is right of mid?
        right_portion = max(0, x1 - mid)
        if right_portion > width / 2.0:
            return "R"
        return "L"

    # Default: center-based
    if center < mid:
        return "L"
    return "R"


def _column_lines(page, mid: float):
    """Yield (col_name, [lines]) for left column then right column.

    Hybrid gutter-aware classification (Fix X v2):
    The buyers-guide PDFs draw right-column section header labels
    ("APPLICATIONS", "PRODUCT ATTRIBUTES", etc.) as blocks that straddle
    the gutter (x0 ~292, x1 ~351).  Pure center-based classification
    pulled those labels into LEFT (causing xref-leak into app_map).
    Pure right-edge classification fixed that but over-corrected on
    pages where legitimate left-column content has x1 near mid.

    Solution: classify by center as default, but for blocks in the gutter
    zone (center within [mid-40, mid+10]), use majority-side logic —
    blocks with >50% of their width right of mid go RIGHT.
    """
    blocks = page.get_text("blocks") or []
    left_blocks = []
    right_blocks = []
    for b in blocks:
        if _classify_block_column(b, mid) == "L":
            left_blocks.append(b)
        else:
            right_blocks.append(b)

    left_blocks.sort(key=lambda b: (b[1], b[0]))
    right_blocks.sort(key=lambda b: (b[1], b[0]))

    for col_name, col_blocks in (("L", left_blocks), ("R", right_blocks)):
        col_lines: list[str] = []
        for block in col_blocks:
            for ln in (block[4] or "").split("\n"):
                ln = ln.strip()
                if ln:
                    col_lines.append(ln)
        yield col_name, col_lines


# ---------------------------------------------------------------------------
# Fix C / C-extension — line-wrap rejoin for year ranges and J&N numbers
# ---------------------------------------------------------------------------

_TRAILING_YR_DASH = re.compile(r"\d{4}-\s*$")
_LEADING_YR = re.compile(r"^\d{4}\b")
_LEADING_DASH_YR = re.compile(r"^-\d{4}\b")
_TRAILING_JN_DASH = re.compile(r"\d-\s*$")
_LEADING_DIGITS = re.compile(r"^\d")


def rejoin_year_wrap(lines):
    """Rejoin lines where a year range or J&N number was split across lines.

    Patterns rejoined:
      * 'Model 2000-' + '2002 ...'        -> 'Model 2000-2002 ...'
      * 'Model 2000' + '-2002 ...'        -> 'Model 2000-2002 ...'
      * 'J&N 130-' + '05002'              -> '130-05002'

    Also handles the C-extension case: engine descriptions whose year-range
    fragment ('engine ... 2000-') wraps to the next line ('2002 ...'), which
    leaks the year into the engine text.  Same rejoin pattern fixes both.

    Returns (rejoined_lines, n_rejoins).
    """
    out: list[str] = []
    rejoins = 0
    i = 0
    n = len(lines)
    while i < n:
        cur = lines[i].rstrip()
        if i + 1 < n:
            nxt = lines[i + 1].lstrip()
            if _TRAILING_YR_DASH.search(cur) and _LEADING_YR.match(nxt):
                out.append(cur + nxt)
                rejoins += 1
                i += 2
                continue
            if _LEADING_DASH_YR.match(nxt) and re.search(r"\d{4}\s*$", cur):
                out.append(cur + nxt)
                rejoins += 1
                i += 2
                continue
            if (
                _TRAILING_JN_DASH.search(cur)
                and _LEADING_DIGITS.match(nxt)
                and len(cur) < 30
            ):
                out.append(cur + nxt)
                rejoins += 1
                i += 2
                continue
        out.append(cur)
        i += 1
    return out, rejoins


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
                num = _clean_interchange_number(num)
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


def parse_document(doc, limit=None, image_db_conn=None, start_page=0):
    """
    Parse entire PDF document into products, interchanges, bom items,
    substitutes, and images.

    If image_db_conn is provided, images are written directly to the DB
    instead of accumulating in memory (critical for large PDFs).
    start_page allows processing a subset of pages (for chunked processing).
    """
    # Accumulators keyed by YouTech number (de-duplicate by YT#)
    product_map = {}       # yt -> dict of attributes
    jn_map = {}            # yt -> list of J&N numbers (order-preserved, unique)
    interchange_map = {}   # (yt, mfr, num) -> True  (de-duplicate)
    bom_map = {}           # yt -> list of (part_name, yt_part, jn_part)
    sub_map = {}           # yt -> list of (sub_yt, sub_jn)
    image_map = {}         # yt -> (image_bytes, ext) — only used if no image_db_conn
    app_map = {}           # yt -> list of raw application text lines
    images_saved = 0

    total_pages = doc.page_count
    if limit:
        total_pages = min(total_pages, limit)

    first_page = start_page

    current_yt = ""
    current_jn = ""
    current_section = ""
    current_attrs = {}
    interchange_buffer = ""
    notes_pending = False  # True while accumulating multi-line Product Notes

    # BOM parsing state
    bom_pending_name = ""
    bom_pending_yt = ""
    bom_pending_jn = ""

    def flush_bom_pending():
        nonlocal bom_pending_name, bom_pending_yt, bom_pending_jn
        if bom_pending_name and bom_pending_yt and current_yt:
            # Clean up line-wrap artifacts in J&N (e.g. "130- 05002" → "130-05002")
            jn_clean = re.sub(r'-\s+', '-', bom_pending_jn)
            jn_clean = re.sub(r'\s+-', '-', jn_clean)
            jn_clean = re.sub(r'\s+', ' ', jn_clean).strip().rstrip(",")
            bom_map[current_yt].append(
                (bom_pending_name, bom_pending_yt, jn_clean)
            )
        bom_pending_name = ""
        bom_pending_yt = ""
        bom_pending_jn = ""

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

    for page_idx in range(first_page, total_pages):
        page = doc[page_idx]

        # --- Image extraction for this page ---
        unit_positions = _extract_unit_positions(page)
        page_images = _extract_page_images(page, doc)
        if unit_positions and page_images:
            page_width = page.rect.width
            matched = _match_images_to_units(unit_positions, page_images, page_width)
            for yt, img_data in matched.items():
                if image_db_conn:
                    try:
                        image_db_conn.execute(
                            "INSERT OR IGNORE INTO buyers_guide_images "
                            "(youtech_number, image_data, image_ext) VALUES (?, ?, ?)",
                            (yt, img_data[0], img_data[1]),
                        )
                        images_saved += 1
                    except Exception:
                        pass
                elif yt not in image_map:
                    image_map[yt] = img_data

        # Fix R1 / B — column-aware text walk (left column, then right column)
        # rather than a single page.get_text() stream that can interleave
        # blocks across the two-column layout.
        mid = compute_page_midpoint(page)
        page_lines = []
        for _col_name, col_lines in _column_lines(page, mid):
            page_lines.extend(col_lines)

        for raw_line in page_lines:
            line = raw_line.strip()
            if not line:
                continue

            # Skip page headers
            if line in ("BUYERS GUIDE", "TILT & TRIM MOTORS",
                        "MILD HYBRID MOTOR/GENERATORS",
                        "ALTERNATORS", "STARTERS", "GENERATORS",
                        "BUYERS GUIDE ALTERNATORS",
                        "ALTERNATORS BUYERS GUIDE",
                        "BUYERS GUIDE STARTERS",
                        "STARTERS BUYERS GUIDE",
                        "BUYERS GUIDE GENERATORS",
                        "GENERATORS BUYERS GUIDE"):
                continue

            # Check for new product header
            m = YOUTECH_HEADER_RE.match(line)
            if m:
                if "(Cont.)" in line:
                    # Continuation header — keep current parsing state
                    continue

                # Flush pending data before starting a new product
                flush_interchanges()
                flush_product()
                flush_bom_pending()

                current_yt = m.group(1)
                current_jn = m.group(2) or ""
                current_section = ""
                current_attrs = {}
                notes_pending = False

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
                flush_bom_pending()
                notes_pending = False
                current_section = clean
                continue

            if not current_yt:
                continue

            # Skip continuation headers like "YouTech #310002 /J&N #400-40020 (Cont.)"
            if "(Cont.)" in line:
                continue

            # Product Notes can appear before or inside PRODUCT ATTRIBUTES
            if line.startswith("Product Notes:") or line.startswith('Product Notes: "'):
                notes_text = line.split(":", 1)[1].strip().strip('"')
                current_attrs["product_notes"] = notes_text
                notes_pending = True
                continue

            # Continuation of multi-line Product Notes (before a section header)
            if notes_pending:
                current_attrs["product_notes"] += " " + line
                continue

            # --- PRODUCT ATTRIBUTES ---
            if current_section == "PRODUCT ATTRIBUTES":
                if "_pending_attr_key" in current_attrs:
                    key = current_attrs.pop("_pending_attr_key")
                    mapped = ATTR_KEY_MAP.get(key, key)
                    current_attrs[mapped] = line
                else:
                    normalized = line.lower().replace(" ", "_")
                    if normalized in ATTR_KEY_MAP:
                        current_attrs["_pending_attr_key"] = normalized
                    elif re.match(r"^\d+$", line) and current_attrs:
                        last_keys = [k for k in current_attrs if k != "_pending_attr_key"]
                        if last_keys:
                            last = last_keys[-1]
                            if not current_attrs[last]:
                                current_attrs[last] = line
                    else:
                        current_attrs["_pending_attr_key"] = normalized

            # --- INTERCHANGES ---
            elif current_section == "INTERCHANGES":
                interchange_buffer += " " + line if interchange_buffer else line

            # --- BILL OF MATERIALS ---
            elif current_section == "BILL OF MATERIALS":
                # Fix I — Skip the column header words "BOM / YOUTECH / J&N"
                # ANYWHERE inside the BOM section.  Multi-page BOMs repeat the
                # column header on each new page; the old gate that only ran
                # at the start of the section would otherwise consume them as
                # part names.
                if line in ("BOM", "YOUTECH", "J&N"):
                    continue

                # Skip page numbers
                if re.match(r'^Pg\.\s*\d+', line):
                    continue

                # If we have name + yt already, accumulate J&N lines
                # (J&N values can wrap; may include letter suffixes like 301-12015R)
                if bom_pending_yt and re.match(r'^\d[\dA-Za-z\-, ]*$', line):
                    bom_pending_jn += " " + line if bom_pending_jn else line
                    continue

                # When we have a pending part name awaiting its part number,
                # check for part-number patterns FIRST (before the part-name
                # check, which would incorrectly consume "TE-10000" etc.)
                if bom_pending_name and not bom_pending_yt:
                    # YouTech part number (e.g. 1A-6103, TE-10000, 2D-30424)
                    if re.match(r'^[A-Z0-9]{1,4}-', line):
                        bom_pending_yt = line
                        continue
                    # Bearing/part number starting with digits (e.g. 6201-2RS)
                    if re.match(r'^\d{3,}', line):
                        bom_pending_yt = line
                        continue

                # A new part name (starts with a letter, not a YouTech header)
                if re.match(r'^[A-Za-z]', line) and not line.startswith("YouTech"):
                    flush_bom_pending()
                    bom_pending_name = line

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
                if re.match(r"^Pg\.\s*\d+", line):
                    continue
                if current_yt not in app_map:
                    app_map[current_yt] = []
                app_map[current_yt].append(line)

        # Flush last BOM pending item if we hit end of page mid-item
        flush_bom_pending()

        # Free the page object to release memory (critical for large PDFs)
        del page

        if (page_idx + 1) % 100 == 0 or page_idx == total_pages - 1:
            img_ct = images_saved if image_db_conn else len(image_map)
            print(
                f"  Page {page_idx + 1:>5}/{total_pages}  |  "
                f"units: {len(product_map):>5}  |  "
                f"xrefs: {len(interchange_map):>7}  |  "
                f"images: {img_ct:>5}",
                flush=True,
            )
            if image_db_conn and (page_idx + 1) % 500 == 0:
                image_db_conn.commit()

    # Final flush
    flush_interchanges()
    flush_product()

    # Build products list with combined J&N numbers and all attributes
    products = []
    for yt, attrs in product_map.items():
        # Remove internal parsing keys
        attrs.pop("_pending_attr_key", None)
        jns = jn_map.get(yt, [])
        jn_combined = " | ".join(jns) if jns else ""
        products.append({
            "youtech_number": yt,
            "jn_number": jn_combined,
            "manufacture": attrs.get("manufacture", ""),
            "oe_manufacturer": attrs.get("oe_manufacturer", ""),
            "family": attrs.get("family", ""),
            "voltage": attrs.get("voltage", ""),
            "rotation": attrs.get("rotation", ""),
            "product_notes": attrs.get("product_notes", ""),
            "amperage_rating": attrs.get("amperage_rating", ""),
            "fan_type": attrs.get("fan_type", ""),
            "regulator_type": attrs.get("regulator_type", ""),
            "plug_type": attrs.get("plug_type", ""),
            "plug_clocking": attrs.get("plug_clocking", ""),
            "belt_type": attrs.get("belt_type", ""),
            "pulley_grooves": attrs.get("pulley_grooves", ""),
            "pulley_type": attrs.get("pulley_type", ""),
            "pulley_od": attrs.get("pulley_od", ""),
            "ground_type": attrs.get("ground_type", ""),
            "decoupled": attrs.get("decoupled", ""),
            "stator_type": attrs.get("stator_type", ""),
            "series": attrs.get("series", ""),
            "mounting_type": attrs.get("mounting_type", ""),
            # Generator-specific
            "circuit_type": attrs.get("circuit_type", ""),
            # Starter-specific
            "design": attrs.get("design", ""),
            "power_rating": attrs.get("power_rating", ""),
            "tooth_quantity": attrs.get("tooth_quantity", ""),
            "case_grounding": attrs.get("case_grounding", ""),
            "nose_cone_type": attrs.get("nose_cone_type", ""),
            "over_crank_protection": attrs.get("over_crank_protection", ""),
            "solenoid_attached": attrs.get("solenoid_attached", ""),
            "reclockable_flange": attrs.get("reclockable_flange", ""),
            "spline_quantity": attrs.get("spline_quantity", ""),
            "drive_housing_position": attrs.get("drive_housing_position", ""),
            "bolt_holes": attrs.get("bolt_holes", ""),
            "with_hardware": attrs.get("with_hardware", ""),
            "with_mounting_shims": attrs.get("with_mounting_shims", ""),
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

    # Combine raw application lines per unit into a single text blob.
    # Fix C / C-extension — rejoin lines where a year range was split across
    # lines.  This catches both year-column wraps ('1998-' + '2002') and
    # engine-text wraps (engine description ending in '... 1998-' continued
    # on the next line with '2002 ...').  Applying once here keeps the
    # importer's _parse_application_text simple.
    applications = []
    for yt, lines in app_map.items():
        rejoined, _ = rejoin_year_wrap(lines)
        app_text = "\n".join(rejoined)
        if app_text.strip():
            applications.append((yt, app_text))

    return products, interchanges, bom_items, substitutes, image_map, applications


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
            product_notes TEXT NOT NULL DEFAULT '',
            amperage_rating TEXT NOT NULL DEFAULT '',
            fan_type TEXT NOT NULL DEFAULT '',
            regulator_type TEXT NOT NULL DEFAULT '',
            plug_type TEXT NOT NULL DEFAULT '',
            plug_clocking TEXT NOT NULL DEFAULT '',
            belt_type TEXT NOT NULL DEFAULT '',
            pulley_grooves TEXT NOT NULL DEFAULT '',
            pulley_type TEXT NOT NULL DEFAULT '',
            pulley_od TEXT NOT NULL DEFAULT '',
            ground_type TEXT NOT NULL DEFAULT '',
            decoupled TEXT NOT NULL DEFAULT '',
            stator_type TEXT NOT NULL DEFAULT '',
            series TEXT NOT NULL DEFAULT '',
            mounting_type TEXT NOT NULL DEFAULT '',
            circuit_type TEXT NOT NULL DEFAULT '',
            design TEXT NOT NULL DEFAULT '',
            power_rating TEXT NOT NULL DEFAULT '',
            tooth_quantity TEXT NOT NULL DEFAULT '',
            case_grounding TEXT NOT NULL DEFAULT '',
            nose_cone_type TEXT NOT NULL DEFAULT '',
            over_crank_protection TEXT NOT NULL DEFAULT '',
            solenoid_attached TEXT NOT NULL DEFAULT '',
            reclockable_flange TEXT NOT NULL DEFAULT '',
            spline_quantity TEXT NOT NULL DEFAULT '',
            drive_housing_position TEXT NOT NULL DEFAULT '',
            bolt_holes TEXT NOT NULL DEFAULT '',
            with_hardware TEXT NOT NULL DEFAULT '',
            with_mounting_shims TEXT NOT NULL DEFAULT ''
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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS buyers_guide_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            youtech_number TEXT NOT NULL,
            application_text TEXT NOT NULL DEFAULT ''
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_bg_yt ON buyers_guide_products(youtech_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bg_their ON buyers_guide_interchanges(their_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bg_our ON buyers_guide_interchanges(our_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bg_bom_yt ON buyers_guide_bom(youtech_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bg_sub_yt ON buyers_guide_substitutes(youtech_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bg_img_yt ON buyers_guide_images(youtech_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bg_app_yt ON buyers_guide_applications(youtech_number)")
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

    print(f"PDF:    {args.pdf_path}", flush=True)
    print(f"Output: {db_path}", flush=True)
    print(flush=True)

    # Create staging DB first so images can be written incrementally
    conn = create_staging_db(db_path)

    doc = fitz.open(args.pdf_path)
    total_pages = doc.page_count
    if args.limit:
        total_pages = min(total_pages, args.limit)
    print(f"Total pages: {total_pages:,}", flush=True)

    start_time = time.time()

    _PRODUCT_COLS = (
        "youtech_number", "jn_number", "manufacture", "oe_manufacturer",
        "family", "voltage", "rotation", "product_notes", "amperage_rating",
        "fan_type", "regulator_type", "plug_type", "plug_clocking",
        "belt_type", "pulley_grooves", "pulley_type", "pulley_od",
        "ground_type", "decoupled", "stator_type", "series", "mounting_type",
        "circuit_type", "design", "power_rating", "tooth_quantity", "case_grounding",
        "nose_cone_type", "over_crank_protection", "solenoid_attached",
        "reclockable_flange", "spline_quantity", "drive_housing_position",
        "bolt_holes", "with_hardware", "with_mounting_shims",
    )
    _placeholders = ", ".join("?" * len(_PRODUCT_COLS))

    def _flush_chunk_to_db(products, interchanges, bom_items, substitutes, image_map, applications):
        """Write one chunk's parsed data to the staging DB immediately."""
        if products:
            conn.executemany(
                f"INSERT INTO buyers_guide_products ({', '.join(_PRODUCT_COLS)}) "
                f"VALUES ({_placeholders})",
                [tuple(p[c] for c in _PRODUCT_COLS) for p in products],
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
        if image_map:
            for yt, (img_bytes, img_ext) in image_map.items():
                conn.execute(
                    "INSERT OR REPLACE INTO buyers_guide_images (youtech_number, image_data, image_ext) "
                    "VALUES (?, ?, ?)",
                    (yt, img_bytes, img_ext),
                )
        if applications:
            conn.executemany(
                "INSERT INTO buyers_guide_applications (youtech_number, application_text) "
                "VALUES (?, ?)",
                applications,
            )
        conn.commit()

    CHUNK = 500
    for chunk_start in range(0, total_pages, CHUNK):
        chunk_end = min(chunk_start + CHUNK, total_pages)
        print(f"\n--- Processing pages {chunk_start + 1}-{chunk_end} ---", flush=True)

        if chunk_start > 0:
            doc.close()
            import gc
            gc.collect()
            doc = fitz.open(args.pdf_path)

        result = parse_document(
            doc, limit=chunk_end, image_db_conn=conn,
            start_page=chunk_start,
        )
        products, interchanges, bom_items, substitutes, image_map, applications = result
        _flush_chunk_to_db(products, interchanges, bom_items, substitutes, image_map, applications)
        del products, interchanges, bom_items, substitutes, image_map, applications, result

    doc.close()
    import gc
    gc.collect()

    elapsed = time.time() - start_time

    prod_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_products").fetchone()[0]
    xref_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_interchanges").fetchone()[0]
    bom_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_bom").fetchone()[0]
    sub_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_substitutes").fetchone()[0]
    img_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_images").fetchone()[0]
    app_count = conn.execute("SELECT COUNT(*) FROM buyers_guide_applications").fetchone()[0]
    conn.close()

    print(flush=True)
    print("=" * 60, flush=True)
    print("SUMMARY", flush=True)
    print("=" * 60, flush=True)
    print(f"  Products (unique YT#):     {prod_count:>10,}", flush=True)
    print(f"  Interchange records:       {xref_count:>10,}", flush=True)
    print(f"  BOM line items:            {bom_count:>10,}", flush=True)
    print(f"  Substitute pairs:          {sub_count:>10,}", flush=True)
    print(f"  Unit images extracted:     {img_count:>10,}", flush=True)
    print(f"  Application entries:       {app_count:>10,}", flush=True)
    print(f"  Time elapsed:              {elapsed:>10.1f}s", flush=True)
    print(flush=True)
    print(f"Staging DB saved to: {db_path}", flush=True)


if __name__ == "__main__":
    main()
