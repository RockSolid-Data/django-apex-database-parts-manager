from django.contrib import admin

from .models import Vendor


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ["name", "contact_name", "email", "phone", "city", "state", "is_active"]
    list_filter = ["is_active", "state"]
    search_fields = ["name", "contact_name", "email"]
