"""
audit_pdf_vs_db — Diagnostic-only tool comparing buyers-guide PDFs against the DB.

Purpose
-------
Phase 1 of the PDF re-import accuracy plan.  This command does NOT modify the
parser, importer, or any data.  It walks a buyers-guide PDF, extracts each
unit's text (column-aware, multi-page aware), then compares to either the
live Django DB or a parser-produced staging DB.

CSV output columns:
    pdf_name, unit_number, category, field, status, pdf_value, db_value,
    severity, notes

Categories:    META, ATTRIBUTE, INTERCHANGE, APPLICATION, BOM, SUBSTITUTE
Statuses:      MATCH, MISSING_IN_DB, EXTRA_IN_DB, MISMATCH, FLAG
Severities:    INFO, WARN, ERROR
"""

from __future__ import annotations

import csv
import os
import random
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

import fitz  # PyMuPDF

from catalog.models import (
    Application,
    ApplicationUnit,
    BOM,
    BOMItem,
    CrossReference,
    Substitute,
    Unit,
)
from data_import.import_utils import normalize_space
from data_import.pdf_parsers.parse_buyers_guide import (
    ATTR_KEY_MAP,
    SECTION_HEADERS,
    YOUTECH_HEADER_RE,
    parse_interchanges_text,
)


PAGE_BANNERS = {
    "BUYERS GUIDE",
    "ALTERNATORS",
    "STARTERS",
    "GENERATORS",
    "TILT & TRIM MOTORS",
    "MILD HYBRID MOTOR/GENERATORS",
    "BUYERS GUIDE ALTERNATORS",
    "ALTERNATORS BUYERS GUIDE",
    "BUYERS GUIDE STARTERS",
    "STARTERS BUYERS GUIDE",
    "BUYERS GUIDE GENERATORS",
    "GENERATORS BUYERS GUIDE",
}

