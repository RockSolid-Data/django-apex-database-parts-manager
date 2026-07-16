"""
Phase 2 — CRUD Tests
Create / Read / Update / Delete for every model via the web views.
No authentication — all views are open.
"""

import os
from datetime import date
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")

from django.test import TestCase
from django.urls import reverse

from catalog.models import (
    Application,
    ApplicationSpecification,
    ApplicationType,
    ApplicationTypeField,
    ApplicationUnit,
    BOM,
    BOMItem,
    CrossReference,
    GearReductionSubstitution,
    Part,
    PartCategory,
    PartCategoryField,
    PartInterchange,
    PartSubstitute,
    PartSuperseding,
    Substitute,
    Unit,
    UnitType,
    UnitTypeCategory,
    UnitTypeCategoryField,
)
from invoicing.models import CompanySettings, Customer, CustomerContact, Invoice, InvoiceItem
from inventory.models import Vendor, VendorContact
from backup.models import BackupSettings

from tests.e2e.factories import (
    ApplicationFactory,
    ApplicationSpecificationFactory,
    ApplicationUnitFactory,
    BackupSettingsFactory,
    BOMFactory,
    BOMItemFactory,
    CompanySettingsFactory,
    CrossReferenceFactory,
    CustomerFactory,
    GearReductionSubstitutionFactory,
    InvoiceFactory,
    InvoiceItemFactory,
    PartCategoryFactory,
    PartFactory,
    PartInterchangeFactory,
    PartSubstituteFactory,
    PartSupersedingFactory,
    SubstituteFactory,
    UnitFactory,
    UnitTypeCategoryFactory,
    VendorFactory,
)


