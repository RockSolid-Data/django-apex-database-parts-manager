from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from catalog.models import Part, Unit, UnitType
from .models import Vendor


class VendorModelTest(TestCase):
    """Verify Vendor model per database plan (6.1)."""

    def test_vendor_create_with_all_fields(self):
        """Vendor has all fields from DATABASE_PLAN."""
        v = Vendor.objects.create(
            name="Acme Parts Co",
            contact_name="John Smith",
            email="john@acme.com",
            phone="555-123-4567",
            address_line1="123 Main St",
            address_line2="Suite 100",
            city="Springfield",
            state="IL",
            zip_code="62701",
            notes="Preferred supplier",
            is_active=True,
        )
        self.assertEqual(v.name, "Acme Parts Co")
        self.assertEqual(v.contact_name, "John Smith")
        self.assertEqual(v.email, "john@acme.com")
        self.assertEqual(v.phone, "555-123-4567")
        self.assertEqual(v.city, "Springfield")
        self.assertEqual(v.state, "IL")
        self.assertTrue(v.is_active)
        self.assertIsNotNone(v.created_at)
        self.assertIsNotNone(v.updated_at)

    def test_vendor_minimal_required_fields(self):
        """Vendor requires only name."""
        v = Vendor.objects.create(name="Minimal Vendor")
        self.assertEqual(v.name, "Minimal Vendor")
        self.assertEqual(v.contact_name, "")
        self.assertEqual(v.email, "")
        self.assertTrue(v.is_active)


