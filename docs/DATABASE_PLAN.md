# Manchester Electric — Database Plan

## Overview

This document defines the database schema for the **Manchester Electric** project. The project folder is currently named **Manchester**; rename it to **Manchester Electric** after you delete the old Manchester Electric folder so the two do not conflict.

The system supports motor repair, parts sales, and motor sales with three apps: **catalog**, **inventory**, and **invoicing**. It tracks Applications (engines/machines), Units (AC/DC motors, alternators, starters, etc.), Parts, Vendors, Customers, and Invoices.

---

## Entity Relationship Summary

```
                    Vendor (supplies)
                         │
                         ▼
Customer ──► Invoice ──► InvoiceItem ◄── Part ◄── BOMItem ◄── BOM
                │              ▲            │         ▲
                │              │            │         │
                └──────────────┴──────── Unit ───────┘
                                    │
              Application ◄──ApplicationUnit──► Unit
                                    │
                    UnitType, CrossReference, Substitute, GearReductionSubstitution
```

---

## Apps and Tables

| App       | Tables |
|-----------|--------|
| catalog   | UnitType, Application, Unit, ApplicationUnit, CrossReference, Substitute, GearReductionSubstitution, Part, BOM, BOMItem |
| inventory | Vendor (plus Part stock fields: stock_quantity, reorder_qty, bin_number) |
| invoicing | Customer, Invoice, InvoiceItem |

---

## Catalog App (10 tables)

### 1. UnitType

Lookup table for unit categories. Pre-populate with: AC Motor, DC Motor, Generator, Starter, Alternator, Pump.

| Field       | Type          | Description                    |
|-------------|---------------|--------------------------------|
| id          | AutoField (PK)| Primary key                    |
| name        | CharField(100)| Unique type name               |
| description | TextField     | Optional description (blank)   |

---

### 2. Application

Machine, engine, or vehicle that units are installed on (e.g. "4 Cylinder Engine 73", "CUMMINS ISL").

| Field        | Type          | Description                  |
|--------------|---------------|-----------------------------|
| id           | AutoField (PK)| Primary key                 |
| name         | CharField(255)| Application name            |
| make         | CharField(150)| Make (blank ok)             |
| engine       | CharField(150)| Engine name/model           |
| year         | CharField(50) | Year or year range          |
| mfr          | CharField(150)| Manufacturer                |
| volt         | CharField(50) | Voltage                     |
| amp          | CharField(50) | Amps                        |
| part_number  | CharField(100)| Associated part number      |
| other_number | CharField(100)| Alternate reference         |
| unit_number  | CharField(100)| Linked unit number          |
| options      | TextField     | Options                     |
| notes        | TextField     | Notes                       |
| is_active    | BooleanField  | Default True                 |
| created_at   | DateTimeField | auto_now_add                 |
| updated_at   | DateTimeField | auto_now                     |

Indexes: name, make, engine.

---

### 3. Unit

Component/assembly (motor, alternator, starter, etc.) that goes on an Application. One table for all unit types; type-specific fields can be blank.

| Field (group)     | Examples |
|-------------------|----------|
| Identification     | unit_number (unique), yt_number, oem, j_and_n_number, model_cat_number, unit_type (FK→UnitType), manufacturer, family |
| Electrical         | voltage, kw_hp, phase, fla, amp_rating, full_load_eff, power_rating |
| Mechanical         | rpm, frame, enclosure, rotation, mount_type, flange_type, housing_type, housing, weight, bearings, design, type, service_factor, duty_cycle, speed_ratio, grounding, insulation_class, overload_protection, c_dimension, u_dimension |
| Starter-specific   | tooth_quantity, nose_type, over_crank_protection, solenoid_attached |
| Generator-specific | circuit_type, brush_type, regulation_type |
| Alternator-specific| fan_type, regulator_type |
| Other              | reclockable_flange, with_mounting_shims, with_hardware, bolt_holes, clocking_degrees, drive |
| Descriptive        | unit_attributes, notes |
| Pricing            | new_unit_price, rebuilt_unit_price (Decimal, null/blank ok) |
| Images             | unit_image, plug_image (ImageField, upload_to units/) |
| Relationships      | applications M:M Application via ApplicationUnit |
| Metadata           | is_active, created_at, updated_at |

Indexes: unit_number, yt_number, oem.

---

### 4. ApplicationUnit (junction)

Links Applications to Units (M:M with extra data).

| Field       | Type               | Description        |
|-------------|--------------------|--------------------|
| id          | AutoField (PK)     | Primary key        |
| application | FK → Application   | Required           |
| unit        | FK → Unit          | Required           |
| position    | CharField(100)     | Position (blank ok)|
| notes       | TextField          | Fitment notes      |
| created_at  | DateTimeField      | auto_now_add       |

