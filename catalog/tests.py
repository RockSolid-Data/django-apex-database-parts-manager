import json

from django.test import TestCase
from django.urls import reverse

from .models import (
    Application,
    ApplicationSpecification,
    ApplicationUnit,
    BOM,
    BOMItem,
    Part,
    PartInterchange,
    Unit,
    UnitType,
)
from .pdf_utils import _apply_manual_entry_adjustments, _finalize_entries, _parse_column_lines, _parse_page


class HomeViewTest(TestCase):
    """Verify home page shortcut cards match header nav links."""

    def test_home_renders(self):
        """Home page loads."""
        resp = self.client.get(reverse("catalog:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Apex Database")
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
            manufacturer_number="KEY-1",
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

    def test_part_can_be_created_without_part_number(self):
        """Part number may be blank so PDF imports can store YT only."""
        part = Part.objects.create(yt_number="YT-MIN")
        self.assertIsNone(part.part_number)
        self.assertEqual(part.stock_quantity, 0)
        self.assertEqual(part.reorder_qty, 0)
        self.assertIsNone(part.unit)
        self.assertEqual(part.yt_number, "YT-MIN")


class YouTechPdfParserTest(TestCase):
    """Verify YouTech PDF parsing edge cases."""

    class _StubPage:
        def __init__(self, words, width=512):
            self._words = words
            self.width = width

        def extract_words(self, **kwargs):
            return list(self._words)

    def _word(self, text, x0, fontname="Regular", top=0):
        return {"text": text, "x0": x0, "fontname": fontname, "top": top}

    def test_parse_column_lines_keeps_wrapped_vendor_name(self):
        """Vendor names that wrap should merge into one source/name."""
        lines = [
            [self._word("0A-00547", 0, "Bold")],
            [self._word("Rectifier", 0, "Bold"), self._word("Bridge", 30, "Bold"), self._word("Nut", 65, "Bold")],
            [self._word("Romaine", 0)],
            [self._word("Electric", 0), self._word("949056-3300", 70)],
        ]

        entries = []
        _parse_column_lines(lines, vendor_num_split=58, entries=entries, page_number=1)

        self.assertEqual(entries[0]["yt_number"], "0A-00547")
        self.assertEqual(entries[0]["page_number"], 1)
        self.assertEqual(
            entries[0]["interchanges"],
            [{"vendor": "Romaine Electric", "number": "949056-3300"}],
        )

    def test_parse_column_lines_splits_embedded_vendor_number(self):
        """Embedded vendor/source text should split into separate interchange rows."""
        lines = [
            [self._word("0A-13002", 0, "Bold"), self._word("Thru", 30, "Bold"), self._word("Bolt", 60, "Bold")],
            [self._word("Delco-Remy", 0), self._word("!2501", 70)],
            [self._word("Voltux", 0), self._word("V4-DR260", 70), self._word("Just", 120), self._word("Parts", 145), self._word("D1-6033", 185)],
        ]

        entries = []
        _parse_column_lines(lines, vendor_num_split=58, entries=entries, page_number=1)

        self.assertNotIn("Check interchange number '!2501'.", entries[0]["issues"])
        self.assertEqual(
            entries[0]["interchanges"],
            [
                {"vendor": "Delco-Remy", "number": "!2501"},
                {"vendor": "Voltux", "number": "V4-DR260"},
                {"vendor": "Just Parts", "number": "D1-6033"},
            ],
        )

    def test_parse_column_lines_appends_trailing_vendor_fragment(self):
        """Trailing vendor fragments should be attached to the last interchange vendor."""
        lines = [
            [self._word("0A-60019", 0, "Bold"), self._word("Connector", 30, "Bold")],
            [self._word("Romaine", 0), self._word("028172-0370", 70)],
            [self._word("Electric", 0)],
        ]

        entries = []
        _parse_column_lines(lines, vendor_num_split=58, entries=entries, page_number=4)

        self.assertEqual(
            entries[0]["interchanges"],
            [{"vendor": "Romaine Electric", "number": "028172-0370"}],
        )
        self.assertEqual(entries[0]["issues"], [])

    def test_parse_column_lines_merges_trailing_vendor_fragment_before_number_only_row(self):
        """Wrapped fragments like Electric should merge before a number-only continuation."""
        lines = [
            [self._word("0A-00547", 0, "Bold")],
            [self._word("Rectifier", 0, "Bold")],
            [self._word("Romaine", 0), self._word("949056-3300", 70)],
            [self._word("Electric", 0)],
            [self._word("949056-3301", 70)],
        ]

        entries = []
        _parse_column_lines(lines, vendor_num_split=58, entries=entries, page_number=1)

        self.assertEqual(
            entries[0]["interchanges"],
            [
                {"vendor": "Romaine Electric", "number": "949056-3300"},
                {"vendor": "Romaine Electric", "number": "949056-3301"},
            ],
        )
        self.assertEqual(entries[0]["issues"], [])

    def test_parse_column_lines_reuses_vendor_for_number_only_rows(self):
        """Number-only rows should inherit the previous vendor."""
        lines = [
            [self._word("0A-00547", 0, "Bold")],
            [self._word("Rectifier", 0, "Bold")],
            [self._word("J&N", 0), self._word("462-64004", 70)],
            [self._word("462-64004-20", 70)],
        ]

        entries = []
        _parse_column_lines(lines, vendor_num_split=58, entries=entries, page_number=1)

        self.assertEqual(
            entries[0]["interchanges"],
            [
                {"vendor": "J&N", "number": "462-64004"},
                {"vendor": "J&N", "number": "462-64004-20"},
            ],
        )

    def test_parse_column_lines_merges_hyphenated_number_fragments(self):
        """Hyphen-ended numbers should merge with the next numeric fragment."""
        lines = [
            [self._word("0A-00548", 0, "Bold")],
            [self._word("Rectifier", 0, "Bold")],
            [self._word("Daihatsu", 0), self._word("27794-87501-", 70)],
            [self._word("000", 70)],
        ]

        entries = []
        _parse_column_lines(lines, vendor_num_split=58, entries=entries, page_number=1)

        self.assertEqual(
            entries[0]["interchanges"],
            [{"vendor": "Daihatsu", "number": "27794-87501-000"}],
        )

    def test_parse_column_lines_splits_compact_right_side_vendor_number(self):
        """When vendor and number both land on the right side, split them back apart."""
        lines = [
            [self._word("1A-1307", 0, "Bold")],
            [self._word("Brush", 0, "Bold")],
            [self._word("NRG", 80), self._word("1207", 100)],
        ]

        entries = []
        _parse_column_lines(lines, vendor_num_split=58, entries=entries, page_number=24)

        self.assertEqual(
            entries[0]["interchanges"],
            [{"vendor": "NRG", "number": "1207"}],
        )
        self.assertEqual(entries[0]["issues"], [])

    def test_parse_column_lines_allows_spaced_numeric_reference(self):
        """References made of spaced numeric groups should not be flagged."""
        lines = [
            [self._word("1A-50090", 0, "Bold")],
            [self._word("Pulley", 0, "Bold")],
            [self._word("INA", 0), self._word("CA", 20), self._word("-", 35), self._word("535", 75), self._word("0226", 92), self._word("10", 113)],
        ]

        entries = []
        _parse_column_lines(lines, vendor_num_split=58, entries=entries, page_number=61)

        self.assertEqual(
            entries[0]["interchanges"],
            [{"vendor": "INA CA -", "number": "535 0226 10"}],
        )
        self.assertEqual(entries[0]["issues"], [])

    def test_parse_column_lines_strips_repeated_vendor_prefix(self):
        """Duplicate vendor text repeated on the number side should be removed."""
        lines = [
            [self._word("1A-1307", 0, "Bold")],
            [self._word("Brush", 0, "Bold")],
            [self._word("NRG", 0), self._word("NRG", 80), self._word("1207", 100)],
        ]

        entries = []
        _parse_column_lines(lines, vendor_num_split=58, entries=entries, page_number=24)

        self.assertEqual(
            entries[0]["interchanges"],
            [{"vendor": "NRG", "number": "1207"}],
        )
        self.assertEqual(entries[0]["issues"], [])

    def test_parse_column_lines_keeps_exact_spaced_reference_when_vendor_is_clear(self):
        """If the source/name is clear, keep the exact spaced reference text."""
        lines = [
            [self._word("1A-12042", 0, "Bold")],
            [self._word("Rectifier", 0, "Bold")],
            [self._word("Model", 0), self._word("Number", 20), self._word("7SI", 80), self._word("Korea", 95)],
        ]

        entries = []
        _parse_column_lines(lines, vendor_num_split=58, entries=entries, page_number=18)

        self.assertEqual(
            entries[0]["interchanges"],
            [{"vendor": "Model Number", "number": "7SI Korea"}],
        )
        self.assertEqual(entries[0]["issues"], [])

    def test_parse_column_lines_splits_embedded_second_vendor(self):
        """A second vendor embedded in the number text should become a new interchange row."""
        lines = [
            [self._word("1G-1200", 0, "Bold")],
            [self._word("Rectifier", 0, "Bold")],
            [self._word("Bosch", 0), self._word("1-127-320-355", 70), self._word("Just", 140), self._word("Parts", 165), self._word("BO1-1220", 210)],
        ]

        entries = []
        _parse_column_lines(lines, vendor_num_split=58, entries=entries, page_number=185)

        self.assertEqual(
            entries[0]["interchanges"],
            [
                {"vendor": "Bosch", "number": "1-127-320-355"},
                {"vendor": "Just Parts", "number": "BO1-1220"},
            ],
        )
        self.assertEqual(entries[0]["issues"], [])

    def test_parse_column_lines_moves_trailing_vendor_fragment_off_number(self):
        """Trailing vendor suffixes at the end of a number should be attached to the vendor."""
        lines = [
            [self._word("1G-50021", 0, "Bold")],
            [self._word("Pulley", 0, "Bold")],
            [self._word("Romaine", 0), self._word("24-91107-1", 70), self._word("Electric", 120)],
        ]

        entries = []
        _parse_column_lines(lines, vendor_num_split=58, entries=entries, page_number=222)

        self.assertEqual(
            entries[0]["interchanges"],
            [{"vendor": "Romaine Electric", "number": "24-91107-1"}],
        )
        self.assertEqual(entries[0]["issues"], [])

    def test_parse_column_lines_replaces_fragment_vendor_with_embedded_vendor(self):
        """A fragment vendor on the left should be replaced by a real vendor in the number text."""
        lines = [
            [self._word("1M-60000", 0, "Bold")],
            [self._word("Regulator", 0, "Bold")],
            [self._word("Parts", 0), self._word("J&N", 80), self._word("230-40004", 105)],
        ]

        entries = []
        _parse_column_lines(lines, vendor_num_split=58, entries=entries, page_number=434)

        self.assertEqual(
            entries[0]["interchanges"],
            [{"vendor": "J&N", "number": "230-40004"}],
        )
        self.assertEqual(entries[0]["issues"], [])

    def test_parse_column_lines_merges_short_alpha_continuation(self):
        """Short alpha continuations like AA should merge onto a trailing hyphenated number."""
        lines = [
            [self._word("1B-6007", 0, "Bold")],
            [self._word("Regulator", 0, "Bold")],
            [self._word("Ford", 0), self._word("D2AF-10316-", 70)],
            [self._word("AA", 70)],
        ]

        entries = []
        _parse_column_lines(lines, vendor_num_split=58, entries=entries, page_number=115)

        self.assertEqual(
            entries[0]["interchanges"],
            [{"vendor": "Ford", "number": "D2AF-10316-AA"}],
        )
        self.assertEqual(entries[0]["issues"], [])

    def test_parse_column_lines_keeps_mgx_reference_together(self):
        """MGX/MSX references should stay together as one reference number."""
        lines = [
            [self._word("1L-30033", 0, "Bold")],
            [self._word("Rotor", 0, "Bold")],
            [self._word("MAHLE", 0), self._word("MGX", 80), self._word("871", 102)],
        ]

        entries = []
        _parse_column_lines(lines, vendor_num_split=58, entries=entries, page_number=413)

        self.assertEqual(
            entries[0]["interchanges"],
            [{"vendor": "MAHLE", "number": "MGX 871"}],
        )
        self.assertEqual(entries[0]["issues"], [])

    def test_parse_page_continues_entry_into_inferred_missing_column(self):
        """Continuation rows before the next bold YT should stay on the current part."""
        words = [
            self._word("1B-6007", 0, "Bold", top=0),
            self._word("Charging", 0, "Bold", top=10),
            self._word("System", 40, "Bold", top=10),
            self._word("Voltage", 75, "Bold", top=10),
            self._word("Ford", 0, top=25),
            self._word("D2AF-10316-", 70, top=25),
            self._word("AA", 70, top=35),
            self._word("J&N", 129, top=0),
            self._word("230-14004", 205, top=0),
            self._word("230-14006", 205, top=10),
            self._word("1B-6008", 258, "Bold", top=60),
            self._word("Charging", 258, "Bold", top=70),
            self._word("Voltage", 298, "Bold", top=70),
            self._word("Transpo", 258, top=85),
            self._word("F540HD", 335, top=85),
        ]

        entries = []
        _parse_page(self._StubPage(words), entries, page_number=115)

        self.assertEqual([entry["yt_number"] for entry in entries], ["1B-6007", "1B-6008"])
        self.assertEqual(
            entries[0]["interchanges"],
            [
                {"vendor": "Ford", "number": "D2AF-10316-AA"},
                {"vendor": "J&N", "number": "230-14004"},
                {"vendor": "J&N", "number": "230-14006"},
            ],
        )
        self.assertEqual(
            entries[1]["interchanges"],
            [{"vendor": "Transpo", "number": "F540HD"}],
        )

    def test_manual_adjustments_convert_aa_reference_and_move_harvester_block(self):
        """Known final edge cases should be normalized after parsing."""
        entries = [
            {
                "yt_number": "1B-6007",
                "description": "Charging System Voltage",
                "category": "Electrical",
                "interchanges": [
                    {"vendor": "AA", "number": "F782"},
                    {"vendor": "Just Parts", "number": "AA"},
                ],
                "page_number": 115,
                "issues": ["Check interchange number 'AA'."],
            },
            {
                "yt_number": "2G-5048",
                "description": "Starter Drive",
                "category": "Hardware",
                "interchanges": [],
                "page_number": 874,
                "issues": [],
            },
            {
                "yt_number": "2G-50479",
                "description": "Starter Drive International 3078 758 R91",
                "category": "Hardware",
                "interchanges": [
                    {"vendor": "", "number": "Harvester (IHC)"},
                    {"vendor": "Bosch", "number": "2-006-382-060 3078 758 R92"},
                    {"vendor": "HC CARGO", "number": "135374 3078 960 R91"},
                ],
                "page_number": 874,
                "issues": ["Check interchange number 'Harvester (IHC)'."],
            },
        ]

        _apply_manual_entry_adjustments(entries)

        self.assertEqual(
            entries[0]["interchanges"],
            [
                {"vendor": "", "number": "AA F782"},
                {"vendor": "", "number": "AA"},
            ],
        )
        self.assertEqual(entries[0]["issues"], [])
        self.assertIn(
            {"vendor": "Harvester (IHC)", "number": "3078 758 R92"},
            entries[1]["interchanges"],
        )
        self.assertIn(
            {"vendor": "Harvester (IHC)", "number": "3132 442 R1"},
            entries[1]["interchanges"],
        )
        self.assertEqual(
            entries[2]["interchanges"],
            [
                {"vendor": "Bosch", "number": "2-006-382-060"},
                {"vendor": "HC CARGO", "number": "135374"},
            ],
        )
        self.assertEqual(entries[2]["issues"], [])

    def test_finalize_entries_merges_page_continuations(self):
        """Same YT number on the next page should merge into one entry."""
        entries = [
            {
                "yt_number": "1A-1232",
                "description": "Rectifier DR4000HD",
                "category": "Electrical",
                "interchanges": [{"vendor": "Ace Electric", "number": "S-1681"}],
                "page_number": 22,
                "issues": [],
            },
            {
                "yt_number": "1A-1232",
                "description": "Rectifier",
                "category": "Electrical",
                "interchanges": [{"vendor": "WAI", "number": "31-136"}],
                "page_number": 23,
                "issues": [],
            },
        ]

        _finalize_entries(entries)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["description"], "Rectifier DR4000HD")
        self.assertEqual(
            entries[0]["interchanges"],
            [
                {"vendor": "Ace Electric", "number": "S-1681"},
                {"vendor": "WAI", "number": "31-136"},
            ],
        )


