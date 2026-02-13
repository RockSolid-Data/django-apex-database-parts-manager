# Manchester Electric — High-Level Implementation Plan

**No code in this document.** This is a step-by-step plan of what to build and in what order. Each step assumes the previous steps are done.

---

## Phase 0 — Foundation

- **0.1** Django project and apps: ensure `config`, `catalog`, `inventory`, `invoicing` exist; `config.settings` has all three apps and correct `ROOT_URLCONF`, `TEMPLATES`, `STATIC`, `MEDIA`.
- **0.2** Base template: one base HTML template with "Manchester Electric" branding and a top navigation bar with links for **Unit Search**, **Unit List**, **Applications**, **Parts**, **Reorder**, **Invoices**, **Inventory** (routes can be placeholders at first).
- **0.3** Static assets: place for global CSS and JS; base template includes them so every page looks consistent.
- **0.4** Database: implement all models per `DATABASE_PLAN.md`; run migrations; optionally seed **UnitType** (AC Motor, DC Motor, Generator, Starter, Alternator, Pump).

---

## Phase 1 — Catalog: Unit Types and Units (Core)

- **1.1** **UnitType**: Admin or simple UI to list/edit unit types (or rely on seed data from 0.4).
- **1.2** **Unit model**: Implement full Unit model (identification, electrical/mechanical specs, pricing, images, relationships) per database plan.
- **1.3** **Unit list page**: One URL (e.g. `/units/` or `/unit-list/`) that lists units in a table. Columns to support: Unit Type, YT Number, OEM, HP, RPM, Type, Voltage, Enclosure, FLA, and a **Details** (View) action. No filters yet.
- **1.4** **Unit type tabs/filter**: On the unit list, add tabs or a filter for unit type (AC Motors, DC Motors, Generators, Starters, Alternators, Pumps). List only units of the selected type.
- **1.5** **Unit list search and filters**: Add search (e.g. by unit number, OEM, design) and dropdown filters: Unit Type, OEM, Voltage, Family. Include **Search** and **Clear** buttons.
- **1.6** **Add New Unit**: Button and form to create a new unit (required fields as per model; optional fields can be blank). After save, redirect to unit list or unit detail.
- **1.7** **Upload CSV (units)**: Button and flow to upload a CSV to create/update units in bulk (define columns and rules in a later detail step).

---

## Phase 2 — Catalog: Unit Detail and Related Data

- **2.1** **Unit detail page**: One URL per unit (e.g. `/units/<id>/`) showing unit details in two columns (specs, pricing, unit type, images). Include placeholders for "No image" / "No plug image" when missing.
- **2.2** **Unit detail actions**: Buttons: **Add to Invoice**, **View BOM**, **Back to List**, **Search Units** (link to unit search/list).
- **2.3** **Cross Reference List** (on unit detail): Section that lists cross-reference units for this unit. Support "No cross reference units found" and a **+ Add Unit** button to add a cross-reference (links to another Unit).
- **2.4** **Substitutes** (on unit detail): Section that lists substitute units. Support "No substitute units found" and **Add Substitutes** to link substitute units.
- **2.5** **Gear Reduction Substitution** (on unit detail): Section with a table: NUMBER, DESCRIPTION, NOTES. Support adding/editing/deleting gear reduction rows for this unit.

---

## Phase 3 — Catalog: Applications and Application–Unit Links

- **3.1** **Application model**: Implement Application model per database plan.
- **3.2** **ApplicationUnit**: Implement junction model and ensure Application ↔ Unit M:M works (e.g. "Linked Units" on application, "Applications" on unit).
- **3.3** **Applications list page**: One URL (e.g. `/applications/`) with table columns: MAKE, ENGINE, YEAR, OPTIONS, MFR, AMP, VOLT, LINKED UNIT (e.g. "Linked" indicator), ACTIONS (View, Edit).
- **3.4** **Applications search and filters**: Search (e.g. "Search applications...") and filters: Make, Year, Mfr, Volt, Unit. **Search** and **Clear** buttons. **+ Add New Application** and **Advanced Search** (optional).
- **3.5** **Application detail page**: One URL per application (e.g. `/applications/<id>/`) with **General Specifications** (make, engine, year, mfr, etc.) and **Unit Linking Status** (e.g. "This application is linked to a unit" or not).
- **3.6** **Linked Units panel** (on application detail): Show "No linked units" or list of linked units; **Link to Unit** button to add a unit to this application (creating ApplicationUnit records).

