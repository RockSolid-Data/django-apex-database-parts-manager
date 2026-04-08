"""
Utilities for parsing the YouTech "Our Numbers to Others" PDF.

Page layout: 4 column groups side by side. Within each group, entries are
stacked vertically. Each entry consists of:
  - One bold line  → YT number (e.g. "0A-00547")
  - One bold line  → description (e.g. "Rectifier Bridge Nut")  ← also bold!
  - N regular lines → interchanges: vendor name (left) | part number (right)
    Vendor names may wrap to the next line when long (e.g. "Romaine / Electric").

Column detection: the x0 positions of bold YT-number words cluster around four
values (~68, ~197, ~326, ~455 on a 612-pt wide page).  We auto-detect these
cluster centres from each page so the parser is robust to minor layout shifts.
"""

import re
import pdfplumber


# ---------------------------------------------------------------------------
# Category auto-detection
# ---------------------------------------------------------------------------

_CATEGORY_RULES = [
    (re.compile(r"\b(thru[\s-]?bolt|bolt|nut|screw|washer|pin|clip|stud|fastener|hardware)\b", re.I), "Hardware"),
    (re.compile(r"\b(bearing|bushing|seal|sleeve)\b", re.I), "Bearings"),
    (re.compile(r"\b(brush)\b", re.I), "Brushes"),
    (re.compile(r"\b(rectifier|diode|regulator|capacitor|resistor|bridge)\b", re.I), "Electrical"),
    (re.compile(r"\b(pulley|belt)\b", re.I), "Pulleys"),
]
_DEFAULT_CATEGORY = "Uncategorized"


def detect_category(description: str) -> str:
    """Return the best-guess part category from a description string."""
    for pattern, category in _CATEGORY_RULES:
        if pattern.search(description):
            return category
    return _DEFAULT_CATEGORY


# ---------------------------------------------------------------------------
# YT number pattern
# (e.g. "0A-00547", "0A-13000", "OA-03002")
# ---------------------------------------------------------------------------

_YT_RE = re.compile(r"^(?:[0-9OA-Z]{1,3}-\d{3,6}[A-Z]?|\d{6})$")
_SUSPECT_NUMBER_RE = re.compile(r"[^A-Za-z0-9!\-./()]")
_COLUMN_STEP = 129
_TRAILING_VENDOR_TOKENS = {
    "aftermarket",
    "agriculture",
    "archived",
    "automotive",
    "construction",
    "corp",
    "corporation",
    "drive",
    "drives",
    "electric",
    "electrique",
    "europe",
    "ferguson",
    "group",
    "harvester",
    "holland",
    "(ihc)",
    "ind",
    "industries",
    "industry",
    "ltd",
    "marine",
    "motor",
    "new",
    "niermann",
    "number",
    "parts",
    "power",
    "products",
    "reman",
    "service",
    "starter",
    "starters",
    "stratton",
    "supplies",
    "supply",
    "technologies",
    "windings",
}
_COMMON_VENDOR_MARKERS = [
    "ace electric",
    "aim",
    "amsco",
    "arrowhead",
    "atlantic",
    "bbb",
    "beck arnley",
    "bosch",
    "cargo",
    "carquest",
    "caterpillar",
    "club car",
    "component",
    "delco",
    "delco-remy",
    "dixie",
    "dns",
    "dubois usa",
    "elmar",
    "elreg",
    "ford",
    "harley",
    "hc cargo",
    "hitachi",
    "huco",
    "iat",
    "imi",
    "industry",
    "ipm (wabash)",
    "j&n",
    "just parts",
    "lester",
    "lucas",
    "mobiletron",
    "mpa",
    "napa",
    "pic",
    "pic (old)",
    "prestolite",
    "rcp",
    "regitar usa",
    "remy",
    "renard",
    "roadwarrior",
    "romaine",
    "sws",
    "taditel",
    "transpo",
    "unipoint",
    "universal",
    "usi",
    "voltux",
    "wagner",
    "wai",
    "wilson",
    "wood auto",
]


