"""
Extract part + interchange rows from image-only PDFs (scanned pages) via OCR.

Uses Tesseract word boxes to split each line into left (source) and right (number),
then merges Ford-style suffix lines (e.g. ``D4TF-10316-`` + ``AA`` on the next line).
"""

from __future__ import annotations

import os
import re
from typing import Any

_YT_TOKEN = re.compile(r"^[0-9A-Z]{1,3}-\d{3,6}[A-Z]?$", re.I)
_SKIP_LINE = re.compile(r"^(OUR\s+NUMBERS|PG\.|PAGE\b)", re.I)


def find_tesseract_exe() -> str | None:
    import shutil

    p = shutil.which("tesseract")
    if p:
        return p
    for candidate in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


def render_pdf_page_pil(doc: Any, page_index: int, dpi: int = 200):
    """Render one PDF page to a PIL Image (requires pymupdf / fitz)."""
    import fitz
    from PIL import Image

    page = doc.load_page(page_index)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


_EASYOCR_READER = None


def _easyocr_reader():
    global _EASYOCR_READER
    if _EASYOCR_READER is None:
        import easyocr

        _EASYOCR_READER = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _EASYOCR_READER


def ocr_words_easyocr(pil_img) -> list[dict]:
    """Word boxes via EasyOCR (no Tesseract install required; pulls models once)."""
    import numpy as np

    reader = _easyocr_reader()
    arr = np.array(pil_img.convert("RGB"))
    results = reader.readtext(arr, paragraph=False)
    words: list[dict] = []
    for bbox, text, conf in results:
        if conf < 0.18 or not (text or "").strip():
            continue
        text = text.strip()
        xs = [float(p[0]) for p in bbox]
        ys = [float(p[1]) for p in bbox]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        parts = text.split()
        if len(parts) == 1:
            words.append({"text": parts[0], "x0": int(x0), "y0": int(y0), "x1": int(x1), "y1": int(y1)})
            continue
        total_w = max(x1 - x0, 1.0)
        pos = float(x0)
        avg = total_w / max(len(text), 1)
        for part in parts:
            pw = max(min(avg * (len(part) + 0.35), x1 - pos), 4.0)
            words.append({
                "text": part,
                "x0": int(pos),
                "y0": int(y0),
                "x1": int(min(pos + pw, x1)),
                "y1": int(y1),
            })
            pos = pos + pw + avg * 0.25
    return words