---

## Phase 4 — Catalog: Parts

- **4.1** **Part model**: Implement Part model per database plan (including all part numbers, stock fields, optional link to Unit, image).
- **4.2** **Parts list page**: One URL (e.g. `/parts/`) with table columns: KEY, YT NUMBER, J&N, OEM #, DESCRIPTION, IN STOCK, DETAILS (View). Support "X parts found".
- **4.3** **Parts search and filter**: Search by key, J&N, OEM #, description, or unit #. Category dropdown (All Categories). **Search** button.
- **4.4** **Add New Part** and **Upload CSV**: Button to create a part (form with required/optional fields); optional flow to upload CSV for bulk part create/update.
- **4.5** **Part detail page**: One URL per part (e.g. `/parts/detail/<id>/`) with sections: **Basic Information** (Item No, Name, Category, Type, Price, Item Typ, Bin Location), **Stock & Inventory** (Reorder Qty, In Stock), **Picture** (or "No image available"), **Compatibility** (Substitutes, Interchange, Superseding—each can show "No ... listed" or list with option to add). **Superseding Notes** as text. **Part Specifications** table (CATEGORY, TYPE, SPECIFICATION). Buttons: **Add to Invoice**, **Back to Parts List**, **Edit**.

---

## Phase 5 — Catalog: BOM (Bill of Materials)

- **5.1** **BOM and BOMItem models**: Implement BOM (name, description, optional link to Unit and/or Application) and BOMItem (part, quantity, description override, notes, unit_qty, stock_qty, bin_number, oem_number, j_and_n, yt_number) per database plan.
- **5.2** **BOM list page**: One URL (e.g. `/bom/`) listing BOMs with actions to open a BOM, create, edit, or delete (as needed).
- **5.3** **BOM detail page**: One URL per BOM (e.g. `/bom/<id>/`). Show BOM name, created date, description. Buttons: **Print All**, **Print Selected (0)**, **Add Part**, **Edit**, **Back to BOMs**, **Edit BOM**, **Delete BOM**.
- **5.4** **Parts in BOM table**: On BOM detail, table with columns: checkbox, DESCRIPTION, PART #, NOTES, UNIT QTY, STOCK QTY, BIN NUMBER, OEM, J&N, YT, ACTIONS (Edit, Delete). **Add Part** to add a BOMItem (select Part, set qty and optional overrides).
- **5.5** **BOM item edit/delete**: From BOM detail, edit or delete individual BOM items (BOMItem records).

---

## Phase 6 — Inventory

- **6.1** **Vendor model**: Implement Vendor (name, contact, email, phone, address, notes, is_active) per database plan.
- **6.2** **Vendor CRUD**: List vendors; add/edit vendor (full contact and address). Used as "Supplier" in inventory and reorder UIs.
- **6.3** **Reorder list page**: One URL (e.g. `/parts/reorder/` or `/inventory/reorder/`). List parts where stock is at or below reorder level. Table columns: KEY, J&N, OEM #, DESCRIPTION, SUPPLIER (Vendor name), UNIT #, IN STOCK, REORDER QTY, STATUS (e.g. Out of Stock / Low Stock), DETAILS (View). Search by key, J&N, OEM #, description. Filters: Category, Supplier. Sort (e.g. "Most Urgent First"). Summary: "X items need reordering". Buttons: **All Parts**, **Upload Parts** (optional).
- **6.4** **Inventory management list**: One URL (e.g. `/inventory/`) with table: ITEM NAME, PART NUMBER, SUPPLIER, COST, MARGIN, SALE PRICE, QUANTITY (e.g. "12 / 18" if you track on-hand vs capacity), TOTAL VALUE, ACTIONS (View, Edit). Search by name, part number, description. Filter by Supplier. **Add Inventory Item** and **Back to Invoices** (or main nav).
- **6.5** **Add Inventory Item**: Form (e.g. `/inventory/create/` or under invoices path as in your screenshot): **Basic** — Item Name*, Part Number, Description, Supplier* (dropdown); **Pricing** — Cost*, Margin %*, Calculated Sale Price (read-only); **Quantity** — Quantity Purchased*, Quantity Available*; **Notes**. **Cancel** and **Add Inventory Item** submit. Decide how this creates/updates Part and stock (e.g. creates Part and sets cost/price/stock, or updates existing Part).

