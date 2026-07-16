from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from catalog.models import Part, Unit, UnitType

from .models import CompanySettings, Customer, Invoice, InvoiceItem, NetTerms


class CompanySettingsTest(TestCase):
    """Verify CompanySettings model and net terms."""

    def test_company_settings_get_creates_default(self):
        """CompanySettings.get() creates default when none exists."""
        self.assertFalse(CompanySettings.objects.exists())
        s = CompanySettings.get()
        self.assertEqual(s.company_name, "")
        self.assertEqual(s.default_net_terms, NetTerms.NET_30)

    def test_get_due_date_net_10(self):
        """Net 10: due_date = invoice_date + 10 days."""
        from datetime import date
        s = CompanySettings.get()
        s.default_net_terms = NetTerms.NET_10
        s.save()
        d = date(2026, 2, 12)
        self.assertEqual(s.get_due_date(d), date(2026, 2, 22))

    def test_get_due_date_due_on_receipt(self):
        """Due on receipt: due_date = invoice_date."""
        from datetime import date
        s = CompanySettings.get()
        s.default_net_terms = NetTerms.DUE_ON_RECEIPT
        s.save()
        d = date(2026, 2, 12)
        self.assertEqual(s.get_due_date(d), d)

    def test_get_due_date_custom(self):
        """Custom: due_date = invoice_date + default_net_days."""
        from datetime import date
        s = CompanySettings.get()
        s.default_net_terms = NetTerms.CUSTOM
        s.default_net_days = 15
        s.save()
        d = date(2026, 2, 12)
        self.assertEqual(s.get_due_date(d), date(2026, 2, 27))


