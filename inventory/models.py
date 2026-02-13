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
    address_line1 = models.CharField("Address Line 1", max_length=255, blank=True, default="")
    address_line2 = models.CharField("Address Line 2", max_length=255, blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    state = models.CharField("State / Province", max_length=100, blank=True, default="")
    zip_code = models.CharField("ZIP / Postal Code", max_length=20, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
