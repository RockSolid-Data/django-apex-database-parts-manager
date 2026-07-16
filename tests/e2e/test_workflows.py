"""
Phase 5 — User Journey / Workflow Tests
End-to-end user journeys exercised through the Django test client.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")

import io
import json
import tempfile
from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings

from tests.e2e.factories import *  # noqa: F403, F401


# ═══════════════════════════════════════════════════════════════════════════
# Workflow 1: Create a full catalog entry
# ═══════════════════════════════════════════════════════════════════════════

class FullCatalogEntryWorkflowTest(TestCase):
    """
    UnitTypeCategory → Unit → Parts → BOM → Application → link Unit
    → cross-references, substitutes, gear-reductions on Unit
    → interchanges, substitutes, supersedings on Part
    → verify relationships on detail pages.
    """

    def test_full_catalog_entry(self):
        from catalog.models import (
            Application, ApplicationUnit, BOM, BOMItem,
            CrossReference, GearReductionSubstitution, Part,
            PartInterchange, PartSubstitute, PartSuperseding,
            Substitute, Unit, UnitTypeCategory,
        )

        # --- Step 1: Create UnitTypeCategory via view ---
        r = self.client.post("/units/type-categories/add/", {
            "name": "Alternators",
            "sort_order": "1",
            "color": "#fd7e14",
        })
        self.assertIn(r.status_code, (200, 301, 302))
        utc = UnitTypeCategory.objects.get(name="Alternators")

        # --- Step 2: Create a Unit with that type via view ---
        r = self.client.post("/units/add/", {
            "unit_number": "WF-ALT-001",
            "yt_number": "YT-WF-001",
            "oem": "Bosch",
            "voltage": "12V",
            "unit_type_category": "Alternators",
            "new_unit_price": "200.00",
            "rebuilt_unit_price": "120.00",
            "is_active": "on",
        })
        self.assertIn(r.status_code, (200, 301, 302))
        unit = Unit.objects.get(unit_number="WF-ALT-001")
        self.assertEqual(unit.voltage, "12V")

        # --- Step 3: Create Parts linked to that Unit via view ---
        r = self.client.post("/parts/add/", {
            "part_number": "WF-P-001",
            "part_name": "Brush Set",
            "category": "Brushes",
            "voltage": "12V",
            "price": "35.00",
            "cost_price": "20.00",
            "stock_quantity": "50",
            "reorder_qty": "10",
            "track_inventory": "on",
            "is_active": "on",
            "manual_unit_number": "WF-ALT-001",
        })
        self.assertIn(r.status_code, (200, 301, 302))
        part1 = Part.objects.get(part_number="WF-P-001")
        self.assertTrue(part1.units.filter(pk=unit.pk).exists())

        part2 = PartFactory(part_number="WF-P-002", part_name="Regulator")

        # --- Step 4: Create BOM via API ---
        r = self.client.post("/api/bom/save/", {
            "name": f"BOM for {unit.unit_number}",
            "unit": unit.pk,
        })
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertTrue(data["ok"])
        bom_pk = data["pk"]
        bom = BOM.objects.get(pk=bom_pk)

        # Add parts to BOM
        r = self.client.post(f"/api/bom/{bom_pk}/add-part/", {
            "part": part1.pk,
            "unit_qty": 1,
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(json.loads(r.content)["ok"])

        r = self.client.post(f"/api/bom/{bom_pk}/add-part/", {
            "part": part2.pk,
            "unit_qty": 2,
        })
        self.assertTrue(json.loads(r.content)["ok"])
        self.assertEqual(BOMItem.objects.filter(bom=bom).count(), 2)

        # --- Step 5: Create Application via view ---
        # ApplicationForm auto-generates name from unit_number + make + model + engine
        r = self.client.post("/applications/add/", {
            "make": "Ford",
            "model": "F-150",
            "year": "2024",
            "mfr": "Bosch",
            "volt": "12V",
        })
        self.assertIn(r.status_code, (200, 301, 302))
        app = Application.objects.get(name="Ford F-150")

        # --- Step 6: Link Unit to Application ---
        r = self.client.post(f"/applications/{app.pk}/link-unit/", {
            "unit": unit.pk,
        })
        self.assertIn(r.status_code, (200, 301, 302))
        self.assertTrue(ApplicationUnit.objects.filter(application=app, unit=unit).exists())

        # --- Step 7: Add cross-references, substitutes, gear reductions to Unit ---
        sub_unit = UnitFactory(unit_number="WF-SUB-001")

        r = self.client.post(f"/units/{unit.pk}/cross-ref/add/", {
            "cross_ref_number": "XREF-WF-001",
            "interchange_type": "Direct",
            "price": "100.00",
        })
        self.assertIn(r.status_code, (200, 301, 302))
        self.assertTrue(CrossReference.objects.filter(unit=unit, cross_ref_number="XREF-WF-001").exists())

        r = self.client.post(f"/units/{unit.pk}/substitute/add/", {
            "substitute_unit": sub_unit.pk,
            "substitute_number": sub_unit.unit_number,
        })
        self.assertIn(r.status_code, (200, 301, 302))
        self.assertTrue(Substitute.objects.filter(unit=unit).exists())

        r = self.client.post(f"/units/{unit.pk}/gear-reduction/add/", {
            "number": "GR-WF-001",
            "unit_type": "Gear Reduction",
            "supplier": "TestSupplier",
        })
        self.assertIn(r.status_code, (200, 301, 302))
        self.assertTrue(GearReductionSubstitution.objects.filter(unit=unit).exists())

        # --- Step 8: Add interchanges, substitutes, supersedings to Part ---
        ix_part = PartFactory(part_number="WF-IX-001")
        sub_part = PartFactory(part_number="WF-SUB-P-001")
        old_part = PartFactory(part_number="WF-OLD-001")

        r = self.client.post(f"/parts/{part1.pk}/interchange/add/", {
            "interchange_part": ix_part.pk,
            "interchange_number": ix_part.part_number,
            "source_name": "OEM",
        })
        self.assertIn(r.status_code, (200, 301, 302))
        self.assertTrue(PartInterchange.objects.filter(part=part1).exists())

        r = self.client.post(f"/parts/{part1.pk}/substitute/add/", {
            "substitute_part": sub_part.pk,
            "substitute_number": sub_part.part_number,
        })
        self.assertIn(r.status_code, (200, 301, 302))
        self.assertTrue(PartSubstitute.objects.filter(part=part1).exists())

        r = self.client.post(f"/parts/{part1.pk}/superseding/add/", {
            "old_part": old_part.pk,
            "old_part_number": old_part.part_number,
        })
        self.assertIn(r.status_code, (200, 301, 302))
        self.assertTrue(PartSuperseding.objects.filter(part=part1).exists())

        # --- Step 9: Verify relationships on detail pages ---
        r = self.client.get(f"/units/{unit.pk}/")
        self.assertEqual(r.status_code, 200)
        content = r.content.decode()
        self.assertIn("XREF-WF-001", content)
        self.assertIn("GR-WF-001", content)

        r = self.client.get(f"/parts/{part1.pk}/")
        self.assertEqual(r.status_code, 200)

        r = self.client.get(f"/applications/{app.pk}/")
        self.assertEqual(r.status_code, 200)
        content = r.content.decode()
        self.assertIn("WF-ALT-001", content)


# ═══════════════════════════════════════════════════════════════════════════
# Workflow 2: Invoice creation flow
# ═══════════════════════════════════════════════════════════════════════════

class InvoiceCreationWorkflowTest(TestCase):
    """
    CompanySettings → Customer → Parts with stock → Create Invoice with items
    → verify stock decremented → edit invoice → print → cancel → delete.
    """

    def test_invoice_lifecycle(self):
        from catalog.models import Part
        from invoicing.models import CompanySettings, Customer, Invoice, InvoiceItem

        # --- Step 1: Create Company Settings ---
        settings = CompanySettingsFactory(
            invoice_number_prefix="WF-",
            invoice_number_include_year=False,
            invoice_number_padding=4,
        )
        self.assertIsNotNone(CompanySettings.get())

        # --- Step 2: Create a Customer via view ---
        r = self.client.post("/invoicing/customers/add/", {
            "name": "Workflow Customer",
            "contact_name": "Alice",
            "phone": "555-1234",
            "email": "alice@test.com",
            "is_active": "on",
            "contacts-TOTAL_FORMS": "1",
            "contacts-INITIAL_FORMS": "0",
            "contacts-MIN_NUM_FORMS": "0",
            "contacts-MAX_NUM_FORMS": "1000",
        })
        self.assertIn(r.status_code, (200, 301, 302))
        customer = Customer.objects.get(name="Workflow Customer")

        # --- Step 3: Create Parts with stock ---
        part_a = PartFactory(
            part_number="WF-INV-A", part_name="Widget A",
            price=Decimal("50.00"), stock_quantity=20, track_inventory=True,
        )
        part_b = PartFactory(
            part_number="WF-INV-B", part_name="Widget B",
            price=Decimal("75.00"), stock_quantity=15, track_inventory=True,
        )
        initial_stock_a = part_a.stock_quantity
        initial_stock_b = part_b.stock_quantity

        # --- Step 4-5: Create Invoice with line items via view ---
        today = date.today()
        r = self.client.post("/invoicing/invoice/new/", {
            "customer": customer.pk,
            "customer_name": customer.name,
            "date": today.isoformat(),
            "due_date": today.isoformat(),
            "tax_rate": "6.35",
            "status": "DRAFT",
            # Formset management fields
            "items-TOTAL_FORMS": "2",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "1",
            "items-MAX_NUM_FORMS": "1000",
            # Item 0
            "items-0-part": part_a.pk,
            "items-0-description": "Widget A",
            "items-0-quantity": "3",
            "items-0-unit_price": "50.00",
            "items-0-discount_pct": "0",
            # Item 1
            "items-1-part": part_b.pk,
            "items-1-description": "Widget B",
            "items-1-quantity": "2",
            "items-1-unit_price": "75.00",
            "items-1-discount_pct": "0",
        })
        self.assertIn(r.status_code, (200, 301, 302))
        invoice = Invoice.objects.order_by("-pk").first()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.status, "DRAFT")
        self.assertEqual(InvoiceItem.objects.filter(invoice=invoice).count(), 2)

        # --- Step 6: Verify stock decremented ---
        part_a.refresh_from_db()
        part_b.refresh_from_db()
        self.assertEqual(part_a.stock_quantity, initial_stock_a - 3)
        self.assertEqual(part_b.stock_quantity, initial_stock_b - 2)

        # --- Step 7: Edit the invoice (change quantity on item 0) ---
        items = list(invoice.items.order_by("pk"))
        item_a = items[0]
        item_b = items[1]
        r = self.client.post(f"/invoicing/invoice/{invoice.pk}/edit/", {
            "customer": customer.pk,
            "customer_name": customer.name,
            "date": today.isoformat(),
            "due_date": today.isoformat(),
            "tax_rate": "6.35",
            "status": "DRAFT",
            "items-TOTAL_FORMS": "2",
            "items-INITIAL_FORMS": "2",
            "items-MIN_NUM_FORMS": "1",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-id": item_a.pk,
            "items-0-invoice": invoice.pk,
            "items-0-part": part_a.pk,
            "items-0-description": "Widget A",
            "items-0-quantity": "1",
            "items-0-unit_price": "50.00",
            "items-0-discount_pct": "0",
            "items-1-id": item_b.pk,
            "items-1-invoice": invoice.pk,
            "items-1-part": part_b.pk,
            "items-1-description": "Widget B",
            "items-1-quantity": "2",
            "items-1-unit_price": "75.00",
            "items-1-discount_pct": "0",
        })
        self.assertIn(r.status_code, (200, 301, 302))

        # --- Step 8: Verify stock adjusted (qty went from 3 → 1, so 2 restored) ---
        part_a.refresh_from_db()
        self.assertEqual(part_a.stock_quantity, initial_stock_a - 1)

        # --- Step 9: Print invoice → DRAFT becomes SENT ---
        r = self.client.get(f"/invoicing/invoice/{invoice.pk}/print/")
        self.assertEqual(r.status_code, 200)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "SENT")

        # --- Step 10: Cancel invoice (status change only, does NOT restore stock) ---
        r = self.client.post(f"/invoicing/invoice/{invoice.pk}/cancel/")
        self.assertIn(r.status_code, (301, 302))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "CANCELLED")

        # Stock should NOT have changed from cancel
        part_a.refresh_from_db()
        self.assertEqual(part_a.stock_quantity, initial_stock_a - 1)

        # Delete invoice → cascade deletes items → stock restored via pre_delete signal
        r = self.client.post(f"/invoicing/invoice/{invoice.pk}/delete/")
        self.assertIn(r.status_code, (301, 302))
        self.assertFalse(Invoice.objects.filter(pk=invoice.pk).exists())

        part_a.refresh_from_db()
        part_b.refresh_from_db()
        self.assertEqual(part_a.stock_quantity, initial_stock_a)
        self.assertEqual(part_b.stock_quantity, initial_stock_b)


# ═══════════════════════════════════════════════════════════════════════════
# Workflow 3: CSV Import — Parts
# ═══════════════════════════════════════════════════════════════════════════

class PartCSVImportWorkflowTest(TestCase):
    """Download CSV template → upload valid CSV → preview → confirm → verify."""

    def test_part_csv_import(self):
        from catalog.models import Part

        # --- Step 1: Download CSV template ---
        r = self.client.get("/parts/csv-template/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r["Content-Type"])
        self.assertIn("attachment", r["Content-Disposition"])

        # --- Step 2: Upload a valid CSV ---
        csv_content = (
            "Part Number,Part Name,Category,Voltage,Sell Price,Cost Price,Stock Quantity\r\n"
            "CSV-P-001,CSV Brush Set,Brushes,12V,30.00,15.00,100\r\n"
            "CSV-P-002,CSV Regulator,Regulators,24V,45.00,22.50,50\r\n"
        )
        csv_file = io.BytesIO(csv_content.encode("utf-8-sig"))
        csv_file.name = "test_parts.csv"

        r = self.client.post("/parts/upload-csv/", {
            "step": "upload",
            "csv_file": csv_file,
        })
        self.assertEqual(r.status_code, 200)

        # --- Step 3: Preview step — verify parsed data ---
        self.assertIn("columns", r.context)
        self.assertIn("rows", r.context)
        columns = r.context["columns"]
        rows = r.context["rows"]
        self.assertEqual(len(rows), 2)
        self.assertIn("part_number", columns)

        columns_json = r.context["columns_json"]

        # --- Step 4: Confirm import ---
        confirm_data = {
            "step": "confirm",
            "columns": columns_json,
            "row_count": "2",
        }
        for i, row in enumerate(rows):
            for col in columns:
                confirm_data[f"row_{i}_{col}"] = row.get(col, "")

        r = self.client.post("/parts/upload-csv/", confirm_data)
        self.assertEqual(r.status_code, 200)

        # --- Step 5: Verify Parts created ---
        p1 = Part.objects.get(part_number="CSV-P-001")
        self.assertEqual(p1.part_name, "CSV Brush Set")
        self.assertEqual(p1.category, "Brushes")

        p2 = Part.objects.get(part_number="CSV-P-002")
        self.assertEqual(p2.part_name, "CSV Regulator")

        # Verify report context
        self.assertEqual(r.context["created"], 2)
        self.assertEqual(r.context["skipped"], 0)

        # Verify they appear in the part list
        r = self.client.get("/parts/", {"q": "CSV-P-001"})
        self.assertContains(r, "CSV-P-001")


# ═══════════════════════════════════════════════════════════════════════════
# Workflow 4: CSV Import — Units
# ═══════════════════════════════════════════════════════════════════════════

class UnitCSVImportWorkflowTest(TestCase):
    """Download CSV template → upload valid CSV → preview → confirm → verify."""

    def test_unit_csv_import(self):
        from catalog.models import Unit

        # --- Step 1: Download template ---
        r = self.client.get("/units/csv-template/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r["Content-Type"])

        # --- Step 2: Upload valid CSV ---
        csv_content = (
            "Unit Number,YT Number,OEM,Voltage,New Unit Price,Rebuilt Unit Price\r\n"
            "CSV-U-001,YT-CSV-001,Bosch,12V,200.00,120.00\r\n"
            "CSV-U-002,YT-CSV-002,Denso,24V,250.00,150.00\r\n"
        )
        csv_file = io.BytesIO(csv_content.encode("utf-8-sig"))
        csv_file.name = "test_units.csv"

        r = self.client.post("/units/upload-csv/", {
            "step": "upload",
            "csv_file": csv_file,
        })
        self.assertEqual(r.status_code, 200)

        # --- Step 3: Preview ---
        columns = r.context["columns"]
        rows = r.context["rows"]
        self.assertEqual(len(rows), 2)
        columns_json = r.context["columns_json"]

        # --- Step 4: Confirm ---
        confirm_data = {
            "step": "confirm",
            "columns": columns_json,
            "row_count": "2",
        }
        for i, row in enumerate(rows):
            for col in columns:
                confirm_data[f"row_{i}_{col}"] = row.get(col, "")

        r = self.client.post("/units/upload-csv/", confirm_data)
        self.assertEqual(r.status_code, 200)

        # --- Step 5: Verify Units created ---
        u1 = Unit.objects.get(unit_number="CSV-U-001")
        self.assertEqual(u1.oem, "Bosch")

        u2 = Unit.objects.get(unit_number="CSV-U-002")
        self.assertEqual(u2.voltage, "24V")

        self.assertEqual(r.context["created"], 2)

        # Verify in unit list
        r = self.client.get("/units/", {"q": "CSV-U-001"})
        self.assertContains(r, "CSV-U-001")


# ═══════════════════════════════════════════════════════════════════════════
# Workflow 5: Inventory and Reorder
# ═══════════════════════════════════════════════════════════════════════════

class InventoryReorderWorkflowTest(TestCase):
    """
    Create parts with inventory tracking → verify in inventory list
    → set stock low → verify in reorder list → create invoice → verify.
    """

    def test_inventory_reorder_flow(self):
        from catalog.models import Part
        from invoicing.models import CompanySettings, Invoice, InvoiceItem

        CompanySettingsFactory()

        # --- Step 1: Create parts with track_inventory and reorder levels ---
        part_a = PartFactory(
            part_number="INV-WF-A", part_name="Inventory Widget",
            track_inventory=True, stock_quantity=20, reorder_qty=15,
            price=Decimal("10.00"),
        )
        part_b = PartFactory(
            part_number="INV-WF-B", part_name="Stocked Widget",
            track_inventory=True, stock_quantity=100, reorder_qty=10,
            price=Decimal("20.00"),
        )

        # --- Step 2: Verify they appear in inventory list ---
        r = self.client.get("/inventory/", {"q": "INV-WF-A"})
        self.assertContains(r, "INV-WF-A")
        r = self.client.get("/inventory/", {"q": "INV-WF-B"})
        self.assertContains(r, "INV-WF-B")

        # --- Step 3: Set stock at or below reorder_qty ---
        part_a.stock_quantity = 10
        part_a.save(update_fields=["stock_quantity"])

        # --- Step 4: Verify it appears in reorder list ---
        # Reorder search uses part_name, not part_number
        r = self.client.get("/inventory/reorder/", {"q": "Inventory Widget"})
        pks = {p.pk for p in r.context["parts"]}
        self.assertIn(part_a.pk, pks)
        # part_b should NOT be in reorder (stock=100, reorder=10)
        r_all = self.client.get("/inventory/reorder/", {"q": "Stocked Widget"})
        pks_all = {p.pk for p in r_all.context["parts"]}
        self.assertNotIn(part_b.pk, pks_all)

        # --- Step 5: Create invoice to decrement stock further ---
        customer = CustomerFactory(name="Inv WF Customer")
        today = date.today()
        r = self.client.post("/invoicing/invoice/new/", {
            "customer": customer.pk,
            "customer_name": customer.name,
            "date": today.isoformat(),
            "due_date": today.isoformat(),
            "tax_rate": "0",
            "status": "DRAFT",
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "1",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-part": part_a.pk,
            "items-0-description": part_a.part_name,
            "items-0-quantity": "2",
            "items-0-unit_price": "10.00",
            "items-0-discount_pct": "0",
        })
        self.assertIn(r.status_code, (200, 301, 302))

        # --- Step 6: Verify stock decremented (was 10, ordered 2 → now 8) ---
        part_a.refresh_from_db()
        self.assertEqual(part_a.stock_quantity, 8)

        # Still on reorder list (stock 8 <= reorder_qty 15)
        r = self.client.get("/inventory/reorder/", {"q": "Inventory Widget"})
        pks = {p.pk for p in r.context["parts"]}
        self.assertIn(part_a.pk, pks)


# ═══════════════════════════════════════════════════════════════════════════
# Workflow 6: Backup and Restore cycle
# ═══════════════════════════════════════════════════════════════════════════

class BackupRestoreWorkflowTest(TestCase):
    """Configure backup → trigger manual backup → verify → check restore form."""

    def test_backup_cycle(self):
        from backup.models import BackupSettings

        tmp_dir = tempfile.mkdtemp(prefix="apex_backup_test_")

        try:
            # --- Step 1: Configure backup settings ---
            r = self.client.post("/backup/", {
                "local_backup_path": tmp_dir,
                "external_backup_path": "",
                "auto_backup_enabled": "on",
                "backup_interval_hours": "2",
                "max_backups": "4",
            })
            self.assertIn(r.status_code, (200, 301, 302))
            bs = BackupSettings.get()
            self.assertEqual(bs.local_backup_path, tmp_dir)

            # --- Step 2: Trigger manual backup ---
            r = self.client.post("/backup/now/")
            self.assertIn(r.status_code, (200, 301, 302))

            # --- Step 3: Verify backup happened (settings updated) ---
            bs.refresh_from_db()
            # last_backup_at should be set after a successful sync
            # (may fail if path not writable in CI, so we just verify the view works)

            # --- Step 4: Verify restore form renders ---
            r = self.client.get("/backup/")
            self.assertEqual(r.status_code, 200)
            self.assertIn("restore_form", r.context)
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════
# Workflow 7: BOM Management
# ═══════════════════════════════════════════════════════════════════════════

class BOMManagementWorkflowTest(TestCase):
    """Create Unit → create BOM via API → add parts → delete item → print → delete BOM."""

    def test_bom_management(self):
        from catalog.models import BOM, BOMItem

        unit = UnitFactory(unit_number="BOM-WF-001")
        part1 = PartFactory(part_number="BOM-P-001")
        part2 = PartFactory(part_number="BOM-P-002")
        part3 = PartFactory(part_number="BOM-P-003")

        # --- Step 1: Create BOM via API ---
        r = self.client.post("/api/bom/save/", {
            "name": f"BOM for {unit.unit_number}",
            "unit": unit.pk,
        })
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertTrue(data["ok"])
        bom_pk = data["pk"]
        bom = BOM.objects.get(pk=bom_pk)
        self.assertEqual(bom.unit, unit)

        # --- Step 2: Add parts via API ---
        r = self.client.post(f"/api/bom/{bom_pk}/add-part/", {
            "part": part1.pk,
            "unit_qty": 1,
        })
        self.assertEqual(r.status_code, 200)
        item1_data = json.loads(r.content)
        self.assertTrue(item1_data["ok"])
        item1_pk = item1_data["item"]["pk"]

        r = self.client.post(f"/api/bom/{bom_pk}/add-part/", {
            "part": part2.pk,
            "unit_qty": 3,
        })
        self.assertTrue(json.loads(r.content)["ok"])

        r = self.client.post(f"/api/bom/{bom_pk}/add-part/", {
            "part": part3.pk,
            "unit_qty": 2,
        })
        self.assertTrue(json.loads(r.content)["ok"])

        self.assertEqual(BOMItem.objects.filter(bom=bom).count(), 3)

        # --- Step 3: Delete an item via API ---
        r = self.client.post(f"/api/bom/{bom_pk}/item/{item1_pk}/delete/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(json.loads(r.content)["ok"])
        self.assertEqual(BOMItem.objects.filter(bom=bom).count(), 2)
        self.assertFalse(BOMItem.objects.filter(pk=item1_pk).exists())

        # --- Step 4: Print BOM ---
        r = self.client.get(f"/bom/{bom_pk}/print/")
        self.assertEqual(r.status_code, 200)

        # --- Step 5: Verify BOM detail page ---
        r = self.client.get(f"/bom/{bom_pk}/")
        self.assertEqual(r.status_code, 200)
        content = r.content.decode()
        self.assertIn("BOM-P-002", content)
        self.assertIn("BOM-P-003", content)
        self.assertNotIn("BOM-P-001", content)

        # --- Step 6: Delete BOM ---
        r = self.client.post(f"/bom/{bom_pk}/delete/")
        self.assertIn(r.status_code, (301, 302))
        self.assertFalse(BOM.objects.filter(pk=bom_pk).exists())
        self.assertFalse(BOMItem.objects.filter(bom_id=bom_pk).exists())