class CustomerNetTermsTest(TestCase):
    """Verify Customer net terms override."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Test Customer")

    def test_customer_uses_company_default_when_net_terms_blank(self):
        """When net_terms is blank, customer uses company default."""
        s = CompanySettings.get()
        s.default_net_terms = NetTerms.NET_30
        s.save()
        days = self.customer.get_effective_net_days()
        self.assertEqual(days, 30)

    def test_customer_override_net_10(self):
        """Customer with Net 10 returns 10 days."""
        self.customer.net_terms = NetTerms.NET_10
        self.customer.save()
        self.assertEqual(self.customer.get_effective_net_days(), 10)

    def test_customer_override_custom(self):
        """Customer with Custom uses net_days."""
        self.customer.net_terms = NetTerms.CUSTOM
        self.customer.net_days = 45
        self.customer.save()
        self.assertEqual(self.customer.get_effective_net_days(), 45)


class CustomerModelTest(TestCase):
    """Verify Customer model per database plan (7.1)."""

    def test_customer_create_with_all_fields(self):
        """Customer has all fields from DATABASE_PLAN."""
        c = Customer.objects.create(
            name="Acme Corp",
            bill_to_line1="123 Main St",
            bill_to_line2="Suite 100",
            bill_to_city="Springfield",
            bill_to_state="IL",
            bill_to_zip="62701",
            notes="Preferred customer",
            is_active=True,
        )
        self.assertEqual(c.name, "Acme Corp")
        self.assertEqual(c.bill_to_city, "Springfield")
        self.assertTrue(c.is_active)
        self.assertIsNotNone(c.created_at)
        self.assertIsNotNone(c.updated_at)

    def test_customer_minimal_required_fields(self):
        """Customer requires only name."""
        c = Customer.objects.create(name="Minimal Customer")
        self.assertEqual(c.name, "Minimal Customer")
        self.assertEqual(c.email, "")
        self.assertTrue(c.is_active)


class SettingsViewTest(TestCase):
    """Verify Settings page."""

    def test_settings_renders(self):
        """Settings page loads."""
        resp = self.client.get(reverse("invoicing:settings"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Settings")
        self.assertContains(resp, "Company Information")
        self.assertContains(resp, "Default Payment Terms")

    def test_settings_post_saves(self):
        """Saving settings updates defaults."""
        resp = self.client.post(reverse("invoicing:settings"), {
            "company_name": "Acme Electric",
            "logo": "",
            "email": "info@acme.com",
            "phone": "555-0000",
            "address": "",
            "default_net_terms": NetTerms.NET_10,
            "default_net_days": "30",
            "default_tax_rate": "8.5",
            "pricing_method": CompanySettings.PRICING_MARKUP,
            "invoice_number_prefix": "INV-",
            "invoice_number_padding": "4",
            "invoice_paper_size": CompanySettings.PAPER_LETTER,
            "invoice_layout_style": CompanySettings.LAYOUT_STANDARD,
            "invoice_date_format": CompanySettings.DATE_FMT_FULL,
            "invoice_currency_symbol": "$",
        })
        self.assertRedirects(resp, reverse("invoicing:settings"))
        s = CompanySettings.get()
        self.assertEqual(s.company_name, "Acme Electric")
        self.assertEqual(s.default_net_terms, NetTerms.NET_10)
        self.assertEqual(s.default_tax_rate, Decimal("8.5"))


class CustomerViewTest(TestCase):
    """Verify Customer CRUD views (7.2)."""

    def test_customer_list_renders(self):
        """Customer list page loads."""
        url = reverse("invoicing:customer_list")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Customers")

    def test_customer_create_renders(self):
        """Add customer form loads."""
        url = reverse("invoicing:customer_create")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Add New Customer")

    def test_customer_create_post(self):
        """Creating a customer redirects to list."""
        url = reverse("invoicing:customer_create")
        resp = self.client.post(url, {
            "name": "New Customer Co",
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
            "net_terms": "",
            "net_days": "0",
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
        self.assertRedirects(resp, reverse("invoicing:customer_list"))
        self.assertTrue(Customer.objects.filter(name="New Customer Co").exists())

    def test_customer_edit_renders(self):
        """Edit customer form loads."""
        c = Customer.objects.create(name="Edit Me")
        url = reverse("invoicing:customer_edit", kwargs={"pk": c.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Edit Customer")
        self.assertContains(resp, "Edit Me")

    def test_customer_edit_post(self):
        """Editing a customer updates and redirects."""
        c = Customer.objects.create(name="Original Name")
        url = reverse("invoicing:customer_edit", kwargs={"pk": c.pk})
        resp = self.client.post(url, {
            "name": "Updated Name",
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
            "net_terms": "",
            "net_days": "0",
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
        self.assertRedirects(resp, reverse("invoicing:customer_list"))
        c.refresh_from_db()
        self.assertEqual(c.name, "Updated Name")


class InvoiceModelTest(TestCase):
    """Verify Invoice model per database plan (7.3)."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Test Customer")

    def test_invoice_create_with_all_fields(self):
        """Invoice has all fields from DATABASE_PLAN."""
        inv = Invoice.objects.create(
            invoice_number="INV-001",
            customer=self.customer,
            date="2026-02-11",
            due_date="2026-03-11",
            status=Invoice.Status.DRAFT,
            subtotal=Decimal("100.00"),
            tax_rate=Decimal("10.00"),
            tax_amount=Decimal("10.00"),
            total=Decimal("110.00"),
            notes="Test notes",
        )
        self.assertEqual(inv.invoice_number, "INV-001")
        self.assertEqual(inv.customer, self.customer)
        self.assertEqual(inv.status, Invoice.Status.DRAFT)
        self.assertEqual(inv.subtotal, 100)
        self.assertEqual(inv.total, 110)
        self.assertIsNotNone(inv.created_at)

    def test_invoice_status_choices(self):
        """Invoice has DRAFT, SENT, PAID, OVERDUE, CANCELLED statuses."""
        for status in Invoice.Status:
            inv = Invoice.objects.create(
                invoice_number=f"INV-{status.value}",
                customer=self.customer,
                date="2026-02-11",
                status=status,
            )
            self.assertEqual(inv.status, status.value)