# ═══════════════════════════════════════════════════════════════════════════
#  1. Application CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestApplicationCRUD(TestCase):

    # -- CREATE --

    def test_create_valid(self):
        data = {"make": "Caterpillar", "model": "3406", "engine": "Diesel"}
        resp = self.client.post(reverse("catalog:application_create"), data)
        self.assertEqual(Application.objects.count(), 1)
        app = Application.objects.first()
        self.assertRedirects(resp, reverse("catalog:application_detail", args=[app.pk]))
        self.assertEqual(app.make, "Caterpillar")
        self.assertIn("Caterpillar", app.name)

    def test_create_missing_all_checkable_fields(self):
        resp = self.client.post(reverse("catalog:application_create"), {})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Application.objects.count(), 0)

    def test_create_with_only_unit_number(self):
        data = {"unit_number": "APP-001"}
        resp = self.client.post(reverse("catalog:application_create"), data)
        self.assertEqual(Application.objects.count(), 1)

    # -- READ --

    def test_detail_existing(self):
        app = ApplicationFactory()
        resp = self.client.get(reverse("catalog:application_detail", args=[app.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, app.name)

    def test_detail_nonexistent(self):
        resp = self.client.get(reverse("catalog:application_detail", args=[99999]))
        self.assertEqual(resp.status_code, 404)

    def test_list(self):
        ApplicationFactory.create_batch(3)
        resp = self.client.get(reverse("catalog:application_list"))
        self.assertEqual(resp.status_code, 200)

    # -- UPDATE --

    def test_edit_valid(self):
        app = ApplicationFactory()
        data = {
            "make": "John Deere",
            "model": app.model,
            "engine": app.engine,
            "year": app.year,
            "mfr": app.mfr,
            "volt": app.volt,
        }
        resp = self.client.post(reverse("catalog:application_edit", args=[app.pk]), data)
        self.assertRedirects(resp, reverse("catalog:application_detail", args=[app.pk]))
        app.refresh_from_db()
        self.assertEqual(app.make, "John Deere")

    def test_edit_invalid_empty_fields(self):
        app = ApplicationFactory()
        resp = self.client.post(reverse("catalog:application_edit", args=[app.pk]), {})
        self.assertEqual(resp.status_code, 200)

    # -- DELETE --

    def test_delete_existing(self):
        app = ApplicationFactory()
        resp = self.client.post(reverse("catalog:application_delete", args=[app.pk]))
        self.assertRedirects(resp, reverse("catalog:application_list"))
        self.assertEqual(Application.objects.count(), 0)

    def test_delete_cascades_specs(self):
        app = ApplicationFactory()
        ApplicationSpecificationFactory(application=app)
        app.delete()
        self.assertEqual(ApplicationSpecification.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════
#  2. Unit CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestUnitCRUD(TestCase):

    # -- CREATE --

    def test_create_valid(self):
        data = {"unit_number": "UN-NEW-001", "oem": "Bosch", "voltage": "12V"}
        resp = self.client.post(reverse("catalog:unit_create"), data)
        self.assertRedirects(resp, reverse("catalog:unit_list"))
        self.assertEqual(Unit.objects.count(), 1)
        self.assertEqual(Unit.objects.first().unit_number, "UN-NEW-001")

    def test_create_missing_all_checkable_fields(self):
        resp = self.client.post(reverse("catalog:unit_create"), {})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Unit.objects.count(), 0)

    def test_create_with_only_yt_number(self):
        data = {"yt_number": "YT-5000"}
        resp = self.client.post(reverse("catalog:unit_create"), data)
        self.assertEqual(Unit.objects.count(), 1)

    def test_create_duplicate_unit_number(self):
        UnitFactory(unit_number="DUP-001")
        data = {"unit_number": "DUP-001"}
        resp = self.client.post(reverse("catalog:unit_create"), data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Unit.objects.count(), 1)

    # -- READ --

    def test_detail_existing(self):
        unit = UnitFactory()
        resp = self.client.get(reverse("catalog:unit_detail", args=[unit.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_detail_nonexistent(self):
        resp = self.client.get(reverse("catalog:unit_detail", args=[99999]))
        self.assertEqual(resp.status_code, 404)

    def test_list(self):
        UnitFactory.create_batch(3)
        resp = self.client.get(reverse("catalog:unit_list"))
        self.assertEqual(resp.status_code, 200)

    # -- UPDATE --

    def test_edit_valid(self):
        unit = UnitFactory()
        data = {
            "unit_number": unit.unit_number,
            "oem": "Updated OEM",
            "voltage": "24V",
        }
        resp = self.client.post(reverse("catalog:unit_edit", args=[unit.pk]), data)
        self.assertRedirects(resp, reverse("catalog:unit_detail", args=[unit.pk]))
        unit.refresh_from_db()
        self.assertEqual(unit.oem, "Updated OEM")
        self.assertEqual(unit.voltage, "24V")

    def test_edit_invalid(self):
        unit = UnitFactory()
        resp = self.client.post(reverse("catalog:unit_edit", args=[unit.pk]), {})
        self.assertEqual(resp.status_code, 200)

    # -- DELETE --

    def test_delete_existing(self):
        unit = UnitFactory()
        resp = self.client.post(reverse("catalog:unit_delete", args=[unit.pk]))
        self.assertRedirects(resp, reverse("catalog:unit_list"))
        self.assertEqual(Unit.objects.count(), 0)

    def test_delete_cascades_cross_refs(self):
        unit = UnitFactory()
        CrossReferenceFactory(unit=unit)
        unit.delete()
        self.assertEqual(CrossReference.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════
#  3. Part CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestPartCRUD(TestCase):

    # -- CREATE --

    def test_create_valid(self):
        data = {"part_number": "PN-NEW-001", "part_name": "Test Brush"}
        resp = self.client.post(reverse("catalog:part_create"), data)
        self.assertEqual(Part.objects.count(), 1)
        part = Part.objects.first()
        self.assertRedirects(resp, reverse("catalog:part_detail", args=[part.pk]))
        self.assertEqual(part.part_number, "PN-NEW-001")

    def test_create_missing_all_checkable_fields(self):
        resp = self.client.post(reverse("catalog:part_create"), {})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Part.objects.count(), 0)

    def test_create_duplicate_part_number(self):
        PartFactory(part_number="DUP-PN")
        data = {"part_number": "DUP-PN", "part_name": "Duplicate"}
        resp = self.client.post(reverse("catalog:part_create"), data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Part.objects.count(), 1)

    # -- READ --

    def test_detail_existing(self):
        part = PartFactory()
        resp = self.client.get(reverse("catalog:part_detail", args=[part.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_detail_nonexistent(self):
        resp = self.client.get(reverse("catalog:part_detail", args=[99999]))
        self.assertEqual(resp.status_code, 404)

    def test_list(self):
        PartFactory.create_batch(3)
        resp = self.client.get(reverse("catalog:part_list"))
        self.assertEqual(resp.status_code, 200)

    # -- UPDATE --

    def test_edit_valid(self):
        part = PartFactory()
        data = {
            "part_number": part.part_number,
            "part_name": "Updated Name",
            "manufacturer_number": part.manufacturer_number,
        }
        resp = self.client.post(reverse("catalog:part_edit", args=[part.pk]), data)
        self.assertRedirects(resp, reverse("catalog:part_detail", args=[part.pk]))
        part.refresh_from_db()
        self.assertEqual(part.part_name, "Updated Name")

    def test_edit_invalid(self):
        part = PartFactory()
        resp = self.client.post(reverse("catalog:part_edit", args=[part.pk]), {})
        self.assertEqual(resp.status_code, 200)

    # -- DELETE --

    def test_delete_existing(self):
        part = PartFactory()
        resp = self.client.post(reverse("catalog:part_delete", args=[part.pk]))
        self.assertRedirects(resp, reverse("catalog:part_list"))
        self.assertEqual(Part.objects.count(), 0)

    def test_delete_cascades_bom_items(self):
        part = PartFactory()
        BOMItemFactory(part=part)
        part.delete()
        self.assertEqual(BOMItem.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════
#  4. BOM CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestBOMCRUD(TestCase):

    # -- CREATE --

    def test_create_valid(self):
        unit = UnitFactory()
        data = {"unit": unit.pk, "description": "Test BOM"}
        resp = self.client.post(reverse("catalog:bom_create"), data)
        self.assertEqual(BOM.objects.count(), 1)
        bom = BOM.objects.first()
        self.assertRedirects(resp, reverse("catalog:bom_detail", args=[bom.pk]))
        self.assertEqual(bom.unit, unit)

    def test_create_no_unit(self):
        data = {"description": "Orphan BOM"}
        resp = self.client.post(reverse("catalog:bom_create"), data)
        self.assertEqual(BOM.objects.count(), 1)

    # -- READ --

    def test_detail_existing(self):
        bom = BOMFactory()
        resp = self.client.get(reverse("catalog:bom_detail", args=[bom.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_detail_nonexistent(self):
        resp = self.client.get(reverse("catalog:bom_detail", args=[99999]))
        self.assertEqual(resp.status_code, 404)

    def test_list(self):
        BOMFactory.create_batch(3)
        resp = self.client.get(reverse("catalog:bom_list"))
        self.assertEqual(resp.status_code, 200)

    # -- UPDATE --

    def test_edit_valid(self):
        bom = BOMFactory()
        new_unit = UnitFactory()
        data = {"unit": new_unit.pk, "description": "Updated desc"}
        resp = self.client.post(reverse("catalog:bom_edit", args=[bom.pk]), data)
        self.assertRedirects(resp, reverse("catalog:bom_detail", args=[bom.pk]))
        bom.refresh_from_db()
        self.assertEqual(bom.unit, new_unit)

    # -- DELETE --

    def test_delete_existing(self):
        bom = BOMFactory()
        resp = self.client.post(reverse("catalog:bom_delete", args=[bom.pk]))
        self.assertRedirects(resp, reverse("catalog:bom_list"))
        self.assertEqual(BOM.objects.count(), 0)

    def test_delete_cascades_items(self):
        bom = BOMFactory()
        BOMItemFactory(bom=bom)
        bom.delete()
        self.assertEqual(BOMItem.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════
#  5. BOMItem CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestBOMItemCRUD(TestCase):

    # -- CREATE --

    def test_add_part_valid(self):
        bom = BOMFactory()
        part = PartFactory()
        data = {"part": part.pk, "unit_qty": 3}
        resp = self.client.post(reverse("catalog:bom_item_add", args=[bom.pk]), data)
        self.assertRedirects(resp, reverse("catalog:bom_edit", args=[bom.pk]))
        self.assertEqual(BOMItem.objects.count(), 1)
        item = BOMItem.objects.first()
        self.assertEqual(item.part, part)
        self.assertEqual(item.unit_qty, 3)

    def test_add_part_missing_part(self):
        bom = BOMFactory()
        data = {"unit_qty": 1}
        resp = self.client.post(reverse("catalog:bom_item_add", args=[bom.pk]), data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(BOMItem.objects.count(), 0)

    # -- READ --

    def test_item_detail(self):
        item = BOMItemFactory()
        resp = self.client.get(
            reverse("catalog:bom_item_detail", args=[item.bom.pk, item.pk])
        )
        self.assertEqual(resp.status_code, 200)

    def test_item_detail_nonexistent(self):
        bom = BOMFactory()
        resp = self.client.get(reverse("catalog:bom_item_detail", args=[bom.pk, 99999]))
        self.assertEqual(resp.status_code, 404)

    # -- UPDATE --

    def test_edit_item(self):
        item = BOMItemFactory()
        data = {"part": item.part.pk, "unit_qty": 10}
        resp = self.client.post(
            reverse("catalog:bom_item_edit", args=[item.bom.pk, item.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:bom_edit", args=[item.bom.pk]))
        item.refresh_from_db()
        self.assertEqual(item.unit_qty, 10)

    # -- DELETE --

    def test_delete_item(self):
        item = BOMItemFactory()
        bom_pk = item.bom.pk
        resp = self.client.post(
            reverse("catalog:bom_item_delete", args=[item.bom.pk, item.pk])
        )
        self.assertRedirects(resp, reverse("catalog:bom_edit", args=[bom_pk]))
        self.assertEqual(BOMItem.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════
#  6. CrossReference CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestCrossReferenceCRUD(TestCase):

    # -- CREATE --

    def test_create_with_number(self):
        unit = UnitFactory()
        data = {
            "cross_ref_number": "XREF-999",
            "interchange_type": "OEM",
            "price": "120.00",
        }
        resp = self.client.post(
            reverse("catalog:cross_reference_add", args=[unit.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:unit_detail", args=[unit.pk]))
        self.assertEqual(CrossReference.objects.count(), 1)

    def test_create_with_unit(self):
        unit = UnitFactory()
        other = UnitFactory()
        data = {"cross_ref_unit": other.pk, "interchange_type": "Direct"}
        resp = self.client.post(
            reverse("catalog:cross_reference_add", args=[unit.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:unit_detail", args=[unit.pk]))
        self.assertEqual(CrossReference.objects.count(), 1)

    def test_create_missing_both(self):
        unit = UnitFactory()
        data = {"interchange_type": "OEM"}
        resp = self.client.post(
            reverse("catalog:cross_reference_add", args=[unit.pk]), data
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(CrossReference.objects.count(), 0)

    # -- READ --

    def test_detail(self):
        cr = CrossReferenceFactory()
        resp = self.client.get(
            reverse("catalog:cross_reference_detail", args=[cr.unit.pk, cr.pk])
        )
        self.assertEqual(resp.status_code, 200)

    # -- UPDATE --

    def test_edit_valid(self):
        cr = CrossReferenceFactory()
        data = {
            "cross_ref_number": "UPDATED-XREF",
            "interchange_type": cr.interchange_type,
        }
        resp = self.client.post(
            reverse("catalog:cross_reference_edit", args=[cr.unit.pk, cr.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:unit_detail", args=[cr.unit.pk]))
        cr.refresh_from_db()
        self.assertEqual(cr.cross_ref_number, "UPDATED-XREF")

    # -- DELETE --

    def test_delete(self):
        cr = CrossReferenceFactory()
        unit_pk = cr.unit.pk
        resp = self.client.post(
            reverse("catalog:cross_reference_delete", args=[cr.unit.pk, cr.pk])
        )
        self.assertRedirects(resp, reverse("catalog:unit_detail", args=[unit_pk]))
        self.assertEqual(CrossReference.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════
#  7. Substitute CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestSubstituteCRUD(TestCase):

    # -- CREATE --

    def test_create_with_number(self):
        unit = UnitFactory()
        data = {"substitute_number": "SUB-001", "substitute_unit_type": "Starter"}
        resp = self.client.post(
            reverse("catalog:substitute_add", args=[unit.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:unit_detail", args=[unit.pk]))
        self.assertEqual(Substitute.objects.count(), 1)

    def test_create_with_unit(self):
        unit = UnitFactory()
        other = UnitFactory()
        data = {"substitute_unit": other.pk}
        resp = self.client.post(
            reverse("catalog:substitute_add", args=[unit.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:unit_detail", args=[unit.pk]))
        self.assertEqual(Substitute.objects.count(), 1)

    def test_create_missing_both(self):
        unit = UnitFactory()
        resp = self.client.post(reverse("catalog:substitute_add", args=[unit.pk]), {})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Substitute.objects.count(), 0)

    # -- UPDATE --

    def test_edit_valid(self):
        sub = SubstituteFactory()
        data = {
            "substitute_number": "SUB-UPDATED",
            "substitute_unit_type": "Alternator",
        }
        resp = self.client.post(
            reverse("catalog:substitute_edit", args=[sub.unit.pk, sub.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:unit_detail", args=[sub.unit.pk]))
        sub.refresh_from_db()
        self.assertEqual(sub.substitute_number, "SUB-UPDATED")

    # -- DELETE --

    def test_delete(self):
        sub = SubstituteFactory()
        unit_pk = sub.unit.pk
        resp = self.client.post(
            reverse("catalog:substitute_delete", args=[sub.unit.pk, sub.pk])
        )
        self.assertRedirects(resp, reverse("catalog:unit_detail", args=[unit_pk]))
        self.assertEqual(Substitute.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════
#  8. GearReductionSubstitution CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestGearReductionCRUD(TestCase):

    # -- CREATE --

    def test_create_valid(self):
        unit = UnitFactory()
        data = {"number": "GR-001", "unit_type": "Gear Reduction", "supplier": "Acme"}
        resp = self.client.post(
            reverse("catalog:gear_reduction_add", args=[unit.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:unit_detail", args=[unit.pk]))
        self.assertEqual(GearReductionSubstitution.objects.count(), 1)
        gr = GearReductionSubstitution.objects.first()
        self.assertEqual(gr.number, "GR-001")

    def test_create_empty(self):
        unit = UnitFactory()
        data = {}
        resp = self.client.post(
            reverse("catalog:gear_reduction_add", args=[unit.pk]), data
        )
        self.assertEqual(GearReductionSubstitution.objects.count(), 1)

    # -- UPDATE --

    def test_edit_valid(self):
        gr = GearReductionSubstitutionFactory()
        data = {"number": "GR-UPDATED", "unit_type": "Updated Type"}
        resp = self.client.post(
            reverse("catalog:gear_reduction_edit", args=[gr.unit.pk, gr.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:unit_detail", args=[gr.unit.pk]))
        gr.refresh_from_db()
        self.assertEqual(gr.number, "GR-UPDATED")

    # -- DELETE --

    def test_delete(self):
        gr = GearReductionSubstitutionFactory()
        unit_pk = gr.unit.pk
        resp = self.client.post(
            reverse("catalog:gear_reduction_delete", args=[gr.unit.pk, gr.pk])
        )
        self.assertRedirects(resp, reverse("catalog:unit_detail", args=[unit_pk]))
        self.assertEqual(GearReductionSubstitution.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════
#  9. PartSubstitute CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestPartSubstituteCRUD(TestCase):

    # -- CREATE --

    def test_create_with_number(self):
        part = PartFactory()
        data = {"substitute_number": "SUB-PN-001"}
        resp = self.client.post(
            reverse("catalog:part_substitute_add", args=[part.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:part_detail", args=[part.pk]))
        self.assertEqual(PartSubstitute.objects.count(), 1)

    def test_create_with_part(self):
        part = PartFactory()
        other = PartFactory()
        data = {"substitute_part": other.pk}
        resp = self.client.post(
            reverse("catalog:part_substitute_add", args=[part.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:part_detail", args=[part.pk]))
        self.assertEqual(PartSubstitute.objects.count(), 1)

    def test_create_missing_both(self):
        part = PartFactory()
        resp = self.client.post(
            reverse("catalog:part_substitute_add", args=[part.pk]), {}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PartSubstitute.objects.count(), 0)

    # -- UPDATE --

    def test_edit_valid(self):
        ps = PartSubstituteFactory()
        data = {"substitute_number": "SUB-UPDATED"}
        resp = self.client.post(
            reverse("catalog:part_substitute_edit", args=[ps.part.pk, ps.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:part_detail", args=[ps.part.pk]))
        ps.refresh_from_db()
        self.assertEqual(ps.substitute_number, "SUB-UPDATED")

    # -- DELETE --

    def test_delete(self):
        ps = PartSubstituteFactory()
        part_pk = ps.part.pk
        resp = self.client.post(
            reverse("catalog:part_substitute_delete", args=[ps.part.pk, ps.pk])
        )
        self.assertRedirects(resp, reverse("catalog:part_detail", args=[part_pk]))
        self.assertEqual(PartSubstitute.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 10. PartInterchange CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestPartInterchangeCRUD(TestCase):

    # -- CREATE --

    def test_create_with_number(self):
        part = PartFactory()
        data = {"interchange_number": "IX-001", "source_name": "OEM"}
        resp = self.client.post(
            reverse("catalog:part_interchange_add", args=[part.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:part_detail", args=[part.pk]))
        self.assertEqual(PartInterchange.objects.count(), 1)

    def test_create_with_part(self):
        part = PartFactory()
        other = PartFactory()
        data = {"interchange_part": other.pk, "source_name": "Direct"}
        resp = self.client.post(
            reverse("catalog:part_interchange_add", args=[part.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:part_detail", args=[part.pk]))
        self.assertEqual(PartInterchange.objects.count(), 1)

    def test_create_missing_both(self):
        part = PartFactory()
        resp = self.client.post(
            reverse("catalog:part_interchange_add", args=[part.pk]), {}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PartInterchange.objects.count(), 0)

    # -- UPDATE --

    def test_edit_valid(self):
        pi = PartInterchangeFactory()
        data = {
            "interchange_number": "IX-UPDATED",
            "source_name": pi.source_name,
        }
        resp = self.client.post(
            reverse("catalog:part_interchange_edit", args=[pi.part.pk, pi.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:part_detail", args=[pi.part.pk]))
        pi.refresh_from_db()
        self.assertEqual(pi.interchange_number, "IX-UPDATED")

    # -- DELETE --

    def test_delete(self):
        pi = PartInterchangeFactory()
        part_pk = pi.part.pk
        resp = self.client.post(
            reverse("catalog:part_interchange_delete", args=[pi.part.pk, pi.pk])
        )
        self.assertRedirects(resp, reverse("catalog:part_detail", args=[part_pk]))
        self.assertEqual(PartInterchange.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 11. PartSuperseding CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestPartSupersedingCRUD(TestCase):

    # -- CREATE --

    def test_create_with_number(self):
        part = PartFactory()
        data = {"old_part_number": "OLD-PN-001"}
        resp = self.client.post(
            reverse("catalog:part_superseding_add", args=[part.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:part_detail", args=[part.pk]))
        self.assertEqual(PartSuperseding.objects.count(), 1)

    def test_create_with_old_part_link(self):
        part = PartFactory()
        old = PartFactory()
        data = {"old_part": old.pk, "old_part_number": old.part_number}
        resp = self.client.post(
            reverse("catalog:part_superseding_add", args=[part.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:part_detail", args=[part.pk]))
        self.assertEqual(PartSuperseding.objects.count(), 1)

    def test_create_missing_both(self):
        part = PartFactory()
        resp = self.client.post(
            reverse("catalog:part_superseding_add", args=[part.pk]), {}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PartSuperseding.objects.count(), 0)

    # -- UPDATE --

    def test_edit_valid(self):
        ps = PartSupersedingFactory(old_part=None)
        data = {"old_part_number": "OLD-UPDATED"}
        resp = self.client.post(
            reverse("catalog:part_superseding_edit", args=[ps.part.pk, ps.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:part_detail", args=[ps.part.pk]))
        ps.refresh_from_db()
        self.assertEqual(ps.old_part_number, "OLD-UPDATED")

    # -- DELETE --

    def test_delete(self):
        ps = PartSupersedingFactory()
        part_pk = ps.part.pk
        resp = self.client.post(
            reverse("catalog:part_superseding_delete", args=[ps.part.pk, ps.pk])
        )
        self.assertRedirects(resp, reverse("catalog:part_detail", args=[part_pk]))
        self.assertEqual(PartSuperseding.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 12. ApplicationSpecification CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestApplicationSpecificationCRUD(TestCase):

    # -- CREATE --

    def test_create_valid(self):
        app = ApplicationFactory()
        data = {"category": "Engine", "type": "Power", "specification": "500HP"}
        resp = self.client.post(
            reverse("catalog:application_spec_add", args=[app.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:application_detail", args=[app.pk]))
        self.assertEqual(ApplicationSpecification.objects.count(), 1)
        spec = ApplicationSpecification.objects.first()
        self.assertEqual(spec.category, "Engine")
        self.assertEqual(spec.specification, "500HP")

    def test_create_empty_fields(self):
        app = ApplicationFactory()
        data = {"category": "", "type": "", "specification": ""}
        resp = self.client.post(
            reverse("catalog:application_spec_add", args=[app.pk]), data
        )
        self.assertEqual(ApplicationSpecification.objects.count(), 1)

    # -- UPDATE --

    def test_edit_valid(self):
        spec = ApplicationSpecificationFactory()
        data = {"category": "Updated Cat", "type": "Updated Type", "specification": "Updated Spec"}
        resp = self.client.post(
            reverse("catalog:application_spec_edit", args=[spec.application.pk, spec.pk]),
            data,
        )
        self.assertRedirects(
            resp, reverse("catalog:application_detail", args=[spec.application.pk])
        )
        spec.refresh_from_db()
        self.assertEqual(spec.category, "Updated Cat")

    # -- DELETE --

    def test_delete(self):
        spec = ApplicationSpecificationFactory()
        app_pk = spec.application.pk
        resp = self.client.post(
            reverse("catalog:application_spec_delete", args=[spec.application.pk, spec.pk])
        )
        self.assertRedirects(resp, reverse("catalog:application_detail", args=[app_pk]))
        self.assertEqual(ApplicationSpecification.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 13. ApplicationUnit (link/unlink) CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestApplicationUnitCRUD(TestCase):

    # -- LINK (CREATE) --

    def test_link_unit(self):
        app = ApplicationFactory()
        unit = UnitFactory()
        data = {"unit": unit.pk, "position": "Front"}
        resp = self.client.post(
            reverse("catalog:application_link_unit", args=[app.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:application_detail", args=[app.pk]))
        self.assertEqual(ApplicationUnit.objects.count(), 1)
        au = ApplicationUnit.objects.first()
        self.assertEqual(au.unit, unit)
        self.assertEqual(au.application, app)

    def test_link_unit_missing(self):
        app = ApplicationFactory()
        resp = self.client.post(
            reverse("catalog:application_link_unit", args=[app.pk]), {}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ApplicationUnit.objects.count(), 0)

    def test_link_duplicate_raises_integrity_error(self):
        """View does not validate unique_together — duplicate link raises IntegrityError."""
        au = ApplicationUnitFactory()
        data = {"unit": au.unit.pk, "position": "Rear"}
        with self.assertRaises(Exception):
            self.client.post(
                reverse("catalog:application_link_unit", args=[au.application.pk]),
                data,
            )

    # -- UNLINK (DELETE) --

    def test_unlink_unit(self):
        au = ApplicationUnitFactory()
        resp = self.client.post(
            reverse(
                "catalog:application_unlink_unit",
                args=[au.application.pk, au.unit.pk],
            )
        )
        self.assertRedirects(
            resp, reverse("catalog:application_detail", args=[au.application.pk])
        )
        self.assertEqual(ApplicationUnit.objects.count(), 0)

    def test_unlink_nonexistent(self):
        app = ApplicationFactory()
        resp = self.client.post(
            reverse("catalog:application_unlink_unit", args=[app.pk, 99999])
        )
        self.assertEqual(resp.status_code, 404)


# ═══════════════════════════════════════════════════════════════════════════
# 14. UnitTypeCategory CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestUnitTypeCategoryCRUD(TestCase):

    # -- CREATE --

    def test_create_valid(self):
        before = UnitTypeCategory.objects.count()
        before_fields = UnitTypeCategoryField.objects.count()
        data = {
            "name": "Turbocharger E2E",
            "field_name": ["yt_number", "oem"],
            "field_label": ["YT Number", "OEM"],
        }
        resp = self.client.post(reverse("catalog:unit_type_category_create"), data)
        self.assertRedirects(resp, reverse("catalog:unit_type_category_list"))
        self.assertEqual(UnitTypeCategory.objects.count(), before + 1)
        self.assertEqual(UnitTypeCategoryField.objects.count(), before_fields + 2)

    def test_create_missing_name(self):
        before = UnitTypeCategory.objects.count()
        data = {"name": ""}
        resp = self.client.post(reverse("catalog:unit_type_category_create"), data)
        self.assertRedirects(resp, reverse("catalog:unit_type_category_create"))
        self.assertEqual(UnitTypeCategory.objects.count(), before)

    def test_create_duplicate_name(self):
        UnitTypeCategoryFactory(name="E2E Motor")
        before = UnitTypeCategory.objects.count()
        data = {"name": "E2E Motor"}
        resp = self.client.post(reverse("catalog:unit_type_category_create"), data)
        self.assertRedirects(resp, reverse("catalog:unit_type_category_create"))
        self.assertEqual(UnitTypeCategory.objects.count(), before)

    # -- READ --

    def test_detail(self):
        cat = UnitTypeCategoryFactory()
        resp = self.client.get(
            reverse("catalog:unit_type_category_detail", args=[cat.pk])
        )
        self.assertEqual(resp.status_code, 200)

    def test_list(self):
        UnitTypeCategoryFactory.create_batch(3)
        resp = self.client.get(reverse("catalog:unit_type_category_list"))
        self.assertEqual(resp.status_code, 200)

    # -- UPDATE --

    def test_edit_valid(self):
        cat = UnitTypeCategoryFactory(name="E2E Editable UTC")
        data = {
            "name": "E2E Renamed UTC",
            "field_name": ["yt_number"],
            "field_label": ["YT Num"],
        }
        resp = self.client.post(
            reverse("catalog:unit_type_category_edit", args=[cat.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:unit_type_category_list"))
        cat.refresh_from_db()
        self.assertEqual(cat.name, "E2E Renamed UTC")

    def test_edit_duplicate_name(self):
        UnitTypeCategoryFactory(name="E2E Existing UTC")
        cat = UnitTypeCategoryFactory()
        data = {"name": "E2E Existing UTC"}
        resp = self.client.post(
            reverse("catalog:unit_type_category_edit", args=[cat.pk]), data
        )
        self.assertRedirects(
            resp, reverse("catalog:unit_type_category_edit", args=[cat.pk])
        )

    # -- DELETE --

    def test_delete(self):
        cat = UnitTypeCategoryFactory(name="E2E Deletable UTC")
        before = UnitTypeCategory.objects.count()
        resp = self.client.post(
            reverse("catalog:unit_type_category_delete", args=[cat.pk])
        )
        self.assertRedirects(resp, reverse("catalog:unit_type_category_list"))
        self.assertEqual(UnitTypeCategory.objects.count(), before - 1)
        self.assertFalse(UnitTypeCategory.objects.filter(pk=cat.pk).exists())


# ═══════════════════════════════════════════════════════════════════════════
# 15. PartCategory CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestPartCategoryCRUD(TestCase):

    # -- CREATE --

    def test_create_valid(self):
        before = PartCategory.objects.count()
        before_fields = PartCategoryField.objects.count()
        data = {
            "name": "E2E Widgets",
            "field_name": ["part_number", "part_name"],
            "field_label": ["Part Number", "Part Name"],
        }
        resp = self.client.post(reverse("catalog:part_category_create"), data)
        self.assertRedirects(resp, reverse("catalog:part_category_list"))
        self.assertEqual(PartCategory.objects.count(), before + 1)
        self.assertEqual(PartCategoryField.objects.count(), before_fields + 2)

    def test_create_missing_name(self):
        before = PartCategory.objects.count()
        data = {"name": ""}
        resp = self.client.post(reverse("catalog:part_category_create"), data)
        self.assertRedirects(resp, reverse("catalog:part_category_create"))
        self.assertEqual(PartCategory.objects.count(), before)

    def test_create_duplicate_name(self):
        PartCategoryFactory(name="E2E DupCat")
        before = PartCategory.objects.count()
        data = {"name": "E2E DupCat"}
        resp = self.client.post(reverse("catalog:part_category_create"), data)
        self.assertRedirects(resp, reverse("catalog:part_category_create"))
        self.assertEqual(PartCategory.objects.count(), before)

    # -- READ --

    def test_detail(self):
        cat = PartCategoryFactory()
        resp = self.client.get(reverse("catalog:part_category_detail", args=[cat.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_list(self):
        PartCategoryFactory.create_batch(2)
        resp = self.client.get(reverse("catalog:part_category_list"))
        self.assertEqual(resp.status_code, 200)

    # -- UPDATE --

    def test_edit_valid(self):
        cat = PartCategoryFactory(name="E2E EditCat")
        data = {
            "name": "E2E Renamed Cat",
            "field_name": ["part_number"],
            "field_label": ["Part #"],
        }
        resp = self.client.post(
            reverse("catalog:part_category_edit", args=[cat.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:part_category_list"))
        cat.refresh_from_db()
        self.assertEqual(cat.name, "E2E Renamed Cat")

    def test_edit_duplicate_name(self):
        PartCategoryFactory(name="E2E ExistingCat")
        cat = PartCategoryFactory()
        data = {"name": "E2E ExistingCat"}
        resp = self.client.post(
            reverse("catalog:part_category_edit", args=[cat.pk]), data
        )
        self.assertRedirects(
            resp, reverse("catalog:part_category_edit", args=[cat.pk])
        )

    # -- DELETE --

    def test_delete(self):
        cat = PartCategoryFactory(name="E2E Deletable Cat")
        before = PartCategory.objects.count()
        resp = self.client.post(
            reverse("catalog:part_category_delete", args=[cat.pk])
        )
        self.assertRedirects(resp, reverse("catalog:part_category_list"))
        self.assertEqual(PartCategory.objects.count(), before - 1)
        self.assertFalse(PartCategory.objects.filter(pk=cat.pk).exists())


# ═══════════════════════════════════════════════════════════════════════════
# 16. ApplicationType CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestApplicationTypeCRUD(TestCase):

    # -- CREATE --

    def test_create_valid(self):
        data = {
            "name": "Marine Engine",
            "field_name": ["unit_number", "make"],
            "field_label": ["Unit Number", "Make"],
        }
        resp = self.client.post(reverse("catalog:application_type_create"), data)
        self.assertRedirects(resp, reverse("catalog:application_type_list"))
        self.assertTrue(ApplicationType.objects.filter(name="Marine Engine").exists())

    def test_create_missing_name(self):
        data = {"name": ""}
        resp = self.client.post(reverse("catalog:application_type_create"), data)
        self.assertRedirects(resp, reverse("catalog:application_type_create"))

    def test_create_duplicate_name(self):
        ApplicationType.objects.create(name="Existing Type")
        data = {"name": "Existing Type"}
        resp = self.client.post(reverse("catalog:application_type_create"), data)
        self.assertRedirects(resp, reverse("catalog:application_type_create"))

    # -- READ --

    def test_detail(self):
        at = ApplicationType.objects.create(name="Test Type")
        resp = self.client.get(
            reverse("catalog:application_type_detail", args=[at.pk])
        )
        self.assertEqual(resp.status_code, 200)

    def test_list(self):
        resp = self.client.get(reverse("catalog:application_type_list"))
        self.assertEqual(resp.status_code, 200)

    # -- UPDATE --

    def test_edit_valid(self):
        at = ApplicationType.objects.create(name="Editable Type")
        data = {
            "field_name": ["unit_number", "make", "model"],
            "field_label": ["Unit #", "Make", "Model"],
        }
        resp = self.client.post(
            reverse("catalog:application_type_edit", args=[at.pk]), data
        )
        self.assertRedirects(resp, reverse("catalog:application_type_list"))
        self.assertEqual(ApplicationTypeField.objects.filter(application_type=at).count(), 3)

    # -- DELETE --

    def test_delete(self):
        at = ApplicationType.objects.create(name="Deletable Type")
        resp = self.client.post(
            reverse("catalog:application_type_delete", args=[at.pk])
        )
        self.assertRedirects(resp, reverse("catalog:application_type_list"))
        self.assertFalse(ApplicationType.objects.filter(pk=at.pk).exists())


# ═══════════════════════════════════════════════════════════════════════════
# 17. Invoice CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestInvoiceCRUD(TestCase):

    def _item_formset_data(self, items=None, *, prefix="items"):
        """Build management + row data for InvoiceItemFormSet."""
        items = items or []
        total = max(len(items), 1)
        data = {
            f"{prefix}-TOTAL_FORMS": str(total),
            f"{prefix}-INITIAL_FORMS": "0",
            f"{prefix}-MIN_NUM_FORMS": "1",
            f"{prefix}-MAX_NUM_FORMS": "1000",
        }
        for i, item in enumerate(items):
            for k, v in item.items():
                data[f"{prefix}-{i}-{k}"] = str(v)
        return data

    # -- CREATE --

    def test_create_valid(self):
        CompanySettingsFactory()
        customer = CustomerFactory()
        part = PartFactory(stock_quantity=100)
        form_data = {
            "customer": customer.pk,
            "customer_name": customer.name,
            "date": "2024-06-01",
            "due_date": "2024-07-01",
            "tax_rate": "6.35",
            "status": "DRAFT",
            "notes": "",
            "private_notes": "",
            "phone": "",
            "email": "",
            "address": "",
            "contact_name": "",
        }
        item_data = self._item_formset_data([
            {"part": part.pk, "unit": "", "description": "Test Part", "quantity": "2", "unit_price": "35.00", "discount_pct": "0"},
        ])
        form_data.update(item_data)
        resp = self.client.post(reverse("invoicing:invoice_create"), form_data)
        self.assertEqual(Invoice.objects.count(), 1)
        inv = Invoice.objects.first()
        self.assertRedirects(resp, reverse("invoicing:invoice_detail", args=[inv.pk]))

    def test_create_missing_customer_name(self):
        CompanySettingsFactory()
        form_data = {
            "date": "2024-06-01",
            "due_date": "2024-07-01",
            "tax_rate": "0",
            "status": "DRAFT",
            "notes": "",
            "private_notes": "",
            "phone": "",
            "email": "",
            "address": "",
            "contact_name": "",
        }
        item_data = self._item_formset_data([
            {"unit": "", "description": "Something", "quantity": "1", "unit_price": "10.00", "discount_pct": "0"},
        ])
        form_data.update(item_data)
        resp = self.client.post(reverse("invoicing:invoice_create"), form_data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Invoice.objects.count(), 0)

    # -- READ --

    def test_detail_existing(self):
        inv = InvoiceFactory()
        resp = self.client.get(reverse("invoicing:invoice_detail", args=[inv.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_detail_nonexistent(self):
        resp = self.client.get(reverse("invoicing:invoice_detail", args=[99999]))
        self.assertEqual(resp.status_code, 404)

    def test_list(self):
        InvoiceFactory.create_batch(3)
        resp = self.client.get(reverse("invoicing:invoice_list"))
        self.assertEqual(resp.status_code, 200)

    # -- UPDATE --

    def test_edit_valid(self):
        inv = InvoiceFactory()
        InvoiceItemFactory(invoice=inv)
        item = inv.items.first()
        form_data = {
            "customer": inv.customer.pk,
            "customer_name": inv.customer_name,
            "contact_name": "Updated Contact",
            "date": str(inv.date.date() if hasattr(inv.date, "date") else inv.date),
            "due_date": "",
            "tax_rate": str(inv.tax_rate),
            "status": inv.status,
            "notes": "",
            "private_notes": "",
            "phone": "",
            "email": "",
            "address": "",
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "1",
            "items-MIN_NUM_FORMS": "1",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-id": str(item.pk),
            "items-0-invoice": str(inv.pk),
            "items-0-part": str(item.part.pk) if item.part else "",
            "items-0-unit": "",
            "items-0-description": item.description,
            "items-0-quantity": str(item.quantity),
            "items-0-unit_price": str(item.unit_price),
            "items-0-discount_pct": str(item.discount_pct),
        }
        resp = self.client.post(reverse("invoicing:invoice_edit", args=[inv.pk]), form_data)
        self.assertRedirects(resp, reverse("invoicing:invoice_detail", args=[inv.pk]))
        inv.refresh_from_db()
        self.assertEqual(inv.contact_name, "Updated Contact")

    # -- CANCEL --

    def test_cancel(self):
        inv = InvoiceFactory(status="DRAFT")
        resp = self.client.post(reverse("invoicing:invoice_cancel", args=[inv.pk]))
        inv.refresh_from_db()
        self.assertEqual(inv.status, "CANCELLED")

    # -- DELETE --

    def test_delete(self):
        inv = InvoiceFactory()
        resp = self.client.post(reverse("invoicing:invoice_delete", args=[inv.pk]))
        self.assertRedirects(resp, reverse("invoicing:invoice_list"))
        self.assertEqual(Invoice.objects.count(), 0)

    def test_delete_cascades_items(self):
        inv = InvoiceFactory()
        InvoiceItemFactory(invoice=inv)
        inv.delete()
        self.assertEqual(InvoiceItem.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 18. Customer CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestCustomerCRUD(TestCase):

    def _contact_formset_data(self, contacts=None, *, prefix="contacts"):
        contacts = contacts or []
        data = {
            f"{prefix}-TOTAL_FORMS": str(max(len(contacts), 1)),
            f"{prefix}-INITIAL_FORMS": "0",
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
        }
        for i, c in enumerate(contacts):
            for k, v in c.items():
                data[f"{prefix}-{i}-{k}"] = str(v)
        return data

    # -- CREATE --

    def test_create_valid(self):
        form_data = {"name": "ACME Corp", "is_active": "on"}
        form_data.update(self._contact_formset_data())
        resp = self.client.post(reverse("invoicing:customer_create"), form_data)
        self.assertRedirects(resp, reverse("invoicing:customer_list"))
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(Customer.objects.first().name, "ACME Corp")

    def test_create_with_contact(self):
        form_data = {"name": "Test Co"}
        form_data.update(self._contact_formset_data([
            {"name": "John Doe", "phone": "555-0101", "email": "john@test.com"},
        ]))
        resp = self.client.post(reverse("invoicing:customer_create"), form_data)
        self.assertRedirects(resp, reverse("invoicing:customer_list"))
        self.assertEqual(CustomerContact.objects.count(), 1)

    def test_create_missing_name(self):
        form_data = {"name": ""}
        form_data.update(self._contact_formset_data())
        resp = self.client.post(reverse("invoicing:customer_create"), form_data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Customer.objects.count(), 0)

    # -- READ --

    def test_list(self):
        CustomerFactory.create_batch(3)
        resp = self.client.get(reverse("invoicing:customer_list"))
        self.assertEqual(resp.status_code, 200)

    # -- UPDATE --

    def test_edit_valid(self):
        customer = CustomerFactory()
        form_data = {"name": "Renamed Corp", "is_active": "on"}
        form_data.update(self._contact_formset_data())
        resp = self.client.post(
            reverse("invoicing:customer_edit", args=[customer.pk]), form_data
        )
        self.assertRedirects(resp, reverse("invoicing:customer_list"))
        customer.refresh_from_db()
        self.assertEqual(customer.name, "Renamed Corp")

    def test_edit_invalid(self):
        customer = CustomerFactory()
        form_data = {"name": ""}
        form_data.update(self._contact_formset_data())
        resp = self.client.post(
            reverse("invoicing:customer_edit", args=[customer.pk]), form_data
        )
        self.assertEqual(resp.status_code, 200)

    # -- DELETE --

    def test_delete(self):
        customer = CustomerFactory()
        resp = self.client.post(
            reverse("invoicing:customer_delete", args=[customer.pk])
        )
        self.assertRedirects(resp, reverse("invoicing:customer_list"))
        self.assertEqual(Customer.objects.count(), 0)

    def test_delete_cascades_contacts(self):
        customer = CustomerFactory()
        CustomerContact.objects.create(customer=customer, name="Contact")
        customer.delete()
        self.assertEqual(CustomerContact.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 19. CompanySettings (read/update singleton)
# ═══════════════════════════════════════════════════════════════════════════
class TestCompanySettingsCRUD(TestCase):

    # -- READ --

    def test_settings_page_loads(self):
        resp = self.client.get(reverse("invoicing:settings"))
        self.assertEqual(resp.status_code, 200)

    def test_settings_auto_creates_singleton(self):
        self.assertEqual(CompanySettings.objects.count(), 0)
        self.client.get(reverse("invoicing:settings"))
        self.assertEqual(CompanySettings.objects.count(), 1)

    # -- UPDATE --

    def test_update_valid(self):
        CompanySettingsFactory()
        data = {
            "company_name": "New Company Name",
            "email": "new@example.com",
            "phone": "555-9999",
            "address": "456 Oak St",
            "default_net_terms": "NET_10",
            "default_net_days": "10",
            "default_tax_rate": "7.00",
            "pricing_method": "margin",
            "invoice_number_prefix": "INV-",
            "invoice_number_include_year": "on",
            "invoice_number_padding": "4",
            "invoice_paper_size": "letter",
            "invoice_layout_style": "standard",
            "invoice_date_format": "F j, Y",
            "invoice_currency_symbol": "$",
            "invoice_footer_message": "Thanks!",
        }
        resp = self.client.post(reverse("invoicing:settings"), data)
        self.assertRedirects(resp, reverse("invoicing:settings"))
        settings_obj = CompanySettings.objects.first()
        self.assertEqual(settings_obj.company_name, "New Company Name")
        self.assertEqual(settings_obj.default_net_terms, "NET_10")

    def test_update_invalid_tax_rate(self):
        CompanySettingsFactory()
        data = {
            "company_name": "Test",
            "default_net_terms": "NET_30",
            "default_net_days": "30",
            "default_tax_rate": "not-a-number",
            "pricing_method": "markup",
            "invoice_number_padding": "4",
            "invoice_paper_size": "letter",
            "invoice_layout_style": "standard",
            "invoice_date_format": "F j, Y",
            "invoice_currency_symbol": "$",
        }
        resp = self.client.post(reverse("invoicing:settings"), data)
        self.assertEqual(resp.status_code, 200)


# ═══════════════════════════════════════════════════════════════════════════
# 20. Vendor CRUD
# ═══════════════════════════════════════════════════════════════════════════
class TestVendorCRUD(TestCase):

    def _contact_formset_data(self, contacts=None, *, prefix="contacts"):
        contacts = contacts or []
        data = {
            f"{prefix}-TOTAL_FORMS": str(max(len(contacts), 1)),
            f"{prefix}-INITIAL_FORMS": "0",
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
        }
        for i, c in enumerate(contacts):
            for k, v in c.items():
                data[f"{prefix}-{i}-{k}"] = str(v)
        return data

    # -- CREATE --

    def test_create_valid(self):
        form_data = {"name": "Parts Unlimited", "is_active": "on"}
        form_data.update(self._contact_formset_data())
        resp = self.client.post(reverse("inventory:vendor_create"), form_data)
        self.assertRedirects(resp, reverse("inventory:vendor_list"))
        self.assertEqual(Vendor.objects.count(), 1)
        self.assertEqual(Vendor.objects.first().name, "Parts Unlimited")

    def test_create_with_contact(self):
        form_data = {"name": "Supplier Co"}
        form_data.update(self._contact_formset_data([
            {"name": "Jane Doe", "phone": "555-0202", "email": "jane@supplier.com"},
        ]))
        resp = self.client.post(reverse("inventory:vendor_create"), form_data)
        self.assertRedirects(resp, reverse("inventory:vendor_list"))
        self.assertEqual(VendorContact.objects.count(), 1)

    def test_create_missing_name(self):
        form_data = {"name": ""}
        form_data.update(self._contact_formset_data())
        resp = self.client.post(reverse("inventory:vendor_create"), form_data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Vendor.objects.count(), 0)

    # -- READ --

    def test_list(self):
        VendorFactory.create_batch(3)
        resp = self.client.get(reverse("inventory:vendor_list"))
        self.assertEqual(resp.status_code, 200)

    # -- UPDATE --

    def test_edit_valid(self):
        vendor = VendorFactory()
        form_data = {"name": "Renamed Vendor", "is_active": "on"}
        form_data.update(self._contact_formset_data())
        resp = self.client.post(
            reverse("inventory:vendor_edit", args=[vendor.pk]), form_data
        )
        self.assertRedirects(resp, reverse("inventory:vendor_list"))
        vendor.refresh_from_db()
        self.assertEqual(vendor.name, "Renamed Vendor")

    def test_edit_invalid(self):
        vendor = VendorFactory()
        form_data = {"name": ""}
        form_data.update(self._contact_formset_data())
        resp = self.client.post(
            reverse("inventory:vendor_edit", args=[vendor.pk]), form_data
        )
        self.assertEqual(resp.status_code, 200)

    # -- DELETE --

    def test_delete(self):
        vendor = VendorFactory()
        resp = self.client.post(
            reverse("inventory:vendor_delete", args=[vendor.pk])
        )
        self.assertRedirects(resp, reverse("inventory:vendor_list"))
        self.assertEqual(Vendor.objects.count(), 0)

    def test_delete_cascades_contacts(self):
        vendor = VendorFactory()
        VendorContact.objects.create(vendor=vendor, name="Contact")
        vendor.delete()
        self.assertEqual(VendorContact.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 21. InventoryItem (Part create via inventory form)
# ═══════════════════════════════════════════════════════════════════════════
class TestInventoryItemCRUD(TestCase):

    # -- CREATE --

    def test_create_form_loads(self):
        resp = self.client.get(reverse("inventory:inventory_item_create"))
        self.assertEqual(resp.status_code, 200)

    def test_create_missing_required(self):
        data = {"item_name": "", "part_number": "", "cost": "", "margin_pct": ""}
        resp = self.client.post(reverse("inventory:inventory_item_create"), data)
        self.assertEqual(resp.status_code, 200)

    # -- READ (list) --

    def test_inventory_list(self):
        resp = self.client.get(reverse("inventory:inventory_list"))
        self.assertEqual(resp.status_code, 200)

    def test_reorder_list(self):
        resp = self.client.get(reverse("inventory:reorder_list"))
        self.assertEqual(resp.status_code, 200)


# ═══════════════════════════════════════════════════════════════════════════
# 22. BackupSettings (read/update singleton)
# ═══════════════════════════════════════════════════════════════════════════
class TestBackupSettingsCRUD(TestCase):

    # -- READ --

    def test_settings_page_loads(self):
        resp = self.client.get(reverse("backup:settings"))
        self.assertEqual(resp.status_code, 200)

    def test_auto_creates_singleton(self):
        self.assertEqual(BackupSettings.objects.count(), 0)
        self.client.get(reverse("backup:settings"))
        self.assertEqual(BackupSettings.objects.count(), 1)

    # -- UPDATE --

    def test_update_valid(self):
        import tempfile

        BackupSettings.get()
        with tempfile.TemporaryDirectory() as tmpdir:
            data = {
                "local_backup_path": tmpdir,
                "external_backup_path": "",
                "auto_backup_enabled": "on",
                "backup_interval_hours": "4",
                "max_backups": "10",
            }
            resp = self.client.post(reverse("backup:settings"), data)
            self.assertRedirects(resp, reverse("backup:settings"))
            bs = BackupSettings.objects.first()
            self.assertEqual(bs.backup_interval_hours, 4)
            self.assertEqual(bs.max_backups, 10)

    def test_update_invalid_interval(self):
        BackupSettings.get()
        data = {
            "local_backup_path": "",
            "external_backup_path": "",
            "auto_backup_enabled": "on",
            "backup_interval_hours": "abc",
            "max_backups": "4",
        }
        resp = self.client.post(reverse("backup:settings"), data)
        self.assertEqual(resp.status_code, 200)
