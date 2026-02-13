from django.urls import path

from . import views

app_name = "invoicing"

urlpatterns = [
    path("", views.invoice_list, name="invoice_list"),
    path("report/", views.invoice_report, name="invoice_report"),
    path("settings/", views.settings_view, name="settings"),
    path("add-item/", views.add_to_invoice, name="add_to_invoice"),
    path("invoice/new/", views.invoice_create, name="invoice_create"),
    path("invoice/<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("invoice/<int:pk>/print/", views.invoice_print, name="invoice_print"),
    path("invoice/<int:pk>/edit/", views.invoice_edit, name="invoice_edit"),
    path("invoice/<int:pk>/cancel/", views.invoice_cancel, name="invoice_cancel"),
    path("customers/", views.customer_list, name="customer_list"),
    path("customers/add/", views.customer_create, name="customer_create"),
    path("customers/<int:pk>/edit/", views.customer_edit, name="customer_edit"),
    path("customers/<int:pk>/delete/", views.customer_delete, name="customer_delete"),
]
