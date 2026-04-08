from django.db import models


# ---------------------------------------------------------------------------
# 11. Vendor
# ---------------------------------------------------------------------------
class Vendor(models.Model):
    """Supplier / vendor with full contact and address."""

    name = models.CharField(max_length=255)
    contact_name = models.CharField(max_length=150, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    fax = models.CharField(max_length=50, blank=True, default="")
    account_number = models.CharField("Account Number", max_length=100, blank=True, default="")

    # Main address
    address_line1 = models.CharField("Address Line 1", max_length=255, blank=True, default="")
    address_line2 = models.CharField("Address Line 2", max_length=255, blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    state = models.CharField("State / Province", max_length=100, blank=True, default="")
    zip_code = models.CharField("ZIP / Postal Code", max_length=20, blank=True, default="")

    # Remit / Accounts Receivable address
    remit_line1 = models.CharField("Address Line 1", max_length=255, blank=True, default="")
    remit_line2 = models.CharField("Address Line 2", max_length=255, blank=True, default="")
    remit_city = models.CharField("City", max_length=100, blank=True, default="")
    remit_state = models.CharField("State / Province", max_length=100, blank=True, default="")
    remit_zip = models.CharField("ZIP / Postal Code", max_length=20, blank=True, default="")

    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return self.name

    def get_primary_contact(self):
        return self.contacts.filter(is_primary=True).first() or self.contacts.first()


class VendorContact(models.Model):
    """Contact person for a vendor. First entry is primary."""

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="contacts")
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
        return f"{self.name} ({self.vendor.name})"
