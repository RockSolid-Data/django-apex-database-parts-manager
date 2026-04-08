"""
Additive catalog sync: inserts new reference records from seed.sqlite3
into the customer database. Never updates or deletes existing records.

Lookup key is seed_id. If a record with that seed_id already exists in
the customer DB, it is skipped entirely (even if the customer edited it).
"""

import sqlite3
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

SYNC_MODELS = [
    ("catalog", "UnitType"),
    ("catalog", "Application"),
    ("catalog", "ApplicationSpecification"),
    ("catalog", "Unit"),
    ("catalog", "ApplicationUnit"),
    ("catalog", "CrossReference"),
    ("catalog", "Substitute"),
    ("catalog", "GearReductionSubstitution"),
    ("catalog", "Part"),
    ("catalog", "PartSubstitute"),
    ("catalog", "PartInterchange"),
    ("catalog", "PartSuperseding"),
    ("catalog", "BOM"),
    ("catalog", "BOMItem"),
]

SKIP_COLUMNS = {"id"}

FK_SUFFIX = "_id"


class Command(BaseCommand):
    help = "Sync new catalog records from seed.sqlite3 (additive only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--seed-db", required=True,
            help="Path to the seed.sqlite3 database",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show what would be inserted without actually doing it",
        )

    def handle(self, *args, **options):
        seed_path = Path(options["seed_db"])
        dry_run = options["dry_run"]

        if not seed_path.exists():
            raise CommandError(f"Seed database not found: {seed_path}")

        seed_conn = sqlite3.connect(str(seed_path))
        seed_conn.row_factory = sqlite3.Row

        totals = {"inserted": 0, "skipped": 0}

        for app_label, model_name in SYNC_MODELS:
            inserted, skipped = self._sync_model(
                seed_conn, app_label, model_name, dry_run
            )
            totals["inserted"] += inserted
            totals["skipped"] += skipped

        seed_conn.close()

        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Catalog sync complete: "
            f"{totals['inserted']} new records inserted, "
            f"{totals['skipped']} existing records skipped."
        ))

    def _sync_model(self, seed_conn, app_label, model_name, dry_run):
        Model = apps.get_model(app_label, model_name)
        db_table = Model._meta.db_table
        cursor = seed_conn.cursor()

        try:
            cursor.execute(f"SELECT * FROM [{db_table}] WHERE seed_id IS NOT NULL")
        except sqlite3.OperationalError:
            self.stderr.write(f"  {model_name}: table not found in seed -- skipping")
            return 0, 0

        seed_rows = cursor.fetchall()
        if not seed_rows:
            return 0, 0

        columns = [desc[0] for desc in cursor.description]

        existing_seed_ids = set(
            Model.objects.filter(seed_id__isnull=False)
            .values_list("seed_id", flat=True)
        )

        inserted = 0
        skipped = 0

        for row in seed_rows:
            row_dict = dict(zip(columns, row))
            seed_id = row_dict.get("seed_id")
            if seed_id is None:
                continue

            if seed_id in existing_seed_ids:
                skipped += 1
                continue

            if dry_run:
                inserted += 1
                continue

            insert_data = {}
            for col in columns:
                if col in SKIP_COLUMNS:
                    continue
                value = row_dict[col]
                insert_data[col] = value

            col_names = list(insert_data.keys())
            placeholders = ", ".join(["?" for _ in col_names])
            col_str = ", ".join([f"[{c}]" for c in col_names])
            values = [insert_data[c] for c in col_names]

            try:
                with connection.cursor() as db_cursor:
                    db_cursor.execute(
                        f"INSERT INTO [{db_table}] ({col_str}) VALUES ({placeholders})",
                        values,
                    )
                inserted += 1
                existing_seed_ids.add(seed_id)
            except Exception as e:
                self.stderr.write(
                    f"  {model_name} seed_id={seed_id}: insert failed -- {e}"
                )

        if inserted or skipped:
            self.stdout.write(
                f"  {model_name}: {inserted} inserted, {skipped} skipped"
            )

        return inserted, skipped
