"""
Build a reviewable HTML + JSON preview for one YouTech part from an image-only PDF (OCR)
or from a pasted interchange table (--interchange-file).

Example::
    python manage.py preview_part_image_pdf \"path/images.pdf\" --yt 1B-6007 --out preview.html
    python manage.py preview_part_image_pdf --yt 1B-6007 --interchange-file ix.txt --description \"Brush\" --out preview.html

After review::
    python manage.py preview_part_image_pdf --apply --json preview.json --replace-interchanges --i-understand
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.template.defaultfilters import escape
from django.urls import reverse

from catalog.image_pdf_interchange import (
    build_preview_entry,
    find_tesseract_exe,
    parse_entry_from_image_pdf,
)
from catalog.models import Part, PartInterchange


def _write_preview_html(out_path: Path, entry: dict, json_path: Path, part_pk: int | None) -> None:
    rows = "".join(
        f"<tr><td>{escape(ix.get('vendor',''))}</td><td><code>{escape(ix.get('number',''))}</code></td></tr>"
        for ix in entry.get("interchanges") or []
    )
    issues_block = ""
    issues_wrap = ""
    if entry.get("issues"):
        issues_block = "<ul>" + "".join(f"<li>{escape(s)}</li>" for s in entry["issues"]) + "</ul>"
        issues_wrap = f'<div class="alert alert-warning">{issues_block}</div>'

    part_link = ""
    if part_pk:
        url = reverse("catalog:part_detail", args=[part_pk])
        part_link = f'<p><a class="btn btn-outline-primary" href="{escape(url)}">Open part in database</a></p>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Preview import — {escape(entry.get("yt_number",""))}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="p-4">
<div class="container" style="max-width:900px">
  <h1 class="h3 mb-3">Review before import</h1>
  <p class="text-muted">Part <strong>{escape(entry.get("yt_number",""))}</strong>
  — {escape(entry.get("description","") or "—")}</p>
  {part_link}
  <p>Interchange rows: <strong>{len(entry.get("interchanges") or [])}</strong>
  &middot; JSON for import: <code>{escape(str(json_path))}</code></p>
  {issues_wrap}
  <div class="table-responsive">
    <table class="table table-sm table-bordered">
      <thead class="table-dark"><tr><th>Source / Name</th><th>Reference number</th></tr></thead>
      <tbody>{rows or '<tr><td colspan="2" class="text-muted">No interchanges parsed</td></tr>'}</tbody>
    </table>
  </div>
  <p class="small text-muted">When satisfied, run apply (see command help). Close this file after review.</p>
</div>
</body>
</html>"""
    out_path.write_text(html, encoding="utf-8")


