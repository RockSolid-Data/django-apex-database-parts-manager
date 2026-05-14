import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render

from catalog.models import Part

from .forms import InventoryItemForm, VendorForm, VendorContactFormSet
from .models import Vendor, VendorContact

logger = logging.getLogger(__name__)


def inventory_item_create(request):
    """Add Inventory Item: creates or updates Part with cost, price, stock."""
    if request.method == "POST":
        form = InventoryItemForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            cost = data["cost"]
            margin_pct = data["margin_pct"]
            if margin_pct >= 100:
                margin_pct = 99  # cap at 99% to avoid division by zero
            sale_price = cost / (1 - margin_pct / 100)
            supplier_name = data["supplier"].name

            part, created = Part.objects.update_or_create(
                part_number=data["part_number"].strip(),
                defaults={
                    "part_name": data["item_name"].strip(),
                    "description": data["description"].strip() or "",
                    "primary_vendor": supplier_name,
                    "cost_price": cost,
                    "price": round(sale_price, 2),
                    "stock_quantity": data["quantity_available"],
                    "foot_notes": data["notes"].strip() or "",
                    "is_active": True,
                },
            )
            action = "Created" if created else "Updated"
            logger.info("[Inventory] %s item %s", action, part.part_number)
            messages.success(request, f"Inventory item '{part.part_number}' {'created' if created else 'updated'}.")
            return redirect("inventory:inventory_list")
    else:
        form = InventoryItemForm()

    return render(request, "inventory/inventory_item_form.html", {"form": form})


def inventory_list(request):
    """Inventory management list: parts with cost, margin, sale price, quantity, total value."""
    parts = Part.objects.select_related("unit").filter(is_active=True, track_inventory=True).order_by("part_number")

    # --- Text search (name, part number, description) ---
    q = request.GET.get("q", "").strip()
    if q:
        parts = parts.filter(
            Q(part_name__icontains=q)
            | Q(part_number__icontains=q)
            | Q(yt_number__icontains=q)
            | Q(description__icontains=q)
        )

    # --- Supplier filter ---
    filter_supplier = request.GET.get("supplier", "").strip()
    if filter_supplier:
        parts = parts.filter(primary_vendor=filter_supplier)

    supplier_choices = (
        Part.objects.filter(is_active=True, track_inventory=True)
        .exclude(primary_vendor="")
        .values_list("primary_vendor", flat=True)
        .distinct()
        .order_by("primary_vendor")
    )

    total_count = parts.count()
    try:
        per_page = min(int(request.GET.get("per_page", 50)), 100)
    except (ValueError, TypeError):
        per_page = 50
    paginator = Paginator(parts, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "parts": page_obj,
        "page_obj": page_obj,
        "total_count": total_count,
        "per_page": per_page,
        "q": q,
        "filter_supplier": filter_supplier,
        "supplier_choices": supplier_choices,
    }
    if request.GET.get("print") == "1":
        return render(request, "inventory/inventory_list_print.html", context)
    return render(request, "inventory/inventory_list.html", context)


def reorder_list(request):
    """List parts where stock is at or below reorder level. Search, filters, sort."""
    # Only show parts the user has opted into reorder tracking (reorder_qty > 0)
    parts = (
        Part.objects.select_related("unit")
        .filter(is_active=True, track_inventory=True, reorder_qty__gt=0)
        .filter(stock_quantity__lte=F("reorder_qty"))
    )

    # --- Text search (key, J&N, OEM #, description) ---
    q = request.GET.get("q", "").strip()
    if q:
        parts = parts.filter(
            Q(manufacturer_number__icontains=q)
            | Q(j_and_n__icontains=q)
            | Q(oem_number__icontains=q)
            | Q(description__icontains=q)
            | Q(part_name__icontains=q)
        )

    # --- Filters ---
    filter_category = request.GET.get("category", "").strip()
    if filter_category:
        parts = parts.filter(category=filter_category)

    filter_supplier = request.GET.get("supplier", "").strip()
    if filter_supplier:
        parts = parts.filter(primary_vendor=filter_supplier)

    # --- Sort: Most Urgent First (lowest stock first) ---
    sort = request.GET.get("sort", "urgent")
    if sort == "urgent":
        parts = parts.order_by("stock_quantity", "part_number")
    elif sort == "part":
        parts = parts.order_by("part_number")
    elif sort == "supplier":
        parts = parts.order_by("primary_vendor", "stock_quantity")

    # --- Build filter choices from reorder parts (before slicing) ---
    base_reorder = Part.objects.filter(is_active=True, track_inventory=True, reorder_qty__gt=0).filter(
        stock_quantity__lte=F("reorder_qty")
    )
    category_choices = (
        base_reorder.exclude(category="")
        .values_list("category", flat=True)
        .distinct()
        .order_by("category")
    )
    supplier_choices = (
        base_reorder.exclude(primary_vendor="")
        .values_list("primary_vendor", flat=True)
        .distinct()
        .order_by("primary_vendor")
    )

    total_count = parts.count()
    try:
        per_page = min(int(request.GET.get("per_page", 50)), 100)
    except (ValueError, TypeError):
        per_page = 50
    paginator = Paginator(parts, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "parts": page_obj,
        "page_obj": page_obj,
        "total_count": total_count,
        "per_page": per_page,
        "q": q,
        "filter_category": filter_category,
        "filter_supplier": filter_supplier,
        "sort": sort,
        "category_choices": category_choices,
        "supplier_choices": supplier_choices,
    }
    return render(request, "inventory/reorder_list.html", context)


