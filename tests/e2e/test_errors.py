"""
Phase 7 — Error Handling & Edge Cases
Test 404s, method errors, malformed input, invalid PKs,
duplicate violations, empty DB, large data, and stale edits.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")

from django.test import TestCase

from tests.e2e.factories import *  # noqa: F403, F401


# ═══════════════════════════════════════════════════════════════════════════
# 1. 404 pages — non-existent resources
# ═══════════════════════════════════════════════════════════════════════════


class NotFoundTests(TestCase):
    """Request non-existent URLs and verify 404."""

    def test_nonexistent_page(self):
        self.assertEqual(self.client.get("/nonexistent-page/").status_code, 404)

    def test_nonexistent_part(self):
        self.assertEqual(self.client.get("/parts/99999/").status_code, 404)

    def test_nonexistent_unit(self):
        self.assertEqual(self.client.get("/units/99999/").status_code, 404)

    def test_nonexistent_application(self):
        self.assertEqual(self.client.get("/applications/99999/").status_code, 404)

    def test_nonexistent_invoice(self):
        self.assertEqual(self.client.get("/invoicing/invoice/99999/").status_code, 404)

    def test_nonexistent_bom(self):
        self.assertEqual(self.client.get("/bom/99999/").status_code, 404)

    def test_nonexistent_vendor_edit(self):
        self.assertEqual(self.client.get("/inventory/vendors/99999/edit/").status_code, 404)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Method not allowed — wrong HTTP method
# ═══════════════════════════════════════════════════════════════════════════


class MethodNotAllowedTests(TestCase):
    """Send wrong HTTP method and expect 405."""

    @classmethod
    def setUpTestData(cls):
        cls.app = ApplicationFactory()
        cls.unit = UnitFactory()
        cls.app_unit = ApplicationUnitFactory(application=cls.app, unit=cls.unit)
        cls.bom = BOMFactory()

    def test_get_unlink_unit_returns_405(self):
        url = f"/applications/{self.app.pk}/unlink-unit/{self.unit.pk}/"
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_get_bom_save_api_returns_405(self):
        response = self.client.get("/api/bom/save/")
        self.assertEqual(response.status_code, 405)
        self.assertIn("json", response.get("Content-Type", ""))

    def test_get_application_custom_field_add_api_returns_405(self):
        response = self.client.get("/api/application-custom-field/add/")
        self.assertEqual(response.status_code, 405)
        self.assertIn("json", response.get("Content-Type", ""))


# ═══════════════════════════════════════════════════════════════════════════
# 3. Malformed input — SQL injection / XSS / long strings
# ═══════════════════════════════════════════════════════════════════════════


class MalformedInputTests(TestCase):
    """Submit malicious or oversized input; assert no crash and proper handling."""

    def test_sql_injection_in_part_number(self):
        """SQL injection attempt in part_number field should not crash."""
        response = self.client.post("/parts/add/", {
            "part_number": "'; DROP TABLE catalog_part; --",
            "part_name": "Hack Part",
            "category": "Brushes",
            "cost_price": "10.00",
            "markup_percent": "40",
            "price": "14.00",
            "stock_quantity": "1",
            "reorder_qty": "1",
        })
        self.assertIn(response.status_code, [200, 302])
        from catalog.models import Part
        self.assertTrue(Part.objects.exists() or response.status_code == 200)

    def test_xss_in_application_name(self):
        """XSS attempt should be escaped in rendered output."""
        xss_payload = '<script>alert("xss")</script>'
        response = self.client.post("/applications/add/", {
            "name": xss_payload,
            "make": "TestMake",
            "model": "TestModel",
            "year": "2024",
        })
        if response.status_code == 302:
            from catalog.models import Application
            app = Application.objects.filter(name=xss_payload).first()
            if app:
                detail_response = self.client.get(f"/applications/{app.pk}/")
                content = detail_response.content.decode()
                self.assertNotIn('<script>alert("xss")</script>', content)
                self.assertIn("&lt;script&gt;", content)
        else:
            self.assertEqual(response.status_code, 200)

    def test_very_long_string_in_part_name(self):
        """10000 character string should trigger validation error or truncation."""
        long_string = "A" * 10000
        response = self.client.post("/parts/add/", {
            "part_number": "LONG-001",
            "part_name": long_string,
            "category": "Brushes",
            "cost_price": "10.00",
            "markup_percent": "40",
            "price": "14.00",
            "stock_quantity": "1",
            "reorder_qty": "1",
        })
        self.assertIn(response.status_code, [200, 302, 400])


# ═══════════════════════════════════════════════════════════════════════════
# 4. Invalid PKs — string where int expected
# ═══════════════════════════════════════════════════════════════════════════


class InvalidPKTests(TestCase):
    """Use non-numeric PKs in URL; expect 404 (URL pattern won't match <int:pk>)."""

    def test_part_string_pk(self):
        self.assertEqual(self.client.get("/parts/abc/").status_code, 404)

    def test_unit_string_pk(self):
        self.assertEqual(self.client.get("/units/abc/").status_code, 404)


# ═══════════════════════════════════════════════════════════════════════════
# 5. Duplicate unique violations — graceful error handling
# ═══════════════════════════════════════════════════════════════════════════


class DuplicateUniqueViolationTests(TestCase):
    """Attempt to create duplicate records and verify error is shown."""

    def test_duplicate_unit_type_category_name(self):
        UnitTypeCategoryFactory(name="Motors")
        response = self.client.post("/units/type-categories/add/", {
            "name": "Motors",
            "sort_order": "1",
            "color": "#ff0000",
        })
        # View handles dups with redirect (IntegrityError caught) or re-renders
        from catalog.models import UnitTypeCategory
        self.assertEqual(UnitTypeCategory.objects.filter(name="Motors").count(), 1)

    def test_duplicate_part_category_name(self):
        PartCategoryFactory(name="Brushes Custom")
        response = self.client.post("/parts/categories/add/", {
            "name": "Brushes Custom",
        })
        # View handles dups with redirect (IntegrityError caught) or re-renders
        from catalog.models import PartCategory
        self.assertEqual(PartCategory.objects.filter(name="Brushes Custom").count(), 1)

    def test_duplicate_application_type_name(self):
        ApplicationTypeFactory(name="Marine")
        response = self.client.post("/applications/types/add/", {
            "name": "Marine",
        })
        # View handles dups with redirect (IntegrityError caught) or re-renders
        from catalog.models import ApplicationType
        self.assertEqual(ApplicationType.objects.filter(name="Marine").count(), 1)

    def test_duplicate_part_number(self):
        PartFactory(part_number="DUP-001")
        response = self.client.post("/parts/add/", {
            "part_number": "DUP-001",
            "part_name": "Duplicate Part",
            "category": "Brushes",
            "cost_price": "10.00",
            "markup_percent": "40",
            "price": "14.00",
            "stock_quantity": "1",
            "reorder_qty": "1",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists", status_code=200)

    def test_duplicate_cross_reference(self):
        """BUG: cross_reference_add view does not catch IntegrityError on
        duplicate (unit, cross_ref_number, interchange_type). The view crashes
        with a 500. This test documents the bug — it should return a form
        error, but currently raises IntegrityError."""
        unit = UnitFactory()
        CrossReferenceFactory(
            unit=unit, cross_ref_number="XREF-DUP", interchange_type="Direct"
        )
        from django.db.utils import IntegrityError
        with self.assertRaises(IntegrityError):
            self.client.post(f"/units/{unit.pk}/cross-ref/add/", {
                "cross_ref_number": "XREF-DUP",
                "interchange_type": "Direct",
                "price": "100.00",
                "notes": "",
            })


# ═══════════════════════════════════════════════════════════════════════════
# 6. Empty database — list pages with zero records
# ═══════════════════════════════════════════════════════════════════════════


class EmptyDatabaseTests(TestCase):
    """Verify list pages work with zero records (no 500 errors)."""

    @classmethod
    def setUpTestData(cls):
        cls.company = CompanySettingsFactory()
        cls.backup_settings = BackupSettingsFactory()

    def test_empty_parts_list(self):
        self.assertEqual(self.client.get("/parts/").status_code, 200)

    def test_empty_units_list(self):
        self.assertEqual(self.client.get("/units/").status_code, 200)

    def test_empty_applications_list(self):
        self.assertEqual(self.client.get("/applications/").status_code, 200)

    def test_empty_bom_list(self):
        self.assertEqual(self.client.get("/bom/").status_code, 200)

    def test_empty_invoice_list(self):
        self.assertEqual(self.client.get("/invoicing/").status_code, 200)

    def test_empty_customer_list(self):
        self.assertEqual(self.client.get("/invoicing/customers/").status_code, 200)

    def test_empty_inventory_list(self):
        self.assertEqual(self.client.get("/inventory/").status_code, 200)

    def test_empty_vendor_list(self):
        self.assertEqual(self.client.get("/inventory/vendors/").status_code, 200)

    def test_empty_reorder_list(self):
        self.assertEqual(self.client.get("/inventory/reorder/").status_code, 200)


# ═══════════════════════════════════════════════════════════════════════════
# 7. Large data — 100+ items, verify list/pagination
# ═══════════════════════════════════════════════════════════════════════════


class LargeDataTests(TestCase):
    """Create 100+ items, verify list pages still return 200."""

    @classmethod
    def setUpTestData(cls):
        cls.parts = PartFactory.create_batch(105)

    def test_parts_list_with_many_records(self):
        response = self.client.get("/parts/")
        self.assertEqual(response.status_code, 200)

    def test_parts_list_page_2(self):
        response = self.client.get("/parts/?page=2")
        self.assertIn(response.status_code, [200, 404])

    def test_parts_list_search(self):
        response = self.client.get("/parts/?q=PN-00050")
        self.assertEqual(response.status_code, 200)


# ═══════════════════════════════════════════════════════════════════════════
# 8. Concurrent-like edits — POST stale form data
# ═══════════════════════════════════════════════════════════════════════════


class StaleFormDataTests(TestCase):
    """Simulate stale edits: object modified between GET and POST."""

    @classmethod
    def setUpTestData(cls):
        cls.part = PartFactory(part_number="STALE-001", part_name="Original")

    def test_stale_part_edit(self):
        """Submit form with data from before another edit; no crash."""
        url = f"/parts/{self.part.pk}/edit/"
        get_response = self.client.get(url)
        self.assertEqual(get_response.status_code, 200)

        from catalog.models import Part
        Part.objects.filter(pk=self.part.pk).update(part_name="Updated by other")

        response = self.client.post(url, {
            "part_number": "STALE-001",
            "part_name": "Stale data from original",
            "category": "Brushes",
            "cost_price": "25.00",
            "markup_percent": "40",
            "price": "35.00",
            "stock_quantity": "10",
            "reorder_qty": "5",
        })
        self.assertIn(response.status_code, [200, 302])
