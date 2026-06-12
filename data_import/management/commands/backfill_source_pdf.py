"""
One-time backfill of source_pdf on Part, Unit, and Application.

Rules (based on import history):

  Parts   → all from PDF 14 - Components
  Apps    → based on unit_type_name:
              Alternator  → PDF 4 - Applications Alternators
              Generator   → PDF 5 - Applications Generators
              Starter     → PDF 6 - Applications Starters
              Motor       → PDF 7 - Applications Motors
              MGU         → PDF 8 - Applications MGU
  Units   → based on unit_type_category:
              Alternator  → PDF 9 - Buyers Guide Alternators
              Starter     → PDF 10 - Buyers Guide Starters
              Generator   → PDF 11 - Buyers Guide Generators
              Motor/DC Motor → PDF 12 - Buyers Guide Motors
              Pump        → PDF 13 - Buyers Guide Pumps
              Mild Hybrid (MGU) → PDF 13 - Buyers Guide Pumps  (same PDF)
"""

from django.core.management.base import BaseCommand
from catalog.models import Application, Part, Unit


APP_PDF_MAP = {
    "Alternator": "PDF 4 - Applications Alternators",
    "Generator": "PDF 5 - Applications Generators",
    "Starter": "PDF 6 - Applications Starters",
    "Motor": "PDF 7 - Applications Motors",
    "MGU": "PDF 8 - Applications MGU",
}

UNIT_PDF_MAP = {
    "Alternator": "PDF 9 - Buyers Guide Alternators",
    "Starter": "PDF 10 - Buyers Guide Starters",
    "Generator": "PDF 11 - Buyers Guide Generators",
    "Motor": "PDF 12 - Buyers Guide Motors",
    "DC Motor": "PDF 12 - Buyers Guide Motors",
    "Pump": "PDF 13 - Buyers Guide Pumps",
    "Mild Hybrid (MGU)": "PDF 13 - Buyers Guide Pumps",
}


class Command(BaseCommand):
    help = "Backfill source_pdf on Part, Unit, and Application records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show what would change without writing.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        tag = "[DRY RUN] " if dry else ""

        # -- Parts --
        parts_qs = Part.objects.filter(source_pdf="")
        parts_count = parts_qs.count()
        if not dry:
            parts_qs.update(source_pdf="PDF 14 - Components")
        self.stdout.write(f"{tag}Parts: {parts_count} -> PDF 14 - Components")

        # -- Applications --
        total_apps = 0
        for utype, pdf_label in APP_PDF_MAP.items():
            qs = Application.objects.filter(unit_type_name=utype, source_pdf="")
            n = qs.count()
            if not dry:
                qs.update(source_pdf=pdf_label)
            self.stdout.write(f"{tag}Applications ({utype}): {n} -> {pdf_label}")
            total_apps += n
        remaining = Application.objects.filter(source_pdf="").count()
        if remaining:
            self.stdout.write(
                self.style.WARNING(f"{tag}Applications with no mapping: {remaining}")
            )

        # -- Units --
        total_units = 0
        for cat, pdf_label in UNIT_PDF_MAP.items():
            qs = Unit.objects.filter(unit_type_category=cat, source_pdf="")
            n = qs.count()
            if not dry:
                qs.update(source_pdf=pdf_label)
            self.stdout.write(f"{tag}Units ({cat}): {n} -> {pdf_label}")
            total_units += n
        remaining = Unit.objects.filter(source_pdf="").count()
        if remaining:
            self.stdout.write(
                self.style.WARNING(f"{tag}Units with no mapping: {remaining}")
            )

        self.stdout.write(self.style.SUCCESS(
            f"\n{tag}Done. Parts={parts_count}  Apps={total_apps}  Units={total_units}"
        ))
