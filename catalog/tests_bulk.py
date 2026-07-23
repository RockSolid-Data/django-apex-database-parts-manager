from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from .models import Part


class BulkActionTestCase(TestCase):
    """Shared setup: create a handful of parts to act on."""

    @classmethod
    def setUpTestData(cls):
        cls.parts = [
            Part.objects.create(
                part_number=f"BP-{i:03d}",
                part_name=f"Bulk Part {i}",
                category="OldCat",
                primary_vendor="OldVendor",
                voltage="12V",
                track_inventory=False,
            )
            for i in range(1, 6)
        ]
        cls.url = reverse("catalog:bulk_action")

    def _ids(self, indices=None):
        if indices is None:
            indices = range(len(self.parts))
        return ",".join(str(self.parts[i].pk) for i in indices)


class BulkChangeCategoryTest(BulkActionTestCase):
    def test_bulk_change_category_updates_selected_parts(self):
        resp = self.client.post(self.url, {
            "action": "change_category",
            "ids": self._ids([0, 1, 2]),
            "value": "Rectifiers",
        })
        self.assertEqual(resp.status_code, 302)
        for p in Part.objects.filter(pk__in=[self.parts[i].pk for i in [0, 1, 2]]):
            self.assertEqual(p.category, "Rectifiers")
        unchanged = Part.objects.get(pk=self.parts[3].pk)
        self.assertEqual(unchanged.category, "OldCat")


class BulkChangeVendorTest(BulkActionTestCase):
    def test_bulk_change_vendor_updates_selected_parts(self):
        resp = self.client.post(self.url, {
            "action": "change_vendor",
            "ids": self._ids([1, 3]),
            "value": "NewVendor Inc",
        })
        self.assertEqual(resp.status_code, 302)
        for p in Part.objects.filter(pk__in=[self.parts[i].pk for i in [1, 3]]):
            self.assertEqual(p.primary_vendor, "NewVendor Inc")
        unchanged = Part.objects.get(pk=self.parts[0].pk)
        self.assertEqual(unchanged.primary_vendor, "OldVendor")


class BulkChangeVoltageTest(BulkActionTestCase):
    def test_bulk_change_voltage_updates_selected_parts(self):
        resp = self.client.post(self.url, {
            "action": "change_voltage",
            "ids": self._ids([0, 4]),
            "value": "24V",
        })
        self.assertEqual(resp.status_code, 302)
        for p in Part.objects.filter(pk__in=[self.parts[i].pk for i in [0, 4]]):
            self.assertEqual(p.voltage, "24V")
        unchanged = Part.objects.get(pk=self.parts[2].pk)
        self.assertEqual(unchanged.voltage, "12V")


class BulkToggleTrackInventoryTest(BulkActionTestCase):
    def test_bulk_toggle_track_inventory_sets_true(self):
        resp = self.client.post(self.url, {
            "action": "toggle_track_inventory",
            "ids": self._ids([0, 1, 2]),
            "value": "true",
        })
        self.assertEqual(resp.status_code, 302)
        for p in Part.objects.filter(pk__in=[self.parts[i].pk for i in [0, 1, 2]]):
            self.assertTrue(p.track_inventory)

    def test_bulk_toggle_track_inventory_sets_false(self):
        Part.objects.filter(
            pk__in=[self.parts[i].pk for i in [0, 1]]
        ).update(track_inventory=True)
        resp = self.client.post(self.url, {
            "action": "toggle_track_inventory",
            "ids": self._ids([0, 1]),
            "value": "false",
        })
        self.assertEqual(resp.status_code, 302)
        for p in Part.objects.filter(pk__in=[self.parts[i].pk for i in [0, 1]]):
            self.assertFalse(p.track_inventory)


class BulkDeleteTest(BulkActionTestCase):
    def test_bulk_delete_removes_selected_parts(self):
        delete_pks = [self.parts[i].pk for i in [3, 4]]
        resp = self.client.post(self.url, {
            "action": "delete",
            "ids": self._ids([3, 4]),
            "confirm": "1",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Part.objects.filter(pk__in=delete_pks).exists())
        self.assertEqual(Part.objects.count(), 3)

    def test_bulk_delete_without_confirm_returns_error(self):
        resp = self.client.post(self.url, {
            "action": "delete",
            "ids": self._ids([0]),
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Part.objects.filter(pk=self.parts[0].pk).exists())
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("confirm" in m.lower() for m in messages))


class BulkActionValidationTest(BulkActionTestCase):
    def test_bulk_action_with_no_ids_returns_error(self):
        resp = self.client.post(self.url, {
            "action": "change_category",
            "ids": "",
            "value": "Whatever",
        })
        self.assertEqual(resp.status_code, 302)
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("select" in m.lower() or "no parts" in m.lower() for m in messages))

    def test_bulk_action_with_invalid_action_returns_error(self):
        resp = self.client.post(self.url, {
            "action": "hack_the_planet",
            "ids": self._ids([0]),
            "value": "x",
        })
        self.assertEqual(resp.status_code, 302)
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("invalid" in m.lower() for m in messages))


class BulkActionRedirectTest(BulkActionTestCase):
    def test_bulk_action_redirects_back_to_parts_list(self):
        resp = self.client.post(self.url, {
            "action": "change_category",
            "ids": self._ids([0]),
            "value": "NewCat",
        })
        self.assertRedirects(resp, reverse("catalog:part_list"), fetch_redirect_response=False)

    def test_bulk_action_preserves_query_string(self):
        resp = self.client.post(self.url + "?category=Rectifiers&q=test", {
            "action": "change_voltage",
            "ids": self._ids([0]),
            "value": "48V",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn("category=Rectifiers", resp.url)
        self.assertIn("q=test", resp.url)
