"""
Export a catalog-only seed database for distribution with the installer.

Copies db.sqlite3 -> seed.sqlite3 then clears customer/config data while
preserving all table schemas so django_migrations stays consistent.
"""

import shutil
import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

TABLES_TO_CLEAR = [
    # Customer / transactional data
    "invoicing_invoice",
    "invoicing_invoiceitem",
    "invoicing_customer",
    "invoicing_customercontact",
    "invoicing_vendor",
    "invoicing_vendorcontact",
    "invoicing_companysettings",
    "inventory_inventoryadjustment",
    "inventory_inventorycount",
    "inventory_inventorycountitem",

    # User-uploaded images (not reference data)
    "catalog_partimage",

    # Django auth / session data (but NOT schema tables like
    # django_migrations, django_content_type, auth_permission, auth_group)
    "auth_user",
    "auth_user_groups",
    "auth_user_user_permissions",
    "django_admin_log",
    "django_session",

    # Reference/config tables that SHIP with the seed (do NOT add here):
    #   catalog_applicationtype, catalog_applicationtypefield,
    #   catalog_partcategory, catalog_partcategoryfield,
    #   catalog_unittypecategory, catalog_unittypecategoryfield
]


class Command(BaseCommand):
    help = "Export a catalog-only seed.sqlite3 for distribution."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output", default="seed.sqlite3",
            help="Output path (default: seed.sqlite3 in project root)",
        )
        parser.add_argument(
            "--source", default=None,
            help="Source database path (default: Django's configured db)",
        )

    def handle(self, *args, **options):
        source = options["source"] or str(settings.DATABASES["default"]["NAME"])
        output = options["output"]

        source_path = Path(source)
        output_path = Path(output)

        if not source_path.exists():
            self.stderr.write(self.style.ERROR(f"Source database not found: {source_path}"))
            return

        self.stdout.write(f"Copying {source_path} -> {output_path} ...")
        shutil.copy2(source_path, output_path)

        conn = sqlite3.connect(str(output_path))
        cursor = conn.cursor()

        cleared = 0
        for table in TABLES_TO_CLEAR:
            try:
                cursor.execute(f"DELETE FROM [{table}]")
                cleared += 1
            except Exception as e:
                self.stderr.write(f"  Warning: could not clear {table}: {e}")

        conn.commit()
        cursor.execute("VACUUM")
        conn.close()

        size_mb = output_path.stat().st_size / (1024 * 1024)
        self.stdout.write(self.style.SUCCESS(
            f"Seed exported: {output_path} ({size_mb:.1f} MB, {cleared} tables cleared)"
        ))
