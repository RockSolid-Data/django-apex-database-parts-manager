from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from .models import Unit


class UnitBulkActionTestCase(TestCase):
    """Shared setup: create units to act on."""

    @classmethod
    def setUpTestData(cls):
        cls.units = [
            Unit.objects.create(
                unit_number=f"BU-{i:03d}",
                yt_number=f"YT-BU-{i:03d}",
                unit_type_category="Starter",
                family="OldFamily",
                oem="OldOEM",
                voltage="12V",
            )
            for i in range(1, 6)
        ]
        cls.url = reverse("catalog:unit_bulk_action")

    def _ids(self, indices=None):
        if indices is None:
            indices = range(len(self.units))
        return ",".join(str(self.units[i].pk) for i in indices)


class UnitBulkChangeUnitTypeTest(UnitBulkActionTestCase):
    def test_bulk_change_unit_type_updates_selected_units(self):
        resp = self.client.post(self.url, {
            "action": "change_unit_type",
            "ids": self._ids([0, 1, 2]),
            "value": "Alternator",
        })
        self.assertEqual(resp.status_code, 302)
        for u in Unit.objects.filter(pk__in=[self.units[i].pk for i in [0, 1, 2]]):
            self.assertEqual(u.unit_type_category, "Alternator")
        unchanged = Unit.objects.get(pk=self.units[3].pk)
        self.assertEqual(unchanged.unit_type_category, "Starter")


class UnitBulkChangeFamilyTest(UnitBulkActionTestCase):
    def test_bulk_change_family_updates_selected_units(self):
        resp = self.client.post(self.url, {
            "action": "change_family",
            "ids": self._ids([1, 3]),
            "value": "NewFamily",
        })
        self.assertEqual(resp.status_code, 302)
        for u in Unit.objects.filter(pk__in=[self.units[i].pk for i in [1, 3]]):
            self.assertEqual(u.family, "NewFamily")
        unchanged = Unit.objects.get(pk=self.units[0].pk)
        self.assertEqual(unchanged.family, "OldFamily")


class UnitBulkChangeOemTest(UnitBulkActionTestCase):
    def test_bulk_change_oem_updates_selected_units(self):
        resp = self.client.post(self.url, {
            "action": "change_oem",
            "ids": self._ids([0, 4]),
            "value": "Bosch",
        })
        self.assertEqual(resp.status_code, 302)
        for u in Unit.objects.filter(pk__in=[self.units[i].pk for i in [0, 4]]):
            self.assertEqual(u.oem, "Bosch")
        unchanged = Unit.objects.get(pk=self.units[2].pk)
        self.assertEqual(unchanged.oem, "OldOEM")


class UnitBulkChangeVoltageTest(UnitBulkActionTestCase):
    def test_bulk_change_voltage_updates_selected_units(self):
        resp = self.client.post(self.url, {
            "action": "change_voltage",
            "ids": self._ids([0, 2]),
            "value": "24V",
        })
        self.assertEqual(resp.status_code, 302)
        for u in Unit.objects.filter(pk__in=[self.units[i].pk for i in [0, 2]]):
            self.assertEqual(u.voltage, "24V")
        unchanged = Unit.objects.get(pk=self.units[1].pk)
        self.assertEqual(unchanged.voltage, "12V")


class UnitBulkDeleteTest(UnitBulkActionTestCase):
    def test_bulk_delete_removes_selected_units(self):
        delete_pks = [self.units[i].pk for i in [3, 4]]
        resp = self.client.post(self.url, {
            "action": "delete",
            "ids": self._ids([3, 4]),
            "confirm": "1",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Unit.objects.filter(pk__in=delete_pks).exists())
        self.assertEqual(Unit.objects.count(), 3)

    def test_bulk_delete_without_confirm_returns_error(self):
        resp = self.client.post(self.url, {
            "action": "delete",
            "ids": self._ids([0]),
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Unit.objects.filter(pk=self.units[0].pk).exists())
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("confirm" in m.lower() for m in messages))


class UnitBulkActionValidationTest(UnitBulkActionTestCase):
    def test_bulk_action_with_no_ids_returns_error(self):
        resp = self.client.post(self.url, {
            "action": "change_unit_type",
            "ids": "",
            "value": "Whatever",
        })
        self.assertEqual(resp.status_code, 302)
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("select" in m.lower() or "no unit" in m.lower() for m in messages))

    def test_bulk_action_with_invalid_action_returns_error(self):
        resp = self.client.post(self.url, {
            "action": "hack_the_planet",
            "ids": self._ids([0]),
            "value": "x",
        })
        self.assertEqual(resp.status_code, 302)
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("invalid" in m.lower() for m in messages))


class UnitBulkActionRedirectTest(UnitBulkActionTestCase):
    def test_bulk_action_redirects_back_to_unit_list(self):
        resp = self.client.post(self.url, {
            "action": "change_unit_type",
            "ids": self._ids([0]),
            "value": "Generator",
        })
        self.assertRedirects(resp, reverse("catalog:unit_list"), fetch_redirect_response=False)

    def test_bulk_action_preserves_query_string(self):
        resp = self.client.post(self.url + "?type=Starter&q=test", {
            "action": "change_voltage",
            "ids": self._ids([0]),
            "value": "48V",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn("type=Starter", resp.url)
        self.assertIn("q=test", resp.url)