class InvoiceItemModelTest(TestCase):
    """Verify InvoiceItem model per database plan (7.3)."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Test Customer")
        self.invoice = Invoice.objects.create(
            invoice_number="INV-001",
            customer=self.customer,
            date="2026-02-11",
        )

    def test_invoice_item_auto_calculates_line_total(self):
        """InvoiceItem line_total = quantity × unit_price."""
        item = InvoiceItem.objects.create(
            invoice=self.invoice,
            description="Test part",
            quantity=3,
            unit_price=Decimal("10.50"),
        )
        self.assertEqual(item.line_total, Decimal("31.50"))

    def test_invoice_item_optional_part_and_unit(self):
        """InvoiceItem allows null part and unit (custom lines)."""
        item = InvoiceItem.objects.create(
            invoice=self.invoice,
            description="Custom line",
            quantity=1,
            unit_price=Decimal("25.00"),
        )
        self.assertIsNone(item.part)
        self.assertIsNone(item.unit)
        self.assertEqual(item.line_total, 25)

    def test_invoice_recalculate_totals(self):
        """Invoice.recalculate_totals() sums items and computes tax."""
        InvoiceItem.objects.create(
            invoice=self.invoice,
            description="Item 1",
            quantity=2,
            unit_price=Decimal("50.00"),
        )
        InvoiceItem.objects.create(
            invoice=self.invoice,
            description="Item 2",
            quantity=1,
            unit_price=Decimal("25.00"),
        )
        self.invoice.tax_rate = Decimal("10.00")
        self.invoice.recalculate_totals()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.subtotal, Decimal("125.00"))
        self.assertEqual(self.invoice.tax_amount, Decimal("12.50"))
        self.assertEqual(self.invoice.total, Decimal("137.50"))


class InvoiceListViewTest(TestCase):
    """Verify Invoice list page (7.4)."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Test Customer")

    def test_invoice_list_renders(self):
        """Invoice list page loads."""
        resp = self.client.get(reverse("invoicing:invoice_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Invoices")
        self.assertContains(resp, "New Invoice")
        self.assertContains(resp, "Customers")
        self.assertContains(resp, "Suppliers")

    def test_invoice_list_shows_invoices(self):
        """Invoices appear in the table; each row links to the invoice detail page."""
        inv = Invoice.objects.create(
            invoice_number="INV-001",
            customer=self.customer,
            date="2026-02-11",
        )
        resp = self.client.get(reverse("invoicing:invoice_list"))
        self.assertContains(resp, "INV-001")
        self.assertContains(resp, "Test Customer")
        # Rows are clickable (data-href) rather than showing separate View/Edit links.
        self.assertContains(resp, reverse("invoicing:invoice_detail", kwargs={"pk": inv.pk}))

    def test_invoice_list_search(self):
        """Search filters by invoice number and customer."""
        Invoice.objects.create(
            invoice_number="INV-AAA",
            customer=self.customer,
            date="2026-02-11",
        )
        c2 = Customer.objects.create(name="Other Corp")
        Invoice.objects.create(
            invoice_number="INV-BBB",
            customer=c2,
            date="2026-02-11",
        )
        resp = self.client.get(reverse("invoicing:invoice_list"), {"q": "AAA"})
        self.assertContains(resp, "INV-AAA")
        self.assertNotContains(resp, "INV-BBB")
        resp = self.client.get(reverse("invoicing:invoice_list"), {"q": "Test Customer"})
        self.assertContains(resp, "INV-AAA")

    def test_invoice_list_has_bulk_print(self):
        """Invoice list offers bulk printing of selected invoices."""
        Invoice.objects.create(
            invoice_number="INV-PRINT",
            customer=self.customer,
            date="2026-02-11",
        )
        resp = self.client.get(reverse("invoicing:invoice_list"))
        self.assertContains(resp, "Print Selected")
        self.assertContains(resp, reverse("invoicing:invoice_bulk_print"))

    def test_invoice_list_has_print_report_button(self):
        """Invoice list includes Print Report button."""
        resp = self.client.get(reverse("invoicing:invoice_list"))
        self.assertContains(resp, "Print Report")
        self.assertContains(resp, reverse("invoicing:invoice_report"))

    def test_invoice_list_print_view(self):
        """Invoice list with print=1 returns print-only template."""
        Invoice.objects.create(
            invoice_number="INV-001",
            customer=self.customer,
            date="2026-02-11",
            total=Decimal("100.00"),
        )
        resp = self.client.get(reverse("invoicing:invoice_list") + "?print=1")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Invoice List")
        self.assertContains(resp, "INV-001")
        self.assertNotContains(resp, "navbar")


class InvoiceReportViewTest(TestCase):
    """Verify Invoice report page."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Test Customer")

    def test_invoice_report_renders(self):
        """Report page loads with filters."""
        resp = self.client.get(reverse("invoicing:invoice_report"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Invoice Report")
        self.assertContains(resp, "Status")
        self.assertContains(resp, "Date From")
        self.assertContains(resp, "Date To")
        self.assertContains(resp, "Detailed")
        self.assertContains(resp, "Customer Summary")

    def test_invoice_report_detailed_shows_invoices(self):
        """Detailed report shows invoice rows and grand total."""
        inv = Invoice.objects.create(
            invoice_number="INV-001",
            customer=self.customer,
            date="2026-02-11",
            total=Decimal("100.00"),
        )
        resp = self.client.get(reverse("invoicing:invoice_report"), {"report_type": "detailed"})
        self.assertContains(resp, "INV-001")
        self.assertContains(resp, "Invoice")
        self.assertContains(resp, "$100.00")
        self.assertContains(resp, "TOTAL")

    def test_invoice_report_customer_summary(self):
        """Customer summary groups by customer with totals."""
        inv1 = Invoice.objects.create(
            invoice_number="INV-001",
            customer=self.customer,
            date="2026-02-11",
            total=Decimal("50.00"),
        )
        inv2 = Invoice.objects.create(
            invoice_number="INV-002",
            customer=self.customer,
            date="2026-02-12",
            total=Decimal("75.00"),
        )
        resp = self.client.get(reverse("invoicing:invoice_report"), {"report_type": "customer_summary"})
        self.assertContains(resp, "Test Customer")
        self.assertContains(resp, "INV-001")
        self.assertContains(resp, "INV-002")
        self.assertContains(resp, "$125.00")
        self.assertContains(resp, "TOTAL")

    def test_invoice_report_status_filter(self):
        """Status filter limits invoices (single or multiple)."""
        Invoice.objects.create(
            invoice_number="INV-PAID",
            customer=self.customer,
            date="2026-02-11",
            status=Invoice.Status.PAID,
            total=Decimal("100.00"),
        )
        Invoice.objects.create(
            invoice_number="INV-DRAFT",
            customer=self.customer,
            date="2026-02-11",
            status=Invoice.Status.DRAFT,
            total=Decimal("50.00"),
        )
        Invoice.objects.create(
            invoice_number="INV-SENT",
            customer=self.customer,
            date="2026-02-11",
            status=Invoice.Status.SENT,
            total=Decimal("75.00"),
        )
        resp = self.client.get(reverse("invoicing:invoice_report"), {"status": "PAID"})
        self.assertContains(resp, "INV-PAID")
        self.assertNotContains(resp, "INV-DRAFT")
        self.assertNotContains(resp, "INV-SENT")
        resp = self.client.get(
            reverse("invoicing:invoice_report"),
            {"status": ["PAID", "DRAFT"]},
        )
        self.assertContains(resp, "INV-PAID")
        self.assertContains(resp, "INV-DRAFT")
        self.assertNotContains(resp, "INV-SENT")


class InvoiceCreateViewTest(TestCase):
    """Verify Create New Invoice (7.5)."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Test Customer")

    def test_invoice_create_renders(self):
        """Create invoice form loads."""
        resp = self.client.get(reverse("invoicing:invoice_create"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "New Invoice")
        self.assertContains(resp, "Save Invoice")

    def test_invoice_create_due_date_from_default_terms(self):
        """Create form initial due_date comes from company default net terms."""
        s = CompanySettings.get()
        s.default_net_terms = NetTerms.NET_30
        s.save()
        resp = self.client.get(reverse("invoicing:invoice_create"))
        self.assertEqual(resp.status_code, 200)
        from datetime import date, timedelta
        today = date.today()
        expected_due = today + timedelta(days=30)
        self.assertContains(resp, expected_due.isoformat())

    def test_invoice_create_with_customer_prefills_and_uses_customer_terms(self):
        """Create with ?customer=pk prefills customer info and due_date from customer net terms."""
        from datetime import date, timedelta
        cust = Customer.objects.create(name="Net10 Customer", net_terms=NetTerms.NET_10)
        resp = self.client.get(reverse("invoicing:invoice_create") + f"?customer={cust.pk}")
        self.assertEqual(resp.status_code, 200)
        today = date.today()
        expected_due = today + timedelta(days=10)
        self.assertContains(resp, expected_due.isoformat())
        self.assertContains(resp, "Net10 Customer")

    def test_invoice_create_post(self):
        """Creating a new invoice with items succeeds."""
        resp = self.client.post(reverse("invoicing:invoice_create"), {
            "customer_name": "Test Customer",
            "contact_name": "",
            "phone": "",
            "email": "",
            "address": "",
            "date": "2026-02-11",
            "due_date": "2026-03-11",
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
            "items-0-description": "Test item",
            "items-0-quantity": "2",
            "items-0-unit_price": "25.00",
            "items-0-discount_pct": "0",
            "items-0-DELETE": "",
        })
        inv = Invoice.objects.first()
        self.assertRedirects(resp, reverse("invoicing:invoice_detail", kwargs={"pk": inv.pk}))
        self.assertEqual(inv.customer_name, "Test Customer")
        self.assertEqual(inv.status, "DRAFT")
        self.assertEqual(inv.items.count(), 1)
        item = inv.items.first()
        self.assertEqual(item.description, "Test item")
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.unit_price, 25)


