# Unit Search & Unit List Separation Plan

**Goal:** Separate Unit Search and Unit List into two distinct pages that match the reference screenshots.

---

## 1. Current State

| Nav Item    | Current URL    | Target View | Result |
|-------------|----------------|-------------|--------|
| Unit Search | `catalog:unit_list` | `/units/` | Same as Unit List |
| Unit List   | `catalog:unit_list` | `/units/` | Same as Unit Search |

**Problem:** Both link to the same page.

---

## 2. Target State (from screenshots)

### Unit Search

- **URL:** `/units/search/` (or `/search/` as home for search)
- **Nav:** "Unit Search" (highlighted when on this page)
- **Title:** "Unit Search"
- **Subtitle:** "Search for units, applications, and parts across the entire system"
- **Tabs:** Units | Applications | Parts (horizontal nav-pills)
- **UI:** No results table on initial load; form-only. Results appear after search submit.

#### Units Tab — Search Fields (from screenshot)

| Field Label         | Model Field (Unit) | Notes |
|---------------------|--------------------|-------|
| Manufacturer        | manufacturer       | |
| Mount Type          | mount_type         | |
| Nose Type           | nose_type          | Starter-specific |
| Weight              | weight             | |
| Clocking Degrees    | clocking_degrees   | |
| Housing             | housing            | |
| Design              | design             | |
| Tooth Quantity      | tooth_quantity     | Starter-specific |
| Over Crank Protection | over_crank_protection | Starter-specific |
| With Mounting Shim  | with_mounting_shims | |
| Power Rating        | power_rating       | |
| Grounding           | grounding          | |
| Voltage             | voltage            | |
| Reclockable Flange  | reclockable_flange | |
| With Hardware       | with_hardware      | |
| Unit Number         | unit_number        | |
| Family              | family             | |
| Rotation            | rotation           | |
| Solenoid Attached   | solenoid_attached  | Starter-specific |
| Bolt Holes          | bolt_holes         | |
| Drive               | drive              | |

**Actions:** "Search Units" (primary), "Clear" (secondary)

#### Applications Tab — Search Fields

| Field Label   | Model Field (Application) | Notes |
|---------------|---------------------------|-------|
| Make          | make                      | |
| Volt          | volt                      | |
| Unit Number   | unit_number               | |
| Created From  | created_at (gte)          | Date |
| Updated From  | updated_at (gte)          | Date |
| Engine        | engine                    | |
| Amp           | amp                       | |
| Options       | options                   | |
| Created To    | created_at (lte)          | Date |
| Updated To    | updated_at (lte)          | Date |
| Year          | year                      | |
| Mfr           | mfr                       | |
| Part #        | part_number               | |
| Other #       | other_number              | |
| Notes         | notes                     | |
| Linked Unit   | (filter by linked units)  | Dropdown: All Applications / Linked / Not Linked |

**Actions:** "Search Applications", "Clear"

#### Parts Tab — Search Fields

| Field Label      | Model Field (Part) | Notes |
|------------------|--------------------|-------|
| OEM #            | oem_number         | |
| Key              | key                | |
| Type             | type               | |
| Catalog          | catalog             | |
| OEM Type         | oem_type            | |
| Price            | price               | |
| Unit             | unit (FK)           | Dropdown |
| Foot Notes       | foot_notes          | |
| Stock Quantity   | stock_quantity      | |
| Updated To       | updated_at (lte)    | Date |
| Item No          | item_no             | |
| Name             | part_name           | |
| Primary Vendor   | primary_vendor      | |
| In Stock         | stock filter        | Dropdown: All / In Stock / Out of Stock |
| Description      | description         | |
| Part Number      | part_number         | |
| Created To       | created_at (lte)    | Date |
| Has Interchange  | has_interchange     | Dropdown |
| J&N              | j_and_n             | |
| Category         | category            | Dropdown |
| Plug ID          | plug_id             | |
| Item Typ         | item_typ            | |
| Reorder Qty      | reorder_qty         | |
| Part Name        | part_name           | |
| Updated From     | updated_at (gte)    | Date |
| Has Superseding  | has_superseding     | Dropdown |
| YT Number        | yt_number           | |
| Description      | description         | |
| Superseding Notes| superseding_notes   | |
| Created From     | created_at (gte)    | Date |
| Has Picture      | has_picture         | Dropdown |

**Actions:** "Search Parts", "Clear"

---

### Unit List

- **URL:** `/units/` (unchanged)
- **Nav:** "Unit List" (highlighted when on this page)
- **Title:** "Unit List"
- **Subtitle:** "Browse all unit models in the system"
- **Unit Type Tabs:** All | AC Motors | DC Motors | Generators | Starters | Alternators | Pumps
- **Filter Panel:** Search (text), Unit Type (dropdown), OEM, Voltage, Family | Search, Clear
- **Table:** Unit type-specific columns; "View" button per row
- **Result count:** "X results found"

