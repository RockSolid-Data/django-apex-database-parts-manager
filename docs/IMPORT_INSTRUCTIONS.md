# Lester CD Import Instructions

## Prerequisites

1. Place `LesterCD_Decrypted.db` in the project root.
2. **Close any process using db.sqlite3** (e.g. Django `runserver`, SQLite browsers, Cursor DB tools) before running the import. SQLite allows only one writer at a time.

## Commands

### 1. Schema discovery (already run)
```bash
python manage.py inspect_lester_db
```
Output: `docs/lester_schema_report.txt`

### 2. Missing-fields report (for boss review)
```bash
python manage.py import_lester --report-only
```
Output: `docs/lester_missing_fields_report.txt`

### 3. Import data
```bash
# Full import (may take 10+ minutes)
python manage.py import_lester --clear

# Limited import for testing
python manage.py import_lester --clear --limit 1000
```

### 4. Verify import
```bash
python manage.py import_lester --verify
```
Output: `docs/lester_import_verification.txt`

## If database is locked

- Stop `python manage.py runserver` if running
- Close any SQLite/Database explorer tools
- Delete `db.sqlite3-journal` if present (indicates interrupted transaction)
- Retry the import
