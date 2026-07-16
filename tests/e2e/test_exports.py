"""
Phase 8 — Print/Export/Download Actions
Test CSV template downloads, print views, invoice print side effects,
and empty data export edge cases.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")

from django.test import TestCase

from tests.e2e.factories import *  # noqa: F403, F401


# ═══════════════════════════════════════════════════════════════════════════
# 1. CSV template downloads
# ═══════════════════════════════════════════════════════════════════════════


class CSVTemplateTests(TestCase):
    """Assert CSV template endpoints return proper CSV responses."""

    def test_parts_csv_template_basic(self):
        response = self.client.get("/parts/csv-template/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.get("Content-Type", ""))
        content = response.content.decode()
        self.assertTrue(len(content) > 0)
        lines = content.strip().split("\n")
        self.assertGreaterEqual(len(lines), 1)

    def test_parts_csv_template_with_category(self):
        PartCategoryFactory(name="Brushes")
        response = self.client.get("/parts/csv-template/?category=Brushes")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.get("Content-Type", ""))
        content = response.content.decode()
        self.assertTrue(len(content) > 0)

    def test_units_csv_template_basic(self):
        response = self.client.get("/units/csv-template/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.get("Content-Type", ""))
        content = response.content.decode()
        self.assertTrue(len(content) > 0)
        lines = content.strip().split("\n")
        self.assertGreaterEqual(len(lines), 1)

    def test_units_csv_template_with_type(self):
        UnitTypeCategoryFactory(name="Starters")
        response = self.client.get("/units/csv-template/?type=Starters")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.get("Content-Type", ""))


# ═══════════════════════════════════════════════════════════════════════════
# 2. Print views (HTML for printing)
# ═══════════════════════════════════════════════════════════════════════════


class PrintViewTests(TestCase):
    """Test print-oriented views return 200 with expected content."""

    @classmethod
    def setUpTestData(cls):
        cls.company = CompanySettingsFactory()
        cls.part = PartFactory()
        cls.unit = UnitFactory()
        cls.bom = BOMFactory()
        cls.bom_item = BOMItemFactory(bom=cls.bom, part=cls.part)
        cls.customer = CustomerFactory()
        cls.invoice1 = InvoiceFactory(customer=cls.customer)
        cls.invoice2 = InvoiceFactory(customer=cls.customer)
        cls.inv_item = InvoiceItemFactory(invoice=cls.invoice1, part=cls.part)
        cls.vendor = VendorFactory()

    def test_parts_print_view(self):
        response = self.client.get("/parts/?print=1")
        self.assertEqual(response.status_code, 200)

    def test_bom_print(self):
        url = f"/bom/{self.bom.pk}/print/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(self.bom_item.part.part_number, content)

    def test_bom_print_all(self):
        url = f"/bom/{self.bom.pk}/print/?all=1"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_bom_print_selected_items(self):
        url = f"/bom/{self.bom.pk}/print/?items={self.bom_item.pk}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_invoice_print(self):
        url = f"/invoicing/invoice/{self.invoice1.pk}/print/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(self.company.company_name, content)

    def test_invoice_bulk_print(self):
        url = f"/invoicing/invoices/bulk-print/?ids={self.invoice1.pk},{self.invoice2.pk}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_customers_print(self):
        response = self.client.get("/invoicing/customers/?print=1")
        self.assertEqual(response.status_code, 200)

    def test_inventory_print(self):
        response = self.client.get("/inventory/?print=1")
        self.assertEqual(response.status_code, 200)

    def test_vendors_print(self):
        response = self.client.get("/inventory/vendors/?print=1")
        self.assertEqual(response.status_code, 200)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Invoice print side effect — DRAFT → SENT
# ═══════════════════════════════════════════════════════════════════════════


class InvoicePrintSideEffectTests(TestCase):
    """Printing a DRAFT invoice should auto-change status to SENT."""

    @classmethod
    def setUpTestData(cls):
        cls.company = CompanySettingsFactory()

    def test_printing_draft_invoice_changes_status_to_sent(self):
        invoice = InvoiceFactory(status="DRAFT")
        url = f"/invoicing/invoice/{invoice.pk}/print/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        from invoicing.models import Invoice
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.SENT)

    def test_printing_sent_invoice_stays_sent(self):
        invoice = InvoiceFactory(status="SENT")
        url = f"/invoicing/invoice/{invoice.pk}/print/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        from invoicing.models import Invoice
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.SENT)

    def test_printing_paid_invoice_stays_paid(self):
        invoice = InvoiceFactory(status="PAID")
        url = f"/invoicing/invoice/{invoice.pk}/print/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        from invoicing.models import Invoice
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Empty data exports — graceful handling
# ═══════════════════════════════════════════════════════════════════════════


class EmptyDataExportTests(TestCase):
    """Print/export with no data should still return 200."""

    @classmethod
    def setUpTestData(cls):
        cls.company = CompanySettingsFactory()

    def test_bom_print_no_items(self):
        bom = BOMFactory()
        url = f"/bom/{bom.pk}/print/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_invoice_list_print_no_invoices(self):
        response = self.client.get("/invoicing/?print=1")
        self.assertEqual(response.status_code, 200)

    def test_csv_template_no_categories(self):
        response = self.client.get("/parts/csv-template/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.get("Content-Type", ""))

    def test_customer_list_print_empty(self):
        response = self.client.get("/invoicing/customers/?print=1")
        self.assertEqual(response.status_code, 200)

    def test_inventory_print_empty(self):
        response = self.client.get("/inventory/?print=1")
        self.assertEqual(response.status_code, 200)

    def test_vendor_print_empty(self):
        response = self.client.get("/inventory/vendors/?print=1")
        self.assertEqual(response.status_code, 200)
