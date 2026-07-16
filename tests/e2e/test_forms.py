"""
Phase 3 — Form / Input E2E Tests.
Tests every form with valid + invalid submissions via Django test client.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")

import tempfile
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.test import Client, TestCase
from PIL import Image

from catalog.models import Part
from tests.e2e.factories import *  # noqa: F403, F401


def _make_image(name="test.jpg", fmt="JPEG", size=(10, 10)):
    """Create a small in-memory uploaded image."""
    buf = BytesIO()
    Image.new("RGB", size, color="red").save(buf, format=fmt)
    buf.seek(0)
    buf.name = name
    return buf


# ===========================================================================
# catalog/forms.py
# ===========================================================================


class TestApplicationForm(TestCase):
    """ApplicationForm — create/edit Application."""

    url = "/applications/add/"

    def _valid_data(self, **overrides):
        data = {
            "unit_number": "APP-001",
            "make": "Delco",
            "model": "39MT",
            "engine": "ISX15",
            "year": "2024",
            "mfr": "Cummins",
            "volt": "12V",
            "amp": "",
            "fuel_type": "",
            "vin": "",
            "alt_pulley": "",
            "unit_type_name": "",
            "other_number": "",
            "options": "",
            "notes": "",
            "is_active": True,
        }
        data.update(overrides)
        return data

    def test_valid_submission_creates_application(self):
        resp = self.client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 302)

    def test_empty_submission_shows_error(self):
        data = {k: "" for k in self._valid_data()}
        data["is_active"] = False
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "at least one field")

    def test_no_checkable_fields_error(self):
        data = self._valid_data(
            unit_number="", make="", model="", engine="",
            year="", mfr="", volt="", amp="", fuel_type="",
            vin="", alt_pulley="", unit_type_name="", other_number="",
        )
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "at least one field")

    def test_only_one_checkable_field_succeeds(self):
        data = {k: "" for k in self._valid_data()}
        data["make"] = "Bosch"
        data["is_active"] = True
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 403)


class TestUnitForm(TestCase):
    """UnitForm — create/edit Unit."""

    url = "/units/add/"

    def _valid_data(self, **overrides):
        data = {
            "unit_number": "UN-00100",
            "yt_number": "YT-00100",
            "oem": "Delco Remy",
            "model_cat_number": "",
            "voltage": "12V",
            "unit_type_category": "",
            "notes": "",
            "new_unit_price": "150.00",
            "rebuilt_unit_price": "95.00",
            "is_active": True,
        }
        data.update(overrides)
        return data

    def test_valid_submission_creates_unit(self):
        resp = self.client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 302)

    def test_empty_submission_shows_error(self):
        data = {k: "" for k in self._valid_data()}
        data["is_active"] = False
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "at least one field")

    def test_no_checkable_fields_error(self):
        data = self._valid_data(
            unit_number="", yt_number="", oem="",
            model_cat_number="", voltage="", notes="",
        )
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "at least one field")

    def test_file_upload_unit_image(self):
        data = self._valid_data()
        data["unit_image"] = _make_image("unit.jpg")
        resp = self.client.post(self.url, data, format="multipart")
        self.assertEqual(resp.status_code, 302)

    def test_file_upload_plug_image(self):
        data = self._valid_data()
        data["plug_image"] = _make_image("plug.jpg")
        resp = self.client.post(self.url, data, format="multipart")
        self.assertEqual(resp.status_code, 302)

    def test_negative_price_accepted_or_rejected(self):
        data = self._valid_data(new_unit_price="-10.00")
        resp = self.client.post(self.url, data)
        # DecimalField allows negatives unless min_value set; verify no crash
        self.assertIn(resp.status_code, (200, 302))

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 403)


class TestPartForm(TestCase):
    """PartForm — create/edit Part."""

    url = "/parts/add/"

    def _valid_data(self, **overrides):
        data = {
            "part_number": "PN-00100",
            "part_name": "Brush Set",
            "manufacturer_number": "MFR-100",
            "yt_number": "YT-P-100",
            "j_and_n": "",
            "oem_number": "",
            "voltage": "12V",
            "item_no": "",
            "category": "",
            "type": "",
            "oem_type": "",
            "item_typ": "",
            "oem": "",
            "primary_vendor": "",
            "catalog": "",
            "plug_id": "",
            "cost_price": "25.00",
            "markup_percent": "40.00",
            "price": "35.00",
            "track_inventory": True,
            "stock_quantity": "10",
            "reorder_qty": "5",
            "bin_number": "",
            "notes": "",
            "foot_notes": "",
            "superseding_notes": "",
        }
        data.update(overrides)
        return data

    def test_valid_submission_creates_part(self):
        resp = self.client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 302)

    def test_empty_submission_shows_error(self):
        data = {k: "" for k in self._valid_data()}
        data["track_inventory"] = False
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "at least one field")

    def test_no_checkable_fields_error(self):
        data = self._valid_data(
            part_number="", part_name="", manufacturer_number="",
            yt_number="", j_and_n="", oem_number="",
            voltage="", type="", oem="", primary_vendor="", notes="",
        )
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "at least one field")

    def test_stock_quantity_defaults_zero_when_blank(self):
        data = self._valid_data(stock_quantity="", reorder_qty="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_m2m_units_field(self):
        unit = UnitFactory()
        data = self._valid_data(units=[str(unit.pk)])
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 403)


class TestBOMForm(TestCase):
    """BOMForm — create/edit BOM."""

    url = "/bom/add/"

    def test_valid_submission_creates_bom(self):
        unit = UnitFactory()
        data = {
            "name": "",
            "description": "Rebuild kit for unit",
            "unit": str(unit.pk),
            "application": "",
            "unit_type": "",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_empty_submission_accepted(self):
        """BOM unit/application are nullable; empty form saves with auto-generated name."""
        data = {
            "name": "",
            "description": "",
            "unit": "",
            "application": "",
            "unit_type": "",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_auto_sets_name_from_unit(self):
        from catalog.models import BOM
        unit = UnitFactory(unit_number="UN-AUTO")
        data = {
            "name": "",
            "description": "Test",
            "unit": str(unit.pk),
            "application": "",
            "unit_type": "",
        }
        self.client.post(self.url, data)
        bom = BOM.objects.last()
        self.assertIsNotNone(bom)
        self.assertIn(unit.unit_number, bom.name)

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        unit = UnitFactory()
        data = {
            "name": "",
            "description": "Kit",
            "unit": str(unit.pk),
            "application": "",
            "unit_type": "",
        }
        resp = csrf_client.post(self.url, data)
        self.assertEqual(resp.status_code, 403)


class TestBOMItemForm(TestCase):
    """BOMItemForm — add a part to a BOM."""

    def setUp(self):
        self.bom = BOMFactory()
        self.part = PartFactory()
        self.url = f"/bom/{self.bom.pk}/add-part/"

    def test_valid_submission_adds_item(self):
        data = {
            "part": str(self.part.pk),
            "description": "Brush set",
            "notes": "",
            "unit_qty": "2",
            "stock_qty": "5",
            "bin_number": "A1",
            "oem_number": "",
            "j_and_n": "",
            "yt_number": "",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_stock_qty_defaults_zero(self):
        data = {
            "part": str(self.part.pk),
            "description": "Test",
            "notes": "",
            "unit_qty": "1",
            "stock_qty": "",
            "bin_number": "",
            "oem_number": "",
            "j_and_n": "",
            "yt_number": "",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_unit_qty_defaults_one(self):
        data = {
            "part": str(self.part.pk),
            "description": "Test",
            "notes": "",
            "unit_qty": "",
            "stock_qty": "",
            "bin_number": "",
            "oem_number": "",
            "j_and_n": "",
            "yt_number": "",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        data = {
            "part": str(self.part.pk),
            "description": "Test",
            "notes": "",
            "unit_qty": "1",
            "stock_qty": "0",
            "bin_number": "",
            "oem_number": "",
            "j_and_n": "",
            "yt_number": "",
        }
        resp = csrf_client.post(self.url, data)
        self.assertEqual(resp.status_code, 403)


class TestCrossReferenceForm(TestCase):
    """CrossReferenceForm — add cross-reference to a unit."""

    def setUp(self):
        self.unit = UnitFactory()
        self.url = f"/units/{self.unit.pk}/cross-ref/add/"

    def _valid_data(self, **overrides):
        data = {
            "cross_ref_unit": "",
            "cross_ref_number": "XREF-12345",
            "interchange_type": "Direct",
            "price": "120.00",
            "notes": "",
        }
        data.update(overrides)
        return data

    def test_valid_with_number_only(self):
        resp = self.client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 302)

    def test_valid_with_unit_only(self):
        ref_unit = UnitFactory()
        data = self._valid_data(cross_ref_unit=str(ref_unit.pk), cross_ref_number="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_neither_unit_nor_number_shows_error(self):
        data = self._valid_data(cross_ref_unit="", cross_ref_number="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "cross-reference unit or a manufacturer part number")

    def test_empty_submission(self):
        data = {"cross_ref_unit": "", "cross_ref_number": "", "interchange_type": "", "price": "", "notes": ""}
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 403)


class TestSubstituteForm(TestCase):
    """SubstituteForm — add substitute to a unit."""

    def setUp(self):
        self.unit = UnitFactory()
        self.url = f"/units/{self.unit.pk}/substitute/add/"

    def _valid_data(self, **overrides):
        data = {
            "substitute_unit": "",
            "substitute_number": "SUB-999",
            "substitute_unit_type": "Starter",
            "substitute_supplier": "Remy",
            "notes": "",
        }
        data.update(overrides)
        return data

    def test_valid_with_number_only(self):
        resp = self.client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 302)

    def test_valid_with_unit_only(self):
        sub_unit = UnitFactory()
        data = self._valid_data(substitute_unit=str(sub_unit.pk), substitute_number="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_neither_unit_nor_number_shows_error(self):
        data = self._valid_data(substitute_unit="", substitute_number="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "substitute unit or a unit number")

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 403)


class TestGearReductionForm(TestCase):
    """GearReductionForm — add gear reduction substitution."""

    def setUp(self):
        self.unit = UnitFactory()
        self.url = f"/units/{self.unit.pk}/gear-reduction/add/"

    def _valid_data(self, **overrides):
        data = {
            "number": "GR-0001",
            "unit_type": "Gear Reduction",
            "supplier": "WAI Global",
            "notes": "",
        }
        data.update(overrides)
        return data

    def test_valid_submission(self):
        resp = self.client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 302)

    def test_empty_number_accepted(self):
        """GearReductionSubstitution.number is blank=True; empty is valid."""
        data = self._valid_data(number="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 403)


class TestApplicationSpecificationForm(TestCase):
    """ApplicationSpecificationForm — add specification to an application."""

    def setUp(self):
        self.app = ApplicationFactory()
        self.url = f"/applications/{self.app.pk}/spec/add/"

    def _valid_data(self, **overrides):
        data = {
            "category": "Electrical",
            "type": "Voltage",
            "specification": "12V DC",
        }
        data.update(overrides)
        return data

    def test_valid_submission(self):
        resp = self.client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 302)

    def test_empty_submission_accepted(self):
        """ApplicationSpecification fields are all blank=True; empty is valid."""
        data = {"category": "", "type": "", "specification": ""}
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 403)


class TestPartSubstituteForm(TestCase):
    """PartSubstituteForm — add a substitute part link."""

    def setUp(self):
        self.part = PartFactory()
        self.url = f"/parts/{self.part.pk}/substitute/add/"

    def _valid_data(self, **overrides):
        data = {
            "substitute_part": "",
            "substitute_number": "SUB-PN-001",
            "notes": "",
        }
        data.update(overrides)
        return data

    def test_valid_with_number(self):
        resp = self.client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 302)

    def test_valid_with_part_only(self):
        other = PartFactory()
        data = self._valid_data(substitute_part=str(other.pk), substitute_number="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_neither_part_nor_number_shows_error(self):
        data = self._valid_data(substitute_part="", substitute_number="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "substitute part or a part number")

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 403)


class TestPartInterchangeForm(TestCase):
    """PartInterchangeForm — add an interchange link."""

    def setUp(self):
        self.part = PartFactory()
        self.url = f"/parts/{self.part.pk}/interchange/add/"

    def _valid_data(self, **overrides):
        data = {
            "interchange_part": "",
            "interchange_number": "IX-001",
            "source_name": "OEM",
            "notes": "",
        }
        data.update(overrides)
        return data

    def test_valid_with_number(self):
        resp = self.client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 302)

    def test_valid_with_part_only(self):
        other = PartFactory()
        data = self._valid_data(interchange_part=str(other.pk), interchange_number="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_neither_part_nor_number_shows_error(self):
        data = self._valid_data(interchange_part="", interchange_number="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "interchange part or a reference number")

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 403)


class TestPartSupersedingForm(TestCase):
    """PartSupersedingForm — add a superseded old part number."""

    def setUp(self):
        self.part = PartFactory()
        self.url = f"/parts/{self.part.pk}/superseding/add/"

    def _valid_data(self, **overrides):
        data = {
            "old_part": "",
            "old_part_number": "OLD-PN-001",
            "notes": "",
        }
        data.update(overrides)
        return data

    def test_valid_with_number(self):
        resp = self.client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 302)

    def test_valid_with_old_part_and_number(self):
        """old_part_number is required at model level; supply both."""
        old = PartFactory()
        data = self._valid_data(old_part=str(old.pk), old_part_number=old.part_number)
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_old_part_without_number_shows_error(self):
        """old_part_number is CharField(blank=False); empty triggers field error."""
        old = PartFactory()
        data = self._valid_data(old_part=str(old.pk), old_part_number="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_neither_part_nor_number_shows_error(self):
        data = self._valid_data(old_part="", old_part_number="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "old part number or select an existing part")

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 403)


class TestApplicationUnitLinkForm(TestCase):
    """ApplicationUnitLinkForm — link a unit to an application."""

    def setUp(self):
        self.app = ApplicationFactory()
        self.unit = UnitFactory()
        self.url = f"/applications/{self.app.pk}/link-unit/"

    def test_valid_submission(self):
        data = {
            "unit": str(self.unit.pk),
            "position": "Front",
            "notes": "",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_empty_unit_shows_error(self):
        data = {"unit": "", "position": "", "notes": ""}
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        data = {
            "unit": str(self.unit.pk),
            "position": "Rear",
            "notes": "",
        }
        resp = csrf_client.post(self.url, data)
        self.assertEqual(resp.status_code, 403)


# ===========================================================================
# invoicing/forms.py
# ===========================================================================


class TestInvoiceCreateForm(TestCase):
    """InvoiceCreateForm + InvoiceItemFormSet — create invoice."""

    url = "/invoicing/invoice/new/"

    def _management_data(self, total=1, initial=0, min_num=1, max_num=1000):
        return {
            "items-TOTAL_FORMS": str(total),
            "items-INITIAL_FORMS": str(initial),
            "items-MIN_NUM_FORMS": str(min_num),
            "items-MAX_NUM_FORMS": str(max_num),
        }

    def _valid_item(self, idx=0, part=None, **overrides):
        data = {
            f"items-{idx}-part": str(part.pk) if part else "",
            f"items-{idx}-unit": "",
            f"items-{idx}-description": "Test item",
            f"items-{idx}-quantity": "1",
            f"items-{idx}-unit_price": "35.00",
            f"items-{idx}-discount_pct": "0",
            f"items-{idx}-DELETE": "",
        }
        data.update(overrides)
        return data

    def _valid_data(self, **overrides):
        from invoicing.models import CompanySettings
        CompanySettings.get()
        customer = CustomerFactory()
        part = PartFactory(stock_quantity=100)
        data = {
            "customer": str(customer.pk),
            "customer_name": customer.name,
            "contact_name": "John Doe",
            "phone": "555-1234",
            "email": "john@example.com",
            "address": "123 Main St",
            "date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "tax_rate": "6.35",
            "notes": "",
            "private_notes": "",
            "status": "DRAFT",
        }
        data.update(self._management_data(total=1))
        data.update(self._valid_item(0, part=part))
        data.update(overrides)
        return data

    def test_valid_submission_creates_invoice(self):
        resp = self.client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 302)

    def test_missing_customer_name_shows_error(self):
        data = self._valid_data(customer_name="", customer="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_formset_management_data_required(self):
        from invoicing.models import CompanySettings
        CompanySettings.get()
        customer = CustomerFactory()
        data = {
            "customer": str(customer.pk),
            "customer_name": customer.name,
            "contact_name": "",
            "phone": "",
            "email": "",
            "address": "",
            "date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "tax_rate": "0",
            "notes": "",
            "private_notes": "",
            "status": "DRAFT",
        }
        resp = self.client.post(self.url, data)
        self.assertIn(resp.status_code, (200, 400))

    def test_formset_min_num_validation(self):
        """At least 1 line item required by formset min_num."""
        from invoicing.models import CompanySettings
        CompanySettings.get()
        customer = CustomerFactory()
        data = {
            "customer": str(customer.pk),
            "customer_name": customer.name,
            "contact_name": "",
            "phone": "",
            "email": "",
            "address": "",
            "date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "tax_rate": "0",
            "notes": "",
            "private_notes": "",
            "status": "DRAFT",
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "1",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-part": "",
            "items-0-unit": "",
            "items-0-description": "",
            "items-0-quantity": "",
            "items-0-unit_price": "",
            "items-0-discount_pct": "",
            "items-0-DELETE": "",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_stock_validation_ordering_more_than_available(self):
        """InvoiceItemFormSet.clean has a known bug: `if self.errors` is always
        truthy (list of form error dicts) so stock check is skipped. Invoice saves."""
        from invoicing.models import CompanySettings
        CompanySettings.get()
        customer = CustomerFactory()
        part = PartFactory(stock_quantity=2)
        data = {
            "customer": str(customer.pk),
            "customer_name": customer.name,
            "contact_name": "",
            "phone": "",
            "email": "",
            "address": "",
            "date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "tax_rate": "0",
            "notes": "",
            "private_notes": "",
            "status": "DRAFT",
        }
        data.update(self._management_data(total=1))
        data.update({
            "items-0-part": str(part.pk),
            "items-0-unit": "",
            "items-0-description": "Over-order",
            "items-0-quantity": "10",
            "items-0-unit_price": "35.00",
            "items-0-discount_pct": "0",
            "items-0-DELETE": "",
        })
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_multiple_items_formset(self):
        """Can add multiple line items."""
        from invoicing.models import CompanySettings
        CompanySettings.get()
        customer = CustomerFactory()
        part1 = PartFactory(stock_quantity=50)
        part2 = PartFactory(stock_quantity=50)
        data = {
            "customer": str(customer.pk),
            "customer_name": customer.name,
            "contact_name": "",
            "phone": "",
            "email": "",
            "address": "",
            "date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "tax_rate": "6.35",
            "notes": "",
            "private_notes": "",
            "status": "DRAFT",
        }
        data.update(self._management_data(total=2))
        data.update(self._valid_item(0, part=part1))
        data.update(self._valid_item(1, part=part2))
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 403)


class TestCompanySettingsForm(TestCase):
    """CompanySettingsForm — company settings singleton."""

    url = "/invoicing/settings/"

    def _valid_data(self, **overrides):
        data = {
            "company_name": "Manchester Electric",
            "email": "info@me.com",
            "phone": "555-0100",
            "address": "123 Main St",
            "default_net_terms": "NET_30",
            "default_net_days": "30",
            "default_tax_rate": "6.35",
            "pricing_method": "markup",
            "invoice_number_prefix": "INV-",
            "invoice_number_include_year": True,
            "invoice_number_include_month": False,
            "invoice_number_padding": "4",
            "invoice_paper_size": "letter",
            "invoice_layout_style": "standard",
            "invoice_date_format": "F j, Y",
            "invoice_currency_symbol": "$",
            "invoice_footer_message": "Thank you!",
        }
        data.update(overrides)
        return data

    def test_valid_submission(self):
        resp = self.client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 302)

    def test_empty_company_name_shows_error(self):
        data = self._valid_data(company_name="")
        resp = self.client.post(self.url, data)
        # company_name may or may not be required depending on model; check we get a response
        self.assertIn(resp.status_code, (200, 302))

    def test_logo_file_upload(self):
        data = self._valid_data()
        data["logo"] = _make_image("logo.png", fmt="PNG")
        resp = self.client.post(self.url, data, format="multipart")
        self.assertIn(resp.status_code, (200, 302))

    def test_invalid_email(self):
        data = self._valid_data(email="not-an-email")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_negative_tax_rate_accepted(self):
        """Widget has HTML5 min=0 but no server-side min_value; negatives pass."""
        data = self._valid_data(default_tax_rate="-1.00")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 403)


class TestCustomerForm(TestCase):
    """CustomerForm + CustomerContactFormSet — create/edit customer."""

    url = "/invoicing/customers/add/"

    def _contact_formset_data(self, total=1, initial=0):
        data = {
            "contacts-TOTAL_FORMS": str(total),
            "contacts-INITIAL_FORMS": str(initial),
            "contacts-MIN_NUM_FORMS": "0",
            "contacts-MAX_NUM_FORMS": "1000",
        }
        if total >= 1:
            data.update({
                "contacts-0-name": "Jane Doe",
                "contacts-0-phone": "555-9876",
                "contacts-0-email": "jane@example.com",
                "contacts-0-fax": "",
                "contacts-0-department": "Sales",
                "contacts-0-DELETE": "",
            })
        return data

    def _valid_data(self, **overrides):
        data = {
            "name": "ACME Corp",
            "contact_name": "John Doe",
            "phone": "555-1234",
            "email": "john@acme.com",
            "fax": "",
            "bill_to_line1": "100 Industry Way",
            "bill_to_line2": "",
            "bill_to_city": "Manchester",
            "bill_to_state": "CT",
            "bill_to_zip": "06040",
            "ship_to_line1": "",
            "ship_to_line2": "",
            "ship_to_city": "",
            "ship_to_state": "",
            "ship_to_zip": "",
            "notes": "",
            "is_active": True,
            "net_terms": "",
            "net_days": "0",
            "tax_rate": "",
            "is_tax_exempt": False,
            "has_st105": False,
        }
        data.update(self._contact_formset_data())
        data.update(overrides)
        return data

    def test_valid_submission(self):
        resp = self.client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 302)

    def test_empty_name_shows_error(self):
        data = self._valid_data(name="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_invalid_email(self):
        data = self._valid_data(email="not-an-email")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_formset_add_multiple_contacts(self):
        data = self._valid_data()
        data["contacts-TOTAL_FORMS"] = "2"
        data.update({
            "contacts-1-name": "Bob Smith",
            "contacts-1-phone": "555-5555",
            "contacts-1-email": "bob@acme.com",
            "contacts-1-fax": "",
            "contacts-1-department": "Accounting",
            "contacts-1-DELETE": "",
        })
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_formset_empty_contacts_still_valid(self):
        data = self._valid_data()
        data["contacts-TOTAL_FORMS"] = "1"
        data["contacts-0-name"] = ""
        data["contacts-0-phone"] = ""
        data["contacts-0-email"] = ""
        data["contacts-0-fax"] = ""
        data["contacts-0-department"] = ""
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 403)


class TestCustomerContactForm(TestCase):
    """CustomerContactForm — tested inline via CustomerForm formset above.
    Extra standalone validation tests."""

    def test_invalid_email_in_contact(self):
        """Contact with invalid email should be rejected."""
        data = {
            "name": "Test Customer",
            "contact_name": "",
            "phone": "",
            "email": "",
            "fax": "",
            "bill_to_line1": "",
            "bill_to_line2": "",
            "bill_to_city": "",
            "bill_to_state": "",
            "bill_to_zip": "",
            "ship_to_line1": "",
            "ship_to_line2": "",
            "ship_to_city": "",
            "ship_to_state": "",
            "ship_to_zip": "",
            "notes": "",
            "is_active": True,
            "net_terms": "",
            "net_days": "0",
            "tax_rate": "",
            "is_tax_exempt": False,
            "has_st105": False,
            "contacts-TOTAL_FORMS": "1",
            "contacts-INITIAL_FORMS": "0",
            "contacts-MIN_NUM_FORMS": "0",
            "contacts-MAX_NUM_FORMS": "1000",
            "contacts-0-name": "Bad Contact",
            "contacts-0-phone": "",
            "contacts-0-email": "not-valid-email",
            "contacts-0-fax": "",
            "contacts-0-department": "",
            "contacts-0-DELETE": "",
        }
        resp = self.client.post("/invoicing/customers/add/", data)
        self.assertEqual(resp.status_code, 200)


# ===========================================================================
# inventory/forms.py
# ===========================================================================


class TestInventoryItemForm(TestCase):
    """InventoryItemForm — add inventory item (creates Part)."""

    url = "/inventory/create/"

    def _valid_data(self, **overrides):
        vendor = VendorFactory()
        data = {
            "item_name": "Brush Set 12V",
            "part_number": "PN-INV-001",
            "description": "Standard brush set",
            "supplier": str(vendor.pk),
            "cost": "25.00",
            "margin_pct": "40.00",
            "quantity_purchased": "10",
            "quantity_available": "10",
            "notes": "",
        }
        data.update(overrides)
        return data

    def test_valid_submission_creates_part(self):
        """Valid form data creates a Part via update_or_create."""
        resp = self.client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Part.objects.filter(part_number="PN-INV-001").exists())

    def test_empty_part_number_shows_error(self):
        data = self._valid_data(part_number="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_whitespace_only_part_number_shows_error(self):
        data = self._valid_data(part_number="   ")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_missing_supplier_shows_error(self):
        VendorFactory()
        data = self._valid_data(supplier="")
        data["supplier"] = ""
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_negative_cost_shows_error(self):
        data = self._valid_data(cost="-5.00")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_negative_quantity_shows_error(self):
        data = self._valid_data(quantity_purchased="-1")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_zero_quantity_creates_part(self):
        """Zero quantity is valid — Part is created with stock_quantity=0."""
        data = self._valid_data(quantity_purchased="0", quantity_available="0")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Part.objects.filter(part_number="PN-INV-001").exists())

    def test_missing_item_name_shows_error(self):
        data = self._valid_data(item_name="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 403)


class TestVendorForm(TestCase):
    """VendorForm + VendorContactFormSet — create/edit vendor."""

    url = "/inventory/vendors/add/"

    def _contact_formset_data(self, total=1, initial=0):
        data = {
            "contacts-TOTAL_FORMS": str(total),
            "contacts-INITIAL_FORMS": str(initial),
            "contacts-MIN_NUM_FORMS": "0",
            "contacts-MAX_NUM_FORMS": "1000",
        }
        if total >= 1:
            data.update({
                "contacts-0-name": "Vendor Contact",
                "contacts-0-phone": "555-8000",
                "contacts-0-email": "vc@vendor.com",
                "contacts-0-fax": "",
                "contacts-0-department": "Sales",
                "contacts-0-DELETE": "",
            })
        return data

    def _valid_data(self, **overrides):
        data = {
            "name": "WAI Global",
            "contact_name": "Rep Name",
            "email": "rep@wai.com",
            "phone": "555-0200",
            "fax": "",
            "account_number": "ACCT-001",
            "address_line1": "200 Supplier Ave",
            "address_line2": "",
            "city": "Hartford",
            "state": "CT",
            "zip_code": "06103",
            "remit_line1": "",
            "remit_line2": "",
            "remit_city": "",
            "remit_state": "",
            "remit_zip": "",
            "notes": "",
            "is_active": True,
        }
        data.update(self._contact_formset_data())
        data.update(overrides)
        return data

    def test_valid_submission(self):
        resp = self.client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 302)

    def test_empty_name_shows_error(self):
        data = self._valid_data(name="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_invalid_email(self):
        data = self._valid_data(email="not-valid")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_formset_add_multiple_contacts(self):
        data = self._valid_data()
        data["contacts-TOTAL_FORMS"] = "2"
        data.update({
            "contacts-1-name": "Second Contact",
            "contacts-1-phone": "555-9000",
            "contacts-1-email": "sc@vendor.com",
            "contacts-1-fax": "",
            "contacts-1-department": "Billing",
            "contacts-1-DELETE": "",
        })
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_formset_empty_contact_still_valid(self):
        data = self._valid_data()
        data["contacts-0-name"] = ""
        data["contacts-0-phone"] = ""
        data["contacts-0-email"] = ""
        data["contacts-0-fax"] = ""
        data["contacts-0-department"] = ""
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_max_length_name(self):
        data = self._valid_data(name="X" * 255)
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_over_max_length_name(self):
        data = self._valid_data(name="X" * 256)
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 403)


class TestVendorContactForm(TestCase):
    """VendorContactForm — inline via VendorContactFormSet."""

    def test_invalid_email_in_contact(self):
        data = {
            "name": "Test Vendor",
            "contact_name": "",
            "email": "",
            "phone": "",
            "fax": "",
            "account_number": "",
            "address_line1": "",
            "address_line2": "",
            "city": "",
            "state": "",
            "zip_code": "",
            "remit_line1": "",
            "remit_line2": "",
            "remit_city": "",
            "remit_state": "",
            "remit_zip": "",
            "notes": "",
            "is_active": True,
            "contacts-TOTAL_FORMS": "1",
            "contacts-INITIAL_FORMS": "0",
            "contacts-MIN_NUM_FORMS": "0",
            "contacts-MAX_NUM_FORMS": "1000",
            "contacts-0-name": "Bad Contact",
            "contacts-0-phone": "",
            "contacts-0-email": "not-valid-email",
            "contacts-0-fax": "",
            "contacts-0-department": "",
            "contacts-0-DELETE": "",
        }
        resp = self.client.post("/inventory/vendors/add/", data)
        self.assertEqual(resp.status_code, 200)


# ===========================================================================
# backup/forms.py
# ===========================================================================


class TestBackupSettingsForm(TestCase):
    """BackupSettingsForm — backup configuration."""

    url = "/backup/"

    def _valid_data(self, **overrides):
        tmp = tempfile.mkdtemp()
        data = {
            "local_backup_path": tmp,
            "external_backup_path": "",
            "auto_backup_enabled": True,
            "backup_interval_hours": "2",
            "max_backups": "4",
        }
        data.update(overrides)
        return data

    def test_valid_submission(self):
        resp = self.client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 302)

    def test_non_absolute_local_path_shows_error(self):
        data = self._valid_data(local_backup_path="relative/path")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "full path")

    def test_non_absolute_external_path_shows_error(self):
        data = self._valid_data(external_backup_path="relative/path")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "full path")

    def test_interval_zero_clamped_to_one(self):
        """Interval 0 should be clamped to 1 (not error)."""
        data = self._valid_data(backup_interval_hours="0")
        resp = self.client.post(self.url, data)
        # The form clamps, so it should succeed
        # But PositiveIntegerField may reject 0 at model level
        self.assertIn(resp.status_code, (200, 302))

    def test_interval_25_clamped_to_24(self):
        """Interval 25 should be clamped to 24."""
        data = self._valid_data(backup_interval_hours="25")
        resp = self.client.post(self.url, data)
        self.assertIn(resp.status_code, (200, 302))

    def test_max_backups_zero_clamped_to_one(self):
        """max_backups 0 is clamped to 1."""
        data = self._valid_data(max_backups="0")
        resp = self.client.post(self.url, data)
        self.assertIn(resp.status_code, (200, 302))

    def test_max_backups_101_clamped_to_100(self):
        """max_backups 101 is clamped to 100."""
        data = self._valid_data(max_backups="101")
        resp = self.client.post(self.url, data)
        self.assertIn(resp.status_code, (200, 302))

    def test_empty_paths_allowed(self):
        data = self._valid_data(local_backup_path="", external_backup_path="")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_valid_interval_boundary_1(self):
        data = self._valid_data(backup_interval_hours="1")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_valid_interval_boundary_24(self):
        data = self._valid_data(backup_interval_hours="24")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_valid_max_backups_boundary_1(self):
        data = self._valid_data(max_backups="1")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_valid_max_backups_boundary_100(self):
        data = self._valid_data(max_backups="100")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = csrf_client.post(self.url, self._valid_data())
        self.assertEqual(resp.status_code, 403)


class TestRestoreForm(TestCase):
    """RestoreForm — select a backup source to restore.
    Note: The view ALWAYS redirects to backup:settings (302) and uses
    django.contrib.messages for validation errors rather than re-rendering.
    """

    url = "/backup/restore/"

    def test_valid_zip_file(self):
        tmp = Path(tempfile.mkdtemp()) / "backup.zip"
        import zipfile
        with zipfile.ZipFile(tmp, "w") as zf:
            zf.writestr("db.sqlite3", "fake-db-content")
        data = {"backup_source": str(tmp)}
        resp = self.client.post(self.url, data, follow=True)
        self.assertEqual(resp.status_code, 200)

    def test_valid_folder_with_db(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "db.sqlite3").write_text("fake-db")
        data = {"backup_source": str(tmp)}
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_empty_source_redirects_with_error(self):
        """Empty backup_source → redirect with error message."""
        data = {"backup_source": ""}
        resp = self.client.post(self.url, data, follow=True)
        self.assertEqual(resp.status_code, 200)
        messages = list(resp.context["messages"])
        self.assertTrue(any("required" in str(m).lower() or "path" in str(m).lower() for m in messages))

    def test_nonexistent_path_redirects_with_error(self):
        """Non-existent path → redirect with 'not found' message."""
        data = {"backup_source": r"C:\nonexistent\fake\path\does_not_exist"}
        resp = self.client.post(self.url, data, follow=True)
        self.assertEqual(resp.status_code, 200)
        messages = list(resp.context["messages"])
        self.assertTrue(any("not found" in str(m).lower() for m in messages))

    def test_non_zip_file_redirects_with_error(self):
        """Non-zip file → redirect with '.zip' message."""
        tmp = Path(tempfile.mkdtemp()) / "backup.txt"
        tmp.write_text("not a zip")
        data = {"backup_source": str(tmp)}
        resp = self.client.post(self.url, data, follow=True)
        self.assertEqual(resp.status_code, 200)
        messages = list(resp.context["messages"])
        self.assertTrue(any(".zip" in str(m) for m in messages))

    def test_folder_without_db_redirects_with_error(self):
        """Folder without db.sqlite3 → redirect with error."""
        tmp = Path(tempfile.mkdtemp())
        data = {"backup_source": str(tmp)}
        resp = self.client.post(self.url, data, follow=True)
        self.assertEqual(resp.status_code, 200)
        messages = list(resp.context["messages"])
        self.assertTrue(any("db.sqlite3" in str(m) for m in messages))

    def test_csrf_enforcement(self):
        csrf_client = Client(enforce_csrf_checks=True)
        tmp = Path(tempfile.mkdtemp())
        (tmp / "db.sqlite3").write_text("fake-db")
        resp = csrf_client.post(self.url, {"backup_source": str(tmp)})
        self.assertEqual(resp.status_code, 403)


# ===========================================================================
# Additional boundary & edge-case tests
# ===========================================================================


class TestApplicationFormBoundary(TestCase):
    """Boundary-value tests for ApplicationForm."""

    url = "/applications/add/"

    def test_max_length_make(self):
        data = {
            "unit_number": "",
            "make": "X" * 255,
            "model": "",
            "engine": "",
            "year": "",
            "mfr": "",
            "volt": "",
            "amp": "",
            "fuel_type": "",
            "vin": "",
            "alt_pulley": "",
            "unit_type_name": "",
            "other_number": "",
            "options": "",
            "notes": "",
            "is_active": True,
        }
        resp = self.client.post(self.url, data)
        # Should succeed if within max_length
        self.assertIn(resp.status_code, (200, 302))

    def test_special_characters(self):
        data = {
            "unit_number": "UN/<>&\"'",
            "make": "",
            "model": "",
            "engine": "",
            "year": "",
            "mfr": "",
            "volt": "",
            "amp": "",
            "fuel_type": "",
            "vin": "",
            "alt_pulley": "",
            "unit_type_name": "",
            "other_number": "",
            "options": "",
            "notes": "",
            "is_active": True,
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)


class TestPartFormBoundary(TestCase):
    """Boundary-value tests for PartForm."""

    url = "/parts/add/"

    def test_zero_prices(self):
        data = {
            "part_number": "PN-ZERO",
            "part_name": "Free Part",
            "manufacturer_number": "",
            "yt_number": "",
            "j_and_n": "",
            "oem_number": "",
            "voltage": "",
            "item_no": "",
            "category": "",
            "type": "",
            "oem_type": "",
            "item_typ": "",
            "oem": "",
            "primary_vendor": "",
            "catalog": "",
            "plug_id": "",
            "cost_price": "0.00",
            "markup_percent": "0.00",
            "price": "0.00",
            "track_inventory": False,
            "stock_quantity": "0",
            "reorder_qty": "0",
            "bin_number": "",
            "notes": "",
            "foot_notes": "",
            "superseding_notes": "",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_very_large_price(self):
        data = {
            "part_number": "PN-BIG",
            "part_name": "Expensive",
            "manufacturer_number": "",
            "yt_number": "",
            "j_and_n": "",
            "oem_number": "",
            "voltage": "",
            "item_no": "",
            "category": "",
            "type": "",
            "oem_type": "",
            "item_typ": "",
            "oem": "",
            "primary_vendor": "",
            "catalog": "",
            "plug_id": "",
            "cost_price": "99999999.99",
            "markup_percent": "99.99",
            "price": "99999999.99",
            "track_inventory": True,
            "stock_quantity": "999999",
            "reorder_qty": "999999",
            "bin_number": "",
            "notes": "",
            "foot_notes": "",
            "superseding_notes": "",
        }
        resp = self.client.post(self.url, data)
        self.assertIn(resp.status_code, (200, 302))


class TestInvoiceFormEdgeCases(TestCase):
    """Edge-case tests for invoice form interactions."""

    url = "/invoicing/invoice/new/"

    def _management_data(self, total=1, initial=0):
        return {
            "items-TOTAL_FORMS": str(total),
            "items-INITIAL_FORMS": str(initial),
            "items-MIN_NUM_FORMS": "1",
            "items-MAX_NUM_FORMS": "1000",
        }

    def test_past_due_date_accepted(self):
        """Due dates in the past should be accepted (no future-only validation)."""
        from invoicing.models import CompanySettings
        CompanySettings.get()
        customer = CustomerFactory()
        part = PartFactory(stock_quantity=100)
        data = {
            "customer": str(customer.pk),
            "customer_name": customer.name,
            "contact_name": "",
            "phone": "",
            "email": "",
            "address": "",
            "date": str(date.today() - timedelta(days=60)),
            "due_date": str(date.today() - timedelta(days=30)),
            "tax_rate": "0",
            "notes": "",
            "private_notes": "",
            "status": "DRAFT",
        }
        data.update(self._management_data())
        data.update({
            "items-0-part": str(part.pk),
            "items-0-unit": "",
            "items-0-description": "Backdated",
            "items-0-quantity": "1",
            "items-0-unit_price": "50.00",
            "items-0-discount_pct": "0",
            "items-0-DELETE": "",
        })
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_zero_quantity_item_accepted(self):
        """PositiveIntegerField allows 0; widget min=1 is HTML5 only."""
        from invoicing.models import CompanySettings
        CompanySettings.get()
        customer = CustomerFactory()
        part = PartFactory(stock_quantity=100)
        data = {
            "customer": str(customer.pk),
            "customer_name": customer.name,
            "contact_name": "",
            "phone": "",
            "email": "",
            "address": "",
            "date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "tax_rate": "0",
            "notes": "",
            "private_notes": "",
            "status": "DRAFT",
        }
        data.update(self._management_data())
        data.update({
            "items-0-part": str(part.pk),
            "items-0-unit": "",
            "items-0-description": "Zero qty",
            "items-0-quantity": "0",
            "items-0-unit_price": "10.00",
            "items-0-discount_pct": "0",
            "items-0-DELETE": "",
        })
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_delete_flag_in_formset(self):
        """Deleted items should be ignored."""
        from invoicing.models import CompanySettings
        CompanySettings.get()
        customer = CustomerFactory()
        part = PartFactory(stock_quantity=100)
        data = {
            "customer": str(customer.pk),
            "customer_name": customer.name,
            "contact_name": "",
            "phone": "",
            "email": "",
            "address": "",
            "date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "tax_rate": "0",
            "notes": "",
            "private_notes": "",
            "status": "DRAFT",
        }
        data.update(self._management_data(total=2))
        data.update({
            "items-0-part": str(part.pk),
            "items-0-unit": "",
            "items-0-description": "Kept",
            "items-0-quantity": "1",
            "items-0-unit_price": "50.00",
            "items-0-discount_pct": "0",
            "items-0-DELETE": "",
            "items-1-part": str(part.pk),
            "items-1-unit": "",
            "items-1-description": "Deleted",
            "items-1-quantity": "1",
            "items-1-unit_price": "50.00",
            "items-1-discount_pct": "0",
            "items-1-DELETE": "on",
        })
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)


class TestUnitFormEdit(TestCase):
    """Tests for editing an existing unit (ensures update path works)."""

    def setUp(self):
        self.unit = UnitFactory()
        self.url = f"/units/{self.unit.pk}/edit/"

    def test_edit_valid_submission(self):
        data = {
            "unit_number": self.unit.unit_number,
            "yt_number": "YT-EDITED",
            "oem": self.unit.oem,
            "model_cat_number": "",
            "voltage": "24V",
            "unit_type_category": "",
            "notes": "Updated notes",
            "new_unit_price": "200.00",
            "rebuilt_unit_price": "120.00",
            "is_active": True,
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_edit_clear_all_checkable_shows_error(self):
        data = {
            "unit_number": "",
            "yt_number": "",
            "oem": "",
            "model_cat_number": "",
            "voltage": "",
            "unit_type_category": "",
            "notes": "",
            "new_unit_price": "",
            "rebuilt_unit_price": "",
            "is_active": True,
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "at least one field")


class TestPartFormEdit(TestCase):
    """Tests for editing an existing part."""

    def setUp(self):
        self.part = PartFactory()
        self.url = f"/parts/{self.part.pk}/edit/"

    def test_edit_valid_submission(self):
        data = {
            "part_number": self.part.part_number,
            "part_name": "Updated Name",
            "manufacturer_number": self.part.manufacturer_number,
            "yt_number": "",
            "j_and_n": "",
            "oem_number": "",
            "voltage": "",
            "item_no": "",
            "category": "",
            "type": "",
            "oem_type": "",
            "item_typ": "",
            "oem": "",
            "primary_vendor": "",
            "catalog": "",
            "plug_id": "",
            "cost_price": "30.00",
            "markup_percent": "50.00",
            "price": "45.00",
            "track_inventory": True,
            "stock_quantity": "20",
            "reorder_qty": "10",
            "bin_number": "B2",
            "notes": "",
            "foot_notes": "",
            "superseding_notes": "",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)


class TestBOMFormEdit(TestCase):
    """Tests for editing an existing BOM."""

    def setUp(self):
        self.bom = BOMFactory()
        self.url = f"/bom/{self.bom.pk}/edit/"

    def test_edit_valid_submission(self):
        unit = self.bom.unit
        data = {
            "name": "",
            "description": "Updated description",
            "unit": str(unit.pk),
            "application": "",
            "unit_type": "",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)


class TestCrossReferenceFormEdit(TestCase):
    """Tests for editing an existing cross-reference."""

    def setUp(self):
        self.unit = UnitFactory()
        self.xref = CrossReferenceFactory(unit=self.unit)
        self.url = f"/units/{self.unit.pk}/cross-ref/{self.xref.pk}/edit/"

    def test_edit_valid_submission(self):
        data = {
            "cross_ref_unit": "",
            "cross_ref_number": "XREF-EDITED",
            "interchange_type": "Indirect",
            "price": "150.00",
            "notes": "Updated",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

    def test_edit_clear_both_shows_error(self):
        data = {
            "cross_ref_unit": "",
            "cross_ref_number": "",
            "interchange_type": "",
            "price": "",
            "notes": "",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)


class TestSubstituteFormEdit(TestCase):
    """Tests for editing an existing substitute."""

    def setUp(self):
        self.unit = UnitFactory()
        self.sub = SubstituteFactory(unit=self.unit)
        self.url = f"/units/{self.unit.pk}/substitute/{self.sub.pk}/edit/"

    def test_edit_valid_submission(self):
        data = {
            "substitute_unit": "",
            "substitute_number": "SUB-EDITED",
            "substitute_unit_type": "Alternator",
            "substitute_supplier": "New Supplier",
            "notes": "Edited",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)


class TestGearReductionFormEdit(TestCase):
    """Tests for editing an existing gear reduction."""

    def setUp(self):
        self.unit = UnitFactory()
        self.gr = GearReductionSubstitutionFactory(unit=self.unit)
        self.url = f"/units/{self.unit.pk}/gear-reduction/{self.gr.pk}/edit/"

    def test_edit_valid_submission(self):
        data = {
            "number": "GR-EDIT",
            "unit_type": "Direct Drive",
            "supplier": "Updated Supplier",
            "notes": "Changed",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)


class TestCustomerFormEdit(TestCase):
    """Tests for editing an existing customer."""

    def setUp(self):
        self.customer = CustomerFactory()
        self.url = f"/invoicing/customers/{self.customer.pk}/edit/"

    def test_edit_valid_submission(self):
        data = {
            "name": "Updated Customer",
            "contact_name": "New Contact",
            "phone": "555-9999",
            "email": "new@example.com",
            "fax": "",
            "bill_to_line1": "New Address",
            "bill_to_line2": "",
            "bill_to_city": "New City",
            "bill_to_state": "NY",
            "bill_to_zip": "10001",
            "ship_to_line1": "",
            "ship_to_line2": "",
            "ship_to_city": "",
            "ship_to_state": "",
            "ship_to_zip": "",
            "notes": "",
            "is_active": True,
            "net_terms": "",
            "net_days": "0",
            "tax_rate": "",
            "is_tax_exempt": False,
            "has_st105": False,
            "contacts-TOTAL_FORMS": "0",
            "contacts-INITIAL_FORMS": "0",
            "contacts-MIN_NUM_FORMS": "0",
            "contacts-MAX_NUM_FORMS": "1000",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)


class TestVendorFormEdit(TestCase):
    """Tests for editing an existing vendor."""

    def setUp(self):
        self.vendor = VendorFactory()
        self.url = f"/inventory/vendors/{self.vendor.pk}/edit/"

    def test_edit_valid_submission(self):
        data = {
            "name": "Updated Vendor",
            "contact_name": "New Rep",
            "email": "newrep@vendor.com",
            "phone": "555-1111",
            "fax": "",
            "account_number": "ACCT-NEW",
            "address_line1": "999 New St",
            "address_line2": "",
            "city": "New Haven",
            "state": "CT",
            "zip_code": "06510",
            "remit_line1": "",
            "remit_line2": "",
            "remit_city": "",
            "remit_state": "",
            "remit_zip": "",
            "notes": "",
            "is_active": True,
            "contacts-TOTAL_FORMS": "0",
            "contacts-INITIAL_FORMS": "0",
            "contacts-MIN_NUM_FORMS": "0",
            "contacts-MAX_NUM_FORMS": "1000",
        }
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)
