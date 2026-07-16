"""
Phase 1 — Smoke Tests
Hit every URL with GET (or POST for delete/action endpoints) and verify non-500.
No authentication required (desktop app).
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")

from django.test import TestCase

from tests.e2e.factories import *  # noqa: F403, F401

NOT_500 = {200, 201, 301, 302, 400, 403, 404, 405, 408}


def assert_not_500(response, url):
    assert response.status_code in NOT_500, (
        f"{url} returned {response.status_code}, expected one of {NOT_500}"
    )


def assert_json(response, url):
    ct = response.get("Content-Type", "")
    assert "json" in ct or "javascript" in ct, (
        f"{url} Content-Type was '{ct}', expected JSON"
    )


# ═══════════════════════════════════════════════════════════════════════════
# catalog app (mounted at /)
# ═══════════════════════════════════════════════════════════════════════════


class CatalogHomeSmoke(TestCase):

    def test_smoke_home(self):
        r = self.client.get("/")
        assert_not_500(r, "/")

    def test_smoke_image_viewer(self):
        r = self.client.get("/image-viewer/", {"src": "/media/test.jpg", "title": "Test"})
        assert_not_500(r, "/image-viewer/")


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------


class ApplicationSmoke(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.app_type = ApplicationTypeFactory()
        cls.app_type_field = ApplicationTypeFieldFactory(application_type=cls.app_type)
        cls.app = ApplicationFactory()
        cls.spec = ApplicationSpecificationFactory(application=cls.app)
        cls.unit = UnitFactory()
        cls.app_unit = ApplicationUnitFactory(application=cls.app, unit=cls.unit)

    def test_smoke_application_list(self):
        r = self.client.get("/applications/")
        assert_not_500(r, "/applications/")

    def test_smoke_application_create(self):
        r = self.client.get("/applications/add/")
        assert_not_500(r, "/applications/add/")

    def test_smoke_application_detail(self):
        url = f"/applications/{self.app.pk}/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_application_edit(self):
        url = f"/applications/{self.app.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_application_delete(self):
        app = ApplicationFactory()
        url = f"/applications/{app.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)

    def test_smoke_application_link_unit(self):
        url = f"/applications/{self.app.pk}/link-unit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_application_unlink_unit(self):
        app = ApplicationFactory()
        unit = UnitFactory()
        au = ApplicationUnitFactory(application=app, unit=unit)
        url = f"/applications/{app.pk}/unlink-unit/{unit.pk}/"
        r = self.client.post(url)
        assert_not_500(r, url)

    def test_smoke_application_spec_add(self):
        url = f"/applications/{self.app.pk}/spec/add/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_application_spec_edit(self):
        url = f"/applications/{self.app.pk}/spec/{self.spec.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_application_spec_delete(self):
        app = ApplicationFactory()
        spec = ApplicationSpecificationFactory(application=app)
        url = f"/applications/{app.pk}/spec/{spec.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)


class ApplicationTypeSmoke(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.app_type = ApplicationTypeFactory()
        cls.app_type_field = ApplicationTypeFieldFactory(application_type=cls.app_type)

    def test_smoke_application_type_list(self):
        r = self.client.get("/applications/types/")
        assert_not_500(r, "/applications/types/")

    def test_smoke_application_type_create(self):
        r = self.client.get("/applications/types/add/")
        assert_not_500(r, "/applications/types/add/")

    def test_smoke_application_type_detail(self):
        url = f"/applications/types/{self.app_type.pk}/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_application_type_edit(self):
        url = f"/applications/types/{self.app_type.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_application_type_delete(self):
        at = ApplicationTypeFactory()
        url = f"/applications/types/{at.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)

    def test_smoke_application_type_fields_api(self):
        url = f"/applications/type-fields/{self.app_type.name}/"
        r = self.client.get(url)
        assert_not_500(r, url)
        assert_json(r, url)

    def test_smoke_application_custom_field_add_api(self):
        url = "/api/application-custom-field/add/"
        r = self.client.post(url, content_type="application/json", data="{}")
        assert_not_500(r, url)


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------


class PartSmoke(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.part = PartFactory()
        cls.part2 = PartFactory()
        cls.sub = PartSubstituteFactory(part=cls.part, substitute_part=cls.part2)
        cls.interchange = PartInterchangeFactory(part=cls.part, interchange_part=cls.part2)
        cls.superseding = PartSupersedingFactory(part=cls.part, old_part=cls.part2)
        cls.category = PartCategoryFactory()
        cls.category_field = PartCategoryFieldFactory(category=cls.category)

    def test_smoke_part_list(self):
        r = self.client.get("/parts/")
        assert_not_500(r, "/parts/")

    def test_smoke_part_create(self):
        r = self.client.get("/parts/add/")
        assert_not_500(r, "/parts/add/")

    def test_smoke_part_detail(self):
        url = f"/parts/{self.part.pk}/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_part_edit(self):
        url = f"/parts/{self.part.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_part_delete(self):
        part = PartFactory()
        url = f"/parts/{part.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)

    def test_smoke_part_upload_csv(self):
        r = self.client.get("/parts/upload-csv/")
        assert_not_500(r, "/parts/upload-csv/")

    def test_smoke_part_csv_template(self):
        r = self.client.get("/parts/csv-template/")
        assert_not_500(r, "/parts/csv-template/")

    # substitutes
    def test_smoke_part_substitute_add(self):
        url = f"/parts/{self.part.pk}/substitute/add/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_part_substitute_edit(self):
        url = f"/parts/{self.part.pk}/substitute/{self.sub.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_part_substitute_delete(self):
        part = PartFactory()
        sub = PartSubstituteFactory(part=part)
        url = f"/parts/{part.pk}/substitute/{sub.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)

    # interchanges
    def test_smoke_part_interchange_add(self):
        url = f"/parts/{self.part.pk}/interchange/add/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_part_interchange_edit(self):
        url = f"/parts/{self.part.pk}/interchange/{self.interchange.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_part_interchange_delete(self):
        part = PartFactory()
        ix = PartInterchangeFactory(part=part)
        url = f"/parts/{part.pk}/interchange/{ix.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)

    # superseding
    def test_smoke_part_superseding_add(self):
        url = f"/parts/{self.part.pk}/superseding/add/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_part_superseding_edit(self):
        url = f"/parts/{self.part.pk}/superseding/{self.superseding.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_part_superseding_delete(self):
        part = PartFactory()
        sup = PartSupersedingFactory(part=part)
        url = f"/parts/{part.pk}/superseding/{sup.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)


class PartCategorySmoke(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.category = PartCategoryFactory()
        cls.category_field = PartCategoryFieldFactory(category=cls.category)

    def test_smoke_part_category_list(self):
        r = self.client.get("/parts/categories/")
        assert_not_500(r, "/parts/categories/")

    def test_smoke_part_category_create(self):
        r = self.client.get("/parts/categories/add/")
        assert_not_500(r, "/parts/categories/add/")

    def test_smoke_part_category_detail(self):
        url = f"/parts/categories/{self.category.pk}/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_part_category_edit(self):
        url = f"/parts/categories/{self.category.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_part_category_delete(self):
        cat = PartCategoryFactory()
        url = f"/parts/categories/{cat.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)

    def test_smoke_part_category_fields_api(self):
        url = f"/parts/category-fields/{self.category.name}/"
        r = self.client.get(url)
        assert_not_500(r, url)
        assert_json(r, url)

    def test_smoke_part_category_custom_field_add_api(self):
        url = "/api/part-category-custom-field/add/"
        r = self.client.post(url, content_type="application/json", data="{}")
        assert_not_500(r, url)


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------


class UnitSmoke(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.unit = UnitFactory()
        cls.unit2 = UnitFactory()
        cls.cross_ref = CrossReferenceFactory(unit=cls.unit)
        cls.substitute = SubstituteFactory(unit=cls.unit, substitute_unit=cls.unit2)
        cls.gear_reduction = GearReductionSubstitutionFactory(unit=cls.unit)
        cls.type_cat = UnitTypeCategoryFactory()
        cls.type_cat_field = UnitTypeCategoryFieldFactory(category=cls.type_cat)

    def test_smoke_unit_list(self):
        r = self.client.get("/units/")
        assert_not_500(r, "/units/")

    def test_smoke_unit_search(self):
        r = self.client.get("/units/search/")
        assert_not_500(r, "/units/search/")

    def test_smoke_unit_create(self):
        r = self.client.get("/units/add/")
        assert_not_500(r, "/units/add/")

    def test_smoke_unit_detail(self):
        url = f"/units/{self.unit.pk}/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_unit_edit(self):
        url = f"/units/{self.unit.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_unit_delete(self):
        unit = UnitFactory()
        url = f"/units/{unit.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)

    def test_smoke_unit_bom(self):
        url = f"/units/{self.unit.pk}/bom/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_unit_upload_csv(self):
        r = self.client.get("/units/upload-csv/")
        assert_not_500(r, "/units/upload-csv/")

    def test_smoke_unit_csv_template(self):
        r = self.client.get("/units/csv-template/")
        assert_not_500(r, "/units/csv-template/")

    # cross-references
    def test_smoke_unit_cross_ref_add(self):
        url = f"/units/{self.unit.pk}/cross-ref/add/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_unit_cross_ref_detail(self):
        url = f"/units/{self.unit.pk}/cross-ref/{self.cross_ref.pk}/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_unit_cross_ref_edit(self):
        url = f"/units/{self.unit.pk}/cross-ref/{self.cross_ref.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_unit_cross_ref_delete(self):
        unit = UnitFactory()
        cr = CrossReferenceFactory(unit=unit)
        url = f"/units/{unit.pk}/cross-ref/{cr.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)

    # substitutes
    def test_smoke_unit_substitute_add(self):
        url = f"/units/{self.unit.pk}/substitute/add/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_unit_substitute_edit(self):
        url = f"/units/{self.unit.pk}/substitute/{self.substitute.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_unit_substitute_delete(self):
        unit = UnitFactory()
        sub = SubstituteFactory(unit=unit)
        url = f"/units/{unit.pk}/substitute/{sub.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)

    # gear-reduction
    def test_smoke_unit_gear_reduction_add(self):
        url = f"/units/{self.unit.pk}/gear-reduction/add/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_unit_gear_reduction_edit(self):
        url = f"/units/{self.unit.pk}/gear-reduction/{self.gear_reduction.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_unit_gear_reduction_delete(self):
        unit = UnitFactory()
        gr = GearReductionSubstitutionFactory(unit=unit)
        url = f"/units/{unit.pk}/gear-reduction/{gr.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)


class UnitTypeCategorySmoke(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.type_cat = UnitTypeCategoryFactory()
        cls.type_cat_field = UnitTypeCategoryFieldFactory(category=cls.type_cat)

    def test_smoke_unit_type_category_list(self):
        r = self.client.get("/units/type-categories/")
        assert_not_500(r, "/units/type-categories/")

    def test_smoke_unit_type_category_create(self):
        r = self.client.get("/units/type-categories/add/")
        assert_not_500(r, "/units/type-categories/add/")

    def test_smoke_unit_type_category_detail(self):
        url = f"/units/type-categories/{self.type_cat.pk}/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_unit_type_category_edit(self):
        url = f"/units/type-categories/{self.type_cat.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_unit_type_category_delete(self):
        tc = UnitTypeCategoryFactory()
        url = f"/units/type-categories/{tc.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)

    def test_smoke_unit_type_category_fields_api(self):
        url = f"/units/type-category-fields/{self.type_cat.name}/"
        r = self.client.get(url)
        assert_not_500(r, url)
        assert_json(r, url)

    def test_smoke_unit_type_custom_field_add_api(self):
        url = "/api/unit-type-custom-field/add/"
        r = self.client.post(url, content_type="application/json", data="{}")
        assert_not_500(r, url)


# ---------------------------------------------------------------------------
# BOM
# ---------------------------------------------------------------------------


class BOMSmoke(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.bom = BOMFactory()
        cls.bom_item = BOMItemFactory(bom=cls.bom)

    def test_smoke_bom_list(self):
        r = self.client.get("/bom/")
        assert_not_500(r, "/bom/")

    def test_smoke_bom_create(self):
        r = self.client.get("/bom/add/")
        assert_not_500(r, "/bom/add/")

    def test_smoke_bom_detail(self):
        url = f"/bom/{self.bom.pk}/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_bom_print(self):
        url = f"/bom/{self.bom.pk}/print/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_bom_item_add(self):
        url = f"/bom/{self.bom.pk}/add-part/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_bom_item_detail(self):
        url = f"/bom/{self.bom.pk}/item/{self.bom_item.pk}/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_bom_item_edit(self):
        url = f"/bom/{self.bom.pk}/item/{self.bom_item.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_bom_item_delete(self):
        bom = BOMFactory()
        item = BOMItemFactory(bom=bom)
        url = f"/bom/{bom.pk}/item/{item.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)

    def test_smoke_bom_edit(self):
        url = f"/bom/{self.bom.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_bom_delete(self):
        url = f"/bom/{self.bom.pk}/delete/"
        r = self.client.get(url)
        assert_not_500(r, url)


class BOMApiSmoke(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.bom = BOMFactory()
        cls.bom_item = BOMItemFactory(bom=cls.bom)

    def test_smoke_bom_save_api(self):
        url = "/api/bom/save/"
        r = self.client.post(url, content_type="application/json", data="{}")
        assert_not_500(r, url)

    def test_smoke_bom_item_add_api(self):
        url = f"/api/bom/{self.bom.pk}/add-part/"
        r = self.client.post(url, content_type="application/json", data="{}")
        assert_not_500(r, url)

    def test_smoke_bom_item_delete_api(self):
        bom = BOMFactory()
        item = BOMItemFactory(bom=bom)
        url = f"/api/bom/{bom.pk}/item/{item.pk}/delete/"
        r = self.client.post(url, content_type="application/json")
        assert_not_500(r, url)


# ---------------------------------------------------------------------------
# Autocomplete / JSON API endpoints
# ---------------------------------------------------------------------------


class CatalogApiSmoke(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.part = PartFactory()

    def test_smoke_unit_autocomplete(self):
        url = "/api/units/autocomplete/"
        r = self.client.get(url)
        assert_not_500(r, url)
        assert_json(r, url)

    def test_smoke_part_autocomplete(self):
        url = "/api/parts/autocomplete/"
        r = self.client.get(url)
        assert_not_500(r, url)
        assert_json(r, url)

    def test_smoke_part_detail_api(self):
        url = f"/api/parts/{self.part.pk}/detail/"
        r = self.client.get(url)
        assert_not_500(r, url)
        assert_json(r, url)

    def test_smoke_application_autocomplete(self):
        url = "/api/applications/autocomplete/"
        r = self.client.get(url)
        assert_not_500(r, url)
        assert_json(r, url)

    def test_smoke_application_model_filter(self):
        url = "/api/applications/model-filter/"
        r = self.client.get(url)
        assert_not_500(r, url)
        assert_json(r, url)


# ═══════════════════════════════════════════════════════════════════════════
# inventory app (mounted at /inventory/)
# ═══════════════════════════════════════════════════════════════════════════


class InventorySmoke(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.vendor = VendorFactory()

    def test_smoke_inventory_list(self):
        r = self.client.get("/inventory/")
        assert_not_500(r, "/inventory/")

    def test_smoke_inventory_create(self):
        r = self.client.get("/inventory/create/")
        assert_not_500(r, "/inventory/create/")

    def test_smoke_inventory_reorder(self):
        r = self.client.get("/inventory/reorder/")
        assert_not_500(r, "/inventory/reorder/")

    def test_smoke_vendor_list(self):
        r = self.client.get("/inventory/vendors/")
        assert_not_500(r, "/inventory/vendors/")

    def test_smoke_vendor_create(self):
        r = self.client.get("/inventory/vendors/add/")
        assert_not_500(r, "/inventory/vendors/add/")

    def test_smoke_vendor_edit(self):
        url = f"/inventory/vendors/{self.vendor.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_vendor_delete(self):
        vendor = VendorFactory()
        url = f"/inventory/vendors/{vendor.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)


# ═══════════════════════════════════════════════════════════════════════════
# invoicing app (mounted at /invoicing/)
# ═══════════════════════════════════════════════════════════════════════════


class InvoicingSmoke(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.settings = CompanySettingsFactory()
        cls.customer = CustomerFactory()
        cls.invoice = InvoiceFactory(customer=cls.customer)
        cls.part = PartFactory()
        cls.unit = UnitFactory()

    def test_smoke_invoice_list(self):
        r = self.client.get("/invoicing/")
        assert_not_500(r, "/invoicing/")

    def test_smoke_invoice_report(self):
        r = self.client.get("/invoicing/report/")
        assert_not_500(r, "/invoicing/report/")

    def test_smoke_invoice_settings(self):
        r = self.client.get("/invoicing/settings/")
        assert_not_500(r, "/invoicing/settings/")

    def test_smoke_add_to_invoice_part(self):
        url = f"/invoicing/add-item/?part={self.part.pk}"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_add_to_invoice_unit(self):
        url = f"/invoicing/add-item/?unit={self.unit.pk}"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_invoice_create(self):
        r = self.client.get("/invoicing/invoice/new/")
        assert_not_500(r, "/invoicing/invoice/new/")

    def test_smoke_invoice_detail(self):
        url = f"/invoicing/invoice/{self.invoice.pk}/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_invoice_print(self):
        url = f"/invoicing/invoice/{self.invoice.pk}/print/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_invoice_edit(self):
        url = f"/invoicing/invoice/{self.invoice.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_invoice_cancel(self):
        inv = InvoiceFactory()
        url = f"/invoicing/invoice/{inv.pk}/cancel/"
        r = self.client.post(url)
        assert_not_500(r, url)

    def test_smoke_invoice_delete(self):
        inv = InvoiceFactory()
        url = f"/invoicing/invoice/{inv.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)

    def test_smoke_invoice_bulk_print(self):
        url = f"/invoicing/invoices/bulk-print/?ids={self.invoice.pk}"
        r = self.client.get(url)
        assert_not_500(r, url)


class InvoicingCustomerSmoke(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.customer = CustomerFactory()

    def test_smoke_customer_list(self):
        r = self.client.get("/invoicing/customers/")
        assert_not_500(r, "/invoicing/customers/")

    def test_smoke_customer_create(self):
        r = self.client.get("/invoicing/customers/add/")
        assert_not_500(r, "/invoicing/customers/add/")

    def test_smoke_customer_edit(self):
        url = f"/invoicing/customers/{self.customer.pk}/edit/"
        r = self.client.get(url)
        assert_not_500(r, url)

    def test_smoke_customer_delete(self):
        cust = CustomerFactory()
        url = f"/invoicing/customers/{cust.pk}/delete/"
        r = self.client.post(url)
        assert_not_500(r, url)


class InvoicingApiSmoke(TestCase):

    def test_smoke_api_parts_search(self):
        url = "/invoicing/api/parts-search/?q=test"
        self.client.raise_request_exception = False
        r = self.client.get(url)
        assert_not_500(r, url)
        assert_json(r, url)

    def test_smoke_api_units_search(self):
        url = "/invoicing/api/units-search/?q=test"
        self.client.raise_request_exception = False
        r = self.client.get(url)
        assert_not_500(r, url)
        assert_json(r, url)


# ═══════════════════════════════════════════════════════════════════════════
# backup app (mounted at /backup/)
# ═══════════════════════════════════════════════════════════════════════════


class BackupSmoke(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.settings = BackupSettingsFactory()

    def test_smoke_backup_settings(self):
        r = self.client.get("/backup/")
        assert_not_500(r, "/backup/")

    def test_smoke_backup_now(self):
        r = self.client.post("/backup/now/")
        assert_not_500(r, "/backup/now/")

    def test_smoke_backup_restore(self):
        r = self.client.post("/backup/restore/")
        assert_not_500(r, "/backup/restore/")

    def test_smoke_backup_api_pick_folder(self):
        r = self.client.get("/backup/api/pick-folder/")
        assert_not_500(r, "/backup/api/pick-folder/")

    def test_smoke_backup_api_pick_file(self):
        r = self.client.get("/backup/api/pick-file/")
        assert_not_500(r, "/backup/api/pick-file/")


# ═══════════════════════════════════════════════════════════════════════════
# config (root-level endpoints)
# ═══════════════════════════════════════════════════════════════════════════


class ConfigApiSmoke(TestCase):

    def test_smoke_media_status(self):
        url = "/api/media-status/"
        r = self.client.get(url)
        assert_not_500(r, url)
        assert_json(r, url)