class PartImportPdfConfirmTest(TestCase):
    """Verify the PDF confirm step writes part and interchange data correctly."""

    def test_confirm_import_leaves_part_number_blank_and_saves_source(self):
        """YT number stays in YT field only, and interchanges store source separately."""
        response = self.client.post(
            reverse("catalog:part_import_pdf"),
            {
                "step": "confirm",
                "row_count": "1",
                "row_0_yt_number": "0A-00547",
                "row_0_description": "Rectifier Bridge Nut",
                "row_0_category": "Electrical",
                "row_0_interchanges": json.dumps(
                    [
                        {"vendor": "J&N", "number": "462-64004"},
                        {"vendor": "PIC", "number": "9590-003"},
                    ]
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        part = Part.objects.get(yt_number="0A-00547")
        self.assertIsNone(part.part_number)
        self.assertEqual(part.part_name, "Rectifier Bridge Nut")
        self.assertEqual(part.description, "Rectifier Bridge Nut")
        self.assertTrue(part.has_interchange)

        interchanges = list(
            PartInterchange.objects.filter(part=part).order_by("source_name", "interchange_number")
        )
        self.assertEqual(
            [(ix.source_name, ix.interchange_number, ix.notes) for ix in interchanges],
            [
                ("J&N", "462-64004", ""),
                ("PIC", "9590-003", ""),
            ],
        )


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
