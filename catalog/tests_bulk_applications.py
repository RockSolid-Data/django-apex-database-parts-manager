from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from .models import Application


class ApplicationBulkActionTestCase(TestCase):
    """Shared setup: create applications to act on."""

    @classmethod
    def setUpTestData(cls):
        cls.apps = [
            Application.objects.create(
                name=f"Bulk App {i}",
                make="OldMake",
                year="2010",
                unit_type_name="Starter",
                volt="12V",
            )
            for i in range(1, 6)
        ]
        cls.url = reverse("catalog:application_bulk_action")

    def _ids(self, indices=None):
        if indices is None:
            indices = range(len(self.apps))
        return ",".join(str(self.apps[i].pk) for i in indices)


class ApplicationBulkChangeMakeTest(ApplicationBulkActionTestCase):
    def test_bulk_change_make_updates_selected_applications(self):
        resp = self.client.post(self.url, {
            "action": "change_make",
            "ids": self._ids([0, 1, 2]),
            "value": "Caterpillar",
        })
        self.assertEqual(resp.status_code, 302)
        for a in Application.objects.filter(pk__in=[self.apps[i].pk for i in [0, 1, 2]]):
            self.assertEqual(a.make, "Caterpillar")
        unchanged = Application.objects.get(pk=self.apps[3].pk)
        self.assertEqual(unchanged.make, "OldMake")


class ApplicationBulkChangeYearTest(ApplicationBulkActionTestCase):
    def test_bulk_change_year_updates_selected_applications(self):
        resp = self.client.post(self.url, {
            "action": "change_year",
            "ids": self._ids([1, 3]),
            "value": "2020-2024",
        })
        self.assertEqual(resp.status_code, 302)
        for a in Application.objects.filter(pk__in=[self.apps[i].pk for i in [1, 3]]):
            self.assertEqual(a.year, "2020-2024")
        unchanged = Application.objects.get(pk=self.apps[0].pk)
        self.assertEqual(unchanged.year, "2010")


class ApplicationBulkChangeUnitTypeTest(ApplicationBulkActionTestCase):
    def test_bulk_change_unit_type_updates_selected_applications(self):
        resp = self.client.post(self.url, {
            "action": "change_unit_type",
            "ids": self._ids([0, 4]),
            "value": "Alternator",
        })
        self.assertEqual(resp.status_code, 302)
        for a in Application.objects.filter(pk__in=[self.apps[i].pk for i in [0, 4]]):
            self.assertEqual(a.unit_type_name, "Alternator")
        unchanged = Application.objects.get(pk=self.apps[2].pk)
        self.assertEqual(unchanged.unit_type_name, "Starter")


class ApplicationBulkChangeVoltTest(ApplicationBulkActionTestCase):
    def test_bulk_change_volt_updates_selected_applications(self):
        resp = self.client.post(self.url, {
            "action": "change_volt",
            "ids": self._ids([0, 2]),
            "value": "24V",
        })
        self.assertEqual(resp.status_code, 302)
        for a in Application.objects.filter(pk__in=[self.apps[i].pk for i in [0, 2]]):
            self.assertEqual(a.volt, "24V")
        unchanged = Application.objects.get(pk=self.apps[1].pk)
        self.assertEqual(unchanged.volt, "12V")


class ApplicationBulkDeleteTest(ApplicationBulkActionTestCase):
    def test_bulk_delete_removes_selected_applications(self):
        delete_pks = [self.apps[i].pk for i in [3, 4]]
        resp = self.client.post(self.url, {
            "action": "delete",
            "ids": self._ids([3, 4]),
            "confirm": "1",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Application.objects.filter(pk__in=delete_pks).exists())
        self.assertEqual(Application.objects.count(), 3)

    def test_bulk_delete_without_confirm_returns_error(self):
        resp = self.client.post(self.url, {
            "action": "delete",
            "ids": self._ids([0]),
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Application.objects.filter(pk=self.apps[0].pk).exists())
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("confirm" in m.lower() for m in messages))


class ApplicationBulkActionValidationTest(ApplicationBulkActionTestCase):
    def test_bulk_action_with_no_ids_returns_error(self):
        resp = self.client.post(self.url, {
            "action": "change_make",
            "ids": "",
            "value": "Whatever",
        })
        self.assertEqual(resp.status_code, 302)
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(
            any("select" in m.lower() or "no application" in m.lower() for m in messages)
        )

    def test_bulk_action_with_invalid_action_returns_error(self):
        resp = self.client.post(self.url, {
            "action": "hack_the_planet",
            "ids": self._ids([0]),
            "value": "x",
        })
        self.assertEqual(resp.status_code, 302)
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("invalid" in m.lower() for m in messages))


class ApplicationBulkActionRedirectTest(ApplicationBulkActionTestCase):
    def test_bulk_action_redirects_back_to_application_list(self):
        resp = self.client.post(self.url, {
            "action": "change_make",
            "ids": self._ids([0]),
            "value": "John Deere",
        })
        self.assertRedirects(
            resp, reverse("catalog:application_list"), fetch_redirect_response=False
        )

    def test_bulk_action_preserves_query_string(self):
        resp = self.client.post(self.url + "?make=OldMake&q=test", {
            "action": "change_year",
            "ids": self._ids([0]),
            "value": "2022",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn("make=OldMake", resp.url)
        self.assertIn("q=test", resp.url)
