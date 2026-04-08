# Changelog

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
