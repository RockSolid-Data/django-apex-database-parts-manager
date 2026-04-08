from django.contrib import admin

from .models import Vendor, VendorContact


class VendorContactInline(admin.TabularInline):
    model = VendorContact
    extra = 1


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ["name", "contact_name", "fax", "account_number", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "contact_name", "fax", "account_number"]
    inlines = [VendorContactInline]
