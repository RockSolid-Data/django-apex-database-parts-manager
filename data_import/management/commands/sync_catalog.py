"""
Additive catalog sync: inserts new reference records from seed.sqlite3
into the customer database. Never updates or deletes existing records.

Uses SQLite ATTACH DATABASE for bulk INSERT INTO...SELECT operations
instead of row-by-row inserts — syncs ~3 million records in seconds.

Lookup key is seed_id. If a record with that seed_id already exists in
the customer DB, it is skipped entirely (even if the customer edited it).
"""

import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

SYNC_MODELS = [
    ("catalog", "UnitType", "catalog_unittype"),
    ("catalog", "Application", "catalog_application"),
    ("catalog", "ApplicationSpecification", "catalog_applicationspecification"),
    ("catalog", "Unit", "catalog_unit"),
    ("catalog", "ApplicationUnit", "catalog_applicationunit"),
    ("catalog", "CrossReference", "catalog_crossreference"),
    ("catalog", "Substitute", "catalog_substitute"),
    ("catalog", "GearReductionSubstitution", "catalog_gearreductionsubstitution"),
    ("catalog", "Part", "catalog_part"),
    ("catalog", "PartSubstitute", "catalog_partsubstitute"),
    ("catalog", "PartInterchange", "catalog_partinterchange"),
    ("catalog", "PartSuperseding", "catalog_partsuperseding"),
    ("catalog", "BOM", "catalog_bom"),
    ("catalog", "BOMItem", "catalog_bomitem"),
]

SKIP_COLUMNS = {"id"}


class Command(BaseCommand):
    help = "Sync new catalog records from seed.sqlite3 (additive only, bulk SQL)."

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

        t0 = time.perf_counter()
        db_cursor = connection.cursor()

        seed_path_str = str(seed_path).replace("'", "''")
        db_cursor.execute(f"ATTACH DATABASE '{seed_path_str}' AS seed")

        try:
            totals = {"inserted": 0, "skipped": 0}

            for _app, model_name, db_table in SYNC_MODELS:
                inserted, skipped = self._sync_table(
                    db_cursor, model_name, db_table, dry_run
                )
                totals["inserted"] += inserted
                totals["skipped"] += skipped

            if not dry_run:
                connection.connection.commit()
        finally:
            db_cursor.execute("DETACH DATABASE seed")

        elapsed = time.perf_counter() - t0
        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Catalog sync complete: "
            f"{totals['inserted']:,} new records inserted, "
            f"{totals['skipped']:,} existing records skipped "
            f"({elapsed:.1f}s)."
        ))

    def _sync_table(self, db_cursor, model_name, db_table, dry_run):
        try:
            db_cursor.execute(
                f"SELECT COUNT(*) FROM seed.[{db_table}] WHERE seed_id IS NOT NULL"
            )
            seed_total = db_cursor.fetchone()[0]
        except Exception:
            self.stderr.write(f"  {model_name}: table not found in seed -- skipping")
            return 0, 0

        if seed_total == 0:
            return 0, 0

        db_cursor.execute(f"PRAGMA seed.table_info([{db_table}])")
        all_columns = [row[1] for row in db_cursor.fetchall()]
        insert_columns = [c for c in all_columns if c not in SKIP_COLUMNS]

        col_list = ", ".join(f"[{c}]" for c in insert_columns)

        new_count_sql = (
            f"SELECT COUNT(*) FROM seed.[{db_table}] s "
            f"WHERE s.seed_id IS NOT NULL "
            f"AND s.seed_id NOT IN ("
            f"  SELECT seed_id FROM main.[{db_table}] WHERE seed_id IS NOT NULL"
            f")"
        )
        db_cursor.execute(new_count_sql)
        to_insert = db_cursor.fetchone()[0]
        skipped = seed_total - to_insert

        if to_insert > 0 and not dry_run:
            insert_sql = (
                f"INSERT INTO main.[{db_table}] ({col_list}) "
                f"SELECT {col_list} FROM seed.[{db_table}] s "
                f"WHERE s.seed_id IS NOT NULL "
                f"AND s.seed_id NOT IN ("
                f"  SELECT seed_id FROM main.[{db_table}] WHERE seed_id IS NOT NULL"
                f")"
            )
            db_cursor.execute(insert_sql)

        if to_insert or skipped:
            self.stdout.write(
                f"  {model_name}: {to_insert:,} inserted, {skipped:,} skipped"
            )

        return to_insert, skipped
