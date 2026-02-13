# Catalog tests
from django.test import TestCase
from django.urls import reverse

from .models import Application, ApplicationSpecification, ApplicationUnit, BOM, BOMItem, Part, Unit, UnitType


class HomeViewTest(TestCase):
    """Verify home page shortcut cards match header nav links."""

    def test_home_renders(self):
        """Home page loads."""
        resp = self.client.get(reverse("catalog:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Manchester Electric")
        self.assertContains(resp, "Motor repair, parts sales")

    def test_home_has_all_shortcut_links(self):
        """Home page boxes link to same destinations as header nav."""
        resp = self.client.get(reverse("catalog:home"))
        self.assertEqual(resp.status_code, 200)
        links = [
            ("catalog:unit_search", "Unit Search"),
            ("catalog:unit_list", "Unit List"),
            ("catalog:application_list", "Applications"),
            ("catalog:part_list", "Parts"),
            ("catalog:bom_list", "BOMs"),
            ("inventory:vendor_list", "Vendors"),
            ("inventory:reorder_list", "Reorder"),
            ("invoicing:invoice_list", "Invoices"),
            ("invoicing:customer_list", "Customers"),
            ("inventory:inventory_list", "Inventory"),
        ("invoicing:settings", "Settings"),
        ]
        for url_name, label in links:
            url = reverse(url_name)
            self.assertContains(resp, url, msg_prefix=f"Shortcut for {label} should link to {url_name}")
            self.assertContains(resp, label, msg_prefix=f"Shortcut for {label} should display label")


class PartModelTest(TestCase):
    """Verify Part model per database plan (4.1)."""

    def setUp(self):
        self.unit_type, _ = UnitType.objects.get_or_create(
            name="AC Motor", defaults={"description": ""}
        )
        self.unit = Unit.objects.create(
            unit_number="UT-001",
            unit_type=self.unit_type,
        )

    def test_part_create_with_all_fields(self):
        """Part has all fields from DATABASE_PLAN: part numbers, stock, unit link, image."""
        part = Part.objects.create(
            part_number="PN-001",
            part_name="Test Part",
            key="KEY-1",
            yt_number="YT-123",
            j_and_n="JN-456",
            oem_number="OEM-789",
            item_no="ITEM-1",
            category="Category",
            type="Type",
            oem_type="OEMType",
            item_typ="ItemTyp",
            oem="OEM",
            primary_vendor="Vendor",
            catalog="Catalog",
            plug_id="Plug1",
            price=10.99,
            cost_price=5.00,
            stock_quantity=10,
            reorder_qty=5,
            bin_number="BIN-A1",
            description="Description",
            foot_notes="Footnotes",
            superseding_notes="Superseding",
            has_picture=True,
            has_interchange=False,
            has_superseding=False,
            unit=self.unit,
            is_active=True,
        )
        self.assertEqual(part.part_number, "PN-001")
        self.assertEqual(part.stock_quantity, 10)
        self.assertEqual(part.reorder_qty, 5)
        self.assertEqual(part.bin_number, "BIN-A1")
        self.assertEqual(part.unit, self.unit)
        self.assertIsNotNone(part.created_at)
        self.assertIsNotNone(part.updated_at)

    def test_part_minimal_required_fields(self):
        """Part requires only part_number; stock fields default, unit optional."""
        part = Part.objects.create(part_number="PN-MIN")
        self.assertEqual(part.part_number, "PN-MIN")
        self.assertEqual(part.stock_quantity, 0)
        self.assertEqual(part.reorder_qty, 0)
        self.assertIsNone(part.unit)
        self.assertEqual(part.part_name, "")


class BOMModelTest(TestCase):
    """Verify BOM and BOMItem models per database plan (5.1)."""

    def setUp(self):
        self.unit_type, _ = UnitType.objects.get_or_create(
            name="AC Motor", defaults={"description": ""}
        )
        self.unit = Unit.objects.create(
            unit_number="UT-001",
            unit_type=self.unit_type,
        )
        self.app = Application.objects.create(name="Test App")
        self.part = Part.objects.create(part_number="PN-001")

    def test_bom_create_with_unit_and_application(self):
        """BOM has name, description, optional unit, optional application."""
        bom = BOM.objects.create(
            name="Test BOM",
            description="BOM for unit",
            unit=self.unit,
            application=self.app,
        )
        self.assertEqual(bom.name, "Test BOM")
        self.assertEqual(bom.unit, self.unit)
        self.assertEqual(bom.application, self.app)
        self.assertIsNotNone(bom.created_at)
        self.assertIsNotNone(bom.updated_at)

    def test_bom_create_minimal(self):
        """BOM allows name only; unit and application optional."""
        bom = BOM.objects.create(name="Minimal BOM")
        self.assertIsNone(bom.unit)
        self.assertIsNone(bom.application)

    def test_bom_item_create_with_overrides(self):
        """BOMItem has part, quantity, and optional override fields."""
        bom = BOM.objects.create(name="BOM with items")
        item = BOMItem.objects.create(
            bom=bom,
            part=self.part,
            description="Override desc",
            notes="Fitment notes",
            unit_qty=2,
            stock_qty=5,
            bin_number="BIN-A1",
            oem_number="OEM-123",
            j_and_n="JN-456",
            yt_number="YT-789",
        )
        self.assertEqual(item.bom, bom)
        self.assertEqual(item.part, self.part)
        self.assertEqual(item.unit_qty, 2)
        self.assertEqual(item.stock_qty, 5)
        self.assertEqual(item.oem_number, "OEM-123")

    def test_bom_item_minimal(self):
        """BOMItem requires bom and part; unit_qty defaults to 1."""
        bom = BOM.objects.create(name="BOM")
        item = BOMItem.objects.create(bom=bom, part=self.part)
        self.assertEqual(item.unit_qty, 1)
        self.assertEqual(item.stock_qty, 0)


class ApplicationModelTest(TestCase):
    """Verify Application model per database plan (3.1)."""

    def test_application_create_and_fields(self):
        """Application has all required fields from DATABASE_PLAN."""
        app = Application.objects.create(
            name="4 Cylinder Engine 73",
            make="FORD",
            engine="4.0L",
            year="1998",
            mfr="Ford",
            volt="12",
            amp="90",
            part_number="PN-123",
            other_number="ON-456",
            unit_number="UT-001",
            options="Air conditioning",
            notes="Test notes",
            is_active=True,
        )
        self.assertEqual(app.name, "4 Cylinder Engine 73")
        self.assertEqual(app.make, "FORD")
        self.assertEqual(app.engine, "4.0L")
        self.assertEqual(app.year, "1998")
        self.assertTrue(app.is_active)
        self.assertIsNotNone(app.created_at)
        self.assertIsNotNone(app.updated_at)

    def test_application_blank_optional_fields(self):
        """Application allows blank optional fields."""
        app = Application.objects.create(name="Minimal App")
        self.assertEqual(app.make, "")
        self.assertEqual(app.engine, "")
        self.assertEqual(app.year, "")


class ApplicationUnitRelationshipTest(TestCase):
    """Verify Application ↔ Unit M:M works via ApplicationUnit junction."""

    def setUp(self):
        self.unit_type, _ = UnitType.objects.get_or_create(
            name="AC Motor", defaults={"description": ""}
        )
        self.app = Application.objects.create(
            name="4 Cylinder Engine 73",
            make="FORD",
            engine="4.0L",
            year="1998",
        )
        self.unit1 = Unit.objects.create(
            unit_number="UT-001",
            unit_type=self.unit_type,
            voltage="12V",
        )
        self.unit2 = Unit.objects.create(
            unit_number="UT-002",
            unit_type=self.unit_type,
            voltage="24V",
        )

    def test_linked_units_on_application(self):
        """Application.units returns linked units (Linked Units)."""
        ApplicationUnit.objects.create(
            application=self.app,
            unit=self.unit1,
            position="Primary",
            notes="Main alternator",
        )
        ApplicationUnit.objects.create(
            application=self.app,
            unit=self.unit2,
            position="Backup",
        )
        linked = list(self.app.units.order_by("unit_number"))
        self.assertEqual(len(linked), 2)
        self.assertEqual(linked[0].unit_number, "UT-001")
        self.assertEqual(linked[1].unit_number, "UT-002")

    def test_applications_on_unit(self):
        """Unit.applications returns linked applications (Applications)."""
        app2 = Application.objects.create(
            name="CUMMINS ISL",
            make="CUMMINS",
            engine="ISL",
        )
        ApplicationUnit.objects.create(
            application=self.app,
            unit=self.unit1,
            notes="Fits Ford application",
        )
        ApplicationUnit.objects.create(
            application=app2,
            unit=self.unit1,
            notes="Fits Cummins application",
        )
        apps = list(self.unit1.applications.order_by("name"))
        self.assertEqual(len(apps), 2)
        self.assertEqual(apps[0].name, "4 Cylinder Engine 73")
        self.assertEqual(apps[1].name, "CUMMINS ISL")

    def test_application_units_with_extra_data(self):
        """ApplicationUnit stores position and notes."""
        au = ApplicationUnit.objects.create(
            application=self.app,
            unit=self.unit1,
            position="Left",
            notes="Driver side",
        )
        self.assertEqual(au.position, "Left")
        self.assertEqual(au.notes, "Driver side")

    def test_unique_application_unit(self):
        """Same application+unit cannot be linked twice."""
        ApplicationUnit.objects.create(
            application=self.app,
            unit=self.unit1,
        )
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            ApplicationUnit.objects.create(
                application=self.app,
                unit=self.unit1,
            )


class ApplicationSpecificationTest(TestCase):
    """Verify Application Specifications (8.7)."""

    def setUp(self):
        self.app = Application.objects.create(name="Test Application")

    def test_specification_create(self):
        """ApplicationSpecification has category, type, specification."""
        spec = ApplicationSpecification.objects.create(
            application=self.app,
            category="Electrical",
            type="Voltage",
            specification="12V",
        )
        self.assertEqual(spec.category, "Electrical")
        self.assertEqual(spec.type, "Voltage")
        self.assertEqual(spec.specification, "12V")

    def test_application_detail_shows_specifications(self):
        """Application detail displays specifications table."""
        ApplicationSpecification.objects.create(
            application=self.app,
            category="Test Cat",
            type="Test Type",
            specification="Test Spec",
        )
        resp = self.client.get(reverse("catalog:application_detail", kwargs={"pk": self.app.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Application Specifications")
        self.assertContains(resp, "Test Cat")
        self.assertContains(resp, "Test Type")
        self.assertContains(resp, "Test Spec")

    def test_application_spec_add_and_edit(self):
        """Add and edit specifications via forms."""
        resp = self.client.post(
            reverse("catalog:application_spec_add", kwargs={"pk": self.app.pk}),
            {"category": "Mech", "type": "RPM", "specification": "3600"},
        )
        self.assertRedirects(resp, reverse("catalog:application_detail", kwargs={"pk": self.app.pk}))
        spec = ApplicationSpecification.objects.get(application=self.app)
        self.assertEqual(spec.specification, "3600")

        resp = self.client.post(
            reverse("catalog:application_spec_edit", kwargs={"pk": self.app.pk, "spec_pk": spec.pk}),
            {"category": "Mech", "type": "RPM", "specification": "3600 RPM"},
        )
        self.assertRedirects(resp, reverse("catalog:application_detail", kwargs={"pk": self.app.pk}))
        spec.refresh_from_db()
        self.assertEqual(spec.specification, "3600 RPM")


class UnitSearchViewTest(TestCase):
    """Verify Unit Search page (separate from Unit List)."""

    def test_unit_search_renders(self):
        """Unit Search page loads with title, subtitle, and tabs."""
        resp = self.client.get(reverse("catalog:unit_search"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Unit Search")
        self.assertContains(resp, "Search for units, applications, and parts across the entire system")
        self.assertContains(resp, "Units")
        self.assertContains(resp, "Applications")
        self.assertContains(resp, "Parts")
        self.assertContains(resp, "Manufacturer")

    def test_unit_search_tabs_switch(self):
        """Applications and Parts tabs load their forms."""
        resp = self.client.get(reverse("catalog:unit_search") + "?tab=applications")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Make")
        self.assertContains(resp, "Enter make...")

        resp = self.client.get(reverse("catalog:unit_search") + "?tab=parts")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Search Parts")


class UnitBOMViewTest(TestCase):
    """Verify View BOM from Unit (8.3)."""

    def setUp(self):
        self.unit_type, _ = UnitType.objects.get_or_create(
            name="AC Motor", defaults={"description": ""}
        )
        self.unit = Unit.objects.create(
            unit_number="UT-BOM",
            unit_type=self.unit_type,
        )

    def test_unit_bom_empty_redirects_to_create_option(self):
        """Unit with no BOMs shows empty page with Create BOM link."""
        resp = self.client.get(reverse("catalog:unit_bom", kwargs={"pk": self.unit.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No BOMs found")
        self.assertContains(resp, "Create BOM")
        self.assertContains(resp, "unit=" + str(self.unit.pk))

    def test_unit_bom_single_redirects_to_bom_detail(self):
        """Unit with 1 BOM redirects to BOM detail."""
        bom = BOM.objects.create(name="BOM for UT-BOM", unit=self.unit)
        resp = self.client.get(reverse("catalog:unit_bom", kwargs={"pk": self.unit.pk}))
        self.assertRedirects(resp, reverse("catalog:bom_detail", kwargs={"pk": bom.pk}))

    def test_unit_bom_multiple_shows_list(self):
        """Unit with multiple BOMs shows list to choose."""
        BOM.objects.create(name="BOM A", unit=self.unit)
        BOM.objects.create(name="BOM B", unit=self.unit)
        resp = self.client.get(reverse("catalog:unit_bom", kwargs={"pk": self.unit.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "BOMs for Unit UT-BOM")
        self.assertContains(resp, "BOM A")
        self.assertContains(resp, "BOM B")


class BOMPrintTest(TestCase):
    """Verify BOM Print All / Print Selected (8.5)."""

    def setUp(self):
        self.unit_type, _ = UnitType.objects.get_or_create(
            name="AC Motor", defaults={"description": ""}
        )
        self.unit = Unit.objects.create(unit_number="UT-PRINT", unit_type=self.unit_type)
        self.bom = BOM.objects.create(name="Test BOM", unit=self.unit)
        self.part1 = Part.objects.create(part_number="P-001", part_name="Part 1")
        self.part2 = Part.objects.create(part_number="P-002", part_name="Part 2")
        self.item1 = BOMItem.objects.create(bom=self.bom, part=self.part1, unit_qty=2)
        self.item2 = BOMItem.objects.create(bom=self.bom, part=self.part2, unit_qty=1)

    def test_bom_print_all(self):
        """Print All shows all parts."""
        resp = self.client.get(reverse("catalog:bom_print", kwargs={"pk": self.bom.pk}) + "?all=1")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Test BOM")
        self.assertContains(resp, "P-001")
        self.assertContains(resp, "P-002")

    def test_bom_print_selected(self):
        """Print with items= shows only selected parts."""
        resp = self.client.get(
            reverse("catalog:bom_print", kwargs={"pk": self.bom.pk})
            + f"?items={self.item1.pk}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "P-001")
        self.assertNotContains(resp, "P-002")