def vendor_list(request):
    """List vendors with search and filters."""
    vendors = Vendor.objects.order_by("name")

    q = request.GET.get("q", "").strip()
    if q:
        vendors = vendors.filter(
            Q(name__icontains=q)
            | Q(contact_name__icontains=q)
            | Q(fax__icontains=q)
            | Q(account_number__icontains=q)
            | Q(contacts__name__icontains=q)
            | Q(contacts__email__icontains=q)
            | Q(contacts__phone__icontains=q)
            | Q(notes__icontains=q)
        ).distinct()

    show_inactive = request.GET.get("inactive", "").lower() == "1"
    if not show_inactive:
        vendors = vendors.filter(is_active=True)

    total_count = vendors.count()
    try:
        per_page = min(int(request.GET.get("per_page", 50)), 100)
    except (ValueError, TypeError):
        per_page = 50
    paginator = Paginator(vendors, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "vendors": page_obj,
        "page_obj": page_obj,
        "total_count": total_count,
        "per_page": per_page,
        "q": q,
        "show_inactive": show_inactive,
    }
    if request.GET.get("print") == "1":
        return render(request, "inventory/vendor_list_print.html", context)
    return render(request, "inventory/vendor_list.html", context)


def vendor_create(request):
    """Create a new vendor."""
    if request.method == "POST":
        form = VendorForm(request.POST)
        contact_formset = VendorContactFormSet(request.POST, prefix="contacts")
        if form.is_valid() and contact_formset.is_valid():
            vendor = form.save()
            contact_formset.instance = vendor
            contacts = contact_formset.save()
            if contacts and not any(c.is_primary for c in contacts):
                first = contacts[0]
                first.is_primary = True
                first.save(update_fields=["is_primary"])
            logger.info("[Vendor] Created '%s' (pk=%s)", vendor.name, vendor.pk)
            messages.success(request, f"Supplier '{vendor.name}' created.")
            return redirect("inventory:vendor_list")
    else:
        form = VendorForm()
        contact_formset = VendorContactFormSet(prefix="contacts")

    return render(request, "inventory/vendor_form.html", {
        "form": form,
        "contact_formset": contact_formset,
        "vendor": None,
        "title": "Add New Supplier",
    })


def vendor_edit(request, pk):
    """Edit a vendor."""
    vendor = get_object_or_404(Vendor, pk=pk)
    if request.method == "POST":
        form = VendorForm(request.POST, instance=vendor)
        contact_formset = VendorContactFormSet(request.POST, prefix="contacts", instance=vendor)
        if form.is_valid() and contact_formset.is_valid():
            form.save()
            contact_formset.save()
            remaining = vendor.contacts.all()
            if remaining.exists() and not remaining.filter(is_primary=True).exists():
                first = remaining.first()
                first.is_primary = True
                first.save(update_fields=["is_primary"])
            logger.info("[Vendor] Updated '%s' (pk=%s)", vendor.name, vendor.pk)
            messages.success(request, f"Supplier '{vendor.name}' updated.")
            return redirect("inventory:vendor_list")
    else:
        form = VendorForm(instance=vendor)
        contact_formset = VendorContactFormSet(prefix="contacts", instance=vendor)

    return render(request, "inventory/vendor_form.html", {
        "form": form,
        "contact_formset": contact_formset,
        "vendor": vendor,
        "title": "Edit Supplier",
    })


def vendor_delete(request, pk):
    """Delete a vendor."""
    vendor = get_object_or_404(Vendor, pk=pk)
    if request.method == "POST":
        name = vendor.name
        vendor.delete()
        logger.info("[Vendor] Deleted '%s' (pk=%s)", name, pk)
        messages.success(request, f"Supplier '{name}' deleted.")
        return redirect("inventory:vendor_list")
    return redirect("inventory:vendor_edit", pk=pk)
