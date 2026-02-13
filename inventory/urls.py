from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.inventory_list, name="inventory_list"),
    path("create/", views.inventory_item_create, name="inventory_item_create"),
    path("reorder/", views.reorder_list, name="reorder_list"),
    path("vendors/", views.vendor_list, name="vendor_list"),
    path("vendors/add/", views.vendor_create, name="vendor_create"),
    path("vendors/<int:pk>/edit/", views.vendor_edit, name="vendor_edit"),
    path("vendors/<int:pk>/delete/", views.vendor_delete, name="vendor_delete"),
]
