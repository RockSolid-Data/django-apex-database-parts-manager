from django.contrib import admin

from .models import Customer, Invoice, InvoiceItem


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 1


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "phone", "city", "state", "is_active"]
    list_filter = ["is_active", "state"]
    search_fields = ["name", "email"]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ["invoice_number", "customer", "date", "due_date", "status", "total"]
    list_filter = ["status"]
    search_fields = ["invoice_number", "customer__name"]
    inlines = [InvoiceItemInline]


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = ["invoice", "description", "quantity", "unit_price", "line_total"]
    search_fields = ["invoice__invoice_number", "description"]