---

## Phase 7 — Invoicing

- **7.1** **Customer model**: Implement Customer per database plan.
- **7.2** **Customer CRUD**: List customers; add/edit customer (name, contact, email, phone, address). Accessible from nav or **Customers** button on invoice list.
- **7.3** **Invoice and InvoiceItem models**: Implement Invoice (number, customer, date, due_date, status, subtotal, tax_rate, tax_amount, total, notes) and InvoiceItem (invoice, optional part, optional unit, description, quantity, unit_price, line_total) per database plan.
- **7.4** **Invoice list page**: One URL (e.g. `/invoices/`). Table: INVOICE #, CUSTOMER, DATE, DUE DATE, STATUS (Draft, Sent, Paid, Overdue), TOTAL, ACTIONS (View, Edit). Search by invoice #, customer, or supplier; PO (if you add PO field); Status filter; Date From. **New Invoice**, **Customers**, **Suppliers** (Suppliers = Vendor list) buttons.
- **7.5** **Create New Invoice**: Form with **Customer Information** (name, contact, phone, email, address). **Invoice Items** section: rows with Quantity, Part Number, Description, Unit Price, Total (calculated); **+ Add Item**; optional "Select a part" and "Select a unit" per line. Subtotal, Tax (0% or configurable), Total at bottom. **Invoice Notes** (for customer) and **Private Notes** (internal). Buttons: **Print Invoice**, **Back to Invoices**, and submit to save (Draft or Sent as needed).
- **7.6** **Invoice detail/edit**: View and edit existing invoice (same fields as create); recalc totals when line items change; support status changes (Draft → Sent → Paid, etc.).

---

## Phase 8 — Integration and Polish

- **8.1** **Add to Invoice from Unit**: From unit detail, **Add to Invoice** adds this unit as a line (or opens invoice create with this unit pre-filled). Implement flow (e.g. choose existing invoice or create new one).
- **8.2** **Add to Invoice from Part**: From part detail, **Add to Invoice** adds this part as a line; same flow as 8.1.
- **8.3** **View BOM from Unit**: From unit detail, **View BOM** goes to the BOM linked to that unit (or list of BOMs for that unit); if none, show message or create option.
- **8.4** **Print Invoice**: From create/edit or invoice detail, **Print Invoice** produces a printable view (PDF or print-friendly HTML).
- **8.5** **BOM Print**: **Print All** / **Print Selected** on BOM detail produce printable view of BOM and selected parts.
- **8.6** **Overdue and due-date highlighting**: On invoice list, visually highlight overdue or due-soon (e.g. red for overdue).
- **8.7** **Application Specifications (optional)**: If you want the "Application Specifications" table (Category, Type, Specification) on application detail, add a small model or JSON field and UI to edit it; otherwise skip or use notes.

---

## Summary Table

| Phase | Focus |
|-------|--------|
| 0 | Foundation: project, apps, base template, nav, DB and migrations |
| 1 | Catalog: Unit list, type filter, search/filters, add unit, CSV upload (units) |
| 2 | Catalog: Unit detail, cross-ref, substitutes, gear reduction |
| 3 | Catalog: Applications list/detail, linked units |
| 4 | Catalog: Parts list/detail, add part, CSV (parts), part specs/compatibility |
| 5 | Catalog: BOM list/detail, BOM items add/edit/delete |
| 6 | Inventory: Vendor CRUD, reorder list, inventory list, add inventory item |
| 7 | Invoicing: Customer CRUD, invoice list, create/edit invoice |
| 8 | Integration: Add to Invoice from Unit/Part, View BOM from Unit, print invoice/BOM, overdue highlighting |

---

**Reference:** Database schema is in `DATABASE_PLAN.md`. Implement models and migrations in Phase 0; then follow phases 1–8 for URLs, views, templates, and forms—no code in this plan, only the order and scope of work.
