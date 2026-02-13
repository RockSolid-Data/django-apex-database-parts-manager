import csv
import io

from django.contrib import messages
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ApplicationForm, ApplicationSpecificationForm, ApplicationUnitLinkForm, BOMForm, BOMItemForm, CrossReferenceForm, GearReductionForm, PartForm, SubstituteForm, UnitForm
from .models import Application, ApplicationSpecification, ApplicationUnit, BOM, BOMItem, CrossReference, GearReductionSubstitution, Part, Substitute, Unit, UnitType


def home(request):
    """Landing page for Manchester Electric."""
    return render(request, "catalog/home.html")


def application_list(request):
    """List applications with search, filters (Make, Year, Mfr, Volt, Unit), MAKE, ENGINE, YEAR, etc."""
    applications = Application.objects.prefetch_related("units").filter(is_active=True).order_by("name")

    # --- Text search ---
    q = request.GET.get("q", "").strip()
    if q:
        applications = applications.filter(
            Q(name__icontains=q)
            | Q(make__icontains=q)
            | Q(engine__icontains=q)
            | Q(year__icontains=q)
            | Q(mfr__icontains=q)
            | Q(volt__icontains=q)
            | Q(amp__icontains=q)
            | Q(part_number__icontains=q)
            | Q(unit_number__icontains=q)
            | Q(options__icontains=q)
            | Q(notes__icontains=q)
        )

    # --- Dropdown filters ---
    filter_make = request.GET.get("make", "").strip()
    filter_year = request.GET.get("year", "").strip()
    filter_mfr = request.GET.get("mfr", "").strip()
    filter_volt = request.GET.get("volt", "").strip()
    filter_unit = request.GET.get("unit", "").strip()

    if filter_make:
        applications = applications.filter(make=filter_make)
    if filter_year:
        applications = applications.filter(year=filter_year)
    if filter_mfr:
        applications = applications.filter(mfr=filter_mfr)
    if filter_volt:
        applications = applications.filter(volt=filter_volt)
    if filter_unit:
        applications = applications.filter(units__pk=filter_unit).distinct()

    # --- Build distinct value lists for dropdowns ---
    active_apps = Application.objects.filter(is_active=True)
    make_choices = (
        active_apps.exclude(make="")
        .values_list("make", flat=True)
        .distinct()
        .order_by("make")
    )
    year_choices = (
        active_apps.exclude(year="")
        .values_list("year", flat=True)
        .distinct()
        .order_by("year")
    )
    mfr_choices = (
        active_apps.exclude(mfr="")
        .values_list("mfr", flat=True)
        .distinct()
        .order_by("mfr")
    )
    volt_choices = (
        active_apps.exclude(volt="")
        .values_list("volt", flat=True)
        .distinct()
        .order_by("volt")
    )
    unit_choices = Unit.objects.filter(is_active=True).order_by("unit_number")

    context = {
        "applications": applications,
        "q": q,
        "filter_make": filter_make,
        "filter_year": filter_year,
        "filter_mfr": filter_mfr,
        "filter_volt": filter_volt,
        "filter_unit": filter_unit,
        "make_choices": make_choices,
        "year_choices": year_choices,
        "mfr_choices": mfr_choices,
        "volt_choices": volt_choices,
        "unit_choices": unit_choices,
    }
    return render(request, "catalog/application_list.html", context)


def application_detail(request, pk):
    """Show details for a single application with General Specifications and Linked Units panel."""
    app = get_object_or_404(Application, pk=pk)
    # application_units for Linked Units panel (includes position, notes)
    linked_units = (
        ApplicationUnit.objects.filter(application=app)
        .select_related("unit", "unit__unit_type")
        .order_by("unit__unit_number")
    )
    specifications = ApplicationSpecification.objects.filter(application=app).order_by("category", "type")
    return render(request, "catalog/application_detail.html", {
        "application": app,
        "linked_units": linked_units,
        "specifications": specifications,
    })


def application_link_unit(request, pk):
    """Link a unit to an application (creating ApplicationUnit)."""
    app = get_object_or_404(Application, pk=pk)

    if request.method == "POST":
        form = ApplicationUnitLinkForm(request.POST, application=app)
        if form.is_valid():
            au = form.save(commit=False)
            au.application = app
            au.save()
            messages.success(request, f"Unit {au.unit.unit_number} linked to application.")
            return redirect("catalog:application_detail", pk=app.pk)
    else:
        form = ApplicationUnitLinkForm(application=app)

    return render(request, "catalog/application_link_unit.html", {
        "form": form,
        "application": app,
    })


def application_unlink_unit(request, pk, unit_pk):
    """Remove a unit from an application (delete ApplicationUnit)."""
    app = get_object_or_404(Application, pk=pk)
    au = get_object_or_404(ApplicationUnit, application=app, unit_id=unit_pk)

    if request.method == "POST":
        unit_number = au.unit.unit_number
        au.delete()
        messages.success(request, f"Unit {unit_number} unlinked from application.")
    return redirect("catalog:application_detail", pk=app.pk)