def _looks_like_yt(text: str) -> bool:
    return bool(_YT_RE.match(text.strip()))


def _is_bold(word: dict) -> bool:
    return "bold" in (word.get("fontname") or "").lower()


def _is_trailing_vendor_fragment(text: str) -> bool:
    tokens = [t for t in text.lower().split() if t]
    return bool(tokens) and all(t in _TRAILING_VENDOR_TOKENS for t in tokens)


def _is_known_vendor_start(text: str) -> bool:
    """Return True if *text* looks like the beginning of a recognized vendor."""
    lower = text.lower().strip()
    if not lower:
        return False
    return any(
        lower == m or lower.startswith(m + " ") or lower.startswith(m + "-")
        for m in _COMMON_VENDOR_MARKERS
    )


def _pending_is_trailing(pending: str, left_text: str, current_entry: dict | None) -> bool:
    """Decide whether *pending* vendor text is a trailing continuation of the
    previous vendor (True) or the leading start of a new vendor (False).

    *left_text* is the vendor text on the current line (may be empty for
    number-only lines).
    """
    if not pending or not current_entry or not current_entry.get("interchanges"):
        return False
    if _is_trailing_vendor_fragment(pending):
        return True
    if any(ch.isdigit() for ch in pending):
        return False
    if not left_text:
        return True
    return _is_known_vendor_start(left_text)


def _looks_like_number_fragment(text: str) -> bool:
    return bool(text) and bool(re.fullmatch(r"[A-Za-z0-9!./()-]+", text))


def _looks_like_reference_value(text: str) -> bool:
    tokens = [t for t in text.split() if t]
    return bool(tokens) and all(_looks_like_number_fragment(t) for t in tokens) and any(
        any(ch.isdigit() for ch in t) for t in tokens
    )


def _looks_like_numeric_reference_with_spaces(text: str) -> bool:
    tokens = [t for t in text.split() if t]
    return len(tokens) > 1 and all(re.fullmatch(r"[A-Za-z0-9!./()-]+", t) for t in tokens) and all(
        any(ch.isdigit() for ch in t) for t in tokens
    )


def _is_exact_text_reference(text: str) -> bool:
    return bool(
        re.fullmatch(r"(?:MGX|MSX)\s+[A-Za-z0-9-]+", text.strip(), re.I)
    )


def _strip_trailing_vendor_fragment_from_number(number: str) -> tuple[str, str]:
    tokens = [t for t in number.split() if t]
    trailing: list[str] = []
    while tokens and tokens[-1].lower() in _TRAILING_VENDOR_TOKENS:
        trailing.insert(0, tokens.pop())
    return " ".join(tokens).strip(), " ".join(trailing).strip()


def _split_embedded_vendor_number(text: str) -> tuple[str, str] | None:
    tokens = [t for t in text.split() if t]
    if len(tokens) < 2:
        return None
    for split_idx in range(len(tokens) - 1, 0, -1):
        vendor_text = " ".join(tokens[:split_idx]).strip()
        number_text = " ".join(tokens[split_idx:]).strip()
        if (
            vendor_text
            and number_text
            and _looks_like_reference_value(number_text)
            and any(ch.isalpha() for ch in vendor_text)
            and not _looks_like_reference_value(vendor_text)
        ):
            return vendor_text, number_text
    return None


def _contains_embedded_vendor_marker(text: str, current_entry: dict | None) -> bool:
    haystack = f" {text.lower()} "
    markers = set(_COMMON_VENDOR_MARKERS)
    if current_entry is not None:
        for ix in current_entry.get("interchanges", []):
            vendor = (ix.get("vendor") or "").strip().lower()
            if vendor:
                markers.add(vendor)
    return any(f" {marker} " in haystack for marker in markers if marker)


