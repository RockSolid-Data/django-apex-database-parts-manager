"""
Catalog sync: inserts new records from seed.sqlite3 into the customer
database. Optionally fills in blank fields on existing records.

Uses SQLite ATTACH DATABASE for bulk operations. Per-table commits ensure
partial progress is saved even if a later table fails.

Modes:
  - Default: INSERT OR IGNORE new records only (fast, additive, ~1-2s).
  - --fill-blanks: ALSO fill blank fields on existing rows (per-column
    UPDATE that only touches rows actually missing data; safe but slower).
  - --force-update: overwrite all catalog fields from seed
    (still respects BUSINESS_FIELDS). Slowest, opt-in only.
  - --dry-run: preview what would change without writing.
  - --max-seconds N: abort the run gracefully after N seconds (default: 60).

History:
  v1.2.2 ran the fill-blanks pass unconditionally with a single CASE-everything
  UPDATE per table. On installs with millions of rows the rewrites took 10+
  minutes and silently wedged the launcher. v1.2.3 makes fill-blanks opt-in,
  per-column, and time-bounded so upgrades stay fast and safe.
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
    ("catalog", "UnitImage", "catalog_unitimage"),
    ("catalog", "ApplicationUnit", "catalog_applicationunit"),
    ("catalog", "CrossReference", "catalog_crossreference"),
    ("catalog", "Substitute", "catalog_substitute"),
    ("catalog", "GearReductionSubstitution", "catalog_gearreductionsubstitution"),
    ("catalog", "Part", "catalog_part"),
    ("catalog", "PartImage", "catalog_partimage"),
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

DEFAULT_MAX_SECONDS = 60


class TimeBudgetExceeded(Exception):
    """Raised when the time budget for the sync is exhausted."""


class Command(BaseCommand):
    help = "Sync catalog records from seed.sqlite3 (insert new + optional fill-blanks)."

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
            "--fill-blanks", action="store_true",
            help="Also fill in blank/NULL columns on existing rows from the seed.",
        )
        parser.add_argument(
            "--force-update", action="store_true",
            help="Overwrite all catalog fields from seed (still respects business fields)",
        )
        parser.add_argument(
            "--max-seconds", type=int, default=DEFAULT_MAX_SECONDS,
            help=(
                f"Maximum total runtime in seconds before the sync aborts gracefully "
                f"(default: {DEFAULT_MAX_SECONDS}). The launcher uses this as a safety net."
            ),
        )

    def handle(self, *args, **options):
        seed_path = Path(options["seed_db"])
        dry_run = options["dry_run"]
        fill_blanks = options["fill_blanks"] or options["force_update"]
        force_update = options["force_update"]
        max_seconds = max(5, options["max_seconds"])

        if not seed_path.exists():
            raise CommandError(f"Seed database not found: {seed_path}")

        t0 = time.perf_counter()
        deadline = t0 + max_seconds
        cursor = connection.cursor()

        seed_path_str = str(seed_path).replace("'", "''")
        cursor.execute(f"ATTACH DATABASE '{seed_path_str}' AS seed")

        totals = {
            "inserted": 0, "updated": 0, "skipped": 0,
            "conflicts": 0, "errors": [], "aborted": False,
        }

        try:
            for _app, model_name, db_table in SYNC_MODELS:
                if time.perf_counter() >= deadline:
                    totals["aborted"] = True
                    self.stderr.write(self.style.WARNING(
                        f"  Time budget ({max_seconds}s) reached before {model_name}; "
                        f"remaining tables skipped."
                    ))
                    break

                try:
                    result = self._sync_table(
                        cursor, model_name, db_table,
                        dry_run, fill_blanks, force_update, deadline,
                    )
                    totals["inserted"] += result["inserted"]
                    totals["updated"] += result["updated"]
                    totals["skipped"] += result["skipped"]
                    totals["conflicts"] += result["conflicts"]

                    if not dry_run:
                        connection.connection.commit()

                except TimeBudgetExceeded:
                    totals["aborted"] = True
                    self.stderr.write(self.style.WARNING(
                        f"  {model_name}: aborted at time budget ({max_seconds}s)."
                    ))
                    if not dry_run:
                        try:
                            connection.connection.rollback()
                        except Exception:
                            pass
                    break

                except Exception as exc:
                    totals["errors"].append((model_name, str(exc)))
                    self.stderr.write(self.style.ERROR(
                        f"  {model_name}: FAILED -- {exc}"
                    ))
                    try:
                        connection.connection.rollback()
                    except Exception:
                        pass

        finally:
            try:
                cursor.execute("DETACH DATABASE seed")
            except Exception:
                pass

        elapsed = time.perf_counter() - t0
        prefix = "[DRY RUN] " if dry_run else ""
        status_msg = (
            f"{prefix}Catalog sync complete: "
            f"{totals['inserted']:,} inserted, "
            f"{totals['updated']:,} updated, "
            f"{totals['skipped']:,} unchanged"
            f" ({elapsed:.1f}s)."
        )
        if totals["aborted"]:
            self.stdout.write(self.style.WARNING(status_msg + " [PARTIAL - time budget hit]"))
        else:
            self.stdout.write(self.style.SUCCESS(status_msg))

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

    def _sync_table(self, cursor, model_name, db_table,
                    dry_run, fill_blanks, force_update, deadline):
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

        cursor.execute(f"PRAGMA seed.table_info([{db_table}])")
        seed_columns = {row[1] for row in cursor.fetchall()}

        common_columns = main_columns & seed_columns
        insert_columns = sorted(c for c in common_columns if c not in SKIP_COLUMNS)
        col_list = ", ".join(f"[{c}]" for c in insert_columns)

        # --- Phase 0: BACKFILL seed_id on existing records ---
        # Records from a pre-seed_id install have seed_id=NULL but their id
        # matches a seed_id in the seed (because export_seed_data sets
        # seed_id=id). Without this backfill the INSERT phase would re-insert
        # every record from the seed, creating duplicates.
        if "seed_id" in common_columns and not dry_run:
            backfill_sql = (
                f"UPDATE main.[{db_table}] SET seed_id = id "
                f"WHERE seed_id IS NULL "
                f"AND id IN (SELECT s.seed_id FROM seed.[{db_table}] s "
                f"           WHERE s.seed_id IS NOT NULL)"
            )
            cursor.execute(backfill_sql)
            backfilled = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
            if backfilled:
                self.stdout.write(
                    f"  {model_name}: backfilled seed_id on {backfilled:,} existing records"
                )

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

        if conflicts > 0 and not dry_run:
            self._log_conflicts(cursor, db_table, model_name)

        # --- Phase 2: UPDATE existing records (opt-in only) ---
        # By default we do NOT touch existing rows. Customers' DBs may have
        # millions of catalog rows and a blanket UPDATE was the bug that hung
        # the v1.2.2 launcher. Run only when --fill-blanks/--force-update is set.
        updated = 0
        if fill_blanks:
            biz_fields = BUSINESS_FIELDS.get(db_table, set())
            update_candidates = sorted(
                c for c in common_columns
                if c not in NEVER_UPDATE_COLUMNS and c not in biz_fields
            )
            if update_candidates:
                updated = self._update_existing_per_column(
                    cursor, db_table, update_candidates, main_col_types,
                    dry_run, force_update, deadline,
                )

        result["updated"] = updated
        result["skipped"] = max(0, seed_total - to_insert - updated)

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

    def _update_existing_per_column(self, cursor, db_table, columns, col_types,
                                    dry_run, force_update, deadline):
        """Fill blank columns on existing rows.

        Runs ONE narrowly scoped UPDATE per column so SQLite only rewrites
        rows that actually need it. This is dramatically cheaper than the
        v1.2.2 "CASE everything" approach, which rewrote every row even
        when nothing changed.

        Honours `deadline`: raises TimeBudgetExceeded if exceeded between
        columns so the launcher can never get wedged here again.
        """
        total_updated = 0

        for col in columns:
            if time.perf_counter() >= deadline:
                raise TimeBudgetExceeded()

            col_type = col_types.get(col, "TEXT")
            is_text = _is_text_type(col_type)

            if force_update:
                where_filter = "s.[{c}] IS NOT m.[{c}]".format(c=col)
                set_expr = f"[{col}] = ("
                set_expr += (
                    f"SELECT s.[{col}] FROM seed.[{db_table}] s "
                    f"WHERE s.seed_id = main.[{db_table}].seed_id"
                )
                set_expr += ")"
            else:
                if is_text:
                    blank_check = (
                        f"(main.[{db_table}].[{col}] IS NULL "
                        f"OR main.[{db_table}].[{col}] = '')"
                    )
                    seed_has = "s.[{c}] IS NOT NULL AND s.[{c}] != ''".format(c=col)
                else:
                    blank_check = f"main.[{db_table}].[{col}] IS NULL"
                    seed_has = f"s.[{col}] IS NOT NULL"

                set_expr = (
                    f"[{col}] = (SELECT s.[{col}] FROM seed.[{db_table}] s "
                    f"WHERE s.seed_id = main.[{db_table}].seed_id)"
                )
                where_filter = (
                    f"{blank_check} AND main.[{db_table}].seed_id IS NOT NULL "
                    f"AND EXISTS (SELECT 1 FROM seed.[{db_table}] s "
                    f"WHERE s.seed_id = main.[{db_table}].seed_id AND {seed_has})"
                )

            if dry_run:
                count_sql = (
                    f"SELECT COUNT(*) FROM main.[{db_table}] "
                    f"WHERE {where_filter}"
                )
                cursor.execute(count_sql)
                total_updated += cursor.fetchone()[0]
                continue

            update_sql = (
                f"UPDATE main.[{db_table}] SET {set_expr} "
                f"WHERE {where_filter}"
            )
            cursor.execute(update_sql)
            total_updated += cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0

        return total_updated


def _is_text_type(col_type):
    """Return True if the SQLite column type is text-like."""
    text_types = ("TEXT", "VARCHAR", "CHAR", "CLOB", "JSON")
    return any(t in col_type for t in text_types)