def application_spec_add(request, pk):
    """Add an application specification (8.7)."""
    app = get_object_or_404(Application, pk=pk)
    if request.method == "POST":
        form = ApplicationSpecificationForm(request.POST)
        if form.is_valid():
            spec = form.save(commit=False)
            spec.application = app
            spec.save()
            messages.success(request, "Specification added.")
            return redirect("catalog:application_detail", pk=app.pk)
    else:
        form = ApplicationSpecificationForm()
    return render(request, "catalog/application_spec_form.html", {
        "form": form,
        "application": app,
        "spec": None,
        "title": "Add Specification",
    })


def application_spec_edit(request, pk, spec_pk):
    """Edit an application specification."""
    app = get_object_or_404(Application, pk=pk)
    spec = get_object_or_404(ApplicationSpecification, application=app, pk=spec_pk)
    if request.method == "POST":
        form = ApplicationSpecificationForm(request.POST, instance=spec)
        if form.is_valid():
            form.save()
            messages.success(request, "Specification updated.")
            return redirect("catalog:application_detail", pk=app.pk)
    else:
        form = ApplicationSpecificationForm(instance=spec)
    return render(request, "catalog/application_spec_form.html", {
        "form": form,
        "application": app,
        "spec": spec,
        "title": "Edit Specification",
    })


def application_spec_delete(request, pk, spec_pk):
    """Delete an application specification."""
    app = get_object_or_404(Application, pk=pk)
    spec = get_object_or_404(ApplicationSpecification, application=app, pk=spec_pk)
    if request.method == "POST":
        spec.delete()
        messages.success(request, "Specification removed.")
    return redirect("catalog:application_detail", pk=app.pk)


def application_create(request):
    """Create a new application."""
    if request.method == "POST":
        form = ApplicationForm(request.POST)
        if form.is_valid():
            app = form.save()
            messages.success(request, f"Application '{app.name}' created.")
            return redirect("catalog:application_detail", pk=app.pk)
    else:
        form = ApplicationForm()

    return render(request, "catalog/application_form.html", {
        "form": form,
        "application": None,
        "title": "Add New Application",
    })


def application_edit(request, pk):
    """Edit an application."""
    app = get_object_or_404(Application, pk=pk)
    if request.method == "POST":
        form = ApplicationForm(request.POST, instance=app)
        if form.is_valid():
            form.save()
            messages.success(request, f"Application '{app.name}' updated.")
            return redirect("catalog:application_detail", pk=app.pk)
    else:
        form = ApplicationForm(instance=app)
    return render(request, "catalog/application_form.html", {
        "form": form,
        "application": app,
        "title": "Edit Application",
    })


def application_delete(request, pk):
    """Delete an application."""
    app = get_object_or_404(Application, pk=pk)
    if request.method == "POST":
        name = app.name
        app.delete()
        messages.success(request, f"Application '{name}' deleted.")
        return redirect("catalog:application_list")
    return redirect("catalog:application_edit", pk=pk)


def bom_list(request):
    """List BOMs with actions to open, create, edit, delete."""
    boms = BOM.objects.select_related("unit", "application").order_by("name")
    if request.GET.get("print") == "1":
        return render(request, "catalog/bom_list_print.html", {"boms": boms})
    return render(request, "catalog/bom_list.html", {"boms": boms})


def bom_detail(request, pk):
    """Show BOM name, created date, description. Buttons: Print All, Print Selected, Add Part, Edit, Back, Edit BOM, Delete BOM."""
    bom = get_object_or_404(
        BOM.objects.select_related("unit", "application").prefetch_related("items__part"),
        pk=pk,
    )
    return render(request, "catalog/bom_detail.html", {"bom": bom})


def bom_print(request, pk):
    """Print-friendly BOM view (8.5). ?all=1 prints all, ?items=1,2,3 prints selected."""
    bom = get_object_or_404(
        BOM.objects.select_related("unit", "application").prefetch_related("items__part"),
        pk=pk,
    )
    items = list(bom.items.all())
    if request.GET.get("all"):
        print_items = items
    else:
        item_ids = request.GET.get("items", "")
        if item_ids:
            ids = [int(x.strip()) for x in item_ids.split(",") if x.strip().isdigit()]
            print_items = [i for i in items if i.pk in ids]
        else:
            print_items = items
    return render(request, "catalog/bom_print.html", {
        "bom": bom,
        "items": print_items,
    })


def bom_create(request):
    """Create a new BOM. Accepts ?unit=<pk> to pre-fill the unit (8.3)."""
    if request.method == "POST":
        form = BOMForm(request.POST)
        if form.is_valid():
            bom = form.save()
            messages.success(request, f"BOM '{bom.name}' created.")
            return redirect("catalog:bom_detail", pk=bom.pk)
    else:
        initial = {}
        unit_pk = request.GET.get("unit")
        if unit_pk:
            unit = Unit.objects.filter(pk=unit_pk).first()
            if unit:
                initial["unit"] = unit
                initial["name"] = f"BOM — {unit.unit_number}"
        form = BOMForm(initial=initial)

    return render(request, "catalog/bom_form.html", {
        "form": form,
        "bom": None,
        "title": "Create BOM",
    })


