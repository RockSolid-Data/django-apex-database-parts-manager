from django.contrib import admin

from .models import Customer, CustomerContact, Invoice, InvoiceItem


class CustomerContactInline(admin.TabularInline):
    model = CustomerContact
    extra = 1


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 1


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["name", "contact_name", "phone", "email", "fax", "is_active"]
    list_filter = ["is_active", "is_tax_exempt"]
    search_fields = ["name", "contact_name", "email", "fax"]
    inlines = [CustomerContactInline]


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
