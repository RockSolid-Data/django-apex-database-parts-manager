"""
Clean up Parts that have pipe-delimited interchange data stuffed into
yt_number or part_name fields.

These were created by the BOM importer when the PDF parser misclassified
interchange text as BOM entries. The parent units already have proper
CrossReference records, so these Parts are pure junk.

Usage:
    python manage.py cleanup_interchange_in_parts --report-only
    python manage.py cleanup_interchange_in_parts
"""

from django.core.management.base import BaseCommand

from catalog.models import BOM, BOMItem, Part


class Command(BaseCommand):
    help = "Remove Parts with pipe-delimited interchange data in yt_number/part_name fields."

    def add_arguments(self, parser):
        parser.add_argument(
            "--report-only",
            action="store_true",
            dest="report_only",
            help="Show what would be cleaned without making changes",
        )

    def handle(self, *args, **options):
        import sys
        sys.stdout.reconfigure(line_buffering=True)

        # Category 1: Parts where yt_number contains pipes (entirely bogus)
        bad_yt = Part.objects.filter(yt_number__contains="|")

        # Category 2: Parts where part_name contains pipes but yt_number does
        # NOT — the yt_number may be valid, only part_name is corrupted
        bad_name_only = (
            Part.objects.filter(part_name__contains="|")
            .exclude(yt_number__contains="|")
        )

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write("INTERCHANGE-IN-FIELDS CLEANUP")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Parts with pipe in yt_number (delete):      {bad_yt.count()}")
        self.stdout.write(f"  Parts with pipe in part_name only (fix):    {bad_name_only.count()}")

        if options["report_only"]:
            self._report(bad_yt, bad_name_only)
            return

        self._cleanup(bad_yt, bad_name_only)

    def _report(self, bad_yt, bad_name_only):
        self.stdout.write("\n--- Parts to DELETE (pipe in yt_number) ---")
        for p in bad_yt:
            bom_items = BOMItem.objects.filter(part=p)
            bom_info = ""
            if bom_items.exists():
                bi = bom_items.first()
                unit_num = bi.bom.unit.unit_number if bi.bom.unit else "?"
                bom_info = f"  [BOM -> unit {unit_num}]"
            self.stdout.write(
                f"  pk={p.pk:<6} yt={p.yt_number[:60]!r:<62}{bom_info}"
            )

        self.stdout.write("\n--- Parts to FIX (pipe in part_name only) ---")
        for p in bad_name_only:
            bom_items = BOMItem.objects.filter(part=p)
            bom_info = ""
            if bom_items.exists():
                bi = bom_items.first()
                unit_num = bi.bom.unit.unit_number if bi.bom.unit else "?"
                bom_info = f"  [BOM -> unit {unit_num}, will delete BOMItem]"
            self.stdout.write(
                f"  pk={p.pk:<6} yt={p.yt_number!r:<20} "
                f"name={p.part_name[:50]!r}{bom_info}"
            )
        self.stdout.write("")

    def _cleanup(self, bad_yt, bad_name_only):
        # --- Delete Parts with pipe in yt_number ---
        delete_pks = list(bad_yt.values_list("pk", flat=True))
        if delete_pks:
            # Remove BOMItems pointing to these Parts
            bom_items_deleted = BOMItem.objects.filter(part_id__in=delete_pks).delete()[0]
            self.stdout.write(f"  Deleted {bom_items_deleted} BOMItem(s) for bad Parts")

            # Check if any BOMs are now empty and should be removed
            for pk in delete_pks:
                for bi_bom_id in BOMItem.objects.filter(part_id=pk).values_list("bom_id", flat=True):
                    remaining = BOMItem.objects.filter(bom_id=bi_bom_id).exclude(part_id__in=delete_pks).count()
                    if remaining == 0:
                        BOM.objects.filter(pk=bi_bom_id).delete()

            # Delete the bad Parts
            parts_deleted = Part.objects.filter(pk__in=delete_pks).delete()[0]
            self.stdout.write(f"  Deleted {parts_deleted} Part(s) with pipe in yt_number")

        # --- Fix Parts with pipe in part_name only ---
        fixed_count = 0
        for p in bad_name_only:
            # These have a valid yt_number but corrupted part_name
            # Check if they have a BOMItem — if so, the BOMItem is also bad
            bom_items = BOMItem.objects.filter(part=p)
            if bom_items.exists():
                # This part was created from a bad BOM row — delete it entirely
                bom_items.delete()
                p.delete()
                self.stdout.write(f"  Deleted Part pk={p.pk} (bad BOM entry, yt={p.yt_number!r})")
            else:
                # Part has a valid yt_number, just clear the corrupted fields
                p.part_name = ""
                p.notes = ""
                p.save(update_fields=["part_name", "notes"])
                self.stdout.write(f"  Fixed Part pk={p.pk} (cleared part_name, yt={p.yt_number!r})")
            fixed_count += 1

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write("CLEANUP COMPLETE")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"  Parts deleted:   {len(delete_pks)}")
        self.stdout.write(f"  Parts fixed:     {fixed_count}")
        self.stdout.write("")