def bom_edit(request, pk):
    """Edit a BOM."""
    bom = get_object_or_404(BOM, pk=pk)
    if request.method == "POST":
        form = BOMForm(request.POST, instance=bom)
        if form.is_valid():
            form.save()
            messages.success(request, f"BOM '{bom.name}' updated.")
            return redirect("catalog:bom_detail", pk=bom.pk)
    else:
        form = BOMForm(instance=bom)

    return render(request, "catalog/bom_form.html", {
        "form": form,
        "bom": bom,
        "title": "Edit BOM",
    })


def bom_delete(request, pk):
    """Delete a BOM."""
    bom = get_object_or_404(BOM, pk=pk)
    if request.method == "POST":
        name = bom.name
        bom.delete()
        messages.success(request, f"BOM '{name}' deleted.")
        return redirect("catalog:bom_list")
    return render(request, "catalog/bom_confirm_delete.html", {"bom": bom})


def bom_item_add(request, pk):
    """Add a part to a BOM (create BOMItem)."""
    bom = get_object_or_404(BOM, pk=pk)
    if request.method == "POST":
        form = BOMItemForm(request.POST, bom=bom)
        if form.is_valid():
            item = form.save(commit=False)
            item.bom = bom
            item.save()
            messages.success(request, f"Part {item.part.part_number} added to BOM.")
            return redirect("catalog:bom_detail", pk=bom.pk)
    else:
        form = BOMItemForm(bom=bom)

    return render(request, "catalog/bom_item_form.html", {
        "form": form,
        "bom": bom,
        "title": "Add Part",
    })


def bom_item_edit(request, pk, item_pk):
    """Edit a BOM item."""
    bom = get_object_or_404(BOM, pk=pk)
    item = get_object_or_404(BOMItem, pk=item_pk, bom=bom)
    if request.method == "POST":
        form = BOMItemForm(request.POST, instance=item, bom=bom)
        if form.is_valid():
            form.save()
            messages.success(request, f"BOM item updated.")
            return redirect("catalog:bom_detail", pk=bom.pk)
    else:
        form = BOMItemForm(instance=item, bom=bom)

    return render(request, "catalog/bom_item_form.html", {
        "form": form,
        "bom": bom,
        "item": item,
        "title": "Edit BOM Item",
    })


def bom_item_delete(request, pk, item_pk):
    """Delete a BOM item."""
    bom = get_object_or_404(BOM, pk=pk)
    item = get_object_or_404(BOMItem, pk=item_pk, bom=bom)
    if request.method == "POST":
        part_number = item.part.part_number
        item.delete()
        messages.success(request, f"Part {part_number} removed from BOM.")
    return redirect("catalog:bom_detail", pk=bom.pk)


def part_list(request):
    """List parts with search, category filter, KEY, YT NUMBER, J&N, OEM #, DESCRIPTION, IN STOCK, DETAILS."""
    parts = Part.objects.select_related("unit").filter(is_active=True).order_by("part_number")

    # --- Text search (key, J&N, OEM #, description, unit #) ---
    q = request.GET.get("q", "").strip()
    if q:
        parts = parts.filter(
            Q(key__icontains=q)
            | Q(j_and_n__icontains=q)
            | Q(oem_number__icontains=q)
            | Q(description__icontains=q)
            | Q(part_name__icontains=q)
            | Q(part_number__icontains=q)
            | Q(yt_number__icontains=q)
            | Q(unit__unit_number__icontains=q)
        )

    # --- Category filter ---
    filter_category = request.GET.get("category", "").strip()
    if filter_category:
        parts = parts.filter(category=filter_category)

    # --- Build category choices for dropdown ---
    category_choices = (
        Part.objects.filter(is_active=True)
        .exclude(category="")
        .values_list("category", flat=True)
        .distinct()
        .order_by("category")
    )

    context = {
        "parts": parts,
        "q": q,
        "filter_category": filter_category,
        "category_choices": category_choices,
    }
    if request.GET.get("print") == "1":
        return render(request, "catalog/part_list_print.html", context)
    return render(request, "catalog/part_list.html", context)


def part_detail(request, pk):
    """Show details for a single part (minimal for 4.2; enhanced in 4.5)."""
    part = get_object_or_404(Part.objects.select_related("unit"), pk=pk)
    return render(request, "catalog/part_detail.html", {"part": part})


def part_create(request):
    """Create a new part."""
    if request.method == "POST":
        form = PartForm(request.POST, request.FILES)
        if form.is_valid():
            part = form.save()
            messages.success(request, f"Part '{part.part_number}' created.")
            return redirect("catalog:part_detail", pk=part.pk)
    else:
        form = PartForm()

    return render(request, "catalog/part_form.html", {
        "form": form,
        "part": None,
        "title": "Add New Part",
    })


def part_edit(request, pk):
    """Edit a part."""
    part = get_object_or_404(Part, pk=pk)
    if request.method == "POST":
        form = PartForm(request.POST, request.FILES, instance=part)
        if form.is_valid():
            form.save()
            messages.success(request, f"Part '{part.part_number}' updated.")
            return redirect("catalog:part_detail", pk=part.pk)
    else:
        form = PartForm(instance=part)

    return render(request, "catalog/part_form.html", {
        "form": form,
        "part": part,
        "title": "Edit Part",
    })