class InvoiceEditViewTest(TestCase):
    """Verify Invoice detail/edit (7.6)."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Test Customer")
        self.invoice = Invoice.objects.create(
            invoice_number="INV-EDIT-001",
            customer=self.customer,
            date="2026-02-11",
        )
        InvoiceItem.objects.create(
            invoice=self.invoice,
            description="Original item",
            quantity=1,
            unit_price=Decimal("50.00"),
        )

    def test_invoice_edit_renders(self):
        """Edit invoice form loads."""
        resp = self.client.get(reverse("invoicing:invoice_edit", kwargs={"pk": self.invoice.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Edit Invoice")
        self.assertContains(resp, "Original item")

    def test_invoice_edit_post(self):
        """Editing invoice updates and recalculates totals."""
        item_pk = self.invoice.items.first().pk
        resp = self.client.post(
            reverse("invoicing:invoice_edit", kwargs={"pk": self.invoice.pk}),
            {
                "customer_name": "Test Customer",
                "contact_name": "",
                "phone": "",
                "email": "",
                "address": "",
                "date": "2026-02-11",
                "due_date": "2026-03-11",
                "tax_rate": "10",
                "notes": "Updated notes",
                "private_notes": "",
                "status": "SENT",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "1",
                "items-MIN_NUM_FORMS": "1",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-id": str(item_pk),
                "items-0-part": "",
                "items-0-unit": "",
                "items-0-description": "Updated item",
                "items-0-quantity": "3",
                "items-0-unit_price": "25.00",
                "items-0-discount_pct": "0",
                "items-0-DELETE": "",
            },
        )
        self.assertRedirects(resp, reverse("invoicing:invoice_detail", kwargs={"pk": self.invoice.pk}))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "SENT")
        self.assertEqual(self.invoice.notes, "Updated notes")
        self.assertEqual(self.invoice.items.count(), 1)
        item = self.invoice.items.first()
        self.assertEqual(item.description, "Updated item")
        self.assertEqual(item.quantity, 3)
        self.assertEqual(item.unit_price, 25)
        self.assertEqual(self.invoice.subtotal, Decimal("75.00"))
        self.assertEqual(self.invoice.tax_amount, Decimal("7.50"))
        self.assertEqual(self.invoice.total, Decimal("82.50"))

    def test_invoice_detail_shows_invoice(self):
        """Invoice detail page displays invoice with items."""
        resp = self.client.get(reverse("invoicing:invoice_detail", kwargs={"pk": self.invoice.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "INV-EDIT-001")
        self.assertContains(resp, "Original item")
        self.assertContains(resp, "Edit")
        self.assertContains(resp, "Print Invoice")

    def test_invoice_print_renders(self):
        """Print invoice view produces printable output (8.4)."""
        # Company name is user-configured (blank by default); set it so it prints.
        settings_obj = CompanySettings.get()
        settings_obj.company_name = "Manchester Electric"
        settings_obj.save()
        resp = self.client.get(reverse("invoicing:invoice_print", kwargs={"pk": self.invoice.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "INV-EDIT-001")
        self.assertContains(resp, "Test Customer")
        self.assertContains(resp, "Original item")
        self.assertContains(resp, "Manchester Electric")

    def test_invoice_print_quick_print_param(self):
        """Print page with ?print=1 returns 200 and invoice content (auto-print trigger)."""
        url = reverse("invoicing:invoice_print", kwargs={"pk": self.invoice.pk}) + "?print=1"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "INV-EDIT-001")
        self.assertContains(resp, "window.print")

    def test_invoice_print_auto_changes_draft_to_sent(self):
        """Printing a Draft invoice auto-sets status to Sent."""
        self.invoice.status = Invoice.Status.DRAFT
        self.invoice.save()
        self.client.get(reverse("invoicing:invoice_print", kwargs={"pk": self.invoice.pk}))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.SENT)

    def test_invoice_print_shows_paid_stamp_when_paid(self):
        """Printed invoice with PAID status shows PAID stamp."""
        self.invoice.status = Invoice.Status.PAID
        self.invoice.save()
        resp = self.client.get(reverse("invoicing:invoice_print", kwargs={"pk": self.invoice.pk}))
        self.assertContains(resp, 'class="paid-stamp"')
        self.assertContains(resp, "PAID")

    def test_invoice_print_no_paid_stamp_when_not_paid(self):
        """Printed invoice with non-PAID status does not show PAID stamp div."""
        self.invoice.status = Invoice.Status.SENT
        self.invoice.save()
        resp = self.client.get(reverse("invoicing:invoice_print", kwargs={"pk": self.invoice.pk}))
        self.assertNotContains(resp, 'class="paid-stamp"')


class InvoiceListAutoOverdueTest(TestCase):
    """Verify past-due invoices auto-update to OVERDUE when loading list."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Test Customer")

    def test_list_auto_updates_overdue(self):
        """SENT invoice past due_date becomes OVERDUE when invoice list loads."""
        from datetime import date, timedelta
        inv = Invoice.objects.create(
            invoice_number="INV-OVERDUE",
            customer=self.customer,
            date=date.today() - timedelta(days=30),
            due_date=date.today() - timedelta(days=5),
            status=Invoice.Status.SENT,
        )
        self.client.get(reverse("invoicing:invoice_list"))
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.OVERDUE)

    def test_paid_invoice_not_updated_to_overdue(self):
        """PAID invoice past due_date stays PAID."""
        from datetime import date, timedelta
        inv = Invoice.objects.create(
            invoice_number="INV-PAID",
            customer=self.customer,
            date=date.today() - timedelta(days=30),
            due_date=date.today() - timedelta(days=5),
            status=Invoice.Status.PAID,
        )
        self.client.get(reverse("invoicing:invoice_list"))
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.PAID)


