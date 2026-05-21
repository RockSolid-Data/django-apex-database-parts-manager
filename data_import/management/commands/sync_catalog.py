"""
Catalog sync: inserts new records from seed.sqlite3 into the customer
database AND fills in blank fields on existing records.

Uses SQLite ATTACH DATABASE for bulk operations. Per-table commits ensure
partial progress is saved even if a later table fails.

Modes:
  - Default: INSERT OR IGNORE new records + fill blank fields on existing
  - --force-update: overwrite all catalog fields from seed (respects BUSINESS_FIELDS)
  - --dry-run: preview what would change without writing
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

# Customer-owned fields: NEVER overwritten by seed, even with --force-update.
BUSINESS_FIELDS = {
    "catalog_part": {
        "cost_price", "markup_percent", "price", "price_updated_at",
        "track_inventory", "stock_quantity", "reorder_qty", "bin_number",
    },
    "catalog_bomitem": {
        "stock_qty", "bin_number",
    },
}

# Columns excluded from UPDATE on all tables (auto-managed).
NEVER_UPDATE_COLUMNS = {"id", "seed_id", "created_at", "updated_at"}


class Command(BaseCommand):
    help = "Sync catalog records from seed.sqlite3 (insert new + fill blanks)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--seed-db", required=True,
            help="Path to the seed.sqlite3 database",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview changes without writing to the database",
        )
        parser.add_argument(
            "--force-update", action="store_true",
            help="Overwrite all catalog fields from seed (still respects business fields)",
        )

    def handle(self, *args, **options):
        seed_path = Path(options["seed_db"])
        dry_run = options["dry_run"]
        force_update = options["force_update"]

        if not seed_path.exists():
            raise CommandError(f"Seed database not found: {seed_path}")

        t0 = time.perf_counter()
        cursor = connection.cursor()

        seed_path_str = str(seed_path).replace("'", "''")
        cursor.execute(f"ATTACH DATABASE '{seed_path_str}' AS seed")

        totals = {"inserted": 0, "updated": 0, "skipped": 0, "conflicts": 0, "errors": []}

        try:
            for _app, model_name, db_table in SYNC_MODELS:
                try:
                    result = self._sync_table(
                        cursor, model_name, db_table, dry_run, force_update
                    )
                    totals["inserted"] += result["inserted"]
                    totals["updated"] += result["updated"]
                    totals["skipped"] += result["skipped"]
                    totals["conflicts"] += result["conflicts"]

                    if not dry_run:
                        connection.connection.commit()

                except Exception as exc:
                    totals["errors"].append((model_name, str(exc)))
                    self.stderr.write(self.style.ERROR(
                        f"  {model_name}: FAILED -- {exc}"
                    ))
                    connection.connection.rollback()

        finally:
            cursor.execute("DETACH DATABASE seed")

        elapsed = time.perf_counter() - t0
        prefix = "[DRY RUN] " if dry_run else ""

        self.stdout.write(self.style.SUCCESS(
            f"\n{prefix}Catalog sync complete: "
            f"{totals['inserted']:,} inserted, "
            f"{totals['updated']:,} updated, "
            f"{totals['skipped']:,} unchanged"
            f" ({elapsed:.1f}s)."
        ))

        if totals["conflicts"]:
            self.stdout.write(self.style.WARNING(
                f"  {totals['conflicts']:,} records skipped due to conflicts "
                f"(UNIQUE constraint -- customer already has these)."
            ))

        if totals["errors"]:
            self.stderr.write(self.style.WARNING(
                f"  {len(totals['errors'])} table(s) had errors:"
            ))
            for model, err in totals["errors"]:
                self.stderr.write(f"    - {model}: {err}")

    def _sync_table(self, cursor, model_name, db_table, dry_run, force_update):
        result = {"inserted": 0, "updated": 0, "skipped": 0, "conflicts": 0}

        try:
            cursor.execute(
                f"SELECT COUNT(*) FROM seed.[{db_table}] WHERE seed_id IS NOT NULL"
            )
            seed_total = cursor.fetchone()[0]
        except Exception:
            self.stderr.write(f"  {model_name}: table not found in seed -- skipping")
            return result

        if seed_total == 0:
            return result

        # Get column info from the MAIN table (what the customer has)
        cursor.execute(f"PRAGMA main.table_info([{db_table}])")
        main_columns_info = cursor.fetchall()
        main_columns = {row[1] for row in main_columns_info}
        main_col_types = {row[1]: row[2].upper() for row in main_columns_info}

        # Get seed columns — only sync columns that exist in BOTH (schema drift safe)
        cursor.execute(f"PRAGMA seed.table_info([{db_table}])")
        seed_columns = {row[1] for row in cursor.fetchall()}

        common_columns = main_columns & seed_columns
        insert_columns = sorted(c for c in common_columns if c not in SKIP_COLUMNS)
        col_list = ", ".join(f"[{c}]" for c in insert_columns)

        # --- Phase 1: INSERT new records ---
        cursor.execute(
            f"SELECT COUNT(*) FROM seed.[{db_table}] s "
            f"WHERE s.seed_id IS NOT NULL "
            f"AND s.seed_id NOT IN ("
            f"  SELECT seed_id FROM main.[{db_table}] WHERE seed_id IS NOT NULL"
            f")"
        )
        to_insert = cursor.fetchone()[0]

        actual_inserted = 0
        if to_insert > 0 and not dry_run:
            cursor.execute(f"SELECT COUNT(*) FROM main.[{db_table}]")
            before_count = cursor.fetchone()[0]

            insert_sql = (
                f"INSERT OR IGNORE INTO main.[{db_table}] ({col_list}) "
                f"SELECT {col_list} FROM seed.[{db_table}] s "
                f"WHERE s.seed_id IS NOT NULL "
                f"AND s.seed_id NOT IN ("
                f"  SELECT seed_id FROM main.[{db_table}] WHERE seed_id IS NOT NULL"
                f")"
            )
            cursor.execute(insert_sql)

            cursor.execute(f"SELECT COUNT(*) FROM main.[{db_table}]")
            after_count = cursor.fetchone()[0]
            actual_inserted = after_count - before_count
        elif to_insert > 0:
            actual_inserted = to_insert

        conflicts = max(0, to_insert - actual_inserted)
        result["inserted"] = actual_inserted
        result["conflicts"] = conflicts

        # Log conflict details for developer diagnostics
        if conflicts > 0 and not dry_run:
            self._log_conflicts(cursor, db_table, model_name)

        # --- Phase 2: UPDATE existing records (fill blanks or force) ---
        biz_fields = BUSINESS_FIELDS.get(db_table, set())
        update_candidates = sorted(
            c for c in common_columns
            if c not in NEVER_UPDATE_COLUMNS and c not in biz_fields
        )

        updated = 0
        if update_candidates:
            updated = self._update_existing(
                cursor, db_table, update_candidates, main_col_types,
                dry_run, force_update,
            )

        result["updated"] = updated
        result["skipped"] = seed_total - to_insert - updated

        if actual_inserted or updated or conflicts:
            line = f"  {model_name}: {actual_inserted:,} inserted, {updated:,} updated"
            if conflicts:
                line += f", {conflicts:,} skipped (conflict)"
            self.stdout.write(line)

        return result

    def _log_conflicts(self, cursor, db_table, model_name):
        """Log details about records that were skipped due to UNIQUE conflicts."""
        try:
            cursor.execute(
                f"SELECT s.seed_id FROM seed.[{db_table}] s "
                f"WHERE s.seed_id IS NOT NULL "
                f"AND s.seed_id NOT IN ("
                f"  SELECT seed_id FROM main.[{db_table}] WHERE seed_id IS NOT NULL"
                f") LIMIT 20"
            )
            orphan_seed_ids = [row[0] for row in cursor.fetchall()]

            if orphan_seed_ids:
                id_list = ", ".join(str(sid) for sid in orphan_seed_ids[:10])
                self.stderr.write(
                    f"  {model_name}: conflict seed_ids (first 10): [{id_list}]"
                )
        except Exception:
            pass

    def _update_existing(self, cursor, db_table, columns, col_types, dry_run, force_update):
        """Update existing records: fill blanks (default) or overwrite (force)."""

        if force_update:
            set_clauses = [f"[{c}] = s.[{c}]" for c in columns]
        else:
            set_clauses = []
            for c in columns:
                col_type = col_types.get(c, "TEXT")
                if _is_text_type(col_type):
                    set_clauses.append(
                        f"[{c}] = CASE WHEN m.[{c}] IS NULL OR m.[{c}] = '' "
                        f"THEN s.[{c}] ELSE m.[{c}] END"
                    )
                else:
                    set_clauses.append(
                        f"[{c}] = CASE WHEN m.[{c}] IS NULL "
                        f"THEN s.[{c}] ELSE m.[{c}] END"
                    )

        if not set_clauses:
            return 0

        # Count records that would actually change
        if not force_update:
            where_parts = []
            for c in columns:
                col_type = col_types.get(c, "TEXT")
                if _is_text_type(col_type):
                    where_parts.append(
                        f"((m.[{c}] IS NULL OR m.[{c}] = '') "
                        f"AND s.[{c}] IS NOT NULL AND s.[{c}] != '')"
                    )
                else:
                    where_parts.append(
                        f"(m.[{c}] IS NULL AND s.[{c}] IS NOT NULL)"
                    )
            change_condition = " OR ".join(where_parts)
        else:
            diff_parts = [f"m.[{c}] IS NOT s.[{c}]" for c in columns]
            change_condition = " OR ".join(diff_parts)

        count_sql = (
            f"SELECT COUNT(*) FROM main.[{db_table}] m "
            f"INNER JOIN seed.[{db_table}] s ON m.seed_id = s.seed_id "
            f"WHERE m.seed_id IS NOT NULL AND ({change_condition})"
        )
        cursor.execute(count_sql)
        update_count = cursor.fetchone()[0]

        if update_count > 0 and not dry_run:
            set_expr = ", ".join(set_clauses)
            update_sql = (
                f"UPDATE main.[{db_table}] AS m SET {set_expr} "
                f"FROM seed.[{db_table}] AS s "
                f"WHERE m.seed_id = s.seed_id "
                f"AND m.seed_id IS NOT NULL"
            )
            cursor.execute(update_sql)

        return update_count


def _is_text_type(col_type):
    """Return True if the SQLite column type is text-like."""
    text_types = ("TEXT", "VARCHAR", "CHAR", "CLOB", "JSON")
    return any(t in col_type for t in text_types)