def ocr_words_from_pil(pil_img, tesseract_cmd: str | None = None) -> list[dict]:
    """Return word dicts: text, x0, y0, x1, y1 (pixel coords)."""
    import pytesseract

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    data = pytesseract.image_to_data(pil_img, output_type=pytesseract.Output.DICT)
    words: list[dict] = []
    n = len(data["text"])
    for i in range(n):
        t = (data["text"][i] or "").strip()
        if not t:
            continue
        try:
            conf = int(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1
        if conf < 0:
            continue
        x0 = int(data["left"][i])
        y0 = int(data["top"][i])
        x1 = x0 + int(data["width"][i])
        y1 = y0 + int(data["height"][i])
        words.append({"text": t, "x0": x0, "y0": y0, "x1": x1, "y1": y1})
    return words


def words_to_lines(words: list[dict], y_tol: int = 14) -> list[list[dict]]:
    """Group OCR words into lines (sorted left-to-right within each line)."""
    if not words:
        return []
    words = sorted(words, key=lambda w: (w["y0"], w["x0"]))
    lines: list[list[dict]] = []
    current: list[dict] = []
    mid_y: float | None = None
    for w in words:
        cy = (w["y0"] + w["y1"]) / 2.0
        if mid_y is None or abs(cy - mid_y) <= y_tol:
            current.append(w)
            mid_y = cy if mid_y is None else 0.6 * mid_y + 0.4 * cy
        else:
            if current:
                lines.append(sorted(current, key=lambda x: x["x0"]))
            current = [w]
            mid_y = cy
    if current:
        lines.append(sorted(current, key=lambda x: x["x0"]))
    return lines


def split_line_vendor_number(words: list[dict], min_gap: int = 18) -> tuple[str, str]:
    """Split one line into left (vendor) and right (number) using largest x-gap or midpoint."""
    if not words:
        return "", ""
    if len(words) == 1:
        t = words[0]["text"]
        if re.search(r"\d", t) and len(t) >= 4:
            return "", t
        return t, ""

    gaps: list[tuple[int, int]] = []
    for i in range(len(words) - 1):
        g = words[i + 1]["x0"] - words[i]["x1"]
        gaps.append((g, i))
    gaps.sort(key=lambda x: -x[0])
    best_g, idx = gaps[0]

    if best_g >= min_gap:
        left_w, right_w = words[: idx + 1], words[idx + 1 :]
    else:
        mid = (words[0]["x0"] + words[-1]["x1"]) / 2.0
        left_w = [w for w in words if (w["x0"] + w["x1"]) / 2.0 < mid]
        right_w = [w for w in words if w not in left_w]
    left = " ".join(w["text"] for w in left_w).strip()
    right = " ".join(w["text"] for w in right_w).strip()
    return left, right


def _line_plain_text(line_words: list[dict]) -> str:
    return " ".join(w["text"] for w in line_words).strip()


def _first_token(text: str) -> str:
    return (text.split() or [""])[0]


def _normalize_key(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").upper())


def _ocr_yt_first_token_variants_normalized(target_yt: str) -> set[str]:
    """OCR often reads ``1B-6007`` as ``18-6007`` — match both on the first token."""
    u = (target_yt or "").strip().upper()
    s = {_normalize_key(u)}
    if u.startswith("1B-"):
        s.add(_normalize_key("18-" + u[3:]))
    elif u.startswith("18-"):
        s.add(_normalize_key("1B-" + u[3:]))
    return s


_SHORT_REF_SUFFIX = re.compile(r"^[A-Z0-9]{1,4}$", re.I)


def _looks_like_interchange_row(line_words: list[dict]) -> bool:
    left, right = split_line_vendor_number(line_words)
    if right and re.search(r"\d", right):
        return True
    if left and right and len(right) >= 3:
        return True
    return False


def parse_entry_from_ocr_lines(
    all_lines: list[list[dict]],
    target_yt: str,
) -> dict[str, Any] | None:
    """
    Find ``target_yt`` in OCR lines and return
    ``{yt_number, description, interchanges: [{vendor, number}], issues: [str]}``.
    """
    variants = _ocr_yt_first_token_variants_normalized(target_yt)
    start = -1
    for i, line in enumerate(all_lines):
        plain = _line_plain_text(line)
        toks = plain.split()
        if not toks:
            continue
        if _normalize_key(toks[0]) in variants:
            start = i
            break
    if start < 0:
        return None

    header_text = _line_plain_text(all_lines[start])
    tokens = header_text.split()
    yt = target_yt.strip().upper()
    description = ""
    if tokens and _YT_TOKEN.match(tokens[0]):
        description = " ".join(tokens[1:]).strip()
    else:
        for j, t in enumerate(tokens):
            if _normalize_key(t) in variants:
                description = " ".join(tokens[j + 1 :]).strip()
                break

    interchanges_raw: list[tuple[str, str]] = []
    pending_vendor = ""
    issues: list[str] = []

    idx = start + 1
    if not description and idx < len(all_lines):
        # Next line is part name when YT was alone on the header line
        cand = all_lines[idx]
        if not _looks_like_interchange_row(cand):
            description = _line_plain_text(cand).strip()
            idx += 1

    while idx < len(all_lines):
        line_words = all_lines[idx]
        plain = _line_plain_text(line_words)
        if not plain:
            idx += 1
            continue
        if _SKIP_LINE.search(plain):
            idx += 1
            continue

        first = _first_token(plain)
        first_n = _normalize_key(first)
        if _YT_TOKEN.match(first) and first_n not in variants:
            break

        left, right = split_line_vendor_number(line_words)

        if (
            not left
            and right
            and len(right) <= 5
            and _SHORT_REF_SUFFIX.match(right)
            and interchanges_raw
            and interchanges_raw[-1][1].rstrip().endswith("-")
        ):
            pv, num = interchanges_raw[-1]
            interchanges_raw[-1] = (pv, num.rstrip() + right)
            idx += 1
            continue

        if (
            not right
            and left
            and not pending_vendor
            and len(left) <= 5
            and _SHORT_REF_SUFFIX.match(left)
            and interchanges_raw
            and interchanges_raw[-1][1].rstrip().endswith("-")
        ):
            pv, num = interchanges_raw[-1]
            interchanges_raw[-1] = (pv, num.rstrip() + left)
            idx += 1
            continue

        if right:
            vendor = (pending_vendor + " " + left).strip() if pending_vendor else left
            interchanges_raw.append((vendor, right))
            pending_vendor = ""
        elif left:
            pending_vendor = (pending_vendor + " " + left).strip()

        idx += 1

    interchanges: list[dict[str, str]] = []
    for vendor, number in interchanges_raw:
        vendor = vendor.strip()
        number = number.strip()
        if not number:
            continue
        if not vendor:
            issues.append(f"Interchange without vendor for number '{number}' (check OCR).")
        interchanges.append({"vendor": vendor, "number": number})

    return {
        "yt_number": yt,
        "description": description,
        "interchanges": interchanges,
        "issues": issues,
    }


def ocr_pdf_all_lines(
    pdf_path: str,
    *,
    dpi: int = 200,
    tesseract_cmd: str | None = None,
    engine: str = "auto",
) -> list[list[dict]]:
    """
    ``engine``: ``auto`` (Tesseract if installed, else EasyOCR), ``tesseract``, or ``easyocr``.
    """
    import fitz

    tess = tesseract_cmd or find_tesseract_exe()
    lines_out: list[list[dict]] = []
    doc = fitz.open(pdf_path)
    try:
        for pi in range(len(doc)):
            pil = render_pdf_page_pil(doc, pi, dpi=dpi)
            if engine == "easyocr":
                words = ocr_words_easyocr(pil)
            elif engine == "tesseract":
                if not tess:
                    raise OSError(
                        "Tesseract executable not found. Install Tesseract OCR or use --engine easyocr."
                    )
                words = ocr_words_from_pil(pil, tesseract_cmd=tess)
            else:
                if tess:
                    words = ocr_words_from_pil(pil, tesseract_cmd=tess)
                else:
                    words = ocr_words_easyocr(pil)
            page_lines = words_to_lines(words)
            lines_out.extend(page_lines)
    finally:
        doc.close()
    return lines_out


def parse_entry_from_image_pdf(pdf_path: str, target_yt: str, **ocr_kw: Any) -> dict[str, Any] | None:
    lines = ocr_pdf_all_lines(pdf_path, **ocr_kw)
    return parse_entry_from_ocr_lines(lines, target_yt)


def parse_interchanges_from_review_text(text: str) -> tuple[list[dict[str, str]], list[str]]:
    """
    Parse interchange lines from a review file (Tesseract / Acrobat copy-paste).

    - Use TAB or 2+ spaces between source (left) and number (right).
    - A line that is only ``AA``, ``A``, ``AB`` (letters only) appends to the previous
      number if it ends with ``-`` (Ford-style wrap).
    - Continuation line with only a part number: use last vendor.
    """
    issues: list[str] = []
    raw: list[tuple[str, str]] = []
    pending_vendor = ""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if re.fullmatch(r"[A-Za-z]{1,4}", line):
            if raw and raw[-1][1].rstrip().endswith("-"):
                v, n = raw[-1]
                raw[-1] = (v, n.rstrip() + line)
                continue
            issues.append(f"Lone suffix line '{line}' ignored (no preceding number ending in '-').")
            continue

        if "\t" in line:
            left, right = line.split("\t", 1)
        else:
            parts = re.split(r"\s{2,}", line)
            if len(parts) >= 2:
                left, right = parts[0], parts[-1]
            else:
                left, right = "", parts[0]

        left, right = left.strip(), right.strip()
        if right:
            vendor = (pending_vendor + " " + left).strip() if pending_vendor else left
            raw.append((vendor, right))
            pending_vendor = ""
        elif left:
            pending_vendor = (pending_vendor + " " + left).strip()

    out: list[dict[str, str]] = []
    for vendor, number in raw:
        vendor = vendor.strip()
        number = number.strip()
        if not number:
            continue
        if not vendor:
            issues.append(f"Missing vendor for number '{number}'.")
        out.append({"vendor": vendor, "number": number})
    return out, issues


def build_preview_entry(
    yt_number: str,
    description: str,
    interchange_text: str | None,
) -> dict[str, Any]:
    ix, issues = parse_interchanges_from_review_text(interchange_text or "")
    return {
        "yt_number": yt_number.strip().upper(),
        "description": description.strip(),
        "interchanges": ix,
        "issues": issues,
    }