Unique: (application, unit).

---

### 5. CrossReference

Links a unit to equivalent units across brands.

| Field         | Type     | Description   |
|---------------|----------|---------------|
| id            | AutoField| Primary key   |
| unit          | FK → Unit| From unit     |
| cross_ref_unit| FK → Unit| To unit       |
| notes         | TextField| Optional      |
| created_at    | DateTime | auto_now_add  |

Unique: (unit, cross_ref_unit).

---

### 6. Substitute

Interchangeable / substitute units.

| Field          | Type     | Description   |
|----------------|----------|---------------|
| id             | AutoField| Primary key   |
| unit           | FK → Unit| Original      |
| substitute_unit| FK → Unit| Substitute    |
| notes          | TextField| Optional      |
| created_at     | DateTime | auto_now_add  |

Unique: (unit, substitute_unit).

---

### 7. GearReductionSubstitution

Gear reduction options for a unit.

| Field       | Type        | Description        |
|-------------|-------------|--------------------|
| id          | AutoField   | Primary key        |
| unit        | FK → Unit   | Required           |
| number      | CharField(50)| e.g. GR-001       |
| description | CharField(255)| Required          |
| notes       | TextField   | Optional           |
| created_at  | DateTime    | auto_now_add       |

---

### 8. Part

Individual part/component. Can be on a Unit BOM and on invoices. Multiple numbering systems (OEM, J&N, YT) and stock fields.

| Field           | Type          | Description                |
|-----------------|---------------|----------------------------|
| id              | AutoField (PK)| Primary key                |
| part_number     | CharField(100)| Unique                     |
| part_name       | CharField(255)| Descriptive name           |
| key             | CharField(100)| Internal key (blank ok)    |
| yt_number       | CharField(100)| YT Number                  |
| j_and_n         | CharField(100)| J&N                        |
| oem_number      | CharField(100)| OEM #                      |
| item_no         | CharField(100)| Item No                    |
| category        | CharField(100)| Category                   |
| type            | CharField(100)| Type                       |
| oem_type        | CharField(100)| OEM Type                   |
| item_typ        | CharField(100)| Item Type                  |
| oem             | CharField(200)| OEM                        |
| primary_vendor  | CharField(200)| Text or FK→Vendor (see Inventory) |
| catalog         | CharField(100)| Catalog ref                |
| plug_id         | CharField(100)| Plug ID                    |
| price           | DecimalField  | Sell price (null/blank ok) |
| cost_price      | DecimalField  | Cost (null/blank ok)       |
| stock_quantity  | IntegerField  | Default 0                  |
| reorder_qty     | IntegerField  | Reorder threshold           |
| bin_number      | CharField(50) | Bin location               |
| description     | TextField     | Description                |
| foot_notes      | TextField     | Footnotes                  |
| superseding_notes| TextField    | Superseding notes          |
| has_picture     | BooleanField  | Default False              |
| has_interchange | BooleanField  | Default False              |
| has_superseding| BooleanField  | Default False              |
| image           | ImageField    | upload_to parts/ (blank/null ok) |
| unit            | FK → Unit     | Optional linked unit       |
| is_active       | BooleanField  | Default True                |
| created_at      | DateTimeField | auto_now_add                |
| updated_at      | DateTimeField | auto_now                    |

Indexes: part_number, part_name, oem_number, j_and_n, yt_number.

---

### 9. BOM

Bill of Materials header. Optional link to Unit and/or Application.

| Field       | Type        | Description              |
|-------------|-------------|--------------------------|
| id          | AutoField   | Primary key              |
| name        | CharField(255)| BOM title               |
| description | TextField   | Optional                  |
| unit        | FK → Unit   | Optional                  |
| application | FK → Application | Optional             |
| created_at  | DateTime    | auto_now_add              |
| updated_at  | DateTime    | auto_now                  |

---

### 10. BOMItem

One line on a BOM: part, quantity, and optional override/cross-ref fields.

| Field      | Type        | Description              |
|------------|-------------|--------------------------|
| id         | AutoField   | Primary key              |
| bom        | FK → BOM    | Required                 |
| part       | FK → Part   | Required                 |
| description| CharField(255)| Override (blank ok)     |
| notes      | TextField   | Optional                  |
| unit_qty   | PositiveInteger | Default 1            |
| stock_qty  | IntegerField| Snapshot/override        |
| bin_number | CharField(50)| Override                |
| oem_number | CharField(100)| Override               |
| j_and_n    | CharField(100)| Override                |
| yt_number  | CharField(100)| Override                |
| created_at  | DateTime    | auto_now_add              |

