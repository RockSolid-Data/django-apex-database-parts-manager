"""
Tests for _global_reference_search_hits in catalog/views.py.

Verifies the search function returns correct hit types, deduplicates,
and handles edge cases (empty query, short query, no matches).
"""

from django.test import TestCase

from catalog.models import (
    Application,
    CrossReference,
    Part,
    Substitute,
    Unit,
    UnitType,
)
from catalog.views import _global_reference_search_hits


class GlobalReferenceSearchEmptyQueryTest(TestCase):
    """Edge cases: empty, whitespace-only, or None queries."""

    def test_empty_string_returns_empty(self):
        self.assertEqual(_global_reference_search_hits(""), [])

    def test_none_returns_empty(self):
        self.assertEqual(_global_reference_search_hits(None), [])

    def test_whitespace_only_returns_empty(self):
        self.assertEqual(_global_reference_search_hits("   "), [])


class GlobalReferenceSearchCrossRefTest(TestCase):
    """Cross-reference search produces xref hit_type results."""

    @classmethod
    def setUpTestData(cls):
        cls.ut, _ = UnitType.objects.get_or_create(name="Starter")
        cls.unit = Unit.objects.create(
            unit_number="UN-SEARCH-001", yt_number="YT-S001",
            oem="Delco", unit_type=cls.ut, is_active=True,
        )
        cls.xref = CrossReference.objects.create(
            unit=cls.unit, cross_ref_number="XREF-SEARCH-42",
            interchange_type="Direct",
        )

    def test_xref_match_returns_hit(self):
        hits = _global_reference_search_hits("XREF-SEARCH-42")
        self.assertTrue(len(hits) >= 1)
        xref_hits = [h for h in hits if h["hit_type"] == "Unit cross-reference"]
        self.assertEqual(len(xref_hits), 1)
        self.assertEqual(xref_hits[0]["match"], "XREF-SEARCH-42")

    def test_xref_partial_match(self):
        """Partial/contains matching works for cross-ref numbers."""
        hits = _global_reference_search_hits("SEARCH-42")
        xref_hits = [h for h in hits if h["hit_type"] == "Unit cross-reference"]
        self.assertEqual(len(xref_hits), 1)


class GlobalReferenceSearchUnitTest(TestCase):
    """Unit search returns Unit hit_type results."""

    @classmethod
    def setUpTestData(cls):
        cls.ut, _ = UnitType.objects.get_or_create(name="Alternator")
        cls.unit = Unit.objects.create(
            unit_number="UN-SRCH-ALT-77", yt_number="YT-ALT77",
            oem="Bosch", unit_type=cls.ut, is_active=True,
        )

    def test_unit_number_match(self):
        hits = _global_reference_search_hits("UN-SRCH-ALT-77")
        unit_hits = [h for h in hits if h["hit_type"] == "Unit"]
        self.assertEqual(len(unit_hits), 1)
        self.assertIn("UN-SRCH-ALT-77", unit_hits[0]["primary"])

    def test_yt_number_match(self):
        hits = _global_reference_search_hits("YT-ALT77")
        unit_hits = [h for h in hits if h["hit_type"] == "Unit"]
        self.assertTrue(len(unit_hits) >= 1)


class GlobalReferenceSearchPartTest(TestCase):
    """Part search returns Part hit_type results."""

    @classmethod
    def setUpTestData(cls):
        cls.part = Part.objects.create(
            part_number="PN-SRCH-99", part_name="Test Brush",
            yt_number="YT-P-SRCH-99", category="Brushes", is_active=True,
        )

    def test_part_number_match(self):
        hits = _global_reference_search_hits("PN-SRCH-99")
        part_hits = [h for h in hits if h["hit_type"] == "Part"]
        self.assertEqual(len(part_hits), 1)
        self.assertEqual(part_hits[0]["primary"], "PN-SRCH-99")

    def test_part_name_match(self):
        hits = _global_reference_search_hits("Test Brush")
        part_hits = [h for h in hits if h["hit_type"] == "Part"]
        self.assertTrue(len(part_hits) >= 1)


class GlobalReferenceSearchApplicationTest(TestCase):
    """Application search returns Application hit_type results."""

    @classmethod
    def setUpTestData(cls):
        cls.app = Application.objects.create(
            name="1999 Ford F-150 5.4L Starter",
            make="Ford", model="F-150", year="1999",
            engine="5.4L", is_active=True,
        )

    def test_application_make_match(self):
        hits = _global_reference_search_hits("Ford")
        app_hits = [h for h in hits if h["hit_type"] == "Application"]
        self.assertTrue(len(app_hits) >= 1)


class GlobalReferenceSearchDedupTest(TestCase):
    """Duplicate results are suppressed by the dup set."""

    @classmethod
    def setUpTestData(cls):
        cls.ut, _ = UnitType.objects.get_or_create(name="Starter")
        cls.unit = Unit.objects.create(
            unit_number="DEDUP-UNIT-01", yt_number="DEDUP-UNIT-01",
            oem="DEDUP-UNIT-01", unit_type=cls.ut, is_active=True,
        )

    def test_same_unit_appears_once(self):
        """A unit matching multiple fields should appear only once."""
        hits = _global_reference_search_hits("DEDUP-UNIT-01")
        unit_hits = [h for h in hits if h["hit_type"] == "Unit"]
        self.assertEqual(len(unit_hits), 1)


class GlobalReferenceSearchLimitTest(TestCase):
    """The limit parameter caps total results."""

    def test_limit_caps_results(self):
        hits = _global_reference_search_hits("a", limit=5)
        self.assertLessEqual(len(hits), 5)