def part_delete(request, pk):
    """Delete a part."""
    part = get_object_or_404(Part, pk=pk)
    if request.method == "POST":
        part_number = part.part_number
        part.delete()
        messages.success(request, f"Part '{part_number}' deleted.")
        return redirect("catalog:part_list")
    return redirect("catalog:part_edit", pk=pk)


# ---------------------------------------------------------------------------
# Part CSV column header -> Part model field mapping
# ---------------------------------------------------------------------------
PART_CSV_FIELD_MAP = {
    "part_number": "part_number",
    "part_name": "part_name",
    "key": "key",
    "yt_number": "yt_number",
    "j_and_n": "j_and_n",
    "oem_number": "oem_number",
    "item_no": "item_no",
    "category": "category",
    "type": "type",
    "oem_type": "oem_type",
    "item_typ": "item_typ",
    "oem": "oem",
    "primary_vendor": "primary_vendor",
    "catalog": "catalog",
    "plug_id": "plug_id",
    "price": "price",
    "cost_price": "cost_price",
    "stock_quantity": "stock_quantity",
    "reorder_qty": "reorder_qty",
    "bin_number": "bin_number",
    "description": "description",
    "foot_notes": "foot_notes",
    "superseding_notes": "superseding_notes",
}


def part_upload_csv(request):
    """Upload a CSV file to create / update parts in bulk."""
    if request.method == "POST":
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "Please select a CSV file.")
            return redirect("catalog:part_upload_csv")

        if not csv_file.name.endswith(".csv"):
            messages.error(request, "File must be a .csv file.")
            return redirect("catalog:part_upload_csv")

        try:
            decoded = csv_file.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(decoded))

            created = 0
            updated = 0
            errors = []

            for row_num, row in enumerate(reader, start=2):
                row = {k.strip().lower().replace(" ", "_"): v.strip() for k, v in row.items() if k}

                part_number = row.get("part_number", "").strip()
                if not part_number:
                    errors.append(f"Row {row_num}: missing part_number, skipped.")
                    continue

                defaults = {}
                for csv_col, model_field in PART_CSV_FIELD_MAP.items():
                    if csv_col in row and row[csv_col]:
                        defaults[model_field] = row[csv_col]

                for dec_field in ("price", "cost_price"):
                    if dec_field in defaults:
                        try:
                            defaults[dec_field] = (
                                float(defaults[dec_field]) if defaults[dec_field] else None
                            )
                        except (ValueError, TypeError):
                            defaults[dec_field] = None

                for int_field in ("stock_quantity", "reorder_qty"):
                    if int_field in defaults:
                        try:
                            defaults[int_field] = int(defaults[int_field]) if defaults[int_field] else 0
                        except (ValueError, TypeError):
                            defaults[int_field] = 0

                unit_number = row.get("unit_number", "").strip()
                if unit_number:
                    unit = Unit.objects.filter(unit_number=unit_number).first()
                    if unit:
                        defaults["unit"] = unit

                obj, was_created = Part.objects.update_or_create(
                    part_number=part_number, defaults=defaults
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

            summary = f"CSV processed: {created} created, {updated} updated."
            if errors:
                summary += f" {len(errors)} row(s) skipped."
            messages.success(request, summary)

        except Exception as e:
            messages.error(request, f"Error processing CSV: {e}")

        return redirect("catalog:part_list")

    return render(request, "catalog/part_upload_csv.html")


def unit_search(request):
    """Advanced search across Units, Applications, and Parts (8.x — Unit Search page)."""
    tab = request.GET.get("tab", "units")
    results = []
    results_count = 0

    # Only run search when at least one search param is present (not just tab)
    has_search_params = any(k.startswith("q_") for k in request.GET)
    if request.method == "GET" and has_search_params:
        tab = request.GET.get("tab", "units")
        if tab == "units":
            qs = Unit.objects.select_related("unit_type").filter(is_active=True)
            for field in [
                "manufacturer", "mount_type", "nose_type", "weight", "clocking_degrees",
                "housing", "design", "tooth_quantity", "over_crank_protection",
                "with_mounting_shims", "power_rating", "grounding", "voltage",
                "reclockable_flange", "with_hardware", "unit_number", "family",
                "rotation", "solenoid_attached", "bolt_holes", "drive",
            ]:
                val = request.GET.get(f"q_{field}", "").strip()
                if val:
                    qs = qs.filter(**{f"{field}__icontains": val})
            results = list(qs[:100])
            results_count = len(results)
        elif tab == "applications":
            qs = Application.objects.filter(is_active=True)
            for field in [
                "make", "volt", "unit_number", "engine", "amp", "options",
                "year", "mfr", "part_number", "other_number", "notes",
            ]:
                val = request.GET.get(f"q_{field}", "").strip()
                if val:
                    qs = qs.filter(**{f"{field}__icontains": val})
            # Linked Unit filter
            linked = request.GET.get("q_linked_unit", "").strip()
            if linked == "linked":
                qs = qs.filter(application_units__isnull=False).distinct()
            elif linked == "not_linked":
                qs = qs.filter(application_units__isnull=True)
            # Date range filters
            created_from = request.GET.get("q_created_from", "").strip()
            created_to = request.GET.get("q_created_to", "").strip()
            updated_from = request.GET.get("q_updated_from", "").strip()
            updated_to = request.GET.get("q_updated_to", "").strip()
            if created_from:
                qs = qs.filter(created_at__date__gte=created_from)
            if created_to:
                qs = qs.filter(created_at__date__lte=created_to)
            if updated_from:
                qs = qs.filter(updated_at__date__gte=updated_from)
            if updated_to:
                qs = qs.filter(updated_at__date__lte=updated_to)
            results = list(qs[:100])
            results_count = len(results)
        elif tab == "parts":
            qs = Part.objects.select_related("unit").filter(is_active=True)
            part_search = request.GET.get("q_part_search", "").strip()
            if part_search:
                qs = qs.filter(
                    Q(key__icontains=part_search)
                    | Q(j_and_n__icontains=part_search)
                    | Q(oem_number__icontains=part_search)
                    | Q(part_number__icontains=part_search)
                    | Q(part_name__icontains=part_search)
                )
            for field in [
                "oem_number", "key", "type", "catalog", "oem_type", "part_name",
                "item_no", "primary_vendor", "description", "j_and_n",
                "category", "plug_id", "item_typ", "yt_number", "foot_notes",
                "superseding_notes", "part_number", "oem",
            ]:
                val = request.GET.get(f"q_{field}", "").strip()
                if val:
                    qs = qs.filter(**{f"{field}__icontains": val})
            # Name (maps to part_name)
            name_val = request.GET.get("q_name", "").strip()
            if name_val:
                qs = qs.filter(part_name__icontains=name_val)
            # Unit (search by unit_number on related unit)
            unit_val = request.GET.get("q_unit", "").strip()
            if unit_val:
                qs = qs.filter(unit__unit_number__icontains=unit_val)
            # Price (numeric)
            price_val = request.GET.get("q_price", "").strip()
            if price_val:
                try:
                    price = float(price_val)
                    qs = qs.filter(price=price)
                except ValueError:
                    pass
            # Stock quantity (numeric)
            stock_val = request.GET.get("q_stock_quantity", "").strip()
            if stock_val:
                try:
                    qty = int(stock_val)
                    qs = qs.filter(stock_quantity=qty)
                except ValueError:
                    pass
            # Reorder qty (numeric)
            reorder_val = request.GET.get("q_reorder_qty", "").strip()
            if reorder_val:
                try:
                    qty = int(reorder_val)
                    qs = qs.filter(reorder_qty=qty)
                except ValueError:
                    pass
            # In Stock dropdown
            in_stock = request.GET.get("q_in_stock", "").strip()
            if in_stock == "in_stock":
                qs = qs.filter(stock_quantity__gt=0)
            elif in_stock == "out_of_stock":
                qs = qs.filter(stock_quantity=0)
            elif in_stock == "low_stock":
                qs = qs.filter(stock_quantity__lt=F("reorder_qty"))
            # Has Picture / Has Interchange / Has Superseding
            for param, field in [
                ("q_has_picture", "has_picture"),
                ("q_has_interchange", "has_interchange"),
                ("q_has_superseding", "has_superseding"),
            ]:
                v = request.GET.get(param, "").strip()
                if v == "yes":
                    qs = qs.filter(**{field: True})
                elif v == "no":
                    qs = qs.filter(**{field: False})
            # Date range filters
            created_from = request.GET.get("q_created_from", "").strip()
            created_to = request.GET.get("q_created_to", "").strip()
            updated_from = request.GET.get("q_updated_from", "").strip()
            updated_to = request.GET.get("q_updated_to", "").strip()
            if created_from:
                qs = qs.filter(created_at__date__gte=created_from)
            if created_to:
                qs = qs.filter(created_at__date__lte=created_to)
            if updated_from:
                qs = qs.filter(updated_at__date__gte=updated_from)
            if updated_to:
                qs = qs.filter(updated_at__date__lte=updated_to)
            results = list(qs[:100])
            results_count = len(results)

    # Build category choices for Parts tab
    part_category_choices = []
    if tab == "parts":
        part_category_choices = list(
            Part.objects.filter(is_active=True)
            .exclude(category="")
            .values_list("category", flat=True)
            .distinct()
            .order_by("category")
        )

    return render(request, "catalog/unit_search.html", {
        "tab": tab,
        "results": results or [],
        "results_count": results_count,
        "get_params": request.GET,
        "part_category_choices": part_category_choices,
    })


def unit_list(request):
    """List units with type tabs, search, and dropdown filters."""
    units = Unit.objects.select_related("unit_type").filter(is_active=True)

    # --- Unit-type tabs ---
    unit_types = UnitType.objects.all()
    selected_type = request.GET.get("type", "")

    if selected_type:
        units = units.filter(unit_type__id=selected_type)

    # --- Text search ---
    q = request.GET.get("q", "").strip()
    if q:
        units = units.filter(
            Q(unit_number__icontains=q)
            | Q(oem__icontains=q)
            | Q(design__icontains=q)
            | Q(yt_number__icontains=q)
            | Q(manufacturer__icontains=q)
        )

    # --- Dropdown filters ---
    filter_oem = request.GET.get("oem", "").strip()
    filter_voltage = request.GET.get("voltage", "").strip()
    filter_family = request.GET.get("family", "").strip()

    if filter_oem:
        units = units.filter(oem=filter_oem)
    if filter_voltage:
        units = units.filter(voltage=filter_voltage)
    if filter_family:
        units = units.filter(family=filter_family)

    # --- Build distinct value lists for dropdowns ---
    active_units = Unit.objects.filter(is_active=True)
    oem_choices = (
        active_units.exclude(oem="")
        .values_list("oem", flat=True)
        .distinct()
        .order_by("oem")
    )
    voltage_choices = (
        active_units.exclude(voltage="")
        .values_list("voltage", flat=True)
        .distinct()
        .order_by("voltage")
    )
    family_choices = (
        active_units.exclude(family="")
        .values_list("family", flat=True)
        .distinct()
        .order_by("family")
    )

    # Resolve selected unit type name for section heading
    selected_unit_type_name = None
    if selected_type:
        ut = next((t for t in unit_types if str(t.id) == selected_type), None)
        if ut:
            selected_unit_type_name = ut.name

    context = {
        "units": units,
        "unit_types": unit_types,
        "selected_type": selected_type,
        "selected_unit_type_name": selected_unit_type_name,
        "q": q,
        "filter_oem": filter_oem,
        "filter_voltage": filter_voltage,
        "filter_family": filter_family,
        "oem_choices": oem_choices,
        "voltage_choices": voltage_choices,
        "family_choices": family_choices,
    }
    return render(request, "catalog/unit_list.html", context)


def unit_detail(request, pk):
    """Show full details for a single unit."""
    unit = get_object_or_404(Unit.objects.select_related("unit_type"), pk=pk)

    # Build spec sections for the template
    spec_sections = [
        ("Identification", [
            ("Unit Number", unit.unit_number),
            ("YT Number", unit.yt_number),
            ("OEM", unit.oem),
            ("J&N Number", unit.j_and_n_number),
            ("Model/Cat Number", unit.model_cat_number),
            ("Unit Type", str(unit.unit_type) if unit.unit_type else ""),
            ("Manufacturer", unit.manufacturer),
            ("Family", unit.family),
        ]),
        ("Electrical", [
            ("Voltage", unit.voltage),
            ("kW / HP", unit.kw_hp),
            ("Phase", unit.phase),
            ("FLA", unit.fla),
            ("Amp Rating", unit.amp_rating),
            ("Full Load Efficiency", unit.full_load_eff),
            ("Power Rating", unit.power_rating),
        ]),
        ("Mechanical", [
            ("RPM", unit.rpm),
            ("Frame", unit.frame),
            ("Enclosure", unit.enclosure),
            ("Rotation", unit.rotation),
            ("Mount Type", unit.mount_type),
            ("Flange Type", unit.flange_type),
            ("Housing Type", unit.housing_type),
            ("Housing", unit.housing),
            ("Weight", unit.weight),
            ("Bearings", unit.bearings),
            ("Design", unit.design),
            ("Type", unit.type),
            ("Service Factor", unit.service_factor),
            ("Duty Cycle", unit.duty_cycle),
            ("Speed Ratio", unit.speed_ratio),
            ("Grounding", unit.grounding),
            ("Insulation Class", unit.insulation_class),
            ("Overload Protection", unit.overload_protection),
            ("C Dimension", unit.c_dimension),
            ("U Dimension", unit.u_dimension),
        ]),
        ("Starter-Specific", [
            ("Tooth Quantity", unit.tooth_quantity),
            ("Nose Type", unit.nose_type),
            ("Over Crank Protection", unit.over_crank_protection),
            ("Solenoid Attached", unit.solenoid_attached),
        ]),
        ("Generator-Specific", [
            ("Circuit Type", unit.circuit_type),
            ("Brush Type", unit.brush_type),
            ("Regulation Type", unit.regulation_type),
        ]),
        ("Alternator-Specific", [
            ("Fan Type", unit.fan_type),
            ("Regulator Type", unit.regulator_type),
        ]),
        ("Other", [
            ("Reclockable Flange", unit.reclockable_flange),
            ("With Mounting Shims", unit.with_mounting_shims),
            ("With Hardware", unit.with_hardware),
            ("Bolt Holes", unit.bolt_holes),
            ("Clocking Degrees", unit.clocking_degrees),
            ("Drive", unit.drive),
        ]),
    ]

    # Filter out sections where every value is blank
    spec_sections = [
        (title, fields)
        for title, fields in spec_sections
        if any(val for _, val in fields)
    ]

    # Cross references (both directions)
    cross_refs = CrossReference.objects.filter(
        Q(unit=unit) | Q(cross_ref_unit=unit)
    ).select_related("unit", "cross_ref_unit", "unit__unit_type", "cross_ref_unit__unit_type")

    cross_ref_units = []
    for cr in cross_refs:
        other = cr.cross_ref_unit if cr.unit_id == unit.pk else cr.unit
        cross_ref_units.append({"ref": cr, "unit": other})

    # Substitutes (both directions)
    subs_qs = Substitute.objects.filter(
        Q(unit=unit) | Q(substitute_unit=unit)
    ).select_related("unit", "substitute_unit", "unit__unit_type", "substitute_unit__unit_type")

    substitute_units = []
    for s in subs_qs:
        other = s.substitute_unit if s.unit_id == unit.pk else s.unit
        substitute_units.append({"ref": s, "unit": other})

    # Gear Reduction Substitutions
    gear_reductions = GearReductionSubstitution.objects.filter(unit=unit).order_by("number")

    return render(request, "catalog/unit_detail.html", {
        "unit": unit,
        "spec_sections": spec_sections,
        "cross_ref_units": cross_ref_units,
        "substitute_units": substitute_units,
        "gear_reductions": gear_reductions,
    })


def unit_bom_view(request, pk):
    """View BOM(s) for a unit (8.3). If 1 BOM redirect; if multiple show list; if none show create option."""
    unit = get_object_or_404(Unit.objects.select_related("unit_type"), pk=pk)
    boms = BOM.objects.filter(unit=unit).order_by("name")

    if boms.count() == 1:
        return redirect("catalog:bom_detail", pk=boms.first().pk)
    elif boms.exists():
        return render(request, "catalog/unit_bom_list.html", {
            "unit": unit,
            "boms": boms,
        })
    else:
        return render(request, "catalog/unit_bom_empty.html", {
            "unit": unit,
        })


def cross_reference_add(request, pk):
    """Add a cross-reference to a unit."""
    unit = get_object_or_404(Unit, pk=pk)

    if request.method == "POST":
        form = CrossReferenceForm(request.POST, unit=unit)
        if form.is_valid():
            cr = form.save(commit=False)
            cr.unit = unit
            cr.save()
            messages.success(
                request,
                f"Cross reference to {cr.cross_ref_unit.unit_number} added.",
            )
            return redirect("catalog:unit_detail", pk=unit.pk)
    else:
        form = CrossReferenceForm(unit=unit)

    return render(request, "catalog/cross_reference_add.html", {
        "form": form,
        "unit": unit,
    })


def substitute_add(request, pk):
    """Add a substitute to a unit."""
    unit = get_object_or_404(Unit, pk=pk)

    if request.method == "POST":
        form = SubstituteForm(request.POST, unit=unit)
        if form.is_valid():
            sub = form.save(commit=False)
            sub.unit = unit
            sub.save()
            messages.success(
                request,
                f"Substitute {sub.substitute_unit.unit_number} added.",
            )
            return redirect("catalog:unit_detail", pk=unit.pk)
    else:
        form = SubstituteForm(unit=unit)

    return render(request, "catalog/substitute_add.html", {
        "form": form,
        "unit": unit,
    })


def gear_reduction_add(request, pk):
    """Add a gear reduction substitution to a unit."""
    unit = get_object_or_404(Unit, pk=pk)

    if request.method == "POST":
        form = GearReductionForm(request.POST)
        if form.is_valid():
            gr = form.save(commit=False)
            gr.unit = unit
            gr.save()
            messages.success(request, f"Gear reduction '{gr.number}' added.")
            return redirect("catalog:unit_detail", pk=unit.pk)
    else:
        form = GearReductionForm()

    return render(request, "catalog/gear_reduction_form.html", {
        "form": form,
        "unit": unit,
        "title": "Add Gear Reduction",
    })


def gear_reduction_edit(request, pk, gr_pk):
    """Edit a gear reduction substitution."""
    unit = get_object_or_404(Unit, pk=pk)
    gr = get_object_or_404(GearReductionSubstitution, pk=gr_pk, unit=unit)

    if request.method == "POST":
        form = GearReductionForm(request.POST, instance=gr)
        if form.is_valid():
            form.save()
            messages.success(request, f"Gear reduction '{gr.number}' updated.")
            return redirect("catalog:unit_detail", pk=unit.pk)
    else:
        form = GearReductionForm(instance=gr)

    return render(request, "catalog/gear_reduction_form.html", {
        "form": form,
        "unit": unit,
        "title": "Edit Gear Reduction",
    })


def gear_reduction_delete(request, pk, gr_pk):
    """Delete a gear reduction substitution."""
    unit = get_object_or_404(Unit, pk=pk)
    gr = get_object_or_404(GearReductionSubstitution, pk=gr_pk, unit=unit)

    if request.method == "POST":
        gr.delete()
        messages.success(request, f"Gear reduction '{gr.number}' deleted.")
    return redirect("catalog:unit_detail", pk=unit.pk)


def _build_fieldsets(form):
    """Build a list of (section_title, [bound_fields]) for the template."""
    fieldsets = []
    for title, field_names in form.FIELDSETS:
        fields = [form[name] for name in field_names if name in form.fields]
        fieldsets.append((title, fields))
    return fieldsets


def unit_create(request):
    """Create a new unit."""
    if request.method == "POST":
        form = UnitForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Unit created successfully.")
            return redirect("catalog:unit_list")
    else:
        form = UnitForm()

    return render(request, "catalog/unit_form.html", {
        "form": form,
        "unit": None,
        "fieldsets": _build_fieldsets(form),
        "title": "Add New Unit",
    })


def unit_edit(request, pk):
    """Edit an existing unit."""
    unit = get_object_or_404(Unit, pk=pk)
    if request.method == "POST":
        form = UnitForm(request.POST, request.FILES, instance=unit)
        if form.is_valid():
            form.save()
            messages.success(request, f"Unit '{unit.unit_number}' updated.")
            return redirect("catalog:unit_detail", pk=unit.pk)
    else:
        form = UnitForm(instance=unit)

    return render(request, "catalog/unit_form.html", {
        "form": form,
        "unit": unit,
        "fieldsets": _build_fieldsets(form),
        "title": "Edit Unit",
    })


def unit_delete(request, pk):
    """Delete a unit."""
    unit = get_object_or_404(Unit, pk=pk)
    if request.method == "POST":
        unit_number = unit.unit_number
        unit.delete()
        messages.success(request, f"Unit '{unit_number}' deleted.")
        return redirect("catalog:unit_list")
    return redirect("catalog:unit_edit", pk=pk)


# ---------------------------------------------------------------------------
# CSV column header -> Unit model field mapping
# ---------------------------------------------------------------------------
CSV_FIELD_MAP = {
    "unit_number": "unit_number",
    "yt_number": "yt_number",
    "oem": "oem",
    "j_and_n_number": "j_and_n_number",
    "model_cat_number": "model_cat_number",
    "manufacturer": "manufacturer",
    "family": "family",
    "voltage": "voltage",
    "kw_hp": "kw_hp",
    "phase": "phase",
    "fla": "fla",
    "amp_rating": "amp_rating",
    "full_load_eff": "full_load_eff",
    "power_rating": "power_rating",
    "rpm": "rpm",
    "frame": "frame",
    "enclosure": "enclosure",
    "rotation": "rotation",
    "mount_type": "mount_type",
    "flange_type": "flange_type",
    "housing_type": "housing_type",
    "housing": "housing",
    "weight": "weight",
    "bearings": "bearings",
    "design": "design",
    "type": "type",
    "service_factor": "service_factor",
    "duty_cycle": "duty_cycle",
    "speed_ratio": "speed_ratio",
    "grounding": "grounding",
    "insulation_class": "insulation_class",
    "overload_protection": "overload_protection",
    "c_dimension": "c_dimension",
    "u_dimension": "u_dimension",
    "tooth_quantity": "tooth_quantity",
    "nose_type": "nose_type",
    "over_crank_protection": "over_crank_protection",
    "solenoid_attached": "solenoid_attached",
    "circuit_type": "circuit_type",
    "brush_type": "brush_type",
    "regulation_type": "regulation_type",
    "fan_type": "fan_type",
    "regulator_type": "regulator_type",
    "reclockable_flange": "reclockable_flange",
    "with_mounting_shims": "with_mounting_shims",
    "with_hardware": "with_hardware",
    "bolt_holes": "bolt_holes",
    "clocking_degrees": "clocking_degrees",
    "drive": "drive",
    "unit_attributes": "unit_attributes",
    "notes": "notes",
    "new_unit_price": "new_unit_price",
    "rebuilt_unit_price": "rebuilt_unit_price",
}


def unit_upload_csv(request):
    """Upload a CSV file to create / update units in bulk."""
    if request.method == "POST":
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "Please select a CSV file.")
            return redirect("catalog:unit_upload_csv")

        if not csv_file.name.endswith(".csv"):
            messages.error(request, "File must be a .csv file.")
            return redirect("catalog:unit_upload_csv")

        try:
            decoded = csv_file.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(decoded))

            created = 0
            updated = 0
            errors = []

            for row_num, row in enumerate(reader, start=2):
                # Normalise header keys
                row = {k.strip().lower().replace(" ", "_"): v.strip() for k, v in row.items() if k}

                unit_number = row.get("unit_number", "").strip()
                if not unit_number:
                    errors.append(f"Row {row_num}: missing unit_number, skipped.")
                    continue

                # Resolve unit_type by name if provided
                unit_type = None
                type_name = row.get("unit_type", "").strip()
                if type_name:
                    unit_type = UnitType.objects.filter(name__iexact=type_name).first()

                # Build field dict from CSV columns
                defaults = {}
                for csv_col, model_field in CSV_FIELD_MAP.items():
                    if csv_col in row and row[csv_col]:
                        defaults[model_field] = row[csv_col]

                if unit_type:
                    defaults["unit_type"] = unit_type

                # Handle decimal fields — set to None if blank/invalid
                for dec_field in ("new_unit_price", "rebuilt_unit_price"):
                    if dec_field in defaults:
                        try:
                            defaults[dec_field] = (
                                float(defaults[dec_field]) if defaults[dec_field] else None
                            )
                        except (ValueError, TypeError):
                            defaults[dec_field] = None

                obj, was_created = Unit.objects.update_or_create(
                    unit_number=unit_number, defaults=defaults
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

            summary = f"CSV processed: {created} created, {updated} updated."
            if errors:
                summary += f" {len(errors)} row(s) skipped."
            messages.success(request, summary)

        except Exception as e:
            messages.error(request, f"Error processing CSV: {e}")

        return redirect("catalog:unit_list")

    return render(request, "catalog/unit_upload_csv.html")