---

## Inventory App (1 table + Part stock)

### 11. Vendor

Suppliers/vendors with full contact and address. Parts can reference a primary Vendor (e.g. ForeignKey from Part.primary_vendor to Vendor, or keep primary_vendor as CharField and add optional FK vendor).

| Field         | Type          | Description           |
|---------------|---------------|-----------------------|
| id            | AutoField (PK)| Primary key           |
| name          | CharField(255)| Vendor/company name   |
| contact_name  | CharField(150)| Contact (blank ok)    |
| email         | EmailField    | Blank ok              |
| phone         | CharField(50)| Blank ok              |
| address_line1 | CharField(255)| Street               |
| address_line2 | CharField(255)| Suite/Apt             |
| city          | CharField(100)| City                 |
| state         | CharField(100)| State/Province       |
| zip_code      | CharField(20)| ZIP/Postal            |
| notes         | TextField     | Optional              |
| is_active     | BooleanField  | Default True          |
| created_at    | DateTimeField | auto_now_add          |
| updated_at    | DateTimeField | auto_now              |

Inventory day-to-day: Part.stock_quantity, Part.reorder_qty, Part.bin_number. Optional later: StockMovement, PurchaseOrder.

---

## Invoicing App (3 tables)

### 12. Customer

| Field         | Type          | Description           |
|---------------|---------------|-----------------------|
| id            | AutoField (PK)| Primary key           |
| name          | CharField(255)| Customer/company name |
| email         | EmailField    | Blank ok              |
| phone         | CharField(50)| Blank ok              |
| address_line1 | CharField(255)| Blank ok             |
| address_line2 | CharField(255)| Blank ok             |
| city          | CharField(100)| Blank ok             |
| state         | CharField(100)| Blank ok             |
| zip_code      | CharField(20)| Blank ok              |
| notes         | TextField     | Blank ok              |
| is_active     | BooleanField  | Default True          |
| created_at    | DateTimeField | auto_now_add          |
| updated_at    | DateTimeField | auto_now              |

---

### 13. Invoice

| Field          | Type               | Description        |
|----------------|--------------------|--------------------|
| id             | AutoField (PK)     | Primary key        |
| invoice_number | CharField(50)      | Unique             |
| customer       | FK → Customer      | Required           |
| date           | DateField          | Required           |
| due_date       | DateField          | Null/blank ok      |
| status         | CharField(20)      | DRAFT/SENT/PAID/OVERDUE/CANCELLED |
| subtotal       | DecimalField       | Calculated         |
| tax_rate       | DecimalField       | Percentage         |
| tax_amount     | DecimalField       | Calculated         |
| total          | DecimalField       | Calculated         |
| notes          | TextField          | Optional           |
| created_at     | DateTimeField      | auto_now_add       |
| updated_at     | DateTimeField      | auto_now           |

Indexes: invoice_number, status, date.

---

### 14. InvoiceItem

| Field       | Type        | Description                    |
|-------------|-------------|--------------------------------|
| id          | AutoField   | Primary key                    |
| invoice     | FK → Invoice| Required                       |
| part        | FK → Part   | Null/blank (custom lines)      |
| unit        | FK → Unit   | Null/blank (e.g. sold unit)    |
| description | CharField(500)| Line description              |
| quantity    | PositiveInteger | Default 1                  |
| unit_price  | DecimalField| Required                       |
| line_total  | DecimalField| quantity × unit_price          |
| created_at  | DateTime    | auto_now_add                   |

---

## Indexes and Performance

- Application: name, make, engine  
- Unit: unit_number, yt_number, oem  
- Part: part_number, part_name, oem_number, j_and_n, yt_number  
- ApplicationUnit: unique (application, unit)  
- Invoice: invoice_number, status, date  
- Vendor: name (optional)

---

## Key Workflows

1. **Catalog:** Search by Application → Units on that application → BOM per unit.  
2. **Catalog:** Search by Unit → Applications it fits → BOM for that unit.  
3. **Catalog:** Search by Part → Units using it → Applications.  
4. **Inventory:** Vendor list; parts with primary_vendor; reorder list (stock_quantity ≤ reorder_qty).  
5. **Invoicing:** Create invoice → Customer → Add line items (Parts/Units or custom) → Calculate totals → Print/send.

---

## Folder Rename Reminder

This project lives in the **Manchester** folder. After you delete the old **Manchester Electric** folder, rename **Manchester** to **Manchester Electric** so this project becomes the main Manchester Electric codebase.
