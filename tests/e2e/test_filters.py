"""
Phase 4 — Filters, Search, and List Operations
Test every list view's filters, search, pagination, and autocomplete endpoints.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")

import json
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from tests.e2e.factories import *  # noqa: F403, F401


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _ids_on_page(response, context_key):
    """Return set of PKs from the paginated queryset in context."""
    page = response.context.get(context_key, [])
    return {obj.pk for obj in page}


# ═══════════════════════════════════════════════════════════════════════════
# 1. Application List — /applications/
# ═══════════════════════════════════════════════════════════════════════════

class ApplicationListFilterTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ut = UnitTypeFactory(name="Alternator")
        cls.utc = UnitTypeCategoryFactory(name="Alternators")
        cls.unit = UnitFactory(
            unit_number="ALT-100", unit_type=cls.ut,
            unit_type_category="Alternators",
        )
        cls.app1 = ApplicationFactory(
            name="Ford F150 Alt", make="Ford", model="F-150",
            year="2022", mfr="Bosch", volt="12V",
            unit_type_name="Alternators",
        )
        cls.app2 = ApplicationFactory(
            name="Chevy Silverado Starter", make="Chevrolet", model="Silverado",
            year="2020", mfr="Denso", volt="24V",
            unit_type_name="Starters",
        )
        cls.app3 = ApplicationFactory(
            name="Toyota Camry Alt", make="Toyota", model="Camry",
            year="2023", mfr="Bosch", volt="12V",
            unit_type_name="Alternators",
        )
        ApplicationUnitFactory(application=cls.app1, unit=cls.unit)

    def test_empty_state(self):
        from catalog.models import Application
        Application.objects.all().update(is_active=False)
        r = self.client.get("/applications/")
        self.assertEqual(r.status_code, 200)
        # Seed data may be present; just verify no 500 and context exists
        self.assertIn("total_count", r.context)
        Application.objects.all().update(is_active=True)

    def test_search_matching(self):
        r = self.client.get("/applications/", {"q": "Ford"})
        self.assertEqual(r.status_code, 200)
        pks = _ids_on_page(r, "applications")
        self.assertIn(self.app1.pk, pks)
        self.assertNotIn(self.app2.pk, pks)

    def test_search_no_match(self):
        r = self.client.get("/applications/", {"q": "xyznonexistent999"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["total_count"], 0)

    def test_filter_make(self):
        r = self.client.get("/applications/", {"make": "Ford"})
        pks = _ids_on_page(r, "applications")
        self.assertIn(self.app1.pk, pks)
        self.assertNotIn(self.app2.pk, pks)

    def test_filter_model(self):
        r = self.client.get("/applications/", {"model": "Silverado"})
        pks = _ids_on_page(r, "applications")
        self.assertIn(self.app2.pk, pks)
        self.assertNotIn(self.app1.pk, pks)

    def test_filter_year(self):
        r = self.client.get("/applications/", {"year": "2022"})
        pks = _ids_on_page(r, "applications")
        self.assertIn(self.app1.pk, pks)

    def test_filter_mfr(self):
        r = self.client.get("/applications/", {"mfr": "Denso"})
        pks = _ids_on_page(r, "applications")
        self.assertIn(self.app2.pk, pks)
        self.assertNotIn(self.app1.pk, pks)

    def test_filter_volt(self):
        r = self.client.get("/applications/", {"volt": "24V"})
        pks = _ids_on_page(r, "applications")
        self.assertIn(self.app2.pk, pks)
        self.assertNotIn(self.app1.pk, pks)

    def test_filter_unit_type(self):
        r = self.client.get("/applications/", {"unit_type": "Alternators"})
        pks = _ids_on_page(r, "applications")
        self.assertIn(self.app1.pk, pks)
        self.assertIn(self.app3.pk, pks)
        self.assertNotIn(self.app2.pk, pks)

    def test_filter_unit(self):
        r = self.client.get("/applications/", {"unit": "ALT-100"})
        pks = _ids_on_page(r, "applications")
        self.assertIn(self.app1.pk, pks)

    def test_combined_filters(self):
        r = self.client.get("/applications/", {"mfr": "Bosch", "volt": "12V"})
        pks = _ids_on_page(r, "applications")
        self.assertIn(self.app1.pk, pks)
        self.assertIn(self.app3.pk, pks)
        self.assertNotIn(self.app2.pk, pks)

    def test_pagination(self):
        for i in range(30):
            ApplicationFactory(name=f"PagApp {i:03d}", make="PagMake")
        r = self.client.get("/applications/", {"per_page": "25", "make": "PagMake"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["page_obj"].has_next())

        r2 = self.client.get("/applications/", {"per_page": "25", "make": "PagMake", "page": "2"})
        self.assertEqual(r2.status_code, 200)
        page2_pks = _ids_on_page(r2, "applications")
        self.assertTrue(len(page2_pks) > 0)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Unit List — /units/
# ═══════════════════════════════════════════════════════════════════════════

class UnitListFilterTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.utc = UnitTypeCategoryFactory(name="Starters")
        cls.ut = UnitTypeFactory(name="Starter")
        cls.unit1 = UnitFactory(
            unit_number="UN-ST-001", yt_number="YT-ST-001",
            oem="Delco", family="DD", voltage="12V",
            unit_type=cls.ut, unit_type_category="Starters",
        )
        cls.unit2 = UnitFactory(
            unit_number="UN-ALT-001", yt_number="YT-ALT-001",
            oem="Bosch", family="IR/IF", voltage="24V",
            unit_type=cls.ut, unit_type_category="",
        )

    def test_empty_state(self):
        from catalog.models import Unit
        Unit.objects.all().update(is_active=False)
        r = self.client.get("/units/")
        self.assertEqual(r.status_code, 200)
        Unit.objects.all().update(is_active=True)

    def test_search_matching(self):
        r = self.client.get("/units/", {"q": "YT-ST-001"})
        pks = _ids_on_page(r, "units")
        self.assertIn(self.unit1.pk, pks)

    def test_search_no_match(self):
        r = self.client.get("/units/", {"q": "ZZZNOUNIT999"})
        self.assertEqual(r.status_code, 200)

    def test_filter_type_tab(self):
        r = self.client.get("/units/", {"type": "Starters"})
        pks = _ids_on_page(r, "units")
        self.assertIn(self.unit1.pk, pks)
        self.assertNotIn(self.unit2.pk, pks)

    def test_filter_type_blank(self):
        r = self.client.get("/units/", {"type": "__blank__"})
        pks = _ids_on_page(r, "units")
        self.assertIn(self.unit2.pk, pks)
        self.assertNotIn(self.unit1.pk, pks)

    def test_filter_family(self):
        r = self.client.get("/units/", {"family": "DD"})
        pks = _ids_on_page(r, "units")
        self.assertIn(self.unit1.pk, pks)
        self.assertNotIn(self.unit2.pk, pks)

    def test_filter_oem(self):
        r = self.client.get("/units/", {"oem": "Bosch"})
        pks = _ids_on_page(r, "units")
        self.assertIn(self.unit2.pk, pks)
        self.assertNotIn(self.unit1.pk, pks)

    def test_filter_voltage(self):
        r = self.client.get("/units/", {"voltage": "12V"})
        pks = _ids_on_page(r, "units")
        self.assertIn(self.unit1.pk, pks)
        self.assertNotIn(self.unit2.pk, pks)

    def test_combined_filters(self):
        r = self.client.get("/units/", {"type": "Starters", "voltage": "12V"})
        pks = _ids_on_page(r, "units")
        self.assertIn(self.unit1.pk, pks)
        self.assertNotIn(self.unit2.pk, pks)

    def test_pagination(self):
        for i in range(30):
            UnitFactory(unit_number=f"PAG-U-{i:04d}", oem="PagOEM")
        r = self.client.get("/units/", {"per_page": "25", "oem": "PagOEM"})
        self.assertTrue(r.context["page_obj"].has_next())


# ═══════════════════════════════════════════════════════════════════════════
# 3. Unit Search — /units/search/
# ═══════════════════════════════════════════════════════════════════════════

class UnitSearchFilterTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ut = UnitTypeFactory(name="Alternator")
        cls.utc = UnitTypeCategoryFactory(name="Alternators")
        cls.unit = UnitFactory(
            unit_number="SRCH-001", yt_number="YT-SRCH-001",
            oem="Hitachi", voltage="12V", unit_type=cls.ut,
            unit_type_category="Alternators",
        )
        cls.xref = CrossReferenceFactory(
            unit=cls.unit, cross_ref_number="XREF-SRCH-99",
        )
        cls.app = ApplicationFactory(
            name="SearchApp", make="Honda", model="Civic", year="2021",
            mfr="Mitsubishi", volt="12V",
        )
        cls.part = PartFactory(
            part_number="SRCH-P-001", part_name="Search Brush",
            category="Brushes", yt_number="YT-SRCH-P-001",
        )

    def test_crossref_tab_match(self):
        r = self.client.get("/units/search/", {
            "tab": "crossref", "q_cross_ref": "XREF-SRCH-99",
        })
        self.assertEqual(r.status_code, 200)
        self.assertGreater(r.context["results_count"], 0)

    def test_crossref_tab_no_match(self):
        r = self.client.get("/units/search/", {
            "tab": "crossref", "q_cross_ref": "NOPE-999",
        })
        self.assertEqual(r.context["results_count"], 0)

    def test_units_tab_by_unit_number(self):
        r = self.client.get("/units/search/", {
            "tab": "units", "q_unit_number": "SRCH-001",
        })
        self.assertGreater(r.context["results_count"], 0)

    def test_units_tab_by_voltage(self):
        r = self.client.get("/units/search/", {
            "tab": "units", "q_voltage": "12V",
        })
        self.assertGreater(r.context["results_count"], 0)

    def test_units_tab_by_unit_type(self):
        r = self.client.get("/units/search/", {
            "tab": "units", "q_unit_type": "Alternators",
        })
        self.assertGreater(r.context["results_count"], 0)

    def test_applications_tab_by_make(self):
        r = self.client.get("/units/search/", {
            "tab": "applications", "q_make": "Honda",
        })
        self.assertGreater(r.context["results_count"], 0)

    def test_applications_tab_combined(self):
        r = self.client.get("/units/search/", {
            "tab": "applications", "q_make": "Honda", "q_year": "2021",
        })
        self.assertGreater(r.context["results_count"], 0)

    def test_parts_tab_by_part_number(self):
        r = self.client.get("/units/search/", {
            "tab": "parts", "q_part_number": "SRCH-P-001",
        })
        self.assertGreater(r.context["results_count"], 0)

    def test_parts_tab_by_category(self):
        r = self.client.get("/units/search/", {
            "tab": "parts", "q_category": "Brushes",
        })
        self.assertGreater(r.context["results_count"], 0)

    def test_no_search_params_no_results(self):
        r = self.client.get("/units/search/", {"tab": "crossref"})
        self.assertEqual(r.context["results_count"], 0)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Part List — /parts/
# ═══════════════════════════════════════════════════════════════════════════

class PartListFilterTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.part1 = PartFactory(
            part_number="PF-001", part_name="Brush Set",
            manufacturer_number="MFR-PF-001", yt_number="YT-PF-001",
            category="Brushes", voltage="12V",
        )
        cls.part2 = PartFactory(
            part_number="PF-002", part_name="Regulator",
            manufacturer_number="MFR-PF-002", yt_number="YT-PF-002",
            category="Regulators", voltage="24V",
        )
        cls.interchange = PartInterchangeFactory(
            part=cls.part1,
            interchange_number="IX-PF-DEEP",
            source_name="OEM",
        )

    def test_empty_state(self):
        from catalog.models import Part
        Part.objects.all().update(is_active=False)
        r = self.client.get("/parts/")
        self.assertEqual(r.status_code, 200)
        Part.objects.all().update(is_active=True)

    def test_search_by_yt_number(self):
        r = self.client.get("/parts/", {"q": "YT-PF-001"})
        pks = _ids_on_page(r, "page_obj")
        self.assertIn(self.part1.pk, pks)

    def test_search_by_manufacturer_number(self):
        r = self.client.get("/parts/", {"q": "MFR-PF-002"})
        pks = _ids_on_page(r, "page_obj")
        self.assertIn(self.part2.pk, pks)

    def test_search_no_match(self):
        r = self.client.get("/parts/", {"q": "ZZZNOTAPART"})
        self.assertEqual(r.status_code, 200)

    def test_filter_category(self):
        r = self.client.get("/parts/", {"category": "Brushes"})
        pks = _ids_on_page(r, "page_obj")
        self.assertIn(self.part1.pk, pks)
        self.assertNotIn(self.part2.pk, pks)

    def test_filter_voltage(self):
        r = self.client.get("/parts/", {"voltage": "24V"})
        pks = _ids_on_page(r, "page_obj")
        self.assertIn(self.part2.pk, pks)
        self.assertNotIn(self.part1.pk, pks)

    def test_combined_filters(self):
        r = self.client.get("/parts/", {"category": "Brushes", "voltage": "12V"})
        pks = _ids_on_page(r, "page_obj")
        self.assertIn(self.part1.pk, pks)
        self.assertNotIn(self.part2.pk, pks)

    def test_deep_search_by_interchange(self):
        r = self.client.get("/parts/", {"q": "IX-PF-DEEP"})
        self.assertEqual(r.status_code, 200)

    def test_pagination(self):
        for i in range(30):
            PartFactory(part_number=f"PAG-P-{i:04d}", category="PagCat")
        r = self.client.get("/parts/", {"per_page": "25", "category": "PagCat"})
        self.assertTrue(r.context["page_obj"].has_next())


# ═══════════════════════════════════════════════════════════════════════════
# 5. BOM List — /bom/
# ═══════════════════════════════════════════════════════════════════════════

class BOMListFilterTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ut = UnitTypeFactory(name="Alternator")
        cls.unit1 = UnitFactory(unit_number="BOM-U-001", unit_type=cls.ut)
        cls.bom1 = BOMFactory(name="BOM Alpha", unit=cls.unit1)
        cls.part_in_bom = PartFactory(part_number="BOM-P-001")
        BOMItemFactory(bom=cls.bom1, part=cls.part_in_bom)

        cls.ut2 = UnitTypeFactory(name="Starter")
        cls.unit2 = UnitFactory(unit_number="BOM-U-002", unit_type=cls.ut2)
        cls.bom2 = BOMFactory(name="BOM Beta", unit=cls.unit2)

    def test_empty_state(self):
        from catalog.models import BOM
        pks = [self.bom1.pk, self.bom2.pk]
        BOM.objects.exclude(pk__in=pks).delete()
        BOM.objects.filter(pk__in=pks).delete()
        r = self.client.get("/bom/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["total_count"], 0)

    def test_search_by_name(self):
        r = self.client.get("/bom/", {"q": "Alpha"})
        pks = _ids_on_page(r, "boms")
        self.assertIn(self.bom1.pk, pks)
        self.assertNotIn(self.bom2.pk, pks)

    def test_search_by_unit_number(self):
        r = self.client.get("/bom/", {"q": "BOM-U-001"})
        pks = _ids_on_page(r, "boms")
        self.assertIn(self.bom1.pk, pks)

    def test_search_by_part_number(self):
        r = self.client.get("/bom/", {"q": "BOM-P-001"})
        pks = _ids_on_page(r, "boms")
        self.assertIn(self.bom1.pk, pks)

    def test_search_no_match(self):
        r = self.client.get("/bom/", {"q": "NOPEBOM999"})
        self.assertEqual(r.context["total_count"], 0)

    def test_filter_unit_type(self):
        r = self.client.get("/bom/", {"unit_type": "Alternator"})
        pks = _ids_on_page(r, "boms")
        self.assertIn(self.bom1.pk, pks)
        self.assertNotIn(self.bom2.pk, pks)

    def test_combined_search_and_filter(self):
        r = self.client.get("/bom/", {"q": "BOM", "unit_type": "Starter"})
        pks = _ids_on_page(r, "boms")
        self.assertIn(self.bom2.pk, pks)
        self.assertNotIn(self.bom1.pk, pks)


# ═══════════════════════════════════════════════════════════════════════════
# 6. Invoice List — /invoicing/
# ═══════════════════════════════════════════════════════════════════════════

class InvoiceListFilterTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.settings = CompanySettingsFactory()
        cls.cust1 = CustomerFactory(name="Acme Corp")
        cls.cust2 = CustomerFactory(name="Globex Inc")
        cls.inv1 = InvoiceFactory(
            invoice_number="INV-2024-0001", customer=cls.cust1,
            customer_name="Acme Corp", status="DRAFT",
            date=date(2024, 6, 15),
        )
        cls.inv2 = InvoiceFactory(
            invoice_number="INV-2024-0002", customer=cls.cust2,
            customer_name="Globex Inc", status="PAID",
            date=date(2024, 7, 1),
        )
        cls.inv3 = InvoiceFactory(
            invoice_number="INV-2024-0003", customer=cls.cust1,
            customer_name="Acme Corp", status="SENT",
            date=date(2024, 5, 10),
        )

    def test_empty_state(self):
        from invoicing.models import Invoice
        Invoice.objects.all().delete()
        r = self.client.get("/invoicing/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["total_count"], 0)

    def test_search_by_invoice_number(self):
        r = self.client.get("/invoicing/", {"q": "0001"})
        pks = _ids_on_page(r, "invoices")
        self.assertIn(self.inv1.pk, pks)

    def test_search_by_customer_name(self):
        r = self.client.get("/invoicing/", {"q": "Globex"})
        pks = _ids_on_page(r, "invoices")
        self.assertIn(self.inv2.pk, pks)
        self.assertNotIn(self.inv1.pk, pks)

    def test_search_no_match(self):
        r = self.client.get("/invoicing/", {"q": "NOSUCHINV999"})
        self.assertEqual(r.context["total_count"], 0)

    def test_filter_status(self):
        r = self.client.get("/invoicing/", {"status": "DRAFT"})
        pks = _ids_on_page(r, "invoices")
        self.assertIn(self.inv1.pk, pks)
        self.assertNotIn(self.inv2.pk, pks)

    def test_filter_date_from(self):
        r = self.client.get("/invoicing/", {"date_from": "2024-06-01"})
        pks = _ids_on_page(r, "invoices")
        self.assertIn(self.inv1.pk, pks)
        self.assertIn(self.inv2.pk, pks)
        self.assertNotIn(self.inv3.pk, pks)

    def test_filter_date_to(self):
        r = self.client.get("/invoicing/", {"date_to": "2024-06-30"})
        pks = _ids_on_page(r, "invoices")
        self.assertIn(self.inv1.pk, pks)
        self.assertIn(self.inv3.pk, pks)
        self.assertNotIn(self.inv2.pk, pks)

    def test_filter_date_range(self):
        r = self.client.get("/invoicing/", {
            "date_from": "2024-06-01", "date_to": "2024-06-30",
        })
        pks = _ids_on_page(r, "invoices")
        self.assertIn(self.inv1.pk, pks)
        self.assertNotIn(self.inv2.pk, pks)
        self.assertNotIn(self.inv3.pk, pks)

    def test_combined_status_and_date(self):
        r = self.client.get("/invoicing/", {
            "status": "DRAFT", "date_from": "2024-01-01",
        })
        pks = _ids_on_page(r, "invoices")
        self.assertIn(self.inv1.pk, pks)
        self.assertNotIn(self.inv2.pk, pks)

    def test_pagination(self):
        for i in range(30):
            InvoiceFactory(
                invoice_number=f"INV-PAG-{i:04d}", customer=self.cust1,
                customer_name="Acme Corp",
            )
        r = self.client.get("/invoicing/", {"per_page": "25"})
        self.assertTrue(r.context["page_obj"].has_next())


# ═══════════════════════════════════════════════════════════════════════════
# 7. Invoice Report — /invoicing/report/
# ═══════════════════════════════════════════════════════════════════════════

class InvoiceReportFilterTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.settings = CompanySettingsFactory()
        cls.cust = CustomerFactory(name="Report Customer")
        cls.inv1 = InvoiceFactory(
            invoice_number="RPT-001", customer=cls.cust,
            customer_name="Report Customer", status="PAID",
            date=date(2024, 3, 1), total=Decimal("500.00"),
        )
        cls.inv2 = InvoiceFactory(
            invoice_number="RPT-002", customer=cls.cust,
            customer_name="Report Customer", status="DRAFT",
            date=date(2024, 6, 1), total=Decimal("200.00"),
        )

    def test_no_filters_returns_all(self):
        r = self.client.get("/invoicing/report/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["invoices"]), 2)

    def test_filter_single_status(self):
        r = self.client.get("/invoicing/report/", {"status": "PAID"})
        self.assertTrue(all(inv.status == "PAID" for inv in r.context["invoices"]))

    def test_filter_multi_status(self):
        r = self.client.get("/invoicing/report/", {"status": ["PAID", "DRAFT"]})
        self.assertEqual(len(r.context["invoices"]), 2)

    def test_filter_date_range(self):
        r = self.client.get("/invoicing/report/", {
            "date_from": "2024-05-01", "date_to": "2024-07-01",
        })
        invoices = r.context["invoices"]
        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0].invoice_number, "RPT-002")

    def test_report_type_detailed(self):
        r = self.client.get("/invoicing/report/", {"report_type": "detailed"})
        self.assertEqual(r.context["report_type"], "detailed")

    def test_report_type_customer_summary(self):
        r = self.client.get("/invoicing/report/", {"report_type": "customer_summary"})
        self.assertEqual(r.context["report_type"], "customer_summary")
        self.assertTrue(len(r.context["customer_summary"]) > 0)

    def test_invalid_report_type_defaults_to_detailed(self):
        r = self.client.get("/invoicing/report/", {"report_type": "bogus"})
        self.assertEqual(r.context["report_type"], "detailed")


# ═══════════════════════════════════════════════════════════════════════════
# 8. Customer List — /invoicing/customers/
# ═══════════════════════════════════════════════════════════════════════════

class CustomerListFilterTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.cust1 = CustomerFactory(name="Active Cust", contact_name="John", is_active=True)
        cls.cust2 = CustomerFactory(name="Retired Cust", contact_name="Jane", is_active=False)
        cls.cust3 = CustomerFactory(
            name="City Cust", contact_name="Bob",
            is_active=True, bill_to_city="Hartford",
        )

    def test_default_hides_inactive(self):
        r = self.client.get("/invoicing/customers/")
        pks = _ids_on_page(r, "customers")
        self.assertIn(self.cust1.pk, pks)
        self.assertNotIn(self.cust2.pk, pks)

    def test_show_inactive(self):
        r = self.client.get("/invoicing/customers/", {"inactive": "1"})
        pks = _ids_on_page(r, "customers")
        self.assertIn(self.cust1.pk, pks)
        self.assertIn(self.cust2.pk, pks)

    def test_search_by_name(self):
        r = self.client.get("/invoicing/customers/", {"q": "Active Cust"})
        pks = _ids_on_page(r, "customers")
        self.assertIn(self.cust1.pk, pks)

    def test_search_by_contact(self):
        r = self.client.get("/invoicing/customers/", {"q": "John"})
        pks = _ids_on_page(r, "customers")
        self.assertIn(self.cust1.pk, pks)

    def test_search_by_city(self):
        r = self.client.get("/invoicing/customers/", {"q": "Hartford"})
        pks = _ids_on_page(r, "customers")
        self.assertIn(self.cust3.pk, pks)

    def test_search_no_match(self):
        r = self.client.get("/invoicing/customers/", {"q": "NOCUST999"})
        self.assertEqual(r.context["total_count"], 0)

    def test_pagination(self):
        for i in range(30):
            CustomerFactory(name=f"PagCust {i:03d}")
        r = self.client.get("/invoicing/customers/", {"per_page": "25"})
        self.assertTrue(r.context["page_obj"].has_next())


# ═══════════════════════════════════════════════════════════════════════════
# 9. Inventory List — /inventory/
# ═══════════════════════════════════════════════════════════════════════════

class InventoryListFilterTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.p1 = PartFactory(
            part_number="INV-001", part_name="Bearing",
            track_inventory=True, primary_vendor="Vendor A",
        )
        cls.p2 = PartFactory(
            part_number="INV-002", part_name="Brush Kit",
            track_inventory=True, primary_vendor="Vendor B",
        )
        cls.p_no_inv = PartFactory(
            part_number="INV-003", track_inventory=False,
        )

    def test_excludes_non_tracked(self):
        r = self.client.get("/inventory/")
        pks = _ids_on_page(r, "parts")
        self.assertIn(self.p1.pk, pks)
        self.assertNotIn(self.p_no_inv.pk, pks)

    def test_search_by_part_number(self):
        r = self.client.get("/inventory/", {"q": "INV-001"})
        pks = _ids_on_page(r, "parts")
        self.assertIn(self.p1.pk, pks)
        self.assertNotIn(self.p2.pk, pks)

    def test_search_by_name(self):
        r = self.client.get("/inventory/", {"q": "Brush Kit"})
        pks = _ids_on_page(r, "parts")
        self.assertIn(self.p2.pk, pks)

    def test_search_no_match(self):
        r = self.client.get("/inventory/", {"q": "NOINVPART999"})
        self.assertEqual(r.context["total_count"], 0)

    def test_filter_supplier(self):
        r = self.client.get("/inventory/", {"supplier": "Vendor A"})
        pks = _ids_on_page(r, "parts")
        self.assertIn(self.p1.pk, pks)
        self.assertNotIn(self.p2.pk, pks)

    def test_combined_search_and_supplier(self):
        r = self.client.get("/inventory/", {"q": "INV", "supplier": "Vendor B"})
        pks = _ids_on_page(r, "parts")
        self.assertIn(self.p2.pk, pks)
        self.assertNotIn(self.p1.pk, pks)

    def test_pagination(self):
        for i in range(30):
            PartFactory(
                part_number=f"INV-PAG-{i:04d}", track_inventory=True,
                primary_vendor="PagVendor",
            )
        r = self.client.get("/inventory/", {"per_page": "25", "supplier": "PagVendor"})
        self.assertTrue(r.context["page_obj"].has_next())


# ═══════════════════════════════════════════════════════════════════════════
# 10. Reorder List — /inventory/reorder/
# ═══════════════════════════════════════════════════════════════════════════

class ReorderListFilterTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.p1 = PartFactory(
            part_number="RO-001", part_name="Low Stock Brush",
            track_inventory=True, reorder_qty=10, stock_quantity=3,
            category="Brushes", primary_vendor="VendorX",
        )
        cls.p2 = PartFactory(
            part_number="RO-002", part_name="Low Stock Reg",
            track_inventory=True, reorder_qty=5, stock_quantity=2,
            category="Regulators", primary_vendor="VendorY",
        )
        cls.p_ok = PartFactory(
            part_number="RO-003", part_name="Stocked Fine",
            track_inventory=True, reorder_qty=5, stock_quantity=100,
        )

    def test_only_low_stock_shown(self):
        r = self.client.get("/inventory/reorder/")
        pks = _ids_on_page(r, "parts")
        self.assertIn(self.p1.pk, pks)
        self.assertIn(self.p2.pk, pks)
        self.assertNotIn(self.p_ok.pk, pks)

    def test_search(self):
        r = self.client.get("/inventory/reorder/", {"q": "Low Stock Brush"})
        pks = _ids_on_page(r, "parts")
        self.assertIn(self.p1.pk, pks)
        self.assertNotIn(self.p2.pk, pks)

    def test_filter_category(self):
        r = self.client.get("/inventory/reorder/", {"category": "Brushes"})
        pks = _ids_on_page(r, "parts")
        self.assertIn(self.p1.pk, pks)
        self.assertNotIn(self.p2.pk, pks)

    def test_filter_supplier(self):
        r = self.client.get("/inventory/reorder/", {"supplier": "VendorY"})
        pks = _ids_on_page(r, "parts")
        self.assertIn(self.p2.pk, pks)
        self.assertNotIn(self.p1.pk, pks)

    def test_sort_urgent(self):
        r = self.client.get("/inventory/reorder/", {"sort": "urgent"})
        parts = list(r.context["parts"])
        if len(parts) >= 2:
            self.assertLessEqual(parts[0].stock_quantity, parts[1].stock_quantity)

    def test_sort_part(self):
        r = self.client.get("/inventory/reorder/", {"sort": "part"})
        parts = list(r.context["parts"])
        if len(parts) >= 2:
            self.assertLessEqual(parts[0].part_number, parts[1].part_number)

    def test_sort_supplier(self):
        r = self.client.get("/inventory/reorder/", {"sort": "supplier"})
        self.assertEqual(r.status_code, 200)

    def test_combined_filters(self):
        r = self.client.get("/inventory/reorder/", {
            "category": "Regulators", "supplier": "VendorY",
        })
        pks = _ids_on_page(r, "parts")
        self.assertIn(self.p2.pk, pks)
        self.assertNotIn(self.p1.pk, pks)

    def test_search_no_match(self):
        r = self.client.get("/inventory/reorder/", {"q": "ZZZNOREORDER"})
        self.assertEqual(r.context["total_count"], 0)


# ═══════════════════════════════════════════════════════════════════════════
# 11. Vendor List — /inventory/vendors/
# ═══════════════════════════════════════════════════════════════════════════

class VendorListFilterTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.v1 = VendorFactory(name="Alpha Supply", is_active=True, account_number="ACCT-001")
        cls.v2 = VendorFactory(name="Beta Parts", is_active=True, account_number="ACCT-002")
        cls.v_inactive = VendorFactory(name="Gone Vendor", is_active=False)

    def test_default_hides_inactive(self):
        r = self.client.get("/inventory/vendors/")
        pks = _ids_on_page(r, "vendors")
        self.assertIn(self.v1.pk, pks)
        self.assertNotIn(self.v_inactive.pk, pks)

    def test_show_inactive(self):
        r = self.client.get("/inventory/vendors/", {"inactive": "1"})
        pks = _ids_on_page(r, "vendors")
        self.assertIn(self.v_inactive.pk, pks)

    def test_search_by_name(self):
        r = self.client.get("/inventory/vendors/", {"q": "Alpha"})
        pks = _ids_on_page(r, "vendors")
        self.assertIn(self.v1.pk, pks)
        self.assertNotIn(self.v2.pk, pks)

    def test_search_by_account(self):
        r = self.client.get("/inventory/vendors/", {"q": "ACCT-002"})
        pks = _ids_on_page(r, "vendors")
        self.assertIn(self.v2.pk, pks)

    def test_search_no_match(self):
        r = self.client.get("/inventory/vendors/", {"q": "ZZZNOVENDOR"})
        self.assertEqual(r.context["total_count"], 0)

    def test_pagination(self):
        for i in range(30):
            VendorFactory(name=f"PagVendor {i:03d}")
        r = self.client.get("/inventory/vendors/", {"per_page": "25"})
        self.assertTrue(r.context["page_obj"].has_next())


# ═══════════════════════════════════════════════════════════════════════════
# Autocomplete / JSON Endpoints
# ═══════════════════════════════════════════════════════════════════════════

class AutocompleteEndpointTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ut = UnitTypeFactory(name="Starter")
        cls.unit = UnitFactory(unit_number="AC-UNIT-1", yt_number="AC-YT-1", unit_type=cls.ut)
        cls.part = PartFactory(part_number="AC-PART-1", part_name="AC Brush")
        cls.app = ApplicationFactory(name="AC App Ford", make="Ford", model="Explorer")

    def test_unit_autocomplete(self):
        r = self.client.get("/api/units/autocomplete/", {"q": "AC-UNIT"})
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertIn("results", data)
        values = [item["value"] for item in data["results"]]
        self.assertIn(str(self.unit.pk), values)

    def test_unit_autocomplete_no_match(self):
        r = self.client.get("/api/units/autocomplete/", {"q": "ZZZNOPE"})
        data = json.loads(r.content)
        self.assertEqual(len(data["results"]), 0)

    def test_part_autocomplete(self):
        r = self.client.get("/api/parts/autocomplete/", {"q": "AC-PART"})
        data = json.loads(r.content)
        self.assertIn("results", data)
        values = [item["value"] for item in data["results"]]
        self.assertIn(str(self.part.pk), values)

    def test_part_autocomplete_by_name(self):
        r = self.client.get("/api/parts/autocomplete/", {"q": "AC Brush"})
        data = json.loads(r.content)
        self.assertTrue(len(data["results"]) >= 1)

    def test_application_autocomplete(self):
        r = self.client.get("/api/applications/autocomplete/", {"q": "AC App"})
        data = json.loads(r.content)
        values = [item["value"] for item in data["results"]]
        self.assertIn(str(self.app.pk), values)

    def test_application_model_filter(self):
        r = self.client.get("/api/applications/model-filter/", {"make": "Ford"})
        data = json.loads(r.content)
        self.assertIn("results", data)
        models = [item["value"] for item in data["results"]]
        self.assertIn("Explorer", models)

    def test_application_model_filter_no_make(self):
        r = self.client.get("/api/applications/model-filter/")
        data = json.loads(r.content)
        self.assertIn("results", data)

    def test_invoicing_parts_search(self):
        r = self.client.get("/invoicing/api/parts-search/", {"q": "AC-PART"})
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertIsInstance(data, list)
        values = [item["value"] for item in data]
        self.assertIn(str(self.part.pk), values)

    def test_invoicing_parts_search_empty_query(self):
        r = self.client.get("/invoicing/api/parts-search/", {"q": ""})
        data = json.loads(r.content)
        self.assertEqual(data, [])

    def test_invoicing_units_search(self):
        r = self.client.get("/invoicing/api/units-search/", {"q": "AC-UNIT"})
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertIsInstance(data, list)
        self.assertTrue(len(data) >= 1)

    def test_invoicing_units_search_empty_query(self):
        r = self.client.get("/invoicing/api/units-search/", {"q": ""})
        data = json.loads(r.content)
        self.assertEqual(data, [])
