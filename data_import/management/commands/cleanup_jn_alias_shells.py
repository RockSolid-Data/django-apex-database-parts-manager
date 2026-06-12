"""
Clean up J&N alias shell Unit records.

A "J&N alias shell" is a Unit where:
  - unit_number is actually a cross-reference number (e.g. 400-12010R)
  - yt_number points to a real, populated unit (e.g. 310117)
  - All identifying fields are blank (no manufacturer, OEM, voltage, amps, etc.)

These were created during import when J&N / cross-reference numbers were
mistakenly turned into separate Unit records instead of just being
cross-references on the real unit.

The command:
  1. Finds all J&N alias shells
  2. Migrates any application links to the real unit (skipping duplicates)
  3. Redirects any cross_ref_unit FKs pointing at the shell to the real unit
  4. Deletes the shell

Usage:
    python manage.py cleanup_jn_alias_shells --dry-run
    python manage.py cleanup_jn_alias_shells
"""

import time

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from catalog.models import ApplicationUnit, CrossReference, Unit

BATCH = 500


class Command(BaseCommand):
    help = "Remove J&N alias shell units and migrate their application links."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen without making changes.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        t0 = time.time()

        self.stdout.write("\n" + "=" * 65)
        self.stdout.write(
            "J&N ALIAS SHELL CLEANUP" + ("  [DRY RUN]" if dry else "")
        )
        self.stdout.write("=" * 65)

        before = self._snapshot("BEFORE")

        shells = self._find_shells()
        self.stdout.write(f"\nJ&N alias shells found: {len(shells):,}")

        if not shells:
            self.stdout.write("Nothing to do.")
            return

        total_app_links = sum(s["app_count"] for s in shells)
        self.stdout.write(f"Total app links on shells: {total_app_links:,}")

        self._print_sample(shells)

        if dry:
            self._dry_run_report(shells)
        else:
            self._apply(shells)

        after = self._snapshot("AFTER" if not dry else "CURRENT (no changes)")
        self._verify(before, after, shells, dry)

        elapsed = time.time() - t0
        self.stdout.write(f"\nTotal elapsed: {elapsed:.1f}s\n")

    # ------------------------------------------------------------------
    # Find shells via raw SQL (avoids SQLite variable limits)
    # ------------------------------------------------------------------
    def _find_shells(self):
        """Return list of dicts with shell info and their real unit id."""
        with connection.cursor() as c:
            c.execute("""
                SELECT
                    shell.id           AS shell_id,
                    shell.unit_number  AS shell_unum,
                    shell.yt_number    AS shell_yt,
                    real_unit.id       AS real_id,
                    real_unit.unit_number AS real_unum,
                    (SELECT COUNT(*) FROM catalog_applicationunit au
                     WHERE au.unit_id = shell.id) AS app_count
                FROM catalog_unit shell
                JOIN catalog_unit real_unit
                    ON real_unit.yt_number = shell.yt_number
                   AND real_unit.id != shell.id
                   AND (   real_unit.manufacturer != ''
                        OR real_unit.oem != ''
                        OR real_unit.voltage != ''
                        OR real_unit.amp_rating != ''
                        OR real_unit.unit_type_id IS NOT NULL)
                WHERE shell.unit_number IN (
                    SELECT DISTINCT cross_ref_number
                    FROM catalog_crossreference
                    WHERE cross_ref_number != ''
                )
                AND shell.manufacturer = ''
                AND shell.oem = ''
                AND shell.voltage = ''
                AND shell.amp_rating = ''
                AND shell.unit_type_id IS NULL
                AND shell.yt_number != ''
                ORDER BY shell.yt_number, shell.unit_number
            """)
            rows = c.fetchall()

        seen_shell_ids = set()
        shells = []
        for row in rows:
            shell_id = row[0]
            if shell_id in seen_shell_ids:
                continue
            seen_shell_ids.add(shell_id)
            shells.append({
                "shell_id": shell_id,
                "shell_unum": row[1],
                "shell_yt": row[2],
                "real_id": row[3],
                "real_unum": row[4],
                "app_count": row[5],
            })
        return shells

    # ------------------------------------------------------------------
    def _print_sample(self, shells):
        self.stdout.write("\n  Sample (first 15):")
        for s in shells[:15]:
            self.stdout.write(
                f"    shell {s['shell_unum']:<18} yt={s['shell_yt']:<10} "
                f"-> real {s['real_unum']:<10}  apps={s['app_count']:,}"
            )

    # ------------------------------------------------------------------
    def _dry_run_report(self, shells):
        self.stdout.write("\n" + "-" * 65)
        self.stdout.write("DRY RUN — no changes made")
        self.stdout.write("-" * 65)

        total_apps = sum(s["app_count"] for s in shells)

        shell_ids = [s["shell_id"] for s in shells]
        xref_fk_count = (
            CrossReference.objects.filter(cross_ref_unit_id__in=shell_ids).count()
        )

        self.stdout.write(f"  Shells to delete:               {len(shells):,}")
        self.stdout.write(f"  App links to migrate:           {total_apps:,}")
        self.stdout.write(f"  cross_ref_unit FKs to redirect: {xref_fk_count:,}")

    # ------------------------------------------------------------------
    def _apply(self, shells):
        self.stdout.write("\n" + "-" * 65)
        self.stdout.write("APPLYING CLEANUP")
        self.stdout.write("-" * 65)
        t0 = time.time()

        apps_migrated = 0
        apps_skipped_dup = 0
        xref_fks_redirected = 0
        shells_deleted = 0

        # Pre-load existing app-unit keys for real units to detect duplicates
        real_ids = list({s["real_id"] for s in shells})
        existing_app_keys = set()
        for chunk_start in range(0, len(real_ids), BATCH):
            chunk = real_ids[chunk_start: chunk_start + BATCH]
            existing_app_keys.update(
                ApplicationUnit.objects.filter(unit_id__in=chunk)
                .values_list("application_id", "unit_id")
            )

        for i, s in enumerate(shells, 1):
            shell_id = s["shell_id"]
            real_id = s["real_id"]

            with transaction.atomic():
                # 1. Migrate app links from shell -> real unit
                app_links = list(
                    ApplicationUnit.objects.filter(unit_id=shell_id)
                    .values_list("id", "application_id")
                )

                ids_to_move = []
                ids_to_delete = []
                for au_id, app_id in app_links:
                    key = (app_id, real_id)
                    if key in existing_app_keys:
                        ids_to_delete.append(au_id)
                        apps_skipped_dup += 1
                    else:
                        ids_to_move.append(au_id)
                        existing_app_keys.add(key)

                if ids_to_move:
                    ApplicationUnit.objects.filter(pk__in=ids_to_move).update(
                        unit_id=real_id
                    )
                    apps_migrated += len(ids_to_move)

                if ids_to_delete:
                    ApplicationUnit.objects.filter(pk__in=ids_to_delete).delete()

                # 2. Redirect cross_ref_unit FKs pointing at this shell
                n = CrossReference.objects.filter(
                    cross_ref_unit_id=shell_id
                ).update(cross_ref_unit_id=real_id)
                xref_fks_redirected += n

                # 3. Delete the shell unit
                Unit.objects.filter(pk=shell_id).delete()
                shells_deleted += 1

            if i % 100 == 0:
                self.stdout.write(f"  Progress: {i:,}/{len(shells):,}")

        self.stdout.write(f"\n  App links migrated:        {apps_migrated:,}")
        self.stdout.write(f"  App links skipped (dupes): {apps_skipped_dup:,}")
        self.stdout.write(f"  cross_ref_unit redirected: {xref_fks_redirected:,}")
        self.stdout.write(f"  Shells deleted:            {shells_deleted:,}")
        self.stdout.write(f"  Time: {time.time() - t0:.1f}s")

    # ------------------------------------------------------------------
    def _snapshot(self, label):
        units = Unit.objects.count()
        app_units = ApplicationUnit.objects.count()
        xrefs = CrossReference.objects.count()
        self.stdout.write(f"\n  {label}:")
        self.stdout.write(f"    Units:            {units:>10,}")
        self.stdout.write(f"    ApplicationUnits: {app_units:>10,}")
        self.stdout.write(f"    CrossReferences:  {xrefs:>10,}")
        return {"units": units, "app_units": app_units, "xrefs": xrefs}

    def _verify(self, before, after, shells, dry):
        self.stdout.write("\n" + "=" * 65)
        self.stdout.write("VERIFICATION")
        self.stdout.write("=" * 65)

        if dry:
            self.stdout.write("  (dry run — no changes to verify)")
            return

        expected_units = before["units"] - len(shells)
        ok = "OK" if after["units"] == expected_units else "MISMATCH"
        self.stdout.write(
            f"  Units:  {before['units']:,} -> {after['units']:,}  "
            f"(expected {expected_units:,})  {ok}"
        )

        au_delta = before["app_units"] - after["app_units"]
        self.stdout.write(
            f"  ApplicationUnits removed: {au_delta:,}  "
            "(duplicates consolidated, not data loss)"
        )
