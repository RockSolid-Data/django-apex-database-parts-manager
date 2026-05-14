# Changelog

## v1.2.1 — Search & Data Cleanup (2026-05-14)

### Improved
- **Applications page speed:** down from ~550ms to ~25ms (warm) — added
  composite index on (is_active, name), cached total count and dropdown
  values for 30 minutes
- **Deep search speed:** consolidated 6 sequential PK-collection queries
  into fewer combined queries; reduced live-search debounce from 400ms to
  250ms; short queries (< 3 chars) skip the deep search entirely
- **Part description → Notes:** renamed the field for clarity across all
  forms, detail pages, and list views

### Fixed
- **BOM data cleanup:** removed 20,200 incomplete J&N-imported BOMs and
  rebuilt 18,259 BOMs exclusively from Buyers Guide PDF data, ensuring
  every unit has a single accurate BOM
- **Deep search only as fallback:** the Match column and deep search
  queries no longer fire when primary identifiers (YT, J&N, Part#, OEM#)
  already match — eliminates unnecessary overhead on most searches
- **Cross-reference price field:** added dedicated price field to cross
  references with separate created/updated timestamps

### Added
- **Media pack auto-extract:** on first launch the app searches for
  `ApexDatabase_Media.zip` on USB drives and the install directory, then
  extracts part images automatically — updates skip extraction since images
  are already installed
- **Part images included in seed:** the seed database now contains image
  metadata so new installs get full image references out of the box
- **Daily rotating log files:** app logs rotate at midnight and auto-delete
  after 14 days — users can find them in %LOCALAPPDATA%\ApexDatabase\logs\
  for troubleshooting

## v1.2.0 — Fast Upgrades & Launch Experience (2026-05-11)

### Improved
- **Upgrade sync speed:** rewrote `sync_catalog` to use bulk SQL
  (`ATTACH DATABASE` + `INSERT INTO...SELECT`) instead of row-by-row
  inserts. Syncing ~3 million catalog records now completes in seconds
  instead of 10-20 minutes.
- **Launch experience:** the browser now opens immediately with a
  professional loading page ("Preparing your system...") while Django,
  migrations, catalog sync, and backup run in the background. The page
  auto-redirects to the app once the server is ready — no more blank
  wait after clicking Launch.

### Fixed
- **Build size:** the 14 GB `staging_dbs` dev directory is now moved
  out of the `data_import` package before cx_Freeze runs, reducing
  the build from ~15 GB to ~670 MB and cutting freeze time from
  timeout to ~75 seconds.

## v1.1.4 — Catalog Sync Fix (2026-05-11)

### Fixed
- **Seed export: seed_id backfill** — `export_seed_data` now sets
  `seed_id = id` on all 14 catalog tables where it was NULL before
  bundling into the installer. Previously ~1.96 million records imported
  after migration 0028 had no `seed_id`, so `sync_catalog` silently
  skipped them during customer upgrades. First-time installs and upgrades
  now ship identical catalog data.

## v1.1.3 — Performance & UX Consistency (2026-05-11)

### Fixed
- **Unit substitute delete:** removing a reverse-linked substitute no longer
  returns a 404 — the delete view now uses a bidirectional lookup matching
  the display logic

### Improved
- **List page performance:** eliminated duplicate COUNT queries in unit, part,
  and application list views; removed unnecessary `select_related` JOINs that
  the templates never used; added database indexes on `is_active`,
  `unit_type_category`, `unit_type_name`, and `category` for faster filtering
- **Backup page load time:** media file count and size are now read from the
  backup manifest instead of walking the filesystem on every page load
- **Gear reductions:** full row is now clickable to edit; delete uses an inline
  "x" button matching substitutes; removed unused Description field
- **Part compatibility sections:** substitutes, interchange, and superseding
  rows are all clickable for editing with a consistent UX pattern

### Changed
- Default maximum backup snapshots reduced from 10 to 4

## v1.1.2 — UI Polish & Data Quality (2026-04-28)

### Fixed
- **Parts list:** "Mfr #" column renamed to "Part Number" and now correctly
  displays `part_number` (not `manufacturer_number`)
- **Track Inventory toggle:** unchecking "Track Inventory" on a part and
  clearing Stock Qty / Reorder Threshold no longer raises a validation error
  — both fields default to `0` when left blank
- **Part categories:** existing categories (Hardware, Misc, etc.) were missing
  the 10 standard default fields; migration 0039 seeds them into every
  category and the edit view now always shows defaults so they can't be lost

### Added
- **Parts list — Match column:** two-tier search now shows a context badge
  for deep matches (Tier 1: direct J&N/YT/OEM/Part# hit, no badge shown;
  Tier 2: description, interchange, supersedes, etc., shows matched snippet)
- **BOM detail — J&N column:** shows only the first J&N number as a direct
  link to the part detail page (consistent with YT# and Part# columns)
- **BOM item detail — J&N field:** each J&N number is now a separate
  clickable link to the part detail page; multiple numbers are comma-separated
- **BOM item edit — J&N tag-input widget:** type a number and press Enter to
  convert it to a link-styled tag; Backspace on empty input restores the last
  tag for editing; pasting comma-separated values splits into separate tags
- **BOM create — Add Part:** fixed "Add Part" button being dead on new
  (unsaved) BOMs; custom autocomplete dropdown replaces TomSelect in the modal

### UI / UX
- **Sticky footer fix:** Save/Cancel bar no longer jumps up when scrolling to
  the bottom of long forms (copyright footer hidden on form pages so the
  action bar is always the last element in the scroll container)
- **Sticky header fix:** breadcrumb nav now sticks at `top: 0` alongside the
  toolbar — both lock in together on scroll, eliminating the brief upward
  drift before the toolbar caught
- **All BOM table number links** (YT#, Part#, J&N#, OEM#) are consistent —
  all link directly to the part detail page so Back always returns to the BOM

## v1.1.1 — Production Bug Fixes (2026-04-21)

### Fixed
- Fixed `InvalidStorageError` crash on unit/part detail pages that have images
  — `STORAGES` in frozen settings was missing the `"default"` key, breaking all
  FileField/ImageField URL resolution
- Fixed `ModuleNotFoundError` on PDF import page — `pdfplumber`, `pdfminer`,
  `charset_normalizer`, and `fitz` were not bundled in the cx_Freeze build
- Fixed media files (uploaded images) not loading in the installed app — media
  URL serving was gated behind `DEBUG=True`
- Set `MEDIA_ROOT` to persistent `DATA_DIR/media/` in frozen settings so uploads
  survive app upgrades

### Added
- `500.html` and `404.html` error templates for graceful error pages
- Cursor rules for frozen-build guardrails and dependency tracking

## v1.1.0 — Data Import, Settings & Installer Overhaul (2026-04-08)

### Data Import Pipeline
- Built `data_import` app with 10 import commands: Lester DB, J&N master
  catalog, J&N BOMs, Transpo catalog, Metro catalog, YT interchange, tilt-trim
  motors, tilt-trim notes/apps, buyers guide products, and applications
- PDF import support for parts with preview and report screens
- CSV upload preview and report for both units and parts

### Catalog Enhancements
- Part interchanges, substitutes, and superseding with add/edit UI
- Multiple images per part (`PartImage` model)
- Part categories with user-managed dynamic fields (Settings)
- Application types with user-managed dynamic fields (Settings)
- Unit type categories with user-managed dynamic fields (Settings)
- Part specifications stored as JSON (category-specific fields)
- Unit specifications stored as JSON (unit-type-specific fields)
- Added Application model fields: model, kw, fuel_type, vin, alt_pulley
- Added Unit fields: description, clock_position, starter_type, pulley_class,
  unit_attributes, and nullable unit_number
- Added Part fields: voltage, manufacturer_number (renamed from key),
  nullable part_number
- Added `seed_id` field to all 14 reference catalog models for upgrade sync
- Database indexes on Application, Unit, Part, and CrossReference tables

### Inventory & Invoicing
- Vendor contacts (`VendorContact` model) with extended address fields
  (account number, fax, remit-to address)
- Customer contacts (`CustomerContact` model) with contact name, email, phone
- Improved customer form with bill-to / ship-to address sections

### UI / Templates
- Redesigned application form with dynamic type-specific field sections
- Redesigned unit form with type-category-aware specification sections
- Redesigned part detail page with tabbed sections (interchange, substitutes,
  superseding, images, BOMs)
- Redesigned unit search with expanded multi-criteria filtering
- Cross-reference detail and edit pages
- BOM item detail page
- Print-friendly list layouts for parts, BOMs, inventory, vendors, customers,
  invoices
- Activity logging middleware for request tracing
- App version and frozen-mode context processor for all templates
- Reusable template includes (`templates/includes/`)

### Packaging & Deployment
- Migrated from MSI to Inno Setup installer (per-user install, seamless updates)
- Additive catalog sync: new reference data is inserted on upgrade without
  overwriting customer edits (`seed_id`-based matching)
- Split settings into `base.py` / `dev.py` / `frozen.py`
- `VERSION` file as single source of truth for app version
- Git LFS tracking for SQLite databases
- New management commands: `export_seed_data`, `sync_catalog`
- `export_seed_data` runs automatically as part of `build_installer.bat`
- Launcher rewritten with `msvcrt` file locking, crash logging, and
  seed-aware upgrade flow (first install vs. upgrade detection)
- Static vendor libraries bundled locally (Bootstrap, Tom Select) for
  fully offline operation

## v1.0.0 — Initial Release (2026-03-09)

- Catalog management for units, applications, parts, and BOMs
- Multi-criteria unit search across units, applications, parts, and cross references
- Cross-reference and substitute tracking with gear reduction support
- Inventory tracking with reorder points and stock levels
- Invoice creation, editing, and PDF printing with customizable formats
- Customer and vendor management with contact details
- CSV import support for units and parts
- Company settings for invoice numbering, tax rates, and payment terms
- Sticky header, filters, and action bars for improved navigation
- Clickable table rows for quick navigation to detail pages
- Universal browser-history Back button across all pages
- Wider table layout for data-heavy list pages
- Modern slim scrollbar styling

---

© 2026 Apex Database. All rights reserved.