class InvoiceCancelTest(TestCase):
    """Verify invoice cancel action."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Test Customer")
        self.invoice = Invoice.objects.create(
            invoice_number="INV-CANCEL",
            customer=self.customer,
            date="2026-02-12",
            status=Invoice.Status.SENT,
        )

    def test_invoice_cancel_post_sets_cancelled(self):
        """POST to cancel sets status to CANCELLED."""
        resp = self.client.post(reverse("invoicing:invoice_cancel", kwargs={"pk": self.invoice.pk}))
        self.assertRedirects(resp, reverse("invoicing:invoice_list") + "?status=CANCELLED")
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.CANCELLED)

    def test_invoice_cancel_filter_shows_only_cancelled(self):
        """Status filter CANCELLED shows only cancelled invoices."""
        self.invoice.status = Invoice.Status.CANCELLED
        self.invoice.save()
        inv2 = Invoice.objects.create(
            invoice_number="INV-OTHER",
            customer=self.customer,
            date="2026-02-12",
            status=Invoice.Status.SENT,
        )
        resp = self.client.get(reverse("invoicing:invoice_list"), {"status": "CANCELLED"})
        self.assertContains(resp, "INV-CANCEL")
        self.assertNotContains(resp, "INV-OTHER")


class InvoiceListHighlightingTest(TestCase):
    """Verify overdue and due-soon highlighting on invoice list (8.6)."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Test Customer")

    def test_overdue_invoice_has_danger_class(self):
        """Overdue invoice row has table-danger class."""
        from datetime import date, timedelta
        inv = Invoice.objects.create(
            invoice_number="INV-OVER",
            customer=self.customer,
            date=date.today() - timedelta(days=10),
            due_date=date.today() - timedelta(days=1),
            status=Invoice.Status.SENT,
        )
        resp = self.client.get(reverse("invoicing:invoice_list"))
        self.assertContains(resp, "table-danger")

    def test_due_soon_invoice_has_warning_class(self):
        """Invoice due within 7 days has table-warning class."""
        from datetime import date, timedelta
        inv = Invoice.objects.create(
            invoice_number="INV-SOON",
            customer=self.customer,
            date=date.today(),
            due_date=date.today() + timedelta(days=3),
            status=Invoice.Status.SENT,
        )
        resp = self.client.get(reverse("invoicing:invoice_list"))
        self.assertContains(resp, "table-warning")

    def test_paid_invoice_no_highlight(self):
        """Paid invoice has no highlighting."""
        from datetime import date, timedelta
        inv = Invoice.objects.create(
            invoice_number="INV-PAID",
            customer=self.customer,
            date=date.today() - timedelta(days=10),
            due_date=date.today() - timedelta(days=1),
            status=Invoice.Status.PAID,
        )
        resp = self.client.get(reverse("invoicing:invoice_list"))
        self.assertNotContains(resp, "table-danger")


