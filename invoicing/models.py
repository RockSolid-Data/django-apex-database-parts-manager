from datetime import date, timedelta
from decimal import Decimal

from django.db import models


# ---------------------------------------------------------------------------
# Net Terms (used by CompanySettings and Customer)
# ---------------------------------------------------------------------------
class NetTerms:
    """Payment term choices: Net 10, Net 30, Due on Receipt, Custom."""

    NET_10 = "NET_10"
    NET_30 = "NET_30"
    DUE_ON_RECEIPT = "DUE_ON_RECEIPT"
    CUSTOM = "CUSTOM"

    CHOICES = [
        (NET_10, "Net 10"),
        (NET_30, "Net 30"),
        (DUE_ON_RECEIPT, "Net due on receipt"),
        (CUSTOM, "Custom"),
    ]

    @classmethod
    def days_for(cls, value, custom_days=0):
        """Return number of days for a term value."""
        if value == cls.NET_10:
            return 10
        if value == cls.NET_30:
            return 30
        if value == cls.DUE_ON_RECEIPT:
            return 0
        if value == cls.CUSTOM:
            return max(0, int(custom_days or 0))
        return 0


# ---------------------------------------------------------------------------
# 11. CompanySettings (singleton)
# ---------------------------------------------------------------------------
class CompanySettings(models.Model):
    """Company info, logo, and default payment terms. One row expected."""

    company_name = models.CharField(max_length=255, default="")
    tagline = models.CharField(max_length=255, blank=True, default="")
    logo = models.ImageField(upload_to="company", blank=True, null=True)
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    address = models.TextField(blank=True, default="")
    default_net_terms = models.CharField(
        max_length=20,
        choices=NetTerms.CHOICES,
        default=NetTerms.NET_30,
    )
    default_net_days = models.PositiveIntegerField(
        default=30,
        help_text="Days when default_net_terms is Custom",
    )
    default_tax_rate = models.DecimalField(
        "Default Tax Rate (%)",
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Used when creating new invoices. Customers can override on their profile.",
    )

    PRICING_MARKUP = "markup"
    PRICING_MARGIN = "margin"
    PRICING_METHOD_CHOICES = [
        (PRICING_MARKUP, "Markup  (Sell = Cost ÷ Factor)"),
        (PRICING_MARGIN, "Margin  (Sell = Cost × (1 + %))"),
    ]
    pricing_method = models.CharField(
        "Resell Calculation Method",
        max_length=10,
        choices=PRICING_METHOD_CHOICES,
        default=PRICING_MARKUP,
    )

    # Invoice numbering
    invoice_number_prefix = models.CharField(max_length=20, default="INV-", blank=True)
    invoice_number_include_year = models.BooleanField(default=True)
    invoice_number_include_month = models.BooleanField(
        default=False,
        help_text="Include month in number (e.g. INV-2602-0001). Only applies when year is included.",
    )
    invoice_number_padding = models.PositiveIntegerField(default=4)

    # Invoice format
    PAPER_LETTER = "letter"
    PAPER_A4 = "a4"
    invoice_paper_size = models.CharField(
        max_length=10,
        choices=[(PAPER_LETTER, "Letter"), (PAPER_A4, "A4")],
        default=PAPER_LETTER,
    )
    LAYOUT_STANDARD = "standard"
    LAYOUT_COMPACT = "compact"
    invoice_layout_style = models.CharField(
        max_length=20,
        choices=[(LAYOUT_STANDARD, "Standard"), (LAYOUT_COMPACT, "Compact")],
        default=LAYOUT_STANDARD,
    )
    DATE_FMT_FULL = "F j, Y"
    DATE_FMT_US = "m/d/Y"
    DATE_FMT_EU = "d/m/Y"
    invoice_date_format = models.CharField(
        max_length=20,
        choices=[
            (DATE_FMT_FULL, "Month DD, YYYY"),
            (DATE_FMT_US, "MM/DD/YYYY"),
            (DATE_FMT_EU, "DD/MM/YYYY"),
        ],
        default=DATE_FMT_FULL,
    )
    invoice_currency_symbol = models.CharField(max_length=10, default="$")
    invoice_footer_message = models.TextField(
        "Default Footer Message",
        blank=True,
        default="",
        help_text="Appears at the bottom of every invoice (e.g. thank-you note, payment instructions).",
    )

    class Meta:
        verbose_name = "Company Settings"
        verbose_name_plural = "Company Settings"

    def __str__(self):
        return self.company_name

    def get_due_date(self, invoice_date):
        """Compute due date from invoice_date using default terms."""
        days = NetTerms.days_for(self.default_net_terms, self.default_net_days)
        return invoice_date + timedelta(days=days)

    def get_next_invoice_number(self, as_of_date=None):
        """Generate next invoice number using prefix, year, month, padding settings.

        Format examples (prefix="INV-", padding=4):
          No year/month:  INV-0001
          Year only:      INV-26-0001
          Year + month:   INV-2605-0001
          No prefix:      26-0001 or 2605-0001 or 0001
        """
        if as_of_date is None:
            as_of_date = date.today()
        prefix = self.invoice_number_prefix or ""
        padding = max(1, min(10, self.invoice_number_padding or 4))
        if self.invoice_number_include_year:
            yy = as_of_date.strftime("%y")
            if self.invoice_number_include_month:
                search_prefix = f"{prefix}{yy}{as_of_date.month:02d}-"
            else:
                search_prefix = f"{prefix}{yy}-"
            last = (
                Invoice.objects.filter(invoice_number__startswith=search_prefix)
                .order_by("-invoice_number")
                .values_list("invoice_number", flat=True)
                .first()
            )
            if last:
                try:
                    seq = int(last.split("-")[-1]) + 1
                except (IndexError, ValueError):
                    seq = 1
            else:
                seq = 1
            return f"{search_prefix}{seq:0{padding}d}"
        else:
            last = (
                Invoice.objects.filter(invoice_number__startswith=prefix)
                .order_by("-invoice_number")
                .values_list("invoice_number", flat=True)
                .first()
            )
            if last:
                try:
                    suffix = last[len(prefix):]
                    seq = int(suffix) + 1
                except (ValueError, IndexError):
                    seq = 1
            else:
                seq = 1
            return f"{prefix}{seq:0{padding}d}"

    @classmethod
    def get(cls):
        """Get or create singleton settings."""
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create(
                company_name="",
                tagline="",
                default_net_terms=NetTerms.NET_30,
                default_net_days=30,
                default_tax_rate=0,
            )
        return obj


