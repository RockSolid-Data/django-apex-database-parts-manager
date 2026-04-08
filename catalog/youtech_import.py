"""Bulk import parsed YouTech \"Our Numbers to Others\" rows into Part + PartInterchange."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from .models import Part, PartInterchange
from .pdf_utils import detect_category

logger = logging.getLogger(__name__)


def _normalise_interchanges(raw: Any) -> list[dict]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return []
        return data if isinstance(data, list) else []
    return []


def import_youtech_rows(
    rows: list[dict[str, Any]],
    *,
    progress_callback: Callable[[int, int], None] | None = None,
    progress_every: int = 1000,
) -> dict[str, Any]:
    """
    Import or update parts from parsed PDF rows.

    Each row supports:
      - yt_number (str)
      - description (str)
      - category (str, optional — blank triggers detect_category)
      - interchanges: list[{"vendor", "number"}] or JSON string (as from the web form)

    Returns dict with keys: created, updated, skipped, report (list of row summaries).
    """
    report: list[dict] = []
    created = updated = skipped = 0

    total_rows = len(rows)
    logger.info("YouTech import started: %d rows", total_rows)
    for row_index, row in enumerate(rows):
        if (
            progress_callback
            and progress_every > 0
            and (row_index + 1) % progress_every == 0
        ):
            progress_callback(row_index + 1, total_rows)
        yt = (row.get("yt_number") or "").strip()
        desc = (row.get("description") or "").strip()
        category = (row.get("category") or "").strip()
        interchanges = _normalise_interchanges(row.get("interchanges"))

        if not yt:
            skipped += 1
            logger.warning("  Row %d: skipped (no YT number)", row_index + 1)
            report.append({
                "yt_number": yt or "(blank)",
                "description": desc,
                "category": category,
                "action": "skipped",
                "reason": "No YT number",
                "interchange_count": 0,
                "ix_created": 0,
                "pk": None,
            })
            continue

        defaults = {
            "part_name": desc,
            "category": category,
            "description": desc,
            "has_interchange": bool(interchanges),
        }
        if not category:
            defaults["category"] = detect_category(desc)

        try:
            obj, was_created = Part.objects.update_or_create(
                yt_number=yt,
                defaults=defaults,
            )
            action = "created" if was_created else "updated"
            if was_created:
                created += 1
            else:
                updated += 1

            ix_created = 0
            for ix in interchanges:
                num = (ix.get("number") or "").strip()
                vendor = (ix.get("vendor") or "").strip()
                if not num:
                    continue
                existing_ix = PartInterchange.objects.filter(
                    part=obj,
                    interchange_number=num,
                    source_name=vendor,
                ).first()
                if existing_ix is None and vendor:
                    existing_ix = PartInterchange.objects.filter(
                        part=obj,
                        interchange_number=num,
                        source_name="",
                        notes=vendor,
                    ).first()
                if existing_ix:
                    update_fields = []
                    if vendor and not existing_ix.source_name:
                        existing_ix.source_name = vendor
                        update_fields.append("source_name")
                    if vendor and existing_ix.notes == vendor:
                        existing_ix.notes = ""
                        update_fields.append("notes")
                    if update_fields:
                        existing_ix.save(update_fields=update_fields)
                else:
                    PartInterchange.objects.create(
                        part=obj,
                        interchange_number=num,
                        source_name=vendor,
                    )
                    ix_created += 1

            if interchanges and not obj.has_interchange:
                obj.has_interchange = True
                obj.save(update_fields=["has_interchange"])

            logger.info("  %s %s (pk=%s) — %d interchange(s), %d new",
                        action.upper(), yt, obj.pk,
                        len([x for x in interchanges if x.get("number")]), ix_created)
            report.append({
                "yt_number": yt,
                "description": desc,
                "category": category or defaults.get("category", ""),
                "action": action,
                "reason": "",
                "interchange_count": len([x for x in interchanges if x.get("number")]),
                "ix_created": ix_created,
                "pk": obj.pk,
            })
        except Exception as exc:
            skipped += 1
            logger.error("  ERROR %s: %s", yt, exc)
            report.append({
                "yt_number": yt,
                "description": desc,
                "category": category,
                "action": "error",
                "reason": str(exc),
                "interchange_count": 0,
                "ix_created": 0,
                "pk": None,
            })

    if progress_callback and total_rows:
        progress_callback(total_rows, total_rows)

    logger.info("YouTech import finished: %d created, %d updated, %d skipped",
                created, updated, skipped)

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "report": report,
    }