class AddToInvoiceUnitTest(TestCase):
    """Verify Add to Invoice from Unit (8.1)."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Test Customer")
        self.unit_type = UnitType.objects.first() or UnitType.objects.create(name="AC Motor")
        self.unit = Unit.objects.create(
            unit_number="UT-001",
            unit_type=self.unit_type,
            rebuilt_unit_price=Decimal("150.00"),
        )

    def test_add_to_invoice_choose_page_renders_for_unit(self):
        """Add to Invoice choose page loads for unit."""
        resp = self.client.get(reverse("invoicing:add_to_invoice") + "?unit=" + str(self.unit.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Add to Invoice")
        self.assertContains(resp, "Unit UT-001")
        self.assertContains(resp, "New Invoice")
        self.assertContains(resp, "Add to Existing Invoice")

    def test_add_to_invoice_create_new_unit_prefilled(self):
        """Create new invoice with unit pre-filled."""
        resp = self.client.get(reverse("invoicing:invoice_create") + "?unit=" + str(self.unit.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "UT-001")
        self.assertContains(resp, "150.00")

    def test_add_to_invoice_post_adds_to_existing(self):
        """Adding unit to existing invoice creates line item."""
        inv = Invoice.objects.create(
            invoice_number="INV-ADD",
            customer=self.customer,
            date="2026-02-11",
            status=Invoice.Status.DRAFT,
        )
        self.assertEqual(inv.items.count(), 0)
        resp = self.client.post(reverse("invoicing:add_to_invoice") + "?unit=" + str(self.unit.pk), {
            "invoice": str(inv.pk),
            "unit": str(self.unit.pk),
        })
        self.assertRedirects(resp, reverse("invoicing:invoice_edit", kwargs={"pk": inv.pk}))
        inv.refresh_from_db()
        self.assertEqual(inv.items.count(), 1)
        item = inv.items.first()
        self.assertEqual(item.unit, self.unit)
        self.assertIsNone(item.part)
        self.assertEqual(item.unit_price, Decimal("150.00"))


class AddToInvoicePartTest(TestCase):
    """Verify Add to Invoice from Part (8.2)."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Test Customer")
        self.part = Part.objects.create(
            part_number="P-001",
            part_name="Test Part",
            price=Decimal("25.50"),
            stock_quantity=10,
        )

    def test_add_to_invoice_choose_page_renders_for_part(self):
        """Add to Invoice choose page loads for part."""
        resp = self.client.get(reverse("invoicing:add_to_invoice") + "?part=" + str(self.part.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Add to Invoice")
        self.assertContains(resp, "Part P-001")
        self.assertContains(resp, "New Invoice")

    def test_add_to_invoice_create_new_part_prefilled(self):
        """Create new invoice with part pre-filled."""
        resp = self.client.get(reverse("invoicing:invoice_create") + "?part=" + str(self.part.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Test Part")
        self.assertContains(resp, "25.50")

    def test_add_to_invoice_post_adds_part_to_existing(self):
        """Adding part to existing invoice creates line item and decrements stock."""
        inv = Invoice.objects.create(
            invoice_number="INV-PART",
            customer=self.customer,
            date="2026-02-11",
            status=Invoice.Status.DRAFT,
        )
        self.assertEqual(inv.items.count(), 0)
        resp = self.client.post(reverse("invoicing:add_to_invoice") + "?part=" + str(self.part.pk), {
            "invoice": str(inv.pk),
            "part": str(self.part.pk),
        })
        self.assertRedirects(resp, reverse("invoicing:invoice_edit", kwargs={"pk": inv.pk}))
        inv.refresh_from_db()
        self.assertEqual(inv.items.count(), 1)
        item = inv.items.first()
        self.assertEqual(item.part, self.part)
        self.assertIsNone(item.unit)
        self.assertEqual(item.unit_price, Decimal("25.50"))
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_quantity, 9)

    def test_add_to_invoice_rejects_part_when_insufficient_stock(self):
        """Adding part with insufficient stock shows error and does not create item."""
        self.part.stock_quantity = 0
        self.part.save()
        inv = Invoice.objects.create(
            invoice_number="INV-NOSTOCK",
            customer=self.customer,
            date="2026-02-11",
            status=Invoice.Status.DRAFT,
        )
        resp = self.client.post(reverse("invoicing:add_to_invoice") + "?part=" + str(self.part.pk), {
            "invoice": str(inv.pk),
            "part": str(self.part.pk),
        })
        self.assertRedirects(resp, reverse("invoicing:add_to_invoice") + "?part=" + str(self.part.pk))
        inv.refresh_from_db()
        self.assertEqual(inv.items.count(), 0)