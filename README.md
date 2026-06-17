# Apex Database (Manchester Electric)

Catalog, inventory, and invoicing system built with Django and packaged as a
standalone Windows desktop application.

## Quick Start (Development)

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000/ in your browser.

## Building the Installer

Edit the `VERSION` file to set the release number, then:

```bash
build_installer.bat all         # full build: freeze + Inno Setup installer
build_installer.bat freeze      # build the frozen exe only
build_installer.bat inno        # create the Inno Setup installer (in dist\)
build_installer.bat test        # run the Debug exe locally
build_installer.bat clean       # remove build artifacts
```

**Prerequisites:** [Inno Setup 6](https://jrsoftware.org/isinfo.php) must be installed.

The installer is output to `dist\`. It installs per-user to
`%LOCALAPPDATA%\ManchesterElectric` with desktop and Start Menu shortcuts.

## Database & Upgrade Strategy

The application uses an **additive seed sync** to ship catalog data with every
build while preserving customer-created data across updates:

- A `seed.sqlite3` (catalog-only snapshot) is bundled with every installer
- **First install:** seed is copied as the initial database
- **Upgrade:** existing database is kept; new catalog records are inserted via
  `seed_id` matching (existing records are never modified or deleted)
- Customer data (invoices, customers, vendors) is completely untouched

Management commands:

```bash
python manage.py export_seed_data     # create seed.sqlite3 from dev db
python manage.py sync_catalog --seed-db seed.sqlite3   # additive sync
python manage.py sync_catalog --seed-db seed.sqlite3 --dry-run  # preview
```

- Run `export_seed_data` only when cutting a release; if seed was exported accidentally, use `git restore seed.sqlite3` before committing.

## Project Structure

```
config/              Django project settings (base / dev / frozen)
catalog/             Units, applications, parts, BOMs, cross-references
inventory/           Inventory tracking, vendors, reorder points
invoicing/           Invoices, customers, company settings
data_import/         Import utilities and management commands
templates/           HTML templates (base layout, all pages)
static/              CSS, JS, vendor libs (Bootstrap, Tom Select)
launcher.py          Desktop entry point (Waitress server, port management)
setup_cx_freeze.py   cx_Freeze packaging configuration
installer.iss        Inno Setup installer script
build_installer.bat  Build pipeline script
VERSION              Single source of truth for the app version
```

## Runtime Architecture

When run as a frozen exe, the launcher:

1. Acquires a file lock to prevent duplicate instances
2. Copies seed database on first install, or detects upgrade
3. Generates a unique SECRET_KEY per installation
4. Runs Django migrations
5. Syncs new catalog records from the bundled seed (upgrade only)
6. Creates a default admin user on first install
7. Finds a free port (8000-8010)
8. Starts Waitress WSGI server and opens the default browser

## Technology

- Python 3.13 / Django 6.0
- SQLite database (tracked in Git LFS)
- Waitress (production WSGI server)
- WhiteNoise (static file serving)
- cx_Freeze (packaging) + Inno Setup (installer)
- Bootstrap 5.3 / Bootstrap Icons
- Tom Select (searchable dropdowns)