# ---------------------------------------------------------------------------
# 12. Customer
# ---------------------------------------------------------------------------
class Customer(models.Model):
    """Customer / company for invoicing."""

    name = models.CharField(max_length=255)
    contact_name = models.CharField("Contact Name", max_length=150, blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    fax = models.CharField(max_length=50, blank=True, default="")

    # Bill-to address
    bill_to_line1 = models.CharField("Address Line 1", max_length=255, blank=True, default="")
    bill_to_line2 = models.CharField("Address Line 2", max_length=255, blank=True, default="")
    bill_to_city = models.CharField("City", max_length=100, blank=True, default="")
    bill_to_state = models.CharField("State / Province", max_length=100, blank=True, default="")
    bill_to_zip = models.CharField("ZIP / Postal Code", max_length=20, blank=True, default="")

    # Ship-to address
    ship_to_line1 = models.CharField("Address Line 1", max_length=255, blank=True, default="")
    ship_to_line2 = models.CharField("Address Line 2", max_length=255, blank=True, default="")
    ship_to_city = models.CharField("City", max_length=100, blank=True, default="")
    ship_to_state = models.CharField("State / Province", max_length=100, blank=True, default="")
    ship_to_zip = models.CharField("ZIP / Postal Code", max_length=20, blank=True, default="")

    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    net_terms = models.CharField(
        max_length=20,
        choices=NetTerms.CHOICES,
        blank=True,
        null=True,
        help_text="Override default payment terms. Leave blank to use company default.",
    )
    net_days = models.PositiveIntegerField(
        default=0,
        blank=True,
        help_text="Custom days when net_terms is Custom",
    )
    tax_rate = models.DecimalField(
        "Tax Rate (%)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Override default tax rate for this customer. Leave blank to use company default.",
    )
    is_tax_exempt = models.BooleanField("Tax Exempt", default=False)
    has_st105 = models.BooleanField("ST105 on file", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_primary_contact(self):
        return self.contacts.filter(is_primary=True).first() or self.contacts.first()

    def get_effective_net_days(self):
        """Days before payment due. Uses customer override or company default."""
        if self.net_terms:
            return NetTerms.days_for(self.net_terms, self.net_days)
        settings = CompanySettings.get()
        return NetTerms.days_for(settings.default_net_terms, settings.default_net_days)

    def get_due_date(self, invoice_date):
        """Compute due date from invoice_date using this customer's terms."""
        days = self.get_effective_net_days()
        return invoice_date + timedelta(days=days)

    def get_effective_tax_rate(self):
        """Tax rate for invoices. Uses customer override or company default."""
        if self.is_tax_exempt:
            return Decimal("0")
        if self.tax_rate is not None:
            return self.tax_rate
        settings = CompanySettings.get()
        return settings.default_tax_rate


class CustomerContact(models.Model):
    """Contact person for a customer. First entry is primary."""

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=50, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    fax = models.CharField(max_length=50, blank=True, default="")
    department = models.CharField(max_length=100, blank=True, default="")
    is_primary = models.BooleanField(default=False)
    ordering = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-is_primary", "ordering", "pk"]

    def __str__(self):
        return f"{self.name} ({self.customer.name})"


# ---------------------------------------------------------------------------
# 13. Invoice
# ---------------------------------------------------------------------------
class Invoice(models.Model):
    """Invoice header with totals and status tracking."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENT = "SENT", "Sent"
        PAID = "PAID", "Paid"
        OVERDUE = "OVERDUE", "Overdue"
        CANCELLED = "CANCELLED", "Cancelled"

    invoice_number = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="invoices",
        null=True, blank=True,
    )
    customer_name = models.CharField("Customer Name", max_length=255, blank=True, default="")
    contact_name = models.CharField("Contact Name", max_length=255, blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    address = models.TextField("Address", blank=True, default="")
    date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_rate = models.DecimalField(
        "Tax Rate (%)", max_digits=5, decimal_places=2, default=0
    )
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField("Invoice Notes (for customer)", blank=True, default="")
    private_notes = models.TextField("Private Notes (internal)", blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["invoice_number"]),
            models.Index(fields=["status"]),
            models.Index(fields=["date"]),
        ]

    def __str__(self):
        return f"Invoice {self.invoice_number}"

    def recalculate_totals(self):
        """Recalc subtotal from items, tax_amount, total."""
        from django.db.models import Sum

        subtotal = self.items.aggregate(s=Sum("line_total"))["s"] or Decimal("0")
        self.subtotal = subtotal
        self.tax_amount = round(subtotal * (self.tax_rate / 100), 2)
        self.total = round(subtotal + self.tax_amount, 2)
        self.save(update_fields=["subtotal", "tax_amount", "total", "updated_at"])

    def get_terms_display(self):
        """Payment terms label (e.g. Net 30) from customer or company default."""
        if self.customer and self.customer.net_terms:
            return self.customer.get_net_terms_display()
        settings = CompanySettings.get()
        return dict(NetTerms.CHOICES).get(settings.default_net_terms, "—")

    def get_bill_to_name(self):
        """Customer/company name for display."""
        return self.customer_name or (self.customer.name if self.customer else "")

    def get_bill_to_address(self):
        """Address lines for Bill To section."""
        if self.address:
            return self.address.strip()
        if self.customer:
            parts = [self.customer.bill_to_line1, self.customer.bill_to_line2]
            if self.customer.bill_to_city or self.customer.bill_to_state or self.customer.bill_to_zip:
                parts.append(
                    f"{self.customer.bill_to_city or ''}, "
                    f"{self.customer.bill_to_state or ''} "
                    f"{self.customer.bill_to_zip or ''}".strip().strip(",")
                )
            return "\n".join(p for p in parts if p)
        return ""

    def get_bill_to_contact(self):
        """Phone and email for Bill To."""
        parts = []
        if self.phone:
            parts.append(f"Phone: {self.phone}")
        if self.email:
            parts.append(f"Email: {self.email}")
        if self.customer and not self.phone and self.customer.phone:
            parts.append(f"Phone: {self.customer.phone}")
        if self.customer and not self.email and self.customer.email:
            parts.append(f"Email: {self.customer.email}")
        return "\n".join(parts)

    def get_bill_to_display(self):
        """Full Bill To block for display/print."""
        lines = []
        name = self.get_bill_to_name()
        if name:
            lines.append(name)
        if self.contact_name:
            lines.append(self.contact_name)
        addr = self.get_bill_to_address()
        if addr:
            lines.append(addr)
        contact = self.get_bill_to_contact()
        if contact:
            lines.append(contact)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 14. InvoiceItem
# ---------------------------------------------------------------------------
class InvoiceItem(models.Model):
    """One line item on an invoice."""

    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="items"
    )
    part = models.ForeignKey(
        "catalog.Part",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_items",
    )
    unit = models.ForeignKey(
        "catalog.Unit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_items",
    )
    description = models.CharField(max_length=500, blank=True, default="")
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_pct = models.DecimalField(
        "Discount %", max_digits=5, decimal_places=2, default=0,
    )
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Invoice Item"
        verbose_name_plural = "Invoice Items"

    def __str__(self):
        return f"{self.invoice.invoice_number} — {self.description[:50]}"

    def save(self, *args, **kwargs):
        """Auto-calculate line_total = quantity × unit_price × (1 - discount/100)."""
        gross = Decimal(str(self.quantity)) * Decimal(str(self.unit_price))
        discount = Decimal(str(self.discount_pct or 0))
        self.line_total = round(gross * (1 - discount / 100), 2)
        super().save(*args, **kwargs)