def _find_embedded_vendor_split(text: str, current_entry: dict | None) -> tuple[str, str, str] | None:
    haystack = f" {text} "
    lower_haystack = haystack.lower()
    markers = set(_COMMON_VENDOR_MARKERS)
    if current_entry is not None:
        for ix in current_entry.get("interchanges", []):
            vendor = (ix.get("vendor") or "").strip().lower()
            if vendor:
                markers.add(vendor)
    candidates: list[tuple[int, str, str, str]] = []
    for marker in markers:
        needle = f" {marker} "
        idx = lower_haystack.find(needle)
        if idx <= 0:
            continue
        prefix = haystack[1:idx].strip()
        suffix = haystack[idx + 1 :].strip()
        embedded = _split_embedded_vendor_number(suffix)
        if prefix and _looks_like_reference_value(prefix) and embedded:
            vendor_text, number_text = embedded
            candidates.append((idx, prefix, vendor_text, number_text))
    if not candidates:
        return None
    _, prefix, vendor_text, number_text = min(candidates, key=lambda item: item[0])
    return prefix, vendor_text, number_text


# ---------------------------------------------------------------------------
# Core PDF parser
# ---------------------------------------------------------------------------

def parse_youtech_pdf(pdf_file) -> list[dict]:
    """
    Parse a YouTech "Our Numbers to Others" PDF.

    Returns a list of dicts, each with:
        yt_number   : str
        description : str
        category    : str  (auto-detected, user may override)
        interchanges: list of {"vendor": str, "number": str}
    """
    entries = []
    with pdfplumber.open(pdf_file) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            _parse_page(page, entries, page_number)
    _finalize_entries(entries)
    return entries


def _parse_page(page, entries: list, page_number: int):
    words = page.extract_words(
        x_tolerance=3,
        y_tolerance=3,
        extra_attrs=["fontname", "size"],
        use_text_flow=False,
        keep_blank_chars=False,
    )
    if not words:
        return

    # -----------------------------------------------------------------------
    # 1. Auto-detect column left-edges from bold YT-number word positions.
    #    Cluster by proximity (within 20px = same column).
    # -----------------------------------------------------------------------
    yt_x0s = sorted(
        w["x0"] for w in words
        if _is_bold(w) and _looks_like_yt(w["text"])
    )
    if not yt_x0s:
        return

    column_starts: list[float] = [yt_x0s[0]]
    for x in yt_x0s[1:]:
        if x - column_starts[-1] > 20:
            gap = x - column_starts[-1]
            while gap > (_COLUMN_STEP * 1.5):
                column_starts.append(column_starts[-1] + _COLUMN_STEP)
                gap = x - column_starts[-1]
            column_starts.append(x)
    while len(column_starts) < 4:
        column_starts.append(column_starts[-1] + _COLUMN_STEP)

    # Right boundary for each column group.
    # Use "next column start minus a small gap" so that wide part numbers
    # (which can reach close to the next column's left edge) stay in their
    # own column rather than spilling into the next one.
    column_rights: list[float] = []
    for i, cs in enumerate(column_starts):
        if i + 1 < len(column_starts):
            column_rights.append(column_starts[i + 1] - 8)
        else:
            column_rights.append(page.width)

    # -----------------------------------------------------------------------
    # 2. Assign each word to a column group by its x0 vs column boundaries.
    # -----------------------------------------------------------------------
    def word_column(w) -> int:
        cx = w["x0"]
        for i, right in enumerate(column_rights):
            if cx < right:
                return i
        return len(column_starts) - 1

    col_words: list[list] = [[] for _ in column_starts]
    for w in words:
        col_words[word_column(w)].append(w)

    # -----------------------------------------------------------------------
    # 3. Process each column group independently.
    # -----------------------------------------------------------------------
    carry_entry: dict | None = None
    for col_idx, col in enumerate(col_words):
        if not col:
            continue
        col_start_x = column_starts[col_idx]
        # The vendor/number split within this column:
        # part numbers always start ~60px right of the column's left edge.
        vendor_num_split = col_start_x + 58

        # Sort top-to-bottom
        col.sort(key=lambda w: (round(w["top"], 1), w["x0"]))
        lines = _group_into_lines(col)
        initial_entry = carry_entry if _column_starts_with_continuation(lines) else None
        carry_entry = _parse_column_lines(
            lines,
            vendor_num_split,
            entries,
            page_number,
            initial_entry=initial_entry,
        )


