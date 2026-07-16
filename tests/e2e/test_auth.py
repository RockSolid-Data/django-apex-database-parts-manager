"""
Phase 6 — Auth & Permissions Tests
Desktop app with NO authentication. Verify:
- All major URLs accessible without login
- Admin still protected
- CSRF protection enforced on POST forms
- POST-only views reject GET properly
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")

from django.test import TestCase, override_settings

from tests.e2e.factories import *  # noqa: F403, F401


# ═══════════════════════════════════════════════════════════════════════════
# 1. No login required — major URLs accessible anonymously
# ═══════════════════════════════════════════════════════════════════════════


class NoLoginRequiredTests(TestCase):
    """Assert every major URL is accessible without login."""

    @classmethod
    def setUpTestData(cls):
        cls.part = PartFactory()
        cls.unit = UnitFactory()
        cls.app = ApplicationFactory()
        cls.bom = BOMFactory()
        cls.customer = CustomerFactory()
        cls.company = CompanySettingsFactory()
        cls.invoice = InvoiceFactory(customer=cls.customer)
        cls.vendor = VendorFactory()
        cls.backup_settings = BackupSettingsFactory()

    def test_home_accessible(self):
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_parts_list_accessible(self):
        self.assertEqual(self.client.get("/parts/").status_code, 200)

    def test_part_detail_accessible(self):
        self.assertEqual(self.client.get(f"/parts/{self.part.pk}/").status_code, 200)

    def test_units_list_accessible(self):
        self.assertEqual(self.client.get("/units/").status_code, 200)

    def test_unit_detail_accessible(self):
        self.assertEqual(self.client.get(f"/units/{self.unit.pk}/").status_code, 200)

    def test_applications_list_accessible(self):
        self.assertEqual(self.client.get("/applications/").status_code, 200)

    def test_application_detail_accessible(self):
        self.assertEqual(self.client.get(f"/applications/{self.app.pk}/").status_code, 200)

    def test_bom_list_accessible(self):
        self.assertEqual(self.client.get("/bom/").status_code, 200)

    def test_invoicing_list_accessible(self):
        self.assertEqual(self.client.get("/invoicing/").status_code, 200)

    def test_invoice_detail_accessible(self):
        self.assertEqual(self.client.get(f"/invoicing/invoice/{self.invoice.pk}/").status_code, 200)

    def test_customers_list_accessible(self):
        self.assertEqual(self.client.get("/invoicing/customers/").status_code, 200)

    def test_inventory_list_accessible(self):
        self.assertEqual(self.client.get("/inventory/").status_code, 200)

    def test_vendor_list_accessible(self):
        self.assertEqual(self.client.get("/inventory/vendors/").status_code, 200)

    def test_backup_settings_accessible(self):
        self.assertEqual(self.client.get("/backup/").status_code, 200)

    def test_invoice_create_form_accessible(self):
        self.assertEqual(self.client.get("/invoicing/invoice/new/").status_code, 200)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Admin access protected
# ═══════════════════════════════════════════════════════════════════════════


class AdminProtectedTests(TestCase):
    """Django admin IS protected and requires login."""

    def test_admin_redirects_to_login(self):
        response = self.client.get("/admin/", follow=False)
        self.assertIn(response.status_code, [301, 302])
        location = response.get("Location", "")
        self.assertIn("login", location)

    def test_admin_login_page_exists(self):
        response = self.client.get("/admin/login/")
        self.assertEqual(response.status_code, 200)


# ═══════════════════════════════════════════════════════════════════════════
# 3. CSRF protection — POST without token → 403
# ═══════════════════════════════════════════════════════════════════════════


@override_settings(CSRF_COOKIE_HTTPONLY=False)
class CSRFProtectionTests(TestCase):
    """POST requests without CSRF token must be rejected (403)."""

    @classmethod
    def setUpTestData(cls):
        cls.part = PartFactory()
        cls.unit = UnitFactory()
        cls.app = ApplicationFactory()
        cls.customer = CustomerFactory()
        cls.company = CompanySettingsFactory()
        cls.invoice = InvoiceFactory(customer=cls.customer)
        cls.backup_settings = BackupSettingsFactory()

    def _post_no_csrf(self, url, data=None):
        """POST without the CSRF middleware token (enforce_csrf_checks=True)."""
        client = self.client_class(enforce_csrf_checks=True)
        return client.post(url, data=data or {})

    def test_csrf_application_create(self):
        response = self._post_no_csrf("/applications/add/", {"name": "Test"})
        self.assertEqual(response.status_code, 403)

    def test_csrf_part_create(self):
        response = self._post_no_csrf("/parts/add/", {"part_number": "TEST-001"})
        self.assertEqual(response.status_code, 403)

    def test_csrf_invoice_create(self):
        response = self._post_no_csrf("/invoicing/invoice/new/", {"customer": self.customer.pk})
        self.assertEqual(response.status_code, 403)

    def test_csrf_customer_create(self):
        response = self._post_no_csrf("/invoicing/customers/add/", {"name": "Test"})
        self.assertEqual(response.status_code, 403)

    def test_csrf_backup_now(self):
        response = self._post_no_csrf("/backup/now/")
        self.assertEqual(response.status_code, 403)


# ═══════════════════════════════════════════════════════════════════════════
# 4. POST-only enforcement — GET returns redirect or 405
# ═══════════════════════════════════════════════════════════════════════════


class PostOnlyEnforcementTests(TestCase):
    """Views that only accept POST should return 405 or redirect on GET."""

    @classmethod
    def setUpTestData(cls):
        cls.app = ApplicationFactory()
        cls.unit = UnitFactory()
        cls.app_unit = ApplicationUnitFactory(application=cls.app, unit=cls.unit)
        cls.company = CompanySettingsFactory()
        cls.invoice = InvoiceFactory()
        cls.backup_settings = BackupSettingsFactory()

    def test_unlink_unit_get_returns_405(self):
        url = f"/applications/{self.app.pk}/unlink-unit/{self.unit.pk}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_application_delete_get_not_destructive(self):
        """GET on delete page should show confirmation or redirect, NOT delete."""
        app = ApplicationFactory()
        url = f"/applications/{app.pk}/delete/"
        response = self.client.get(url)
        self.assertIn(response.status_code, [200, 301, 302])
        from catalog.models import Application
        self.assertTrue(Application.objects.filter(pk=app.pk).exists())

    def test_backup_now_get_redirects(self):
        response = self.client.get("/backup/now/")
        self.assertEqual(response.status_code, 302)

    def test_backup_restore_get_redirects(self):
        response = self.client.get("/backup/restore/")
        self.assertEqual(response.status_code, 302)

    def test_invoice_cancel_get_redirects(self):
        url = f"/invoicing/invoice/{self.invoice.pk}/cancel/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_invoice_delete_get_redirects(self):
        url = f"/invoicing/invoice/{self.invoice.pk}/delete/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