# Mapping from staging-column / canonical key to Unit model field name.
# Mirrors import_buyers_guide_products.ATTR_FIELD_MAP (kept local so we don't
# import that module just for the dict — it lives next door).
ATTR_TO_MODEL_FIELD = {
    "manufacture":           ("manufacturer",    "manufacturer"),
    "oe_manufacturer":       ("oem",             "oem"),
    "family":                ("family",          "family"),
    "voltage":               ("voltage",         "voltage"),
    "rotation":              ("rotation",        "rotation"),
    "mounting_type":         ("mount_type",      "mount_type"),
    "amperage_rating":       ("amp_rating",      "amp_rating"),
    "fan_type":              ("fan_type",        "fan_type"),
    "regulator_type":        ("regulator_type",  "regulator_type"),
    "ground_type":           ("grounding",       "grounding"),
    "plug_type":             (None,              "plug_type"),
    "plug_clocking":         (None,              "plug_clocking"),
    "belt_type":             (None,              "belt_type"),
    "pulley_grooves":        (None,              "pulley_grooves"),
    "pulley_type":           (None,              "pulley_type"),
    "pulley_od":             (None,              "pulley_od"),
    "decoupled":             (None,              "decoupled"),
    "stator_type":           (None,              "stator_type"),
    "series":                (None,              "series"),
    "circuit_type":          ("circuit_type",    "circuit_type"),
    "design":                ("design",          "design"),
    "power_rating":          ("power_rating",    "power_rating"),
    "tooth_quantity":        ("tooth_quantity",  "tooth_quantity"),
    "case_grounding":        ("grounding",       "grounding"),
    "nose_cone_type":        ("nose_type",       "nose_type"),
    "over_crank_protection": ("over_crank_protection", "over_crank_protection"),
    "solenoid_attached":     ("solenoid_attached", "solenoid_attached"),
    "reclockable_flange":    ("reclockable_flange", "reclockable_flange"),
    "bolt_holes":            ("bolt_holes",      "bolt_holes"),
    "with_hardware":         ("with_hardware",   "with_hardware"),
    "with_mounting_shims":   ("with_mounting_shims", "with_mounting_shims"),
    "spline_quantity":       (None,              "spline_quantity"),
    "drive_housing_position":(None,              "drive_housing_position"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_YEAR_RANGE_4_RE = re.compile(r"^(\d{4})-(\d{4})$")
_YEAR_RANGE_2_RE = re.compile(r"^(\d{2})-(\d{2})$")
_YEAR_WRAP_RE = re.compile(r"\d{4}-\s+\d{4}")  # "2000- 2002" line-wrap artifact
_SUBMODEL_LIST_RE = re.compile(r"^[\w\.\/]+-[A-Z](,[A-Z])+$")
_JN_WRAP_RE = re.compile(r"\d-\s+\d")  # "130- 05002" line-wrap artifact

# Year ranges that show up inside an engine string (we detect them so we can
# strip them when normalizing engine text for application matching).
_YEAR_IN_TEXT_RE = re.compile(r"\b\d{4}-\d{4}\b")


def normalize_year(y: str) -> str:
    """Convert 2-digit ranges like '00-02' -> '2000-2002'.  Year >= 70 -> 19xx."""
    if not y:
        return ""
    y = y.strip()
    m = _YEAR_RANGE_2_RE.match(y)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        a_full = 1900 + a if a >= 70 else 2000 + a
        b_full = 1900 + b if b >= 70 else 2000 + b
        return f"{a_full}-{b_full}"
    return y


def normalize_mfr(name: str) -> str:
    """Lowercase manufacturer name for case-insensitive comparison."""
    return (name or "").strip().lower()


def normalize_text(s: str) -> str:
    """Strip + collapse whitespace + lowercase, for fuzzy equality."""
    return " ".join((s or "").split()).lower()


# ---------------------------------------------------------------------------
# PDF scanning
# ---------------------------------------------------------------------------


def enumerate_units(pdf_path: str, stdout=None) -> dict[str, set[int]]:
    """Pass 1: walk full PDF, return {yt_number: {page_idx, ...}} including
    pages where the YT appears in either a primary header or a (Cont.) header."""
    doc = fitz.open(pdf_path)
    n_pages = doc.page_count
    unit_pages: dict[str, set[int]] = defaultdict(set)

    for page_idx in range(n_pages):
        page = doc[page_idx]
        text = page.get_text() or ""
        for line in text.split("\n"):
            line = line.strip()
            m = YOUTECH_HEADER_RE.match(line)
            if m:
                unit_pages[m.group(1)].add(page_idx)
        del page

        if stdout and (page_idx + 1) % 2000 == 0:
            stdout.write(
                f"  enumerate: page {page_idx + 1:>5}/{n_pages}  units so far: {len(unit_pages):>6}"
            )
            stdout.flush()

    doc.close()
    return unit_pages


def _column_lines(page, mid: float):
    """Yield (column_name, [lines]) for left then right column on a page,
    using block-mode extraction filtered by block x0."""
    blocks = page.get_text("blocks")
    left_blocks = sorted(
        [b for b in blocks if b[0] < mid], key=lambda b: (b[1], b[0])
    )
    right_blocks = sorted(
        [b for b in blocks if b[0] >= mid], key=lambda b: (b[1], b[0])
    )
    for col_name, col_blocks in (("L", left_blocks), ("R", right_blocks)):
        col_lines = []
        for block in col_blocks:
            for ln in (block[4] or "").split("\n"):
                ln = ln.strip()
                if ln:
                    col_lines.append(ln)
        yield col_name, col_lines


def extract_unit_sections(pdf_path: str, target_yt: str, page_indices: set[int]):
    """Pass 2: extract per-section text for a single unit, column-aware,
    walking only the pages it appears on.

    Returns:
        sections: dict[section_name] -> list[str] of lines
        pages_used: sorted list of page indices contributing data
    """
    sections: dict[str, list[str]] = defaultdict(list)
    pages_used: list[int] = []
    current_section = "HEADER"  # pre-first-section content

    doc = fitz.open(pdf_path)
    try:
        for page_idx in sorted(page_indices):
            page = doc[page_idx]
            page_width = page.rect.width
            mid = page_width / 2.0

            page_contributed = False
            for _col_name, col_lines in _column_lines(page, mid):
                in_unit = False
                for ln in col_lines:
                    m = YOUTECH_HEADER_RE.match(ln)
                    if m:
                        this_yt = m.group(1)
                        is_cont = "(Cont.)" in ln
                        if this_yt == target_yt:
                            in_unit = True
                            if not is_cont:
                                current_section = "HEADER"
                            page_contributed = True
                        else:
                            if in_unit:
                                # Another unit's primary header ends ours.
                                in_unit = False
                            # else: another unit's column — ignore lines below
                        continue

                    if not in_unit:
                        continue

                    if ln in PAGE_BANNERS:
                        continue
                    if re.match(r"^Pg\.\s*\d", ln):
                        continue

                    clean = ln.rstrip(":")
                    if clean in SECTION_HEADERS:
                        current_section = clean
                        continue

                    sections[current_section].append(ln)

            if page_contributed:
                pages_used.append(page_idx)
            del page
    finally:
        doc.close()

    return dict(sections), pages_used


# ---------------------------------------------------------------------------
# PDF section parsers
# ---------------------------------------------------------------------------


def parse_pdf_attributes(attr_lines: list[str]) -> dict[str, str]:
    """Parse PRODUCT ATTRIBUTES section lines into {key_normalized: value}.

    PyMuPDF emits attribute name then value on alternating lines (mostly).
    Match the parser's logic with ATTR_KEY_MAP.
    """
    attrs: dict[str, str] = {}
    pending_key = None
    notes_pending = False
    notes_buf: list[str] = []

    for ln in attr_lines:
        if ln.startswith("Product Notes:"):
            notes_text = ln.split(":", 1)[1].strip().strip('"')
            notes_pending = True
            notes_buf = [notes_text]
            continue
        if notes_pending:
            # Notes can wrap, but stop accumulating on next known attribute key
            normalized = ln.lower().replace(" ", "_")
            if normalized in ATTR_KEY_MAP:
                # End of notes
                attrs["product_notes"] = " ".join(notes_buf).strip()
                notes_pending = False
                pending_key = normalized
                continue
            else:
                notes_buf.append(ln)
                continue

        if pending_key is not None:
            mapped = ATTR_KEY_MAP.get(pending_key, pending_key)
            attrs[mapped] = ln
            pending_key = None
            continue

        normalized = ln.lower().replace(" ", "_")
        if normalized in ATTR_KEY_MAP:
            pending_key = normalized
        else:
            # Unknown attribute name — capture under raw key for diagnostics
            pending_key = normalized

    if notes_pending:
        attrs["product_notes"] = " ".join(notes_buf).strip()
    return attrs


def parse_pdf_interchanges(int_lines: list[str]) -> list[tuple[str, str]]:
    """Join multi-line interchange text + use parser's helper to get pairs."""
    blob = " ".join(int_lines)
    return parse_interchanges_text(blob)


def parse_pdf_applications(app_lines: list[str]) -> list[dict]:
    """Best-effort parse of APPLICATION section.  Mirrors the importer's
    _parse_application_text and _split_model_entries so we can compare apples
    to apples against what was inserted.

    Returns list of {make, model, engine, year, raw}.
    """
    results: list[dict] = []
    current_make = ""
    model_buffer = ""

    _year_range_re = re.compile(r"\d{4}-\d{4}")
    _engine_re = re.compile(r"\b([VLH]\d)\s+(.+)")
    _disp_re = re.compile(r"\b(\d+\.\d+L\b.*)")

    def flush_buffer():
        nonlocal model_buffer
        if not (current_make and model_buffer):
            model_buffer = ""
            return
        for entry in model_buffer.split(";"):
            entry = entry.strip()
            if not entry:
                continue
            raw = entry
            year = ""
            engine = ""

            ym = _year_range_re.search(entry)
            if ym:
                year = ym.group(0)
                entry = entry[: ym.start()].strip()

            em = _engine_re.search(entry)
            if em:
                model = entry[: em.start()].strip()
                engine = em.group(0).strip()
            else:
                dm = _disp_re.search(entry)
                if dm:
                    model = entry[: dm.start()].strip()
                    engine = dm.group(0).strip()
                else:
                    model = entry
                    engine = ""

            model = model.strip().rstrip(",")
            if model:
                results.append({
                    "make": current_make,
                    "model": model,
                    "engine": engine,
                    "year": year,
                    "raw": raw,
                })
        model_buffer = ""

    for raw_line in app_lines:
        line = raw_line.strip()
        if not line:
            continue
        is_make_line = (
            bool(re.match(r"^[A-Za-z]", line))
            and ";" not in line
            and not _year_range_re.search(line)
            and not re.match(r".*\d{2,}[A-Z]", line)
            and len(line) < 80
        )
        if current_make and re.match(r"^\(.+\)$", line) and not model_buffer:
            current_make = f"{current_make} {line}".title()
            continue
        if is_make_line:
            flush_buffer()
            current_make = line.title()
        else:
            model_buffer = (model_buffer + " " + line) if model_buffer else line

    flush_buffer()
    return results


def parse_pdf_bom(bom_lines: list[str]) -> list[dict]:
    """Parse BILL OF MATERIALS lines into [{part_name, yt_part, jn_part, raw}].
    Mirrors the parser's flush-on-name state machine, but accepts raw line list.
    """
    results: list[dict] = []
    pending_name = ""
    pending_yt = ""
    pending_jn = ""
    in_header = True

    def flush():
        nonlocal pending_name, pending_yt, pending_jn
        if pending_name and pending_yt:
            jn_clean = re.sub(r"-\s+", "-", pending_jn)
            jn_clean = re.sub(r"\s+-", "-", jn_clean)
            jn_clean = re.sub(r"\s+", " ", jn_clean).strip().rstrip(",")
            results.append({
                "part_name": pending_name,
                "yt_part": pending_yt,
                "jn_part": jn_clean,
                "jn_raw": pending_jn.strip(),
            })
        pending_name = ""
        pending_yt = ""
        pending_jn = ""

    for ln in bom_lines:
        if in_header:
            if ln in ("BOM", "YOUTECH", "J&N"):
                continue
            in_header = False
        if re.match(r"^Pg\.\s*\d", ln):
            continue

        if pending_yt and re.match(r"^\d[\dA-Za-z\-, ]*$", ln):
            pending_jn += " " + ln if pending_jn else ln
            continue

        if pending_name and not pending_yt:
            if re.match(r"^[A-Z0-9]{1,4}-", ln):
                pending_yt = ln
                continue
            if re.match(r"^\d{3,}", ln):
                pending_yt = ln
                continue

        if re.match(r"^[A-Za-z]", ln) and not ln.startswith("YouTech"):
            flush()
            pending_name = ln

    flush()
    return results


def parse_pdf_substitutes(sub_lines: list[str]) -> list[dict]:
    """Parse POSSIBLE SUBSTITUTIONS lines into [{yt, jn}]."""
    blob = " ".join(sub_lines)
    pairs = re.findall(r"YouTech\s*:\s*(\d+)(?:\s*\|\s*J&N\s*:\s*([\d\-]+))?", blob)
    return [{"yt": yt, "jn": jn or ""} for yt, jn in pairs]


# ---------------------------------------------------------------------------
# DB lookups (Django ORM path)
# ---------------------------------------------------------------------------


def fetch_db_unit(yt: str):
    """Return Unit, list[CrossReference], list[Application], list[BOMItem], list[Substitute]."""
    try:
        unit = Unit.objects.filter(unit_number=yt).first()
        if not unit:
            unit = Unit.objects.filter(yt_number=yt).first()
        if not unit:
            return None, [], [], [], []

        xrefs = list(
            CrossReference.objects.filter(unit=unit)
            .values("id", "cross_ref_number", "interchange_type")
        )
        app_links = list(
            ApplicationUnit.objects.filter(unit=unit)
            .select_related("application")
        )
        apps = []
        for au in app_links:
            a = au.application
            apps.append({
                "id": a.pk,
                "make": a.make,
                "model": a.model,
                "engine": a.engine,
                "year": a.year,
                "name": a.name,
            })
        bom_items = []
        bom = BOM.objects.filter(unit=unit).first()
        if bom:
            bom_items = list(
                BOMItem.objects.filter(bom=bom)
                .values("id", "yt_number", "description", "j_and_n")
            )
        subs = list(
            Substitute.objects.filter(unit=unit)
            .values("id", "substitute_number", "substitute_unit_id")
        )
        return unit, xrefs, apps, bom_items, subs
    except Exception as e:  # noqa: BLE001
        return None, [], [], [], []


# ---------------------------------------------------------------------------
# DB lookups (staging-sqlite path)
# ---------------------------------------------------------------------------


def fetch_staging_unit(conn: sqlite3.Connection, yt: str):
    """Return analogous tuple from a parser-produced staging DB."""
    conn.row_factory = sqlite3.Row
    prod = conn.execute(
        "SELECT * FROM buyers_guide_products WHERE youtech_number = ?", (yt,)
    ).fetchone()

    xrefs = [
        dict(r) for r in conn.execute(
            "SELECT manufacturer AS interchange_type, their_number AS cross_ref_number "
            "FROM buyers_guide_interchanges WHERE our_number = ?",
            (yt,),
        )
    ]
    bom_items = [
        dict(r) for r in conn.execute(
            "SELECT yt_part_number AS yt_number, part_name AS description, "
            "jn_part_number AS j_and_n "
            "FROM buyers_guide_bom WHERE youtech_number = ?",
            (yt,),
        )
    ]
    subs = [
        dict(r) for r in conn.execute(
            "SELECT substitute_yt AS substitute_number, substitute_jn AS j_and_n "
            "FROM buyers_guide_substitutes WHERE youtech_number = ?",
            (yt,),
        )
    ]
    apps_raw = conn.execute(
        "SELECT application_text FROM buyers_guide_applications "
        "WHERE youtech_number = ?",
        (yt,),
    ).fetchone()
    apps = []
    if apps_raw and apps_raw["application_text"]:
        for entry in parse_pdf_applications(apps_raw["application_text"].split("\n")):
            apps.append({
                "make": entry["make"], "model": entry["model"],
                "engine": entry["engine"], "year": entry["year"],
                "name": "",
            })
    return prod, xrefs, apps, bom_items, subs


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------


class Findings:
    """Accumulator for CSV rows + counters."""

    def __init__(self, pdf_name: str):
        self.pdf_name = pdf_name
        self.rows: list[dict] = []
        self.issue_counter: Counter = Counter()
        self.severity_counter: Counter = Counter()

    def add(self, unit: str, category: str, field: str, status: str,
            pdf_value: str = "", db_value: str = "",
            severity: str = "INFO", notes: str = ""):
        self.rows.append({
            "pdf_name": self.pdf_name,
            "unit_number": unit,
            "category": category,
            "field": field,
            "status": status,
            "pdf_value": str(pdf_value)[:500],
            "db_value": str(db_value)[:500],
            "severity": severity,
            "notes": str(notes)[:500],
        })
        self.severity_counter[severity] += 1
        if status != "MATCH":
            self.issue_counter[f"{category}:{status}"] += 1
        if notes:
            # Tally bug categories (notes starts with a tag like "year_2digit")
            tag = notes.split(":", 1)[0].strip()
            if tag and len(tag) < 60:
                self.issue_counter[f"FLAG:{tag}"] += 1


def compare_attributes(yt, pdf_attrs, db_unit, db_unit_is_staging, findings):
    """Compare per-attribute values."""
    cat = "ATTRIBUTE"
    # Walk every canonical attribute we know about.
    seen_keys = set()
    for staging_col, (model_field, spec_key) in ATTR_TO_MODEL_FIELD.items():
        pdf_val = normalize_space(pdf_attrs.get(staging_col, ""))
        seen_keys.add(staging_col)

        if db_unit_is_staging:
            db_val = normalize_space(db_unit[staging_col]) if (db_unit and staging_col in db_unit.keys()) else ""
        else:
            if model_field and db_unit:
                db_val = normalize_space(getattr(db_unit, model_field, "") or "")
            elif db_unit:
                db_val = normalize_space((db_unit.specifications or {}).get(spec_key, ""))
            else:
                db_val = ""

        if not pdf_val and not db_val:
            continue
        if not pdf_val and db_val:
            findings.add(
                yt, cat, staging_col, "EXTRA_IN_DB",
                pdf_value="", db_value=db_val,
                severity="INFO",
                notes="db_value_no_pdf_source"
            )
            continue
        if pdf_val and not db_val:
            findings.add(
                yt, cat, staging_col, "MISSING_IN_DB",
                pdf_value=pdf_val, db_value="",
                severity="ERROR",
                notes="pdf_attr_not_imported"
            )
            continue
        if normalize_text(pdf_val) == normalize_text(db_val):
            findings.add(yt, cat, staging_col, "MATCH",
                         pdf_value=pdf_val, db_value=db_val, severity="INFO")
        else:
            findings.add(
                yt, cat, staging_col, "MISMATCH",
                pdf_value=pdf_val, db_value=db_val,
                severity="ERROR",
                notes="attr_value_differs"
            )

    # Surface PDF attribute keys that the parser's ATTR_KEY_MAP doesn't cover
    for k, v in pdf_attrs.items():
        if k in seen_keys:
            continue
        if k in ("_pending_attr_key",):
            continue
        if not v:
            continue
        # Only flag if v looks like a value (not the key itself)
        if k.startswith("product_notes") or k == "product_notes":
            continue
        findings.add(
            yt, cat, k, "FLAG",
            pdf_value=v, db_value="",
            severity="WARN",
            notes="unmapped_attr_key"
        )


def compare_interchanges(yt, pdf_pairs, db_xrefs, findings):
    cat = "INTERCHANGE"

    # Normalize DB rows: (lower_mfr, mixed_mfr, num)
    db_rows = []
    for r in db_xrefs:
        mfr = (r["interchange_type"] or "").strip()
        num = (r["cross_ref_number"] or "").strip()
        db_rows.append((normalize_mfr(mfr), mfr, num))

    # Case-variant duplicates: same (lower_mfr, num) appears with multiple original mfrs
    by_norm = defaultdict(list)
    for lm, mfr, num in db_rows:
        by_norm[(lm, num)].append(mfr)
    for (lm, num), mfrs in by_norm.items():
        unique_mfrs = sorted(set(mfrs))
        if len(unique_mfrs) > 1:
            findings.add(
                yt, cat, f"{lm}:{num}", "FLAG",
                pdf_value="", db_value=" | ".join(unique_mfrs),
                severity="ERROR",
                notes=f"case_variant_dupe: {len(unique_mfrs)} mfr spellings for same (mfr_lower,num)"
            )

    # PDF expected set
    pdf_set = set((normalize_mfr(m), n.strip()) for m, n in pdf_pairs)
    db_set = set((lm, num) for lm, _mfr, num in db_rows)

    # PDF rows missing in DB
    for m, n in pdf_pairs:
        key = (normalize_mfr(m), n.strip())
        if key not in db_set:
            findings.add(
                yt, cat, f"{m}:{n}", "MISSING_IN_DB",
                pdf_value=f"{m}: {n}", db_value="",
                severity="ERROR",
                notes="pdf_xref_not_in_db"
            )
        else:
            findings.add(
                yt, cat, f"{m}:{n}", "MATCH",
                pdf_value=f"{m}: {n}", db_value=f"{m}: {n}",
                severity="INFO",
            )

    # DB rows not in PDF (these may be from Lester source, not necessarily a bug)
    for lm, mfr, num in db_rows:
        if (lm, num) not in pdf_set:
            findings.add(
                yt, cat, f"{mfr}:{num}", "EXTRA_IN_DB",
                pdf_value="", db_value=f"{mfr}: {num}",
                severity="INFO",
                notes="db_xref_not_in_pdf (likely lester source)"
            )


def _app_match_key(make, model, engine, year):
    return (
        normalize_text(make),
        normalize_text(model),
        normalize_text(engine),
        normalize_year((year or "").strip()),
    )


def compare_applications(yt, pdf_apps, db_apps, findings):
    cat = "APPLICATION"

    # Build PDF expectation set with year normalized
    pdf_keys = set()
    for a in pdf_apps:
        pdf_keys.add(_app_match_key(a["make"], a["model"], a["engine"], a["year"]))

    # Build DB grouping by normalized key to detect year-format dupes
    db_by_norm = defaultdict(list)
    for a in db_apps:
        k = _app_match_key(a["make"], a["model"], a["engine"], a["year"])
        db_by_norm[k].append(a)

    # FLAG year-format dupes (same normalized key, multiple rows with differing raw years)
    for k, rows in db_by_norm.items():
        raw_years = sorted({(r["year"] or "").strip() for r in rows})
        if len(raw_years) > 1:
            findings.add(
                yt, cat, " / ".join(filter(None, [rows[0]["make"], rows[0]["model"], rows[0]["engine"]])),
                "FLAG",
                pdf_value=" / ".join(raw_years),
                db_value=" + ".join([str(r["id"]) for r in rows]),
                severity="ERROR",
                notes=f"year_format_dupe: same logical app in DB with year formats {raw_years}",
            )

    # FLAG per-row quality issues in DB rows
    for a in db_apps:
        # Year format 2-digit
        if _YEAR_RANGE_2_RE.match((a["year"] or "").strip()):
            findings.add(
                yt, cat, f"{a['make']}/{a['model']}/{a['engine']}",
                "FLAG",
                pdf_value="(should be 4-digit)",
                db_value=a["year"],
                severity="WARN",
                notes=f"year_2digit: app id={a['id']}",
            )
        # Year contains '|' (pipe noise)
        if "|" in (a["year"] or ""):
            findings.add(
                yt, cat, f"{a['make']}/{a['model']}/{a['engine']}",
                "FLAG",
                pdf_value="(pipe noise)",
                db_value=a["year"],
                severity="ERROR",
                notes=f"year_pipe_noise: app id={a['id']}",
            )
        # Year is XXXX-XXXX with same start/end (line-wrap rejoin failure)
        ym = _YEAR_RANGE_4_RE.match((a["year"] or "").strip())
        if ym and ym.group(1) == ym.group(2):
            findings.add(
                yt, cat, f"{a['make']}/{a['model']}/{a['engine']}",
                "FLAG",
                pdf_value="(suspicious same-year range)",
                db_value=a["year"],
                severity="WARN",
                notes=f"year_same_start_end: app id={a['id']}",
            )
        # Engine contains a year-wrap artifact like "2000- 2002"
        if _YEAR_WRAP_RE.search(a["engine"] or ""):
            findings.add(
                yt, cat, f"{a['make']}/{a['model']}/{a['engine']}",
                "FLAG",
                pdf_value="(year leaked into engine)",
                db_value=a["engine"],
                severity="ERROR",
                notes=f"line_wrap_year_in_engine: app id={a['id']}",
            )
        # Model is an unsplit submodel list like "3.0GSM-A,B,C"
        if _SUBMODEL_LIST_RE.match((a["model"] or "").strip()):
            findings.add(
                yt, cat, f"{a['make']}/{a['model']}",
                "FLAG",
                pdf_value="(should split into individual submodels)",
                db_value=a["model"],
                severity="ERROR",
                notes=f"submodel_list_not_split: app id={a['id']}",
            )

    db_keys = set(db_by_norm.keys())

    # PDF entries missing in DB
    for a in pdf_apps:
        k = _app_match_key(a["make"], a["model"], a["engine"], a["year"])
        if k not in db_keys:
            findings.add(
                yt, cat,
                f"{a['make']}/{a['model']}/{a['engine']}/{a['year']}",
                "MISSING_IN_DB",
                pdf_value=f"{a['make']} | {a['model']} | {a['engine']} | {a['year']}",
                db_value="",
                severity="ERROR",
                notes=f"pdf_app_not_in_db (raw: {a.get('raw', '')[:100]})",
            )
        else:
            findings.add(
                yt, cat,
                f"{a['make']}/{a['model']}/{a['engine']}/{a['year']}",
                "MATCH",
                pdf_value=f"{a['make']} | {a['model']} | {a['engine']} | {a['year']}",
                db_value="(matched)",
                severity="INFO",
            )

    # DB entries not in PDF (extras — may be from other source)
    for k, rows in db_by_norm.items():
        if k not in pdf_keys:
            for a in rows:
                findings.add(
                    yt, cat,
                    f"{a['make']}/{a['model']}/{a['engine']}/{a['year']}",
                    "EXTRA_IN_DB",
                    pdf_value="",
                    db_value=f"{a['make']} | {a['model']} | {a['engine']} | {a['year']}",
                    severity="INFO",
                    notes=f"db_app_not_in_pdf: id={a['id']}",
                )


def compare_bom(yt, pdf_items, db_items, findings):
    cat = "BOM"

    pdf_by_yt = {i["yt_part"].upper(): i for i in pdf_items if i["yt_part"]}
    db_by_yt = {(i["yt_number"] or "").upper(): i for i in db_items if i["yt_number"]}

    # Flag j_and_n line-wrap (e.g. "130- 05002")
    for i in db_items:
        jn = i.get("j_and_n") or ""
        if _JN_WRAP_RE.search(jn):
            findings.add(
                yt, cat, i["yt_number"], "FLAG",
                pdf_value="", db_value=jn,
                severity="ERROR",
                notes=f"jn_line_wrap: BOMItem id={i['id']}",
            )

    # PDF items missing in DB
    for ytp, item in pdf_by_yt.items():
        if ytp not in db_by_yt:
            findings.add(
                yt, cat, ytp, "MISSING_IN_DB",
                pdf_value=f"{item['part_name']} ({item['yt_part']}) j&n={item['jn_part']}",
                db_value="",
                severity="ERROR",
                notes="pdf_bom_item_missing",
            )
        else:
            db_item = db_by_yt[ytp]
            # Compare j_and_n
            pdf_jn = (item["jn_part"] or "").strip()
            db_jn = (db_item["j_and_n"] or "").strip()
            if pdf_jn and db_jn and normalize_text(pdf_jn) != normalize_text(db_jn):
                findings.add(
                    yt, cat, ytp, "MISMATCH",
                    pdf_value=pdf_jn, db_value=db_jn,
                    severity="WARN",
                    notes="bom_jn_differs",
                )
            else:
                findings.add(
                    yt, cat, ytp, "MATCH",
                    pdf_value=item["part_name"], db_value=db_item["description"] or "",
                    severity="INFO",
                )

    # DB items not in PDF
    for ytp, db_item in db_by_yt.items():
        if ytp not in pdf_by_yt:
            findings.add(
                yt, cat, ytp, "EXTRA_IN_DB",
                pdf_value="",
                db_value=f"{db_item.get('description', '')} j&n={db_item.get('j_and_n', '')}",
                severity="INFO",
                notes="db_bom_item_not_in_pdf",
            )


def compare_subs(yt, pdf_subs, db_subs, findings):
    cat = "SUBSTITUTE"
    pdf_set = {s["yt"] for s in pdf_subs if s["yt"]}
    db_set = {(s["substitute_number"] or "").strip() for s in db_subs if (s.get("substitute_number") or "").strip()}

    for s in pdf_subs:
        if s["yt"] not in db_set:
            findings.add(
                yt, cat, s["yt"], "MISSING_IN_DB",
                pdf_value=f"YT:{s['yt']} J&N:{s['jn']}",
                db_value="",
                severity="WARN",
                notes="pdf_substitute_not_in_db",
            )
        else:
            findings.add(
                yt, cat, s["yt"], "MATCH",
                pdf_value=s["yt"], db_value=s["yt"],
                severity="INFO",
            )
    for ds in db_subs:
        n = (ds.get("substitute_number") or "").strip()
        if n and n not in pdf_set:
            findings.add(
                yt, cat, n, "EXTRA_IN_DB",
                pdf_value="", db_value=n,
                severity="INFO",
                notes="db_substitute_not_in_pdf",
            )


# ---------------------------------------------------------------------------
# Per-unit driver
# ---------------------------------------------------------------------------


def audit_one_unit(yt, pdf_path, unit_pages, findings, stdout=None, quiet=False,
                   staging_conn=None, pdf_name=""):
    sections, pages_used = extract_unit_sections(pdf_path, yt, unit_pages.get(yt, set()))

    # META row: pages used
    findings.add(
        yt, "META", "pages_used", "INFO",
        pdf_value=",".join(str(p + 1) for p in pages_used),
        db_value="",
        severity="INFO",
        notes=f"unit_pages_count={len(pages_used)}",
    )

    pdf_attrs = parse_pdf_attributes(sections.get("PRODUCT ATTRIBUTES", []))
    pdf_pairs = parse_pdf_interchanges(sections.get("INTERCHANGES", []))
    pdf_apps_combined = (
        sections.get("APPLICATION", [])
        + sections.get("APPLICATIONS", [])
    )
    pdf_apps = parse_pdf_applications(pdf_apps_combined)
    pdf_bom = parse_pdf_bom(sections.get("BILL OF MATERIALS", []))
    pdf_subs = parse_pdf_substitutes(sections.get("POSSIBLE SUBSTITUTIONS", []))

    # Header J&N from inferred attributes (skipped — we rely on the attributes section)

    if staging_conn is not None:
        prod_row, db_xrefs, db_apps, db_bom, db_subs = fetch_staging_unit(staging_conn, yt)
        if not prod_row:
            findings.add(yt, "META", "unit_in_db", "MISSING_IN_DB",
                         pdf_value="present", db_value="absent",
                         severity="ERROR",
                         notes="unit not present in staging DB")
            if not quiet and stdout:
                stdout.write(f"  [!] YT#{yt}: unit not present in staging DB")
            return
        compare_attributes(yt, pdf_attrs, prod_row, True, findings)
    else:
        unit, db_xrefs, db_apps, db_bom, db_subs = fetch_db_unit(yt)
        if not unit:
            findings.add(yt, "META", "unit_in_db", "MISSING_IN_DB",
                         pdf_value="present", db_value="absent",
                         severity="ERROR",
                         notes="unit not present in Django DB")
            if not quiet and stdout:
                stdout.write(f"  [!] YT#{yt}: unit not present in Django DB")
            return
        compare_attributes(yt, pdf_attrs, unit, False, findings)

    compare_interchanges(yt, pdf_pairs, db_xrefs, findings)
    compare_applications(yt, pdf_apps, db_apps, findings)
    compare_bom(yt, pdf_bom, db_bom, findings)
    compare_subs(yt, pdf_subs, db_subs, findings)

    if not quiet and stdout:
        _print_unit_diff(
            stdout, yt, pages_used, pdf_attrs, pdf_pairs,
            pdf_apps, pdf_bom, pdf_subs,
            db_xrefs, db_apps, db_bom, db_subs,
        )


def _print_unit_diff(stdout, yt, pages_used, pdf_attrs, pdf_pairs,
                     pdf_apps, pdf_bom, pdf_subs,
                     db_xrefs, db_apps, db_bom, db_subs):
    stdout.write("")
    stdout.write("=" * 78)
    stdout.write(f"YouTech #{yt}    pages: {','.join(str(p + 1) for p in pages_used) or '(none)'}")
    stdout.write("=" * 78)

    stdout.write(f"  Attributes parsed from PDF: {len(pdf_attrs)}")
    for k, v in list(pdf_attrs.items())[:8]:
        stdout.write(f"      {k:24s} = {v}")
    if len(pdf_attrs) > 8:
        stdout.write(f"      ... +{len(pdf_attrs) - 8} more")

    stdout.write(f"  Interchanges: PDF={len(pdf_pairs):4d}  DB={len(db_xrefs):4d}")
    if pdf_pairs[:3]:
        for m, n in pdf_pairs[:3]:
            stdout.write(f"      PDF:  {m}: {n}")
    if db_xrefs[:3]:
        for r in db_xrefs[:3]:
            stdout.write(f"      DB :  {r['interchange_type']}: {r['cross_ref_number']}")

    stdout.write(f"  Applications: PDF={len(pdf_apps):4d}  DB={len(db_apps):4d}")
    for a in pdf_apps[:3]:
        stdout.write(
            f"      PDF:  {a['make']} | {a['model']} | {a['engine']} | {a['year']}"
        )
    for a in db_apps[:3]:
        stdout.write(
            f"      DB :  {a['make']} | {a['model']} | {a['engine']} | {a['year']}  (id={a['id']})"
        )

    stdout.write(f"  BOM items:    PDF={len(pdf_bom):4d}  DB={len(db_bom):4d}")
    for b in pdf_bom[:3]:
        stdout.write(f"      PDF:  {b['part_name']:30s}  YT:{b['yt_part']:14s}  J&N:{b['jn_part']}")
    for b in db_bom[:3]:
        stdout.write(f"      DB :  {(b.get('description') or '')[:30]:30s}  YT:{(b.get('yt_number') or ''):14s}  J&N:{b.get('j_and_n')}")

    stdout.write(f"  Substitutes:  PDF={len(pdf_subs):4d}  DB={len(db_subs):4d}")
    for s in pdf_subs[:3]:
        stdout.write(f"      PDF:  YT:{s['yt']}  J&N:{s['jn']}")
    for s in db_subs[:3]:
        stdout.write(f"      DB :  YT:{s.get('substitute_number')}")
    stdout.flush()


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    help = "Audit a buyers-guide PDF against the live DB (or a staging DB)."

    def add_arguments(self, parser):
        parser.add_argument("--pdf", required=True, help="Path to the PDF to audit")
        parser.add_argument("--unit", default=None, help="Audit a single YouTech number")
        parser.add_argument("--sample", type=int, default=10,
                            help="Random N units (seed=42) when --unit not given (default: 10)")
        parser.add_argument("--output", default=None, help="CSV output path")
        parser.add_argument("--quiet", action="store_true",
                            help="Suppress per-unit console output")
        parser.add_argument("--staging", default=None,
                            help="Path to staging sqlite DB (compare against staging instead of Django DB)")

    def handle(self, *args, **options):
        sys.stdout.reconfigure(line_buffering=True)
        pdf_path = options["pdf"]
        if not os.path.exists(pdf_path):
            self.stderr.write(self.style.ERROR(f"PDF not found: {pdf_path}"))
            sys.exit(1)

        pdf_name = os.path.basename(pdf_path)
        out_path = options["output"] or os.path.join(
            str(settings.BASE_DIR),
            f"audit_{os.path.splitext(pdf_name)[0].replace(' ', '_')}.csv"
        )

        staging_conn = None
        if options["staging"]:
            staging_path = options["staging"]
            if not os.path.exists(staging_path):
                self.stderr.write(self.style.ERROR(f"Staging DB not found: {staging_path}"))
                sys.exit(1)
            staging_conn = sqlite3.connect(staging_path)

        self.stdout.write(f"PDF:      {pdf_path}", ending="\n")
        self.stdout.write(f"DB:       {'staging=' + options['staging'] if staging_conn else 'Django (' + str(settings.DATABASES['default']['NAME']) + ')'}")
        self.stdout.write(f"Output:   {out_path}")
        self.stdout.write("")
        self.stdout.flush()

        # Pass 1: enumerate
        t0 = time.time()
        self.stdout.write("Pass 1/2: enumerating units in PDF...", ending="\n")
        self.stdout.flush()
        unit_pages = enumerate_units(pdf_path, stdout=self.stdout)
        t_enum = time.time() - t0
        self.stdout.write(
            f"  found {len(unit_pages):,} unique YT numbers across PDF "
            f"({t_enum:.1f}s)"
        )
        self.stdout.flush()

        # Choose sample
        if options["unit"]:
            target_yts = [options["unit"]]
            if options["unit"] not in unit_pages:
                self.stdout.write(self.style.WARNING(
                    f"Note: YT#{options['unit']} not found in this PDF. Will still audit "
                    f"(may yield 'unit_in_db' findings only)."
                ))
                # Still allow audit so we can show 'unit_in_db' status
                unit_pages.setdefault(options["unit"], set())
        else:
            random.seed(42)
            all_yts = sorted(unit_pages.keys())
            n = min(options["sample"], len(all_yts))
            target_yts = random.sample(all_yts, n)

        self.stdout.write(f"Pass 2/2: auditing {len(target_yts)} unit(s)...")
        self.stdout.write("")
        self.stdout.flush()

        findings = Findings(pdf_name)
        for i, yt in enumerate(target_yts, 1):
            t1 = time.time()
            audit_one_unit(
                yt, pdf_path, unit_pages, findings,
                stdout=self.stdout, quiet=options["quiet"],
                staging_conn=staging_conn, pdf_name=pdf_name,
            )
            t1 = time.time() - t1
            if not options["quiet"]:
                self.stdout.write(f"  (audited YT#{yt} in {t1:.1f}s)  [{i}/{len(target_yts)}]")
                self.stdout.flush()

        # Write CSV
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            fieldnames = ["pdf_name", "unit_number", "category", "field", "status",
                          "pdf_value", "db_value", "severity", "notes"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in findings.rows:
                writer.writerow(row)

        if staging_conn:
            staging_conn.close()

        self._print_summary(findings, target_yts, out_path)

    def _print_summary(self, findings, target_yts, out_path):
        self.stdout.write("")
        self.stdout.write("=" * 78)
        self.stdout.write("AUDIT SUMMARY")
        self.stdout.write("=" * 78)
        self.stdout.write(f"  Units checked:           {len(target_yts):>6}")
        self.stdout.write(f"  Findings rows:           {len(findings.rows):>6}")
        self.stdout.write(f"  ERROR findings:          {findings.severity_counter.get('ERROR', 0):>6}")
        self.stdout.write(f"  WARN findings:           {findings.severity_counter.get('WARN', 0):>6}")
        self.stdout.write(f"  INFO findings:           {findings.severity_counter.get('INFO', 0):>6}")
        self.stdout.write("")
        self.stdout.write("  Top 10 issue types:")
        for tag, n in findings.issue_counter.most_common(10):
            self.stdout.write(f"    {n:>5}  {tag}")
        self.stdout.write("")
        self.stdout.write(f"  CSV written: {out_path}")
        self.stdout.flush()