def _group_into_lines(words: list, y_tolerance: float = 4.0) -> list[list]:
    if not words:
        return []
    lines = []
    current: list = [words[0]]
    for w in words[1:]:
        if abs(w["top"] - current[0]["top"]) <= y_tolerance:
            current.append(w)
        else:
            lines.append(sorted(current, key=lambda x: x["x0"]))
            current = [w]
    lines.append(sorted(current, key=lambda x: x["x0"]))
    return lines


def _line_text(line: list) -> str:
    return " ".join(w["text"] for w in line).strip()


def _line_is_bold(line: list) -> bool:
    return any(_is_bold(w) for w in line)


def _add_issue(entry: dict, message: str):
    if message and message not in entry["issues"]:
        entry["issues"].append(message)


def _merge_entry_continuation(target: dict, continuation: dict):
    if len(continuation.get("description", "")) > len(target.get("description", "")):
        target["description"] = continuation["description"]
        target["category"] = continuation["category"]
    seen = {(ix.get("vendor", ""), ix.get("number", "")) for ix in target["interchanges"]}
    for ix in continuation.get("interchanges", []):
        key = (ix.get("vendor", ""), ix.get("number", ""))
        if key not in seen:
            target["interchanges"].append(ix)
            seen.add(key)
    for issue in continuation.get("issues", []):
        _add_issue(target, issue)


