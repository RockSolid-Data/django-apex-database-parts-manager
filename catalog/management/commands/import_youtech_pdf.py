"""Import YouTech \"Our Numbers to Others\" PDF via CLI (suited for very large files)."""

from django.core.management.base import BaseCommand, CommandError

from catalog.pdf_utils import parse_youtech_pdf
from catalog.youtech_import import import_youtech_rows


class Command(BaseCommand):
    help = (
        "Parse a YouTech Our Numbers to Others PDF and import parts + interchanges. "
        "Use this for full catalogs; the web preview is impractical for tens of thousands of rows."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "pdf",
            type=str,
            help="Path to the .pdf file",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse only: print counts, do not write to the database",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            metavar="N",
            help="Import at most the first N entries (after parsing)",
        )

    def handle(self, *args, **options):
        pdf_path = options["pdf"]
        dry_run = options["dry_run"]
        limit = options["limit"]

        try:
            entries = parse_youtech_pdf(pdf_path)
        except OSError as exc:
            raise CommandError(f"Cannot read PDF: {exc}") from exc
        except Exception as exc:
            raise CommandError(f"PDF parse failed: {exc}") from exc

        total_parsed = len(entries)
        if limit is not None:
            entries = entries[:limit]

        ix_total = sum(len(e.get("interchanges") or []) for e in entries)

        self.stdout.write(f"Parsed entries: {total_parsed:,}")
        if limit is not None:
            self.stdout.write(f"Applying limit: importing first {len(entries):,} rows")
        self.stdout.write(f"Interchange lines in scope: {ix_total:,}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no database changes."))
            return

        self.stdout.write("Importing…")

        def _progress(done: int, total: int) -> None:
            self.stdout.write(f"  … {done:,} / {total:,} rows processed")

        result = import_youtech_rows(entries, progress_callback=_progress)
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created: {result['created']:,}, "
                f"updated: {result['updated']:,}, "
                f"skipped/errors: {result['skipped']:,}"
            )
        )