class VendorViewTest(TestCase):
    """Verify Vendor CRUD views (6.2)."""

    def test_vendor_list_renders(self):
        """Vendor list page loads (labeled 'Suppliers' in the UI)."""
        url = reverse("inventory:vendor_list")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Suppliers")

    def test_vendor_create_renders(self):
        """Add vendor form loads."""
        url = reverse("inventory:vendor_create")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Add New Supplier")

    def test_vendor_create_post(self):
        """Creating a vendor redirects to list."""
        url = reverse("inventory:vendor_create")
        resp = self.client.post(url, {
            "name": "New Vendor Co",
            "contact_name": "Jane Doe",
            "email": "jane@newvendor.com",
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
            "is_active": "on",
            "contacts-TOTAL_FORMS": "1",
            "contacts-INITIAL_FORMS": "0",
            "contacts-MIN_NUM_FORMS": "0",
            "contacts-MAX_NUM_FORMS": "1000",
            "contacts-0-name": "",
            "contacts-0-phone": "",
            "contacts-0-email": "",
            "contacts-0-fax": "",
            "contacts-0-department": "",
        })
        self.assertRedirects(resp, reverse("inventory:vendor_list"))
        self.assertTrue(Vendor.objects.filter(name="New Vendor Co").exists())

    def test_vendor_edit_renders(self):
        """Edit vendor form loads."""
        v = Vendor.objects.create(name="Edit Me")
        url = reverse("inventory:vendor_edit", kwargs={"pk": v.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Edit Supplier")
        self.assertContains(resp, "Edit Me")

    def test_vendor_edit_post(self):
        """Editing a vendor updates and redirects."""
        v = Vendor.objects.create(name="Original Name")
        url = reverse("inventory:vendor_edit", kwargs={"pk": v.pk})
        resp = self.client.post(url, {
            "name": "Updated Name",
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
            "is_active": "on",
            "contacts-TOTAL_FORMS": "1",
            "contacts-INITIAL_FORMS": "0",
            "contacts-MIN_NUM_FORMS": "0",
            "contacts-MAX_NUM_FORMS": "1000",
            "contacts-0-name": "",
            "contacts-0-phone": "",
            "contacts-0-email": "",
            "contacts-0-fax": "",
            "contacts-0-department": "",
        })
        self.assertRedirects(resp, reverse("inventory:vendor_list"))
        v.refresh_from_db()
        self.assertEqual(v.name, "Updated Name")


class InventoryItemCreateTest(TestCase):
    """Verify Add Inventory Item form (6.5)."""

    def setUp(self):
        self.vendor = Vendor.objects.create(name="Acme Supplier")

    def test_inventory_item_create_renders(self):
        """Add Inventory Item form loads."""
        resp = self.client.get(reverse("inventory:inventory_item_create"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Add Inventory Item")
        self.assertContains(resp, "Supplier")

    def test_inventory_item_create_post_creates_part(self):
        """Submitting form creates new Part."""
        url = reverse("inventory:inventory_item_create")
        resp = self.client.post(url, {
            "item_name": "Test Part",
            "part_number": "INV-NEW-001",
            "description": "A test part",
            "supplier": str(self.vendor.pk),
            "cost": "10.00",
            "margin_pct": "25",
            "quantity_purchased": "5",
            "quantity_available": "5",
            "notes": "",
        })
        self.assertRedirects(resp, reverse("inventory:inventory_list"))
        part = Part.objects.get(part_number="INV-NEW-001")
        self.assertEqual(part.part_name, "Test Part")
        self.assertEqual(part.primary_vendor, "Acme Supplier")
        self.assertEqual(part.cost_price, 10)
        # Price uses true margin: cost / (1 - margin%) = 10 / (1 - 0.25) = 13.33
        self.assertEqual(part.price, Decimal("13.33"))
        self.assertEqual(part.stock_quantity, 5)

    def test_inventory_item_create_post_updates_existing_part(self):
        """Submitting with existing part_number updates Part."""
        Part.objects.create(
            part_number="INV-EXIST",
            part_name="Old Name",
            stock_quantity=3,
        )
        url = reverse("inventory:inventory_item_create")
        resp = self.client.post(url, {
            "item_name": "Updated Name",
            "part_number": "INV-EXIST",
            "description": "Updated desc",
            "supplier": str(self.vendor.pk),
            "cost": "20.00",
            "margin_pct": "50",
            "quantity_purchased": "10",
            "quantity_available": "13",
            "notes": "",
        })
        self.assertRedirects(resp, reverse("inventory:inventory_list"))
        part = Part.objects.get(part_number="INV-EXIST")
        self.assertEqual(part.part_name, "Updated Name")
        self.assertEqual(part.cost_price, 20)
        # Price uses true margin: cost / (1 - margin%) = 20 / (1 - 0.50) = 40.00
        self.assertEqual(part.price, Decimal("40.00"))
        self.assertEqual(part.stock_quantity, 13)


class InventoryListViewTest(TestCase):
    """Verify Inventory management list (6.4)."""

    def setUp(self):
        self.unit_type, _ = UnitType.objects.get_or_create(
            name="AC Motor", defaults={"description": ""}
        )
        self.unit = Unit.objects.create(
            unit_number="UT-001",
            unit_type=self.unit_type,
        )

    def test_inventory_list_renders(self):
        """Inventory list page loads."""
        resp = self.client.get(reverse("inventory:inventory_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Inventory")

    def test_inventory_list_shows_parts(self):
        """Parts appear on inventory list with cost, price, quantity."""
        Part.objects.create(
            part_number="INV-001",
            part_name="Test Item",
            primary_vendor="Acme",
            cost_price=10.00,
            price=15.00,
            stock_quantity=5,
            track_inventory=True,
        )
        resp = self.client.get(reverse("inventory:inventory_list"))
        self.assertContains(resp, "INV-001")
        self.assertContains(resp, "Test Item")
        self.assertContains(resp, "Acme")


class ReorderViewTest(TestCase):
    """Verify Reorder list page (6.3)."""

    def setUp(self):
        self.unit_type, _ = UnitType.objects.get_or_create(
            name="AC Motor", defaults={"description": ""}
        )
        self.unit = Unit.objects.create(
            unit_number="UT-001",
            unit_type=self.unit_type,
        )

    def test_reorder_list_renders(self):
        """Reorder page loads."""
        resp = self.client.get(reverse("inventory:reorder_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Reorder")

    def test_reorder_shows_parts_at_or_below_reorder_level(self):
        """Parts with stock <= reorder_qty appear on reorder list."""
        low = Part.objects.create(
            part_number="P-LOW",
            stock_quantity=2,
            reorder_qty=5,
            primary_vendor="Acme",
            track_inventory=True,
        )
        out = Part.objects.create(
            part_number="P-OUT",
            stock_quantity=0,
            reorder_qty=3,
            primary_vendor="Acme",
            track_inventory=True,
        )
        Part.objects.create(
            part_number="P-OK",
            stock_quantity=10,
            reorder_qty=5,
            primary_vendor="Acme",
            track_inventory=True,
        )
        resp = self.client.get(reverse("inventory:reorder_list"))
        self.assertContains(resp, "2 items need reordering")
        self.assertContains(resp, "Low Stock")
        self.assertContains(resp, "Out of Stock")
        self.assertContains(resp, f"/parts/{low.pk}/")
        self.assertContains(resp, f"/parts/{out.pk}/")
        self.assertNotContains(resp, "P-OK")

    def test_reorder_empty_state(self):
        """When no parts need reorder, shows empty message."""
        Part.objects.create(
            part_number="P-FINE",
            stock_quantity=10,
            reorder_qty=5,
        )
        resp = self.client.get(reverse("inventory:reorder_list"))
        self.assertContains(resp, "No items need reordering")

class VendorListPrintSelectedTest(TestCase):
    """Print supplier list with ?print=1&ids= filters to selected rows."""

    def setUp(self):
        self.v1 = Vendor.objects.create(name="Alpha Supplier")
        self.v2 = Vendor.objects.create(name="Beta Supplier")
        self.v3 = Vendor.objects.create(name="Gamma Supplier")

    def test_print_with_ids_renders_only_selected_vendors(self):
        ids = f"{self.v1.pk},{self.v3.pk}"
        url = reverse("inventory:vendor_list") + f"?print=1&ids={ids}"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "inventory/vendor_list_print.html")
        body = resp.content.decode()
        self.assertIn("Alpha Supplier", body)
        self.assertIn("Gamma Supplier", body)
        self.assertNotIn("Beta Supplier", body)

    def test_print_without_ids_still_renders_print_template(self):
        url = reverse("inventory:vendor_list") + "?print=1"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "inventory/vendor_list_print.html")

    def test_vendor_list_has_select_checkboxes(self):
        resp = self.client.get(reverse("inventory:vendor_list"))
        self.assertContains(resp, "bulk-row-check")
        self.assertContains(resp, "list-print-btn")


class InventoryListPrintSelectedTest(TestCase):
    """Print inventory list with ?print=1&ids= filters to selected parts."""

    def setUp(self):
        self.p1 = Part.objects.create(
            part_number="INV-P1", part_name="Item One",
            track_inventory=True, stock_quantity=5, price=10,
        )
        self.p2 = Part.objects.create(
            part_number="INV-P2", part_name="Item Two",
            track_inventory=True, stock_quantity=5, price=10,
        )
        self.p3 = Part.objects.create(
            part_number="INV-P3", part_name="Item Three",
            track_inventory=True, stock_quantity=5, price=10,
        )

    def test_print_with_ids_renders_only_selected_parts(self):
        ids = f"{self.p1.pk},{self.p3.pk}"
        url = reverse("inventory:inventory_list") + f"?print=1&ids={ids}"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "inventory/inventory_list_print.html")
        body = resp.content.decode()
        self.assertIn("INV-P1", body)
        self.assertIn("INV-P3", body)
        self.assertNotIn("INV-P2", body)

    def test_inventory_list_has_select_checkboxes(self):
        resp = self.client.get(reverse("inventory:inventory_list"))
        self.assertContains(resp, "bulk-row-check")
        self.assertContains(resp, "list-print-btn")


class ReorderListPrintSelectedTest(TestCase):
    """Reorder list print view + ids filter."""

    def setUp(self):
        self.p1 = Part.objects.create(
            part_number="RO-P1", stock_quantity=1, reorder_qty=5,
            track_inventory=True, primary_vendor="Acme",
        )
        self.p2 = Part.objects.create(
            part_number="RO-P2", stock_quantity=0, reorder_qty=3,
            track_inventory=True, primary_vendor="Acme",
        )
        self.p3 = Part.objects.create(
            part_number="RO-P3", stock_quantity=2, reorder_qty=5,
            track_inventory=True, primary_vendor="Acme",
        )

    def test_print_without_ids_renders_print_template(self):
        url = reverse("inventory:reorder_list") + "?print=1"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "inventory/reorder_list_print.html")
        body = resp.content.decode()
        self.assertIn("RO-P1", body)
        self.assertIn("RO-P2", body)
        self.assertIn("RO-P3", body)

    def test_print_with_ids_renders_only_selected_parts(self):
        ids = f"{self.p1.pk},{self.p3.pk}"
        url = reverse("inventory:reorder_list") + f"?print=1&ids={ids}"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "inventory/reorder_list_print.html")
        body = resp.content.decode()
        self.assertIn("RO-P1", body)
        self.assertIn("RO-P3", body)
        self.assertNotIn("RO-P2", body)

    def test_reorder_list_has_select_checkboxes_and_print(self):
        resp = self.client.get(reverse("inventory:reorder_list"))
        self.assertContains(resp, "bulk-row-check")
        self.assertContains(resp, "list-print-btn")