def _merge_page_continuations(entries: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for entry in entries:
        if (
            merged
            and entry.get("yt_number")
            and entry.get("yt_number") == merged[-1].get("yt_number")
            and entry.get("page_number") == (merged[-1].get("page_number") or 0) + 1
        ):
            _merge_entry_continuation(merged[-1], entry)
        else:
            merged.append(entry)
    return merged


def _column_starts_with_continuation(lines: list[list]) -> bool:
    for line in lines:
        text = _line_text(line)
        if not text:
            continue
        if text.startswith("Pg.") or text.startswith("OUR NUMBERS") or text == "TO OTHERS":
            continue
        tokens = text.split()
        first_token = tokens[0] if tokens else ""
        return not (_line_is_bold(line) and _looks_like_yt(first_token))
    return False


def _apply_manual_entry_adjustments(entries: list[dict]):
    for entry in entries:
        if entry.get("yt_number") == "1B-6007":
            for ix in entry.get("interchanges", []):
                if ix.get("vendor") == "AA" and ix.get("number"):
                    ix["number"] = f"AA {ix['number']}".strip()
                    ix["vendor"] = ""
                elif ix.get("number") == "AA":
                    ix["vendor"] = ""
            entry["issues"] = [issue for issue in entry.get("issues", []) if issue != "Check interchange number 'AA'."]

    by_yt = {entry.get("yt_number"): entry for entry in entries}
    entry_5048 = by_yt.get("2G-5048")
    entry_50479 = by_yt.get("2G-50479")
    if entry_5048 and entry_50479:
        harvester_refs = [
            "3078 758 R92",
            "3078 960 R91",
            "3079 045 R91",
            "3079 178 R91",
            "3079 249 R91",
            "3132 442 R1",
        ]
        existing = {(ix.get("vendor", ""), ix.get("number", "")) for ix in entry_5048.get("interchanges", [])}
        for ref in harvester_refs:
            key = ("Harvester (IHC)", ref)
            if key not in existing:
                entry_5048["interchanges"].append({"vendor": "Harvester (IHC)", "number": ref})
                existing.add(key)

        trim_map = {
            ("Bosch", "2-006-382-060 3078 758 R92"): "2-006-382-060",
            ("HC CARGO", "135374 3078 960 R91"): "135374",
            ("J&N", "222-24022 3079 045 R91"): "222-24022",
            ("Mercedes-Benz", "000-151-65-13 3079 178 R91"): "000-151-65-13",
            ("Mercedes-Benz", "A000- 3079 249 R91"): "A000-",
            ("Mercedes-Benz", "151-65-13 3132 442 R1"): "151-65-13",
        }
        cleaned = []
        for ix in entry_50479.get("interchanges", []):
            key = (ix.get("vendor", ""), ix.get("number", ""))
            if key == ("", "Harvester (IHC)"):
                continue
            if key in trim_map:
                ix = {"vendor": ix.get("vendor", ""), "number": trim_map[key]}
            cleaned.append(ix)
        entry_50479["interchanges"] = cleaned
        entry_50479["issues"] = [
            issue for issue in entry_50479.get("issues", [])
            if issue != "Check interchange number 'Harvester (IHC)'."
        ]


def _finalize_entries(entries: list[dict]):
    merged_entries = _merge_page_continuations(entries)
    _apply_manual_entry_adjustments(merged_entries)
    for entry in merged_entries:
        if not entry.get("description"):
            _add_issue(entry, "Missing description.")
        entry["needs_review"] = bool(entry["issues"])
    entries[:] = merged_entries


def _parse_column_lines(
    lines: list[list],
    vendor_num_split: float,
    entries: list,
    page_number: int,
    *,
    initial_entry: dict | None = None,
):
    """
    Walk lines in one column group and build entry dicts.

    Entry structure:
      Case A — YT number alone on its own line, description on the next bold line:
        [bold] "0A-00547"
        [bold] "Rectifier Bridge Nut"
        [reg]  "J&N"           "462-64004"
        ...
      Case B — YT number and description share the same bold line:
        [bold] "0A-03001 Regulator Screw"
        [reg]  "Ace Electric"  "S-119"
        ...

    Interchange rows (regular font):
        Left words  (x0 < vendor_num_split)  → vendor name (may wrap across lines)
        Right words (x0 >= vendor_num_split) → part number
    """
    current_entry: dict | None = initial_entry
    pending_vendor: str = ""

    def _save_interchange(vendor: str, number: str):
        if current_entry is None:
            return
        vendor = vendor.strip()
        number = number.strip()
        if not vendor and current_entry["interchanges"]:
            vendor = current_entry["interchanges"][-1]["vendor"].strip()
        if number:
            if (
                current_entry["interchanges"]
                and current_entry["interchanges"][-1].get("number", "").strip().endswith("-")
                and re.fullmatch(r"[A-Za-z]{1,3}", number)
            ):
                current_entry["interchanges"][-1]["number"] = (
                    current_entry["interchanges"][-1]["number"].strip() + number
                )
                return
            if not (vendor and _is_exact_text_reference(number)):
                embedded_vendor_number = _split_embedded_vendor_number(number)
                if embedded_vendor_number and (
                    not vendor or _is_trailing_vendor_fragment(vendor) or vendor.lower() != embedded_vendor_number[0].lower()
                ):
                    vendor, number = embedded_vendor_number
            trimmed_number, trailing_vendor = _strip_trailing_vendor_fragment_from_number(number)
            if trailing_vendor and vendor:
                vendor = f"{vendor} {trailing_vendor}".strip()
                number = trimmed_number
            embedded_split = _find_embedded_vendor_split(number, current_entry)
            if embedded_split:
                prefix_number, embedded_vendor, embedded_number = embedded_split
                _save_interchange(vendor, prefix_number)
                _save_interchange(embedded_vendor, embedded_number)
                return
            if current_entry["interchanges"]:
                last_ix = current_entry["interchanges"][-1]
                last_vendor = last_ix.get("vendor", "").strip()
                last_number = last_ix.get("number", "").strip()
                if (
                    vendor == last_vendor
                    and last_number.endswith("-")
                    and _looks_like_number_fragment(number)
                ):
                    last_ix["number"] = f"{last_number}{number}"
                    return
            current_entry["interchanges"].append({"vendor": vendor, "number": number})
            if vendor:
                suspicious = _contains_embedded_vendor_marker(number, current_entry)
            else:
                suspicious = _SUSPECT_NUMBER_RE.search(number.replace(" ", "")) or (
                    " " in number and not _looks_like_numeric_reference_with_spaces(number)
                )
            if _is_exact_text_reference(number):
                suspicious = False
            if suspicious:
                _add_issue(current_entry, f"Check interchange number '{number}'.")

    for line in lines:
        text = _line_text(line)
        if not text:
            continue

        # Skip page header / footer lines (e.g. "OUR NUMBERS TO OTHERS", "Pg. 7059")
        if text.startswith("Pg.") or text.startswith("OUR NUMBERS"):
            continue

        bold = _line_is_bold(line)
        tokens = text.split()
        first_token = tokens[0] if tokens else ""

        # ---- New entry: bold line whose first token is a YT number ----
        if bold and _looks_like_yt(first_token):
            if pending_vendor and current_entry is not None:
                _save_interchange(pending_vendor, "")
            pending_vendor = ""

            # Remaining tokens on the same line → description (Case B)
            desc = " ".join(tokens[1:]).strip()
            current_entry = {
                "yt_number": first_token,
                "description": desc,
                "category": detect_category(desc) if desc else _DEFAULT_CATEGORY,
                "interchanges": [],
                "page_number": page_number,
                "issues": [],
            }
            entries.append(current_entry)
            continue

        if current_entry is None:
            continue

        # ---- Description: next bold line when YT was alone (Case A) ----
        if bold and not current_entry["description"]:
            current_entry["description"] = text
            current_entry["category"] = detect_category(text)
            continue

        # Skip other bold lines (column headings, continuation of bold header)
        if bold:
            continue

        # ---- Interchange line (regular font) ----
        left_words = [w for w in line if w["x0"] < vendor_num_split]
        right_words = [w for w in line if w["x0"] >= vendor_num_split]

        left_text = " ".join(w["text"] for w in left_words).strip()
        right_text = " ".join(w["text"] for w in right_words).strip()
        if not left_text and right_text:
            embedded = _split_embedded_vendor_number(right_text)
            if embedded:
                left_text, right_text = embedded
        elif left_text and right_text:
            repeated_prefix = f"{left_text} "
            if right_text.startswith(repeated_prefix):
                right_text = right_text[len(repeated_prefix):].strip()

        if right_text:
            if left_text:
                # Both vendor name and part number are present. If the vendor
                # wrapped from a previous line, join it back together.
                if _pending_is_trailing(pending_vendor, left_text, current_entry):
                    current_entry["interchanges"][-1]["vendor"] = (
                        f"{current_entry['interchanges'][-1]['vendor']} {pending_vendor}".strip()
                    )
                    vendor_text = left_text
                else:
                    vendor_text = f"{pending_vendor} {left_text}".strip() if pending_vendor else left_text
                _save_interchange(vendor_text, right_text)
                pending_vendor = ""
            else:
                # Part number only (no vendor name on this line). If the pending
                # text is a trailing vendor fragment, fold it into the previous
                # interchange vendor before reusing it.
                if _pending_is_trailing(pending_vendor, "", current_entry):
                    last_ix = current_entry["interchanges"][-1]
                    last_vendor = last_ix.get("vendor", "").strip()
                    merged_vendor = f"{last_vendor} {pending_vendor}".strip() if last_vendor else pending_vendor
                    last_ix["vendor"] = merged_vendor
                    vendor_text = merged_vendor
                else:
                    vendor_text = pending_vendor
                _save_interchange(vendor_text, right_text)
                pending_vendor = ""
        elif left_text:
            # Vendor name only → accumulate (may continue on next line)
            pending_vendor = (pending_vendor + " " + left_text).strip()

    if pending_vendor and current_entry is not None:
        if _pending_is_trailing(pending_vendor, "", current_entry):
            last_ix = current_entry["interchanges"][-1]
            last_vendor = last_ix.get("vendor", "").strip()
            last_ix["vendor"] = f"{last_vendor} {pending_vendor}".strip() if last_vendor else pending_vendor
        else:
            _add_issue(current_entry, f"Vendor without number: {pending_vendor}.")
    return current_entry