**Current implementation already matches Unit List.** Minor tweaks:
- Add subtitle "Browse all unit models in the system" if missing
- Ensure Unit Type dropdown in filter panel reflects tab selection

---

## 3. Implementation Plan

### Phase A: Unit Search (new)

| Step | Task | Details |
|------|------|---------|
| A1 | URL | Add `path("units/search/", views.unit_search, name="unit_search")` |
| A2 | View | `unit_search(request)` — GET: show form; POST: run query, show results |
| A3 | Form | Create `UnitSearchForm`, `ApplicationSearchForm`, `PartSearchForm` (or single form with tab-specific fields) |
| A4 | Template | `unit_search.html` — title, subtitle, tabs (Units/Applications/Parts), forms, results area |
| A5 | Nav | Point "Unit Search" in base.html to `catalog:unit_search` |

### Phase B: Unit List (verify)

| Step | Task | Details |
|------|------|---------|
| B1 | URL | Keep `path("units/", views.unit_list, name="unit_list")` |
| B2 | Template | Add subtitle "Browse all unit models in the system" if not present |
| B3 | Nav | Point "Unit List" in base.html to `catalog:unit_list` (already correct) |

### Phase C: Testing Checklist

| # | Test | Expected |
|---|------|----------|
| 1 | Click "Unit Search" in nav | Goes to `/units/search/`, shows "Unit Search" title and subtitle |
| 2 | Unit Search — Units tab | Form with ~20 unit fields; "Search Units" and "Clear" buttons |
| 3 | Unit Search — Applications tab | Form with application fields; "Search Applications" button |
| 4 | Unit Search — Parts tab | Form with part fields; "Search Parts" button |
| 5 | Unit Search — Submit Units | Runs search, shows units table below form |
| 6 | Click "Unit List" in nav | Goes to `/units/`, shows "Unit List" and "Browse all unit models" |
| 7 | Unit List — type tabs | AC Motors, DC Motors, etc.; clicking filters list |
| 8 | Unit List — filters | Search, Unit Type, OEM, Voltage, Family work |
| 9 | Unit List — table | Shows units with View button |
| 10 | Nav highlighting | Unit Search active on search page; Unit List active on list page |

---

## 4. Screenshot Comparison Checklist

Compare against reference screenshots after implementation:

### Unit Search

- [ ] Title: "Unit Search"
- [ ] Subtitle: "Search for units, applications, and parts across the entire system"
- [ ] Tabs: Units | Applications | Parts
- [ ] Units tab: multi-column form layout; all fields from screenshot
- [ ] Applications tab: Make, Engine, Year, Volt, Amp, etc.
- [ ] Parts tab: OEM #, Key, J&N, Name, Category, etc.
- [ ] Buttons: Search [Entity], Clear

### Unit List

- [ ] Title: "Unit List"
- [ ] Subtitle: "Browse all unit models in the system"
- [ ] Unit type tabs: AC Motors, DC Motors, Generators, Starters, Alternators, Pumps
- [ ] Filter bar: Search, Unit Type, OEM, Voltage, Family
- [ ] Buttons: Add New Unit, Upload CSV
- [ ] Table: appropriate columns per unit type
- [ ] View button per row

---

## 5. Risk / Scope Notes

- **Unit Search result display:** Screenshots show the form; result layout (table vs cards) may vary. Plan: show results in a table below the form, similar to Unit List.
- **Unit-type-specific columns:** Screenshots show different columns for AC Motor vs DC Motor vs Generator, etc. Current unit list uses a single column set. Consider: either one generic set or dynamic columns per type.
- **Home page:** Unit Search card on home could link to `unit_search` instead of `unit_list`.

---

## 6. Execution Order

1. Create this plan document ✓
2. **Review plan** — confirm field lists and URLs match screenshots ✓
3. Implement Phase A (Unit Search) ✓
4. Implement Phase B (Unit List tweaks) ✓
5. Update nav (Phase A5, B3) ✓
6. Run testing checklist (Phase C) ✓
7. Visual comparison against screenshots ✓

---

## 7. Implementation Complete (Tested)

**Verified:**
- Unit Search at `/units/search/`: Title, subtitle, Units/Applications/Parts tabs, multi-field forms, Search/Clear buttons
- Unit List at `/units/`: Title, subtitle "Browse all unit models in the system", type tabs, filter panel, table
- Nav: Unit Search and Unit List are separate links; active state highlights correctly
- Tab switching on Unit Search works (Units → Applications → Parts)