class Command(BaseCommand):
    help = "OCR an image PDF (or read interchange lines) for one YT part; write HTML + JSON preview."

    def add_arguments(self, parser):
        parser.add_argument(
            "pdf",
            nargs="?",
            type=str,
            default=None,
            help="Path to image-only .pdf (optional if --interchange-file is set)",
        )
        parser.add_argument("--yt", type=str, required=True, help="YT number e.g. 1B-6007")
        parser.add_argument(
            "--out",
            type=str,
            default="preview_part_import.html",
            help="Output HTML path",
        )
        parser.add_argument(
            "--json-out",
            type=str,
            default=None,
            help="Output JSON path (default: next to HTML with .json)",
        )
        parser.add_argument(
            "--interchange-file",
            type=str,
            default=None,
            help="TAB or multi-space separated vendor/number lines (optional; skips OCR)",
        )
        parser.add_argument(
            "--description",
            type=str,
            default="",
            help="Part description when using --interchange-file only",
        )
        parser.add_argument("--dpi", type=int, default=220, help="Render DPI for OCR (default 220)")
        parser.add_argument(
            "--engine",
            type=str,
            choices=["auto", "tesseract", "easyocr"],
            default="auto",
            help="OCR engine: auto prefers Tesseract if installed, else EasyOCR",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply JSON to database (requires --json)",
        )
        parser.add_argument(
            "--json",
            type=str,
            default=None,
            help="JSON file to apply (with --apply)",
        )
        parser.add_argument(
            "--replace-interchanges",
            action="store_true",
            help="With --apply: delete existing PartInterchange rows for this part first",
        )
        parser.add_argument(
            "--i-understand",
            action="store_true",
            help="Required with --apply --replace-interchanges",
        )

    def handle(self, *args, **options):
        yt = options["yt"].strip()
        if options["apply"]:
            return self._apply(options)

        entry: dict | None = None

        if options.get("interchange_file"):
            text = Path(options["interchange_file"]).read_text(encoding="utf-8", errors="replace")
            entry = build_preview_entry(yt, options.get("description") or "", text)
        elif options.get("pdf"):
            eng = options["engine"]
            tess = find_tesseract_exe() if eng in ("auto", "tesseract") else None
            if eng == "tesseract" and not tess:
                raise CommandError(
                    "Tesseract not found. Install it or run with --engine easyocr (pip install easyocr)."
                )
            if tess:
                try:
                    import pytesseract  # noqa: F401
                except ImportError as exc:
                    raise CommandError("Install pytesseract: pip install pytesseract") from exc
            elif eng == "easyocr" or (eng == "auto" and not tess):
                try:
                    import easyocr  # noqa: F401
                except ImportError as exc:
                    raise CommandError("Install easyocr: pip install easyocr") from exc

            pdf_path = options["pdf"]
            entry = parse_entry_from_image_pdf(
                pdf_path,
                yt,
                dpi=options["dpi"],
                tesseract_cmd=tess,
                engine=eng,
            )
            if entry is None:
                raise CommandError(
                    f"Could not find '{yt}' in OCR text. Try higher --dpi, check the scan, "
                    f"or use --interchange-file with lines copied from the PDF."
                )
        else:
            raise CommandError("Provide a PDF path or --interchange-file.")

        out_html = Path(options["out"])
        json_out = options["json_out"] or str(out_html.with_suffix(".json"))
        out_json = Path(json_out)

        part = Part.objects.filter(yt_number__iexact=yt).first()
        payload = {
            "yt_number": entry["yt_number"],
            "description": entry.get("description") or "",
            "interchanges": entry.get("interchanges") or [],
            "issues": entry.get("issues") or [],
        }
        out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _write_preview_html(out_html, entry, out_json, part.pk if part else None)

        self.stdout.write(self.style.SUCCESS(f"Wrote {out_html}"))
        self.stdout.write(self.style.SUCCESS(f"Wrote {out_json}"))
        if entry.get("issues"):
            self.stdout.write(self.style.WARNING(f"Issues flagged: {len(entry['issues'])}"))

    def _apply(self, options):
        path = options.get("json")
        if not path:
            raise CommandError("--apply requires --json path")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        yt = (data.get("yt_number") or options["yt"] or "").strip()
        if not yt:
            raise CommandError("JSON missing yt_number")
        part = Part.objects.filter(yt_number__iexact=yt).first()
        if not part:
            raise CommandError(f"No Part with yt_number matching '{yt}'")
        if options["replace_interchanges"]:
            if not options["i_understand"]:
                raise CommandError("--replace-interchanges requires --i-understand")
            PartInterchange.objects.filter(part=part).delete()

        ix_list = data.get("interchanges") or []
        created = 0
        for ix in ix_list:
            num = (ix.get("number") or "").strip()
            vendor = (ix.get("vendor") or "").strip()
            if not num:
                continue
            exists = PartInterchange.objects.filter(
                part=part,
                interchange_number=num,
                source_name=vendor,
            ).exists()
            if not exists:
                PartInterchange.objects.create(
                    part=part,
                    interchange_number=num,
                    source_name=vendor,
                )
                created += 1
        part.has_interchange = bool(ix_list)
        part.save(update_fields=["has_interchange"])
        self.stdout.write(self.style.SUCCESS(f"Applied {created} interchange row(s) on part pk={part.pk}"))
