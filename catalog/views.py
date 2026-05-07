import csv
import io
import json
import logging


from django.contrib import messages

logger = logging.getLogger(__name__)
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Case, Exists, F, Max, OuterRef, Q, Value, When
from django.db.models.functions import NullIf
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import ApplicationForm, ApplicationSpecificationForm, ApplicationUnitLinkForm, BOMForm, BOMItemForm, CrossReferenceForm, GearReductionForm, PartForm, PartInterchangeForm, PartSubstituteForm, PartSupersedingForm, SubstituteForm, UnitForm
from .models import Application, ApplicationSpecification, ApplicationType, ApplicationTypeField, ApplicationUnit, BOM, BOMItem, CrossReference, GearReductionSubstitution, Part, PartCategory, PartCategoryField, PartInterchange, PartSubstitute, PartSuperseding, Substitute, Unit, UnitType, UnitTypeCategory, UnitTypeCategoryField

PART_DEFAULT_FIELDS = [
    ("part_number", "Part Number"),
    ("part_name", "Part Name"),
    ("manufacturer_number", "Manufacturer Number"),
    ("yt_number", "YT Number"),
    ("j_and_n", "J&N Number"),
    ("oem_number", "OEM #"),
    ("voltage", "Voltage"),
    ("type", "Type"),
    ("oem", "OEM"),
    ("primary_vendor", "Primary Vendor"),
]

UNIT_DEFAULT_FIELDS = [
    ("yt_number", "YT Number"),
    ("oem", "OEM"),
    ("model_cat_number", "Model / Cat Number"),
    ("voltage", "Voltage"),
]

APPLICATION_DEFAULT_FIELDS = [
    ("unit_number", "Unit Number"),
    ("make", "Make"),
    ("model", "Model"),
    ("engine", "Engine"),
    ("year", "Year"),
    ("mfr", "Manufacturer"),
    ("volt", "Voltage"),
    ("amp", "Amps"),
    ("fuel_type", "Fuel Type"),
    ("vin", "VIN"),
    ("alt_pulley", "Alt Pulley"),
    ("unit_type_name", "Unit Type"),
    ("other_number", "Other Number"),
    ("options", "Options"),
    ("notes", "Notes"),
]


def _part_display_number(part) -> str:
    return part.part_number or part.yt_number or f"Part #{part.pk}"


def _get_application_type_field_defs():
    """Build application type field definitions dict from the database."""
    result = {}
    for at in ApplicationType.objects.prefetch_related("fields").all():
        result[at.name] = [
            {"name": f.field_name, "label": f.field_label, "type": "text"}
            for f in at.fields.all()
        ]
    return result


def _get_category_field_defs():
    """Build CATEGORY_FIELD_DEFINITIONS dict from the database."""
    result = {}
    for cat in PartCategory.objects.prefetch_related("fields").all():
        result[cat.name] = [
            {"name": f.field_name, "label": f.field_label, "type": "text"}
            for f in cat.fields.all()
        ]
    return result


def _get_unit_type_field_defs():
    """Build unit type category field definitions dict from the database."""
    result = {}
    for cat in UnitTypeCategory.objects.prefetch_related("fields").all():
        result[cat.name] = [
            {"name": f.field_name, "label": f.field_label, "type": "text"}
            for f in cat.fields.all()
        ]
    return result


def home(request):
    """Landing page for Apex Database."""
    backup_configured = False
    try:
        from backup.models import BackupSettings
        settings = BackupSettings.get()
        backup_configured = bool(settings.local_backup_path or settings.external_backup_path)
    except Exception:
        pass
    return render(request, "catalog/home.html", {
        "backup_configured": backup_configured,
    })


def image_viewer(request):
    """Standalone image viewer with zoom, pan, and print."""
    image_url = request.GET.get("src", "")
    title = request.GET.get("title", "Image Viewer")
    return render(request, "catalog/image_viewer.html", {
        "image_url": image_url,
        "title": title,
    })


def application_list(request):
    """List applications with search, filters (Make, Year, Mfr, Volt, Unit), MAKE, ENGINE, YEAR, etc."""
    applications = Application.objects.filter(is_active=True).order_by("name")

    # --- Text search ---
    q = request.GET.get("q", "").strip()
    if q:
        applications = applications.filter(
            Q(name__icontains=q)
            | Q(make__icontains=q)
            | Q(model__icontains=q)
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
        applications = applications.filter(year__icontains=filter_year)
    if filter_mfr:
        applications = applications.filter(mfr=filter_mfr)
    if filter_volt:
        applications = applications.filter(volt=filter_volt)
    if filter_unit:
        applications = applications.filter(unit_number__icontains=filter_unit)

    filter_unit_type = request.GET.get("unit_type", "").strip()
    if filter_unit_type:
        applications = applications.filter(unit_type_name=filter_unit_type)

    # --- Build distinct value lists for dropdowns (cached 5 min) ---
    active_apps = Application.objects.filter(is_active=True)
    make_choices = cache.get_or_set("app_make_choices",
        lambda: list(active_apps.exclude(make="").values_list("make", flat=True).distinct().order_by("make")),
        300)
    # Year uses text input (too many distinct values for a dropdown)
    mfr_choices = cache.get_or_set("app_mfr_choices",
        lambda: list(active_apps.exclude(mfr="").values_list("mfr", flat=True).distinct().order_by("mfr")),
        300)
    volt_choices = cache.get_or_set("app_volt_choices",
        lambda: list(active_apps.exclude(volt="").values_list("volt", flat=True).distinct().order_by("volt")),
        300)
    unit_type_choices = cache.get_or_set("app_unit_type_choices",
        lambda: list(active_apps.exclude(unit_type_name="").values_list("unit_type_name", flat=True).distinct().order_by("unit_type_name")),
        300)

    try:
        per_page = min(int(request.GET.get("per_page", 50)), 100)
    except (ValueError, TypeError):
        per_page = 50
    paginator = Paginator(applications, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    total_count = paginator.count

    context = {
        "applications": page_obj,
        "page_obj": page_obj,
        "total_count": total_count,
        "per_page": per_page,
        "q": q,
        "filter_make": filter_make,
        "filter_year": filter_year,
        "filter_mfr": filter_mfr,
        "filter_volt": filter_volt,
        "filter_unit": filter_unit,
        "filter_unit_type": filter_unit_type,
        "make_choices": make_choices,
        "mfr_choices": mfr_choices,
        "volt_choices": volt_choices,
        "unit_type_choices": unit_type_choices,
    }
    return render(request, "catalog/application_list.html", context)


def application_detail(request, pk):
    """Show details for a single application with General Specifications and Linked Units panel."""
    app = get_object_or_404(Application, pk=pk)
    linked_units = (
        ApplicationUnit.objects.filter(application=app)
        .select_related("unit", "unit__unit_type")
        .order_by("unit__unit_number")
    )
    specifications = ApplicationSpecification.objects.filter(application=app).order_by("category", "type")

    custom_spec_display = []
    custom_fields = _get_application_custom_fields()
    type_specs = app.type_specifications or {}
    label_map = {f["name"]: f["label"] for f in custom_fields}
    for key, val in type_specs.items():
        if val:
            label = label_map.get(key, key)
            custom_spec_display.append({"label": label, "value": val})

    return render(request, "catalog/application_detail.html", {
        "application": app,
        "linked_units": linked_units,
        "specifications": specifications,
        "custom_spec_display": custom_spec_display,
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
            logger.info("[Application] Linked unit %s to %s", au.unit.unit_number, app)
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
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    app = get_object_or_404(Application, pk=pk)
    au = get_object_or_404(ApplicationUnit, application=app, unit_id=unit_pk)
    unit_number = au.unit.unit_number
    au.delete()
    logger.info("[Application] Unlinked unit %s from application", unit_number)
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
            logger.info("[Application] Added spec to %s", app)
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
            logger.info("[Application] Updated spec on %s", spec.application)
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
        logger.info("[Application] Removed spec from %s", app)
        messages.success(request, "Specification removed.")
    return redirect("catalog:application_detail", pk=app.pk)


def _get_application_custom_fields():
    """Return list of custom field dicts for the Application type (excludes default fields)."""
    default_names = {fn for fn, _ in APPLICATION_DEFAULT_FIELDS}
    at = ApplicationType.objects.filter(name="Application").prefetch_related("fields").first()
    if not at:
        return []
    return [
        {"name": f.field_name, "label": f.field_label}
        for f in at.fields.all()
        if f.field_name not in default_names
    ]


def _build_app_fieldsets(form):
    """Build a list of (section_title, [bound_fields]) for the application template."""
    fieldsets = []
    for title, field_names in form.FIELDSETS:
        fields = [form[name] for name in field_names if name in form.fields]
        fieldsets.append((title, fields))
    return fieldsets


def application_create(request):
    """Create a new application."""
    if request.method == "POST":
        form = ApplicationForm(request.POST)
        del form.fields["is_active"]
        if form.is_valid():
            app = form.save()
            # Link selected units
            for unit_pk in request.POST.getlist("link_units"):
                try:
                    unit = Unit.objects.get(pk=int(unit_pk))
                    ApplicationUnit.objects.get_or_create(application=app, unit=unit)
                except (Unit.DoesNotExist, ValueError):
                    pass
            logger.info("[Application] Created '%s' (pk=%s)", app.name, app.pk)
            messages.success(request, f"Application '{app.name}' created.")
            return redirect("catalog:application_detail", pk=app.pk)
    else:
        form = ApplicationForm()
        del form.fields["is_active"]

    custom_fields = _get_application_custom_fields()
    fieldsets = [(t, f) for t, f in _build_app_fieldsets(form) if f]
    return render(request, "catalog/application_form.html", {
        "form": form,
        "application": None,
        "fieldsets": fieldsets,
        "linked_units": [],
        "title": "Add New Application",
        "custom_fields_json": json.dumps(custom_fields),
        "existing_type_specs_json": "{}",
    })


def application_edit(request, pk):
    """Edit an application."""
    app = get_object_or_404(Application, pk=pk)
    if request.method == "POST":
        form = ApplicationForm(request.POST, instance=app)
        del form.fields["is_active"]
        if form.is_valid():
            form.save()
            # Handle unit linking: remove unchecked existing links, add new ones
            kept_pks = set(int(x) for x in request.POST.getlist("keep_unit") if x.isdigit())
            ApplicationUnit.objects.filter(application=app).exclude(unit_id__in=kept_pks).delete()
            for unit_pk in request.POST.getlist("link_units"):
                try:
                    unit = Unit.objects.get(pk=int(unit_pk))
                    ApplicationUnit.objects.get_or_create(application=app, unit=unit)
                except (Unit.DoesNotExist, ValueError):
                    pass
            logger.info("[Application] Updated '%s' (pk=%s)", app.name, app.pk)
            messages.success(request, f"Application '{app.name}' updated.")
            return redirect("catalog:application_detail", pk=app.pk)
    else:
        form = ApplicationForm(instance=app)
        del form.fields["is_active"]

    custom_fields = _get_application_custom_fields()
    existing_type_specs = app.type_specifications or {}
    linked_units = (
        ApplicationUnit.objects.filter(application=app)
        .select_related("unit")
        .order_by("unit__unit_number")
    )
    fieldsets = [(t, f) for t, f in _build_app_fieldsets(form) if f]
    return render(request, "catalog/application_form.html", {
        "form": form,
        "application": app,
        "fieldsets": fieldsets,
        "linked_units": linked_units,
        "title": "Edit Application",
        "custom_fields_json": json.dumps(custom_fields),
        "existing_type_specs_json": json.dumps(existing_type_specs),
    })


def application_delete(request, pk):
    """Delete an application."""
    app = get_object_or_404(Application, pk=pk)
    if request.method == "POST":
        name = app.name
        app.delete()
        logger.info("[Application] Deleted '%s'", name)
        messages.success(request, f"Application '{name}' deleted.")
        return redirect("catalog:application_list")
    return redirect("catalog:application_edit", pk=pk)


def bom_list(request):
    """List BOMs with search, unit-type filter, and pagination."""
    boms = BOM.objects.select_related("unit", "application", "unit__unit_type").order_by("name")

    if request.GET.get("print") == "1":
        return render(request, "catalog/bom_list_print.html", {"boms": boms})

    q = request.GET.get("q", "").strip()
    if q:
        boms = boms.filter(
            Q(name__icontains=q)
            | Q(unit__unit_number__icontains=q)
            | Q(application__name__icontains=q)
            | Q(items__part__part_number__icontains=q)
            | Q(items__part__oem_number__icontains=q)
            | Q(items__part__j_and_n__icontains=q)
            | Q(items__part__yt_number__icontains=q)
            | Q(items__oem_number__icontains=q)
            | Q(items__j_and_n__icontains=q)
            | Q(items__yt_number__icontains=q)
        ).distinct()

    filter_unit_type = request.GET.get("unit_type", "").strip()
    if filter_unit_type:
        boms = boms.filter(unit__unit_type__name=filter_unit_type)

    unit_type_choices = list(
        UnitType.objects.filter(units__boms__isnull=False)
        .values_list("name", flat=True)
        .distinct()
        .order_by("name")
    )

    total_count = boms.count()
    try:
        per_page = min(int(request.GET.get("per_page", 50)), 100)
    except (ValueError, TypeError):
        per_page = 50
    paginator = Paginator(boms, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    category_color_map = dict(
        UnitTypeCategory.objects.values_list("name", "color")
    )
    return render(request, "catalog/bom_list.html", {
        "boms": page_obj,
        "page_obj": page_obj,
        "total_count": total_count,
        "per_page": per_page,
        "q": q,
        "filter_unit_type": filter_unit_type,
        "unit_type_choices": unit_type_choices,
        "category_color_map": category_color_map,
    })


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
    """Create a new BOM. Accepts ?unit=<pk> to pre-fill the unit."""
    if request.method == "POST":
        form = BOMForm(request.POST)
        if form.is_valid():
            bom = form.save()
            logger.info("[BOM] Created '%s' (pk=%s)", bom.name, bom.pk)
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
        "item_form": BOMItemForm(),
        "title": "Create BOM",
    })


def bom_edit(request, pk):
    """Edit a BOM."""
    bom = get_object_or_404(
        BOM.objects.prefetch_related("items__part"),
        pk=pk,
    )
    if request.method == "POST":
        form = BOMForm(request.POST, instance=bom)
        if form.is_valid():
            form.save()
            logger.info("[BOM] Updated '%s' (pk=%s)", bom.name, bom.pk)
            messages.success(request, f"BOM '{bom.name}' updated.")
            return redirect("catalog:bom_detail", pk=bom.pk)
    else:
        form = BOMForm(instance=bom)

    return render(request, "catalog/bom_form.html", {
        "form": form,
        "bom": bom,
        "item_form": BOMItemForm(bom=bom),
        "title": "Edit BOM",
    })


def bom_delete(request, pk):
    """Delete a BOM."""
    bom = get_object_or_404(BOM, pk=pk)
    if request.method == "POST":
        name = bom.name
        bom.delete()
        logger.info("[BOM] Deleted '%s'", name)
        messages.success(request, f"BOM '{name}' deleted.")
        return redirect("catalog:bom_list")
    return render(request, "catalog/bom_confirm_delete.html", {"bom": bom})


def bom_item_detail(request, pk, item_pk):
    """Read-only view of a single BOM item with an Edit button."""
    bom = get_object_or_404(BOM.objects.select_related("unit", "application"), pk=pk)
    item = get_object_or_404(
        BOMItem.objects.select_related("part__unit__unit_type"),
        pk=item_pk,
        bom=bom,
    )
    return render(request, "catalog/bom_item_detail.html", {
        "bom": bom,
        "item": item,
    })


def bom_item_add(request, pk):
    """Add a part to a BOM (create BOMItem)."""
    bom = get_object_or_404(BOM, pk=pk)
    if request.method == "POST":
        form = BOMItemForm(request.POST, bom=bom)
        if form.is_valid():
            item = form.save(commit=False)
            item.bom = bom
            item.save()
            part_label = item.part.part_number or item.part.yt_number or item.part.part_name or "Part"
            logger.info("[BOM] Added part %s to %s", part_label, bom.name)
            messages.success(request, f"Part '{part_label}' added to BOM.")
            return redirect("catalog:bom_edit", pk=bom.pk)
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
            logger.info("[BOM] Updated item in %s", bom.name)
            messages.success(request, f"BOM item updated.")
            return redirect("catalog:bom_edit", pk=bom.pk)
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
        part_label = item.part.part_number or item.part.yt_number or item.part.part_name or "Part"
        item.delete()
        logger.info("[BOM] Removed part %s from %s", part_label, bom.name)
        messages.success(request, f"Part '{part_label}' removed from BOM.")
    return redirect("catalog:bom_edit", pk=bom.pk)


# ---------------------------------------------------------------------------
# BOM AJAX API endpoints (for modal-based add-part flow)
# ---------------------------------------------------------------------------

def bom_save_api(request):
    """Create or update a BOM via AJAX, return JSON {ok, pk, name, errors}."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "errors": {"__all__": ["POST required."]}}, status=405)

    pk = request.POST.get("bom_pk")
    if pk:
        bom = get_object_or_404(BOM, pk=pk)
        form = BOMForm(request.POST, instance=bom)
    else:
        form = BOMForm(request.POST)

    if form.is_valid():
        bom = form.save()
        logger.info("[BOM] Saved '%s' (pk=%s) via API", bom.name, bom.pk)
        return JsonResponse({"ok": True, "pk": bom.pk, "name": bom.name})

    errors = {f: e.get_json_data() for f, e in form.errors.items()}
    return JsonResponse({"ok": False, "errors": errors}, status=400)


def bom_item_add_api(request, pk):
    """Add a BOM item via AJAX, return JSON with the new row data."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "errors": {"__all__": ["POST required."]}}, status=405)

    bom = get_object_or_404(BOM, pk=pk)
    form = BOMItemForm(request.POST, bom=bom)
    if form.is_valid():
        item = form.save(commit=False)
        item.bom = bom
        item.save()
        part = item.part
        part_label = part.part_number or part.yt_number or part.part_name or "Part"
        logger.info("[BOM] Added part %s to %s via API", part_label, bom.name)
        return JsonResponse({
            "ok": True,
            "item": {
                "pk": item.pk,
                "yt_number": item.yt_number or (part.yt_number if part else ""),
                "part_number": part.part_number or "" if part else "",
                "j_and_n": item.j_and_n or (part.j_and_n if part else ""),
                "oem_number": item.oem_number or (part.oem_number if part else ""),
                "description": item.description or (part.part_name if part else ""),
                "notes": item.notes or "",
                "unit_qty": item.unit_qty,
                "stock_qty": item.stock_qty or "",
                "bin_number": item.bin_number or "",
                "part_pk": part.pk if part else None,
                "edit_url": reverse("catalog:bom_item_edit", args=[bom.pk, item.pk]),
            },
        })

    errors = {f: e.get_json_data() for f, e in form.errors.items()}
    return JsonResponse({"ok": False, "errors": errors}, status=400)


def bom_item_delete_api(request, pk, item_pk):
    """Delete a BOM item via AJAX."""
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    bom = get_object_or_404(BOM, pk=pk)
    item = get_object_or_404(BOMItem, pk=item_pk, bom=bom)
    part_label = item.part.part_number or item.part.yt_number or item.part.part_name or "Part"
    item.delete()
    logger.info("[BOM] Removed part %s from %s via API", part_label, bom.name)
    return JsonResponse({"ok": True})


def _get_deep_match_label(part, q_lower: str, ic_map: dict, sup_map: dict) -> str:
    """Return the value that matched this part in a deep (tier-2) search."""
    q = q_lower
    if part.manufacturer_number and q in part.manufacturer_number.lower():
        return part.manufacturer_number
    if part.part_name and q in part.part_name.lower():
        return part.part_name[:50]
    if part.description and q in part.description.lower():
        text = part.description
        idx = text.lower().index(q)
        start = max(0, idx - 12)
        end = min(len(text), idx + len(q) + 12)
        snippet = text[start:end].strip()
        return f"\u2026{snippet}\u2026"
    if part.voltage and q in part.voltage.lower():
        return f"Voltage: {part.voltage}"
    for ic_num in ic_map.get(part.pk, []):
        if ic_num and q in ic_num.lower():
            return f"Interchange: {ic_num}"
    for old_num in sup_map.get(part.pk, []):
        if old_num and q in old_num.lower():
            return f"Supersedes: {old_num}"
    return q


def part_list(request):
    """List parts with search, category filter, Part Number, YT Number, J&N, OEM #, Description, In Stock."""
    base_qs = Part.objects.select_related("unit").filter(is_active=True).annotate(
        _sort_yt=NullIf("yt_number", Value("")),
        _sort_pn=NullIf("part_number", Value("")),
    ).order_by(
        F("_sort_yt").asc(nulls_last=True),
        F("_sort_pn").asc(nulls_last=True),
    )

    # --- Category filter ---
    filter_category = request.GET.get("category", "").strip()
    if filter_category:
        base_qs = base_qs.filter(category=filter_category)

    # --- Voltage filter ---
    filter_voltage = request.GET.get("voltage", "").strip()
    if filter_voltage:
        base_qs = base_qs.filter(voltage=filter_voltage)

    # --- Two-tier search ---
    # Tier 1 (direct): matches on the four primary number fields visible in the table.
    #   → Match column stays blank; these bypass the deep search entirely.
    # Tier 2 (deep): only reached when tier-1 yields nothing.
    #   → searches manufacturer number, descriptions, interchange & superseding numbers;
    #     Match column shows the value that caused each hit.
    q = request.GET.get("q", "").strip()
    match_map: dict[int, str] = {}
    search_tier = 0  # 0 = no query, 1 = direct, 2 = deep

    if q:
        direct_qs = base_qs.filter(
            Q(manufacturer_number__icontains=q)
            | Q(yt_number__icontains=q)
            | Q(j_and_n__icontains=q)
            | Q(oem_number__icontains=q)
        )
        if direct_qs[:1].exists():
            parts = direct_qs
            search_tier = 1
        else:
            deep_qs = base_qs.filter(
                Q(part_number__icontains=q)
                | Q(part_name__icontains=q)
                | Q(description__icontains=q)
                | Q(voltage__icontains=q)
                | Q(unit__unit_number__icontains=q)
                | Q(units__unit_number__icontains=q)
                | Q(part_interchanges__interchange_number__icontains=q)
                | Q(interchanged_by_parts__interchange_number__icontains=q)
                | Q(supersedings__old_part_number__icontains=q)
            ).distinct()
            parts = deep_qs
            search_tier = 2
    else:
        parts = base_qs

    # --- Build category choices for dropdown (cached 5 min) ---
    category_choices = cache.get_or_set("part_category_choices",
        lambda: list(Part.objects.filter(is_active=True).exclude(category="").values_list("category", flat=True).distinct().order_by("category")),
        300)

    # --- Build voltage choices for dropdown (cached 5 min) ---
    voltage_choices = cache.get_or_set("part_voltage_choices",
        lambda: list(Part.objects.filter(is_active=True).exclude(voltage="").values_list("voltage", flat=True).distinct().order_by("voltage")),
        300)

    total_count = parts.count()
    try:
        per_page = min(int(request.GET.get("per_page", 50)), 100)
    except (ValueError, TypeError):
        per_page = 50
    paginator = Paginator(parts, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Build (part, match_label) pairs for the current page.
    # match_label is non-empty only for tier-2 deep results.
    parts_with_match: list[tuple] = []
    if q and search_tier == 2:
        q_lower = q.lower()
        page_pks = [p.pk for p in page_obj]

        ic_map: dict[int, list[str]] = {}
        for ic in PartInterchange.objects.filter(
            Q(part_id__in=page_pks) | Q(interchange_part_id__in=page_pks)
        ).values("part_id", "interchange_part_id", "interchange_number"):
            for pk in (ic["part_id"], ic["interchange_part_id"]):
                if pk in page_pks:
                    ic_map.setdefault(pk, []).append(ic["interchange_number"] or "")

        sup_map: dict[int, list[str]] = {}
        for sup in PartSuperseding.objects.filter(
            part_id__in=page_pks
        ).values("part_id", "old_part_number"):
            sup_map.setdefault(sup["part_id"], []).append(sup["old_part_number"] or "")

        for part in page_obj:
            label = _get_deep_match_label(part, q_lower, ic_map, sup_map)
            parts_with_match.append((part, label))
    else:
        parts_with_match = [(part, "") for part in page_obj]

    context = {
        "parts": page_obj,
        "parts_with_match": parts_with_match,
        "page_obj": page_obj,
        "total_count": total_count,
        "per_page": per_page,
        "q": q,
        "search_tier": search_tier,
        "filter_category": filter_category,
        "category_choices": category_choices,
        "filter_voltage": filter_voltage,
        "voltage_choices": voltage_choices,
    }
    if request.GET.get("print") == "1":
        return render(request, "catalog/part_list_print.html", context)
    return render(request, "catalog/part_list.html", context)


def part_detail(request, pk):
    """Show details for a single part (minimal for 4.2; enhanced in 4.5)."""
    part = get_object_or_404(
        Part.objects.select_related("unit").prefetch_related("images", "units"),
        pk=pk,
    )

    ALWAYS_VISIBLE = {
        "part_number", "part_name", "manufacturer_number", "yt_number",
        "j_and_n", "oem_number", "voltage", "type", "oem", "primary_vendor",
    }
    spec_display = []
    if part.specifications:
        category_fields = _get_category_field_defs()
        field_defs = category_fields.get(part.category, [])
        label_map = {fd["name"]: fd for fd in field_defs}
        for key, val in part.specifications.items():
            if key in ALWAYS_VISIBLE:
                continue
            fd = label_map.get(key)
            label = fd["label"] if fd else key
            if fd and fd["type"] == "checkbox":
                display_val = "Yes" if val else "No"
            else:
                display_val = val if val else ""
            if display_val:
                spec_display.append({"label": label, "value": display_val})

    # Part compatibility relationships
    substitutes_qs = PartSubstitute.objects.filter(
        Q(part=part) | Q(substitute_part=part)
    ).select_related("part", "substitute_part")
    part_substitutes = []
    for ps in substitutes_qs:
        other = ps.substitute_part if ps.part_id == part.pk else ps.part
        part_substitutes.append({"ref": ps, "part": other})

    # Sort: J&N first, then alphabetically by source, then by number
    interchanges_qs = PartInterchange.objects.filter(
        Q(part=part) | Q(interchange_part=part)
    ).select_related("part", "interchange_part").annotate(
        _is_jn=Case(
            When(source_name__istartswith="J&N", then=Value(0)),
            default=Value(1),
        ),
    ).order_by("_is_jn", "source_name", "interchange_number")
    part_interchanges = []
    for pi in interchanges_qs:
        other = pi.interchange_part if pi.part_id == part.pk else pi.part
        part_interchanges.append({"ref": pi, "part": other})

    part_supersedings = PartSuperseding.objects.filter(
        part=part
    ).select_related("old_part")

    linked_units = part.units.all().order_by("unit_number")
    linked_unit_count = linked_units.count()

    return render(request, "catalog/part_detail.html", {
        "part": part,
        "part_display_number": _part_display_number(part),
        "spec_display": spec_display,
        "part_substitutes": part_substitutes,
        "part_interchanges": part_interchanges,
        "part_supersedings": part_supersedings,
        "linked_units": linked_units,
        "linked_unit_count": linked_unit_count,
    })


def part_category_fields_api(request, category):
    """Return JSON field definitions for a given part category (AJAX)."""
    from django.http import JsonResponse

    category_fields = _get_category_field_defs()
    fields = category_fields.get(category, [])
    return JsonResponse({"fields": fields})


def part_category_custom_field_add_api(request):
    """AJAX endpoint to add a custom field to an existing PartCategory."""
    from django.http import JsonResponse

    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    category_name = request.POST.get("category_name", "").strip()
    field_label = request.POST.get("field_label", "").strip()
    field_name = request.POST.get("field_name", "").strip()
    if not category_name or not field_label or not field_name:
        return JsonResponse({"error": "category_name, field_label, and field_name are required."}, status=400)

    cat = PartCategory.objects.filter(name=category_name).first()
    if not cat:
        return JsonResponse({"error": f"Category '{category_name}' not found."}, status=404)
    if cat.fields.filter(field_name=field_name).exists():
        return JsonResponse({"error": f"Field '{field_name}' already exists."}, status=400)

    max_order = cat.fields.aggregate(m=Max("display_order"))["m"] or 0
    PartCategoryField.objects.create(
        category=cat, field_name=field_name, field_label=field_label, display_order=max_order + 1,
    )
    return JsonResponse({"ok": True, "field_name": field_name, "field_label": field_label})


def part_create(request):
    """Create a new part."""
    import json
    from .models import PartImage

    if request.method == "POST":
        form = PartForm(request.POST, request.FILES)
        if form.is_valid():
            part = form.save()
            manual_unit = request.POST.get("manual_unit_number", "").strip()
            if manual_unit:
                unit_obj = Unit.objects.filter(unit_number__iexact=manual_unit).first()
                if not unit_obj:
                    unit_obj = Unit.objects.create(unit_number=manual_unit)
                part.units.add(unit_obj)
            for f in request.FILES.getlist("part_images"):
                PartImage.objects.create(part=part, image=f)
            logger.info("[Part] Created '%s' (pk=%s)", _part_display_number(part), part.pk)
            messages.success(request, f"Part '{_part_display_number(part)}' created.")
            return redirect("catalog:part_detail", pk=part.pk)
    else:
        form = PartForm()

    from invoicing.models import CompanySettings
    category_fields = _get_category_field_defs()
    category_pk_map = {c.name: c.pk for c in PartCategory.objects.all()}
    return render(request, "catalog/part_form.html", {
        "form": form,
        "part": None,
        "title": "Add New Part",
        "category_fields_json": json.dumps(category_fields),
        "existing_specs_json": "{}",
        "category_pk_map_json": json.dumps(category_pk_map),
        "pricing_method": CompanySettings.get().pricing_method,
    })


def part_edit(request, pk):
    """Edit a part."""
    import json
    from .models import PartImage

    part = get_object_or_404(Part, pk=pk)
    if request.method == "POST":
        form = PartForm(request.POST, request.FILES, instance=part)
        if form.is_valid():
            form.save()
            manual_unit = request.POST.get("manual_unit_number", "").strip()
            if manual_unit:
                unit_obj = Unit.objects.filter(unit_number__iexact=manual_unit).first()
                if not unit_obj:
                    unit_obj = Unit.objects.create(unit_number=manual_unit)
                part.units.add(unit_obj)
            for f in request.FILES.getlist("part_images"):
                PartImage.objects.create(part=part, image=f)
            delete_ids = request.POST.getlist("delete_image")
            if delete_ids:
                part.images.filter(pk__in=delete_ids).delete()
            logger.info("[Part] Updated '%s' (pk=%s)", _part_display_number(part), part.pk)
            messages.success(request, f"Part '{_part_display_number(part)}' updated.")
            return redirect("catalog:part_detail", pk=part.pk)
    else:
        form = PartForm(instance=part)

    from invoicing.models import CompanySettings
    category_fields = _get_category_field_defs()
    existing_specs = part.specifications or {}
    category_pk_map = {c.name: c.pk for c in PartCategory.objects.all()}
    return render(request, "catalog/part_form.html", {
        "form": form,
        "part": part,
        "title": "Edit Part",
        "category_fields_json": json.dumps(category_fields),
        "existing_specs_json": json.dumps(existing_specs),
        "category_pk_map_json": json.dumps(category_pk_map),
        "pricing_method": CompanySettings.get().pricing_method,
    })


def part_delete(request, pk):
    """Delete a part."""
    part = get_object_or_404(Part, pk=pk)
    if request.method == "POST":
        part_number = _part_display_number(part)
        part.delete()
        logger.info("[Part] Deleted '%s'", part_number)
        messages.success(request, f"Part '{part_number}' deleted.")
        return redirect("catalog:part_list")
    return redirect("catalog:part_edit", pk=pk)


# ---------------------------------------------------------------------------
# Part Compatibility (substitute / interchange / superseding)
# ---------------------------------------------------------------------------
def part_substitute_add(request, pk):
    """Add a substitute link to a part."""
    part = get_object_or_404(Part, pk=pk)
    if request.method == "POST":
        form = PartSubstituteForm(request.POST, part=part)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.part = part
            obj.save()
            label = obj.substitute_part.part_number if obj.substitute_part else obj.substitute_number
            logger.info("[Part] Added substitute '%s' to %s", label, part)
            messages.success(request, f"Substitute '{label}' added.")
            return redirect("catalog:part_detail", pk=part.pk)
    else:
        form = PartSubstituteForm(part=part)
    return render(request, "catalog/part_substitute_add.html", {"form": form, "part": part})


def part_substitute_delete(request, pk, sub_pk):
    """Delete a substitute link from a part."""
    part = get_object_or_404(Part, pk=pk)
    obj = get_object_or_404(PartSubstitute, pk=sub_pk)
    if request.method == "POST":
        obj.delete()
        logger.info("[Part] Removed substitute from %s", part)
        messages.success(request, "Substitute removed.")
    return redirect("catalog:part_detail", pk=part.pk)


def part_interchange_add(request, pk):
    """Add an interchange link to a part."""
    part = get_object_or_404(Part, pk=pk)
    if request.method == "POST":
        form = PartInterchangeForm(request.POST, part=part)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.part = part
            obj.save()
            label = _part_display_number(obj.interchange_part) if obj.interchange_part else obj.interchange_number
            logger.info("[Part] Added interchange '%s' to %s", label, part)
            messages.success(request, f"Interchange '{label}' added.")
            return redirect("catalog:part_detail", pk=part.pk)
    else:
        form = PartInterchangeForm(part=part)
    return render(request, "catalog/part_interchange_add.html", {
        "form": form,
        "part": part,
        "part_display_number": _part_display_number(part),
    })


def part_interchange_edit(request, pk, int_pk):
    """Edit an interchange line (reference, source, notes)."""
    part = get_object_or_404(Part, pk=pk)
    obj = get_object_or_404(PartInterchange, pk=int_pk, part=part)
    if request.method == "POST":
        form = PartInterchangeForm(request.POST, part=part, instance=obj)
        if form.is_valid():
            saved = form.save()
            label = (
                _part_display_number(saved.interchange_part)
                if saved.interchange_part
                else saved.interchange_number
            )
            logger.info("[Part] Updated interchange '%s'", label)
            messages.success(request, f"Interchange '{label}' updated.")
            return redirect("catalog:part_detail", pk=part.pk)
    else:
        form = PartInterchangeForm(part=part, instance=obj)
    return render(request, "catalog/part_interchange_edit.html", {
        "form": form,
        "part": part,
        "interchange": obj,
        "part_display_number": _part_display_number(part),
    })


def part_interchange_delete(request, pk, int_pk):
    """Delete an interchange link from a part."""
    part = get_object_or_404(Part, pk=pk)
    obj = get_object_or_404(PartInterchange, pk=int_pk, part=part)
    if request.method == "POST":
        obj.delete()
        logger.info("[Part] Removed interchange from %s", part)
        messages.success(request, "Interchange removed.")
    return redirect("catalog:part_detail", pk=part.pk)


def part_superseding_add(request, pk):
    """Add a superseding (old part number) to a part."""
    part = get_object_or_404(Part, pk=pk)
    if request.method == "POST":
        form = PartSupersedingForm(request.POST, part=part)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.part = part
            obj.save()
            logger.info("[Part] Added superseding '%s' to %s", obj.old_part_number, part)
            messages.success(request, f"Superseded part '{obj.old_part_number}' added.")
            return redirect("catalog:part_detail", pk=part.pk)
    else:
        form = PartSupersedingForm(part=part)
    return render(request, "catalog/part_superseding_add.html", {"form": form, "part": part})


def part_superseding_delete(request, pk, sup_pk):
    """Delete a superseding entry from a part."""
    part = get_object_or_404(Part, pk=pk)
    obj = get_object_or_404(PartSuperseding, pk=sup_pk)
    if request.method == "POST":
        obj.delete()
        logger.info("[Part] Removed superseding from %s", part)
        messages.success(request, "Superseding entry removed.")
    return redirect("catalog:part_detail", pk=part.pk)


# ---------------------------------------------------------------------------
# Part Category Settings (user-managed categories & fields)
# ---------------------------------------------------------------------------
def part_category_list(request):
    """List all part categories and their fields."""
    from .models import PartCategory

    categories = PartCategory.objects.prefetch_related("fields").all()
    return render(request, "catalog/part_category_list.html", {"categories": categories})


def part_category_detail(request, pk):
    """View a part category and its fields (read-only)."""
    from .models import PartCategory

    cat = get_object_or_404(PartCategory.objects.prefetch_related("fields"), pk=pk)
    return render(request, "catalog/part_category_detail.html", {"category": cat})


def part_category_create(request):
    """Create a new part category with its fields."""
    from .models import PartCategory, PartCategoryField

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            messages.error(request, "Category name is required.")
            return redirect("catalog:part_category_create")
        if PartCategory.objects.filter(name=name).exists():
            messages.error(request, f"Category '{name}' already exists.")
            return redirect("catalog:part_category_create")

        cat = PartCategory.objects.create(name=name)
        field_names = request.POST.getlist("field_name")
        field_labels = request.POST.getlist("field_label")
        for i, (fname, flabel) in enumerate(zip(field_names, field_labels)):
            fname, flabel = fname.strip(), flabel.strip()
            if fname and flabel:
                PartCategoryField.objects.create(
                    category=cat, field_name=fname, field_label=flabel, display_order=i,
                )
        logger.info("[PartCategory] Created '%s'", name)
        messages.success(request, f"Category '{name}' created.")
        return redirect("catalog:part_category_list")

    default_fields = [{"field_label": fl, "field_name": fn} for fn, fl in PART_DEFAULT_FIELDS]
    return render(request, "catalog/part_category_form.html", {
        "title": "Add New Category",
        "category": None,
        "fields": default_fields,
        "default_field_names_json": json.dumps([fn for fn, _ in PART_DEFAULT_FIELDS]),
    })


def part_category_edit(request, pk):
    """Edit an existing part category and its fields."""
    from .models import PartCategory, PartCategoryField

    cat = get_object_or_404(PartCategory, pk=pk)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            messages.error(request, "Category name is required.")
            return redirect("catalog:part_category_edit", pk=pk)
        if PartCategory.objects.filter(name=name).exclude(pk=pk).exists():
            messages.error(request, f"Category '{name}' already exists.")
            return redirect("catalog:part_category_edit", pk=pk)

        cat.name = name
        cat.save()

        cat.fields.all().delete()
        field_names = request.POST.getlist("field_name")
        field_labels = request.POST.getlist("field_label")
        for i, (fname, flabel) in enumerate(zip(field_names, field_labels)):
            fname, flabel = fname.strip(), flabel.strip()
            if fname and flabel:
                PartCategoryField.objects.create(
                    category=cat, field_name=fname, field_label=flabel, display_order=i,
                )
        logger.info("[PartCategory] Updated '%s'", name)
        messages.success(request, f"Category '{name}' updated.")
        return redirect("catalog:part_category_list")

    existing_fields = list(
        cat.fields.order_by("display_order").values("field_name", "field_label")
    )
    existing_names = {f["field_name"] for f in existing_fields}

    # Build merged list: defaults first (locked), then any extra custom fields.
    # If a default was previously saved with a customised label, use that label.
    db_by_name = {f["field_name"]: f for f in existing_fields}
    merged = []
    for fn, fl in PART_DEFAULT_FIELDS:
        merged.append({
            "field_name": fn,
            "field_label": db_by_name[fn]["field_label"] if fn in db_by_name else fl,
        })
    for f in existing_fields:
        if f["field_name"] not in {fn for fn, _ in PART_DEFAULT_FIELDS}:
            merged.append(f)

    return render(request, "catalog/part_category_form.html", {
        "title": f"Edit Category: {cat.name}",
        "category": cat,
        "fields": merged,
        "default_field_names_json": json.dumps([fn for fn, _ in PART_DEFAULT_FIELDS]),
    })


def part_category_delete(request, pk):
    """Delete a part category."""
    from .models import PartCategory

    cat = get_object_or_404(PartCategory, pk=pk)
    if request.method == "POST":
        cat_name = cat.name
        cat.delete()
        logger.info("[PartCategory] Deleted '%s'", cat_name)
        messages.success(request, f"Category '{cat_name}' deleted.")
        return redirect("catalog:part_category_list")
    return redirect("catalog:part_category_edit", pk=pk)


# ---------------------------------------------------------------------------
# Part CSV column header -> Part model field mapping
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Part CSV upload — dynamic field mapping
# ---------------------------------------------------------------------------
_PART_SKIP_FIELDS = {
    "id", "specifications", "image", "unit", "units",
    "is_active", "created_at", "updated_at",
    "has_picture", "has_interchange", "has_superseding",
}
_PART_DECIMAL_FIELDS = {"price", "cost_price"}
_PART_INT_FIELDS = {"stock_quantity", "reorder_qty"}

def _get_part_model_fields():
    """Return set of writable field names on Part."""
    return {
        f.name for f in Part._meta.get_fields()
        if hasattr(f, "column") and f.name not in _PART_SKIP_FIELDS
    }

# Aliases so common CSV header variations map to the correct model fields.
_PART_CSV_ALIASES = {
    "key": "manufacturer_number",
    "part_#": "part_number",
    "part_no": "part_number",
    "part_no.": "part_number",
    "part_num": "part_number",
    "partno": "part_number",
    "partnumber": "part_number",
    "item_number": "part_number",
    "item_#": "part_number",
    "item_no": "part_number",
    "item_num": "part_number",
    "itemnumber": "part_number",
    "number": "part_number",
    "pn": "part_number",
    "p/n": "part_number",
    "p_n": "part_number",
    "sku": "part_number",
    "manufacturer_#": "manufacturer_number",
    "mfr_number": "manufacturer_number",
    "mfr_#": "manufacturer_number",
    "mfr_no": "manufacturer_number",
    "mfr_no.": "manufacturer_number",
    "manufacturer_no": "manufacturer_number",
    "manufacturer": "manufacturer_number",
    "manufacture": "oem",
    "oem_#": "oem_number",
    "oem_no": "oem_number",
    "yt_#": "yt_number",
    "yt_no": "yt_number",
    "j_&_n": "j_and_n",
    "j&n": "j_and_n",
    "j&n_number": "j_and_n",
    "j&n_no": "j_and_n",
    "j&n_#": "j_and_n",
    "jn": "j_and_n",
    "j_n": "j_and_n",
    "jn_number": "j_and_n",
    "unit_type": "category",
    "part_type": "type",
    "part_category": "category",
    "vendor": "primary_vendor",
    "desc": "description",
    "name": "part_name",
    "unit_#": "unit_number",
    "unit_no": "unit_number",
}


def _normalise_csv_header(raw_header):
    """Normalise a CSV header to a model field name via aliases."""
    norm = raw_header.strip().lower().replace(" ", "_")
    return _PART_CSV_ALIASES.get(norm, norm)


def _parse_part_csv(decoded_text):
    """Parse CSV text and return (columns, rows, warnings, header_warning) for preview."""
    reader = csv.DictReader(io.StringIO(decoded_text))
    columns_raw = [c.strip() for c in (reader.fieldnames or []) if c and c.strip()]
    columns = [_normalise_csv_header(c) for c in columns_raw]

    has_part_number_col = "part_number" in columns
    header_warning = ""
    if not has_part_number_col:
        header_warning = (
            f'No "Part Number" (part_number) column detected. '
            f"Your CSV columns are: {', '.join(columns_raw)}. "
            f"Parts will be created without a Part Number."
        )

    rows = []
    warnings = []
    for row_num, raw_row in enumerate(reader, start=2):
        row = {}
        for orig_col, norm_col in zip(columns_raw, columns):
            row[norm_col] = (raw_row.get(orig_col) or "").strip()
        pn = row.get("part_number", "").strip()
        if pn:
            existing = Part.objects.filter(part_number=pn).first()
            if existing:
                warnings.append((row_num, f"Part {pn} already exists — will be updated."))
        elif has_part_number_col:
            warnings.append((row_num, "Empty Part Number — part will be created without one."))
        rows.append(row)
    return columns, rows, warnings, header_warning


def part_upload_csv(request):
    """Step 1: Upload CSV. Step 2: Preview & edit. Step 3: Confirm import with report."""
    step = request.POST.get("step", "upload")

    # ---- Step 3: Confirm import ----
    if request.method == "POST" and step == "confirm":
        columns_json = request.POST.get("columns", "[]")
        columns = json.loads(columns_json)
        row_count = int(request.POST.get("row_count", 0))
        model_fields = _get_part_model_fields()
        logger.info("[Part CSV Import] Confirm import — %d rows submitted", row_count)

        report = []
        created = updated = skipped = 0

        for i in range(row_count):
            row = {}
            for col in columns:
                row[col] = request.POST.get(f"row_{i}_{col}", "").strip()

            pn = row.get("part_number", "").strip() or None

            defaults = {}
            specs = {}
            for col, val in row.items():
                if not val or col in ("part_number", "unit_number"):
                    continue
                field_name = _PART_CSV_ALIASES.get(col, col)
                if field_name in model_fields:
                    defaults[field_name] = val
                else:
                    specs[field_name] = val

            for dec_field in _PART_DECIMAL_FIELDS:
                if dec_field in defaults:
                    try:
                        defaults[dec_field] = float(defaults[dec_field]) if defaults[dec_field] else None
                    except (ValueError, TypeError):
                        defaults[dec_field] = None

            for int_field in _PART_INT_FIELDS:
                if int_field in defaults:
                    try:
                        defaults[int_field] = int(defaults[int_field]) if defaults[int_field] else 0
                    except (ValueError, TypeError):
                        defaults[int_field] = 0

            unit_number = row.get("unit_number", "").strip()
            unit_linked = ""
            if unit_number:
                unit = Unit.objects.filter(unit_number=unit_number).first()
                if unit:
                    defaults["unit"] = unit
                    unit_linked = unit_number

            if specs:
                if pn:
                    existing_specs = Part.objects.filter(part_number=pn).values_list("specifications", flat=True).first()
                    merged = dict(existing_specs or {})
                    merged.update(specs)
                    defaults["specifications"] = merged
                else:
                    defaults["specifications"] = specs

            try:
                if pn:
                    obj, was_created = Part.objects.update_or_create(
                        part_number=pn, defaults=defaults
                    )
                else:
                    obj = Part.objects.create(part_number=None, **defaults)
                    was_created = True
                action = "created" if was_created else "updated"
                if was_created:
                    created += 1
                else:
                    updated += 1
                detail_fields = {k: v for k, v in row.items() if v and k != "part_number"}
                if unit_linked:
                    detail_fields["unit_linked"] = unit_linked
                if specs:
                    detail_fields["custom_specs"] = specs
                report.append({"row": i + 2, "part_number": pn, "action": action,
                               "reason": "", "details": detail_fields, "pk": obj.pk})
            except Exception as e:
                report.append({"row": i + 2, "part_number": pn, "action": "error",
                               "reason": str(e), "details": {}})
                skipped += 1

        logger.info("[Part CSV Import] Finished: %d created, %d updated, %d skipped",
                    created, updated, skipped)
        return render(request, "catalog/part_upload_csv_report.html", {
            "report": report,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "total": row_count,
        })

    # ---- Step 2: Preview (file just uploaded) ----
    if request.method == "POST" and step == "upload":
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "Please select a CSV file.")
            return redirect("catalog:part_upload_csv")
        if not csv_file.name.endswith(".csv"):
            messages.error(request, "File must be a .csv file.")
            return redirect("catalog:part_upload_csv")
        try:
            decoded = csv_file.read().decode("utf-8-sig")
            columns, rows, warnings, header_warning = _parse_part_csv(decoded)
            warnings_by_row = {w[0]: w[1] for w in warnings}
            return render(request, "catalog/part_upload_csv_preview.html", {
                "columns": columns,
                "columns_json": json.dumps(columns),
                "rows": rows,
                "warnings_by_row": warnings_by_row,
                "header_warning": header_warning,
                "filename": csv_file.name,
            })
        except Exception as e:
            messages.error(request, f"Error reading CSV: {e}")
            return redirect("catalog:part_upload_csv")

    # ---- Step 1: Show upload form ----
    model_fields = sorted(_get_part_model_fields())
    category_field_defs = _get_category_field_defs()
    categories = list(PartCategory.objects.values_list("name", flat=True).order_by("name"))
    return render(request, "catalog/part_upload_csv.html", {
        "model_fields": model_fields,
        "categories": categories,
        "category_field_defs_json": json.dumps(category_field_defs),
    })


# Human-friendly labels for CSV template headers
_PART_CSV_LABELS = {
    "part_number": "Part Number",
    "part_name": "Part Name",
    "unit_number": "Unit Number",
    "category": "Category",
    "manufacturer_number": "Manufacturer Number",
    "yt_number": "YT Number",
    "j_and_n": "J&N Number",
    "oem_number": "OEM #",
    "oem": "OEM",
    "type": "Type",
    "voltage": "Voltage",
    "primary_vendor": "Primary Vendor",
    "description": "Description",
    "price": "Sell Price",
    "cost_price": "Cost Price",
    "stock_quantity": "Stock Quantity",
    "reorder_qty": "Reorder Threshold",
    "bin_number": "Bin Location",
    "item_no": "Item No",
    "oem_type": "OEM Type",
    "item_typ": "Item Type",
    "catalog": "Catalog",
    "plug_id": "Plug ID",
    "foot_notes": "Footnotes",
}

_PART_CSV_TEMPLATE_COLUMNS = [
    "category", "part_number", "part_name", "unit_number",
    "manufacturer_number", "yt_number", "j_and_n", "oem_number",
    "oem", "type", "voltage", "primary_vendor",
    "description", "price", "cost_price",
    "stock_quantity", "bin_number",
]


def part_download_csv_template(request):
    """Download a blank CSV template for part imports.

    No category selected  → includes ALL custom fields from every category (master template).
    Specific category     → includes only that category's custom fields.
    """
    from django.http import HttpResponse

    selected_category = request.GET.get("category", "").strip()
    columns = list(_PART_CSV_TEMPLATE_COLUMNS)
    cat_defs = _get_category_field_defs()
    default_names = set(columns)

    if selected_category:
        for field_def in cat_defs.get(selected_category, []):
            if field_def["name"] not in default_names:
                columns.append(field_def["name"])
    else:
        seen = set(default_names)
        for cat_fields in cat_defs.values():
            for field_def in cat_fields:
                if field_def["name"] not in seen:
                    columns.append(field_def["name"])
                    seen.add(field_def["name"])

    headers = [_PART_CSV_LABELS.get(c, c.replace("_", " ").title()) for c in columns]

    response = HttpResponse(content_type="text/csv")
    suffix = f"_{selected_category.replace(' ', '_')}" if selected_category else "_all_categories"
    response["Content-Disposition"] = f'attachment; filename="part_import_template{suffix}.csv"'

    writer = csv.writer(response)
    writer.writerow(headers)
    return response


def _unit_char_text_field_names():
    """CharField/TextField names on Unit for global number / text lookup."""
    skip = {"unit_image", "plug_image"}
    names = []
    for f in Unit._meta.get_fields():
        if f.name in skip or not hasattr(f, "get_internal_type"):
            continue
        if f.get_internal_type() in ("CharField", "TextField"):
            names.append(f.name)
    return names


def _part_related_number_q(val: str) -> Q:
    """Match parts via interchange, superseding, substitute, BOM lines, or linked units."""
    if not val:
        return Q()
    return (
        Q(part_interchanges__interchange_number__icontains=val)
        | Q(part_interchanges__source_name__icontains=val)
        | Q(part_interchanges__notes__icontains=val)
        | Q(part_interchanges__interchange_part__part_number__icontains=val)
        | Q(part_interchanges__interchange_part__yt_number__icontains=val)
        | Q(supersedings__old_part_number__icontains=val)
        | Q(supersedings__notes__icontains=val)
        | Q(supersedings__old_part__part_number__icontains=val)
        | Q(supersedings__old_part__yt_number__icontains=val)
        | Q(part_substitutes__substitute_number__icontains=val)
        | Q(part_substitutes__notes__icontains=val)
        | Q(part_substitutes__substitute_part__part_number__icontains=val)
        | Q(part_substitutes__substitute_part__yt_number__icontains=val)
        | Q(bom_items__oem_number__icontains=val)
        | Q(bom_items__j_and_n__icontains=val)
        | Q(bom_items__yt_number__icontains=val)
        | Q(bom_items__description__icontains=val)
        | Q(bom_items__notes__icontains=val)
        | Q(bom_items__bin_number__icontains=val)
        | Q(unit__unit_number__icontains=val)
        | Q(unit__yt_number__icontains=val)
        | Q(units__unit_number__icontains=val)
        | Q(units__yt_number__icontains=val)
    )


def _global_reference_search_hits(q_raw: str, limit: int = 200) -> list[dict]:
    """
    Search every major catalog number field: units, parts (incl. interchange/supersede/sub/BOM),
    applications, unit cross-refs, substitutes, gear reductions, application specs.

    Queries are ordered by relevance and short-circuit once the limit is reached.
    """
    q = (q_raw or "").strip()
    if not q:
        return []

    per_q = min(40, max(15, limit // 6))
    hits: list[dict] = []
    dup: set[tuple[str, int]] = set()

    def add(kind: str, pk: int, row: dict) -> None:
        key = (kind, pk)
        if key in dup or len(hits) >= limit:
            return
        dup.add(key)
        hits.append(row)

    def full():
        return len(hits) >= limit

    # 1. Cross-references (most relevant for "cross ref" search)
    for cr in CrossReference.objects.filter(
        Q(cross_ref_number__icontains=q)
        | Q(interchange_type__icontains=q)
    ).select_related("unit", "unit__unit_type").only(
        "id", "cross_ref_number", "interchange_type",
        "unit__id", "unit__unit_number", "unit__yt_number", "unit__oem",
        "unit__unit_type__id", "unit__unit_type__name",
    )[:per_q]:
        u = cr.unit
        add("xref", cr.pk, {
            "hit_type": "Unit cross-reference",
            "match": cr.cross_ref_number or cr.interchange_type or q,
            "detail": cr.interchange_type or "—",
            "primary": u.unit_number or u.yt_number or "—",
            "secondary": str(u.unit_type) if u.unit_type_id else "—",
            "tertiary": u.oem or "—",
            "href": reverse("catalog:unit_detail", args=[u.pk]),
        })
    if full():
        return hits

    # 2. Units — search key identification fields only (not every CharField)
    unit_q = (
        Q(unit_number__icontains=q)
        | Q(yt_number__icontains=q)
        | Q(oem__icontains=q)
        | Q(j_and_n_number__icontains=q)
        | Q(model_cat_number__icontains=q)
        | Q(manufacturer__icontains=q)
    )
    for u in Unit.objects.filter(is_active=True).filter(unit_q).select_related("unit_type").only(
        "id", "unit_number", "yt_number", "oem",
        "unit_type__id", "unit_type__name",
    )[:per_q]:
        add("unit", u.pk, {
            "hit_type": "Unit",
            "match": q,
            "detail": "—",
            "primary": u.unit_number or u.yt_number or "—",
            "secondary": u.yt_number or "—",
            "tertiary": u.oem or "—",
            "href": reverse("catalog:unit_detail", args=[u.pk]),
        })
    if full():
        return hits

    # 3. Parts — search primary number fields first (no expensive JOINs)
    part_q = (
        Q(part_number__icontains=q)
        | Q(manufacturer_number__icontains=q)
        | Q(yt_number__icontains=q)
        | Q(j_and_n__icontains=q)
        | Q(oem_number__icontains=q)
        | Q(item_no__icontains=q)
        | Q(part_name__icontains=q)
    )
    for part in Part.objects.filter(is_active=True).filter(part_q).only(
        "id", "part_number", "yt_number", "part_name", "j_and_n",
        "oem_number", "category",
    )[:per_q]:
        add("part", part.pk, {
            "hit_type": "Part",
            "match": q,
            "detail": part.category or "—",
            "primary": part.part_number or part.yt_number or "—",
            "secondary": part.part_name or "—",
            "tertiary": part.j_and_n or part.oem_number or "—",
            "href": reverse("catalog:part_detail", args=[part.pk]),
        })
    if full():
        return hits

    # 4. Applications — search key fields only
    app_q = (
        Q(name__icontains=q)
        | Q(make__icontains=q)
        | Q(model__icontains=q)
        | Q(engine__icontains=q)
        | Q(year__icontains=q)
        | Q(mfr__icontains=q)
        | Q(unit_number__icontains=q)
        | Q(part_number__icontains=q)
    )
    for app in Application.objects.filter(is_active=True).filter(app_q).only(
        "id", "name", "make", "model", "year", "engine", "unit_number",
    )[:per_q]:
        add("app", app.pk, {
            "hit_type": "Application",
            "match": q,
            "detail": app.unit_number or "—",
            "primary": app.name[:80] if app.name else "—",
            "secondary": " ".join(x for x in (app.make, app.model, app.year) if x).strip() or "—",
            "tertiary": app.engine or "—",
            "href": reverse("catalog:application_detail", args=[app.pk]),
        })
    if full():
        return hits

    # 5. Substitutes
    for sub in Substitute.objects.filter(
        Q(substitute_number__icontains=q)
    ).select_related("unit", "substitute_unit").only(
        "id", "substitute_number",
        "unit__id", "unit__unit_number", "unit__yt_number", "unit__oem",
        "substitute_unit__id", "substitute_unit__unit_number",
    )[:per_q]:
        u = sub.unit
        add("sub", sub.pk, {
            "hit_type": "Unit substitute",
            "match": sub.substitute_number or q,
            "detail": "—",
            "primary": u.unit_number or u.yt_number or "—",
            "secondary": sub.substitute_unit.unit_number if sub.substitute_unit_id else "—",
            "tertiary": u.oem or "—",
            "href": reverse("catalog:unit_detail", args=[u.pk]),
        })
    if full():
        return hits

    # 6. Gear reductions
    for gr in GearReductionSubstitution.objects.filter(
        Q(number__icontains=q) | Q(description__icontains=q)
    ).select_related("unit").only(
        "id", "number", "description",
        "unit__id", "unit__unit_number", "unit__yt_number", "unit__oem",
    )[:per_q]:
        u = gr.unit
        add("gear", gr.pk, {
            "hit_type": "Gear reduction",
            "match": gr.number or gr.description[:40] or q,
            "detail": gr.description[:80] if gr.description else "—",
            "primary": u.unit_number or u.yt_number or "—",
            "secondary": u.yt_number or "—",
            "tertiary": u.oem or "—",
            "href": reverse("catalog:unit_detail", args=[u.pk]),
        })
    if full():
        return hits

    # 7. BOM items
    for bi in BOMItem.objects.filter(
        Q(oem_number__icontains=q)
        | Q(j_and_n__icontains=q)
        | Q(yt_number__icontains=q)
    ).select_related("part", "bom").only(
        "id", "oem_number", "j_and_n", "yt_number",
        "part__id", "part__part_number", "part__yt_number", "part__part_name",
        "part__j_and_n", "part__is_active",
        "bom__id", "bom__name",
    )[:per_q]:
        p = bi.part
        if not p.is_active:
            continue
        add("bomi", bi.pk, {
            "hit_type": "BOM line",
            "match": bi.yt_number or bi.j_and_n or bi.oem_number or q,
            "detail": bi.bom.name if bi.bom_id else "—",
            "primary": p.part_number or p.yt_number or "—",
            "secondary": p.part_name or "—",
            "tertiary": p.j_and_n or "—",
            "href": reverse("catalog:part_detail", args=[p.pk]),
        })
    if full():
        return hits

    # 8. Application specifications (only if still need more hits)
    for spec in ApplicationSpecification.objects.filter(
        specification__icontains=q
    ).select_related("application").only(
        "id", "specification", "category", "type",
        "application__id", "application__name", "application__unit_number",
        "application__make", "application__is_active",
    )[:per_q]:
        app = spec.application
        if not app.is_active:
            continue
        add("appspec", spec.pk, {
            "hit_type": "Application spec",
            "match": spec.specification[:100],
            "detail": f"{spec.category} / {spec.type}".strip(" /") or "—",
            "primary": app.name[:80],
            "secondary": app.unit_number or "—",
            "tertiary": app.make or "—",
            "href": reverse("catalog:application_detail", args=[app.pk]),
        })

    return hits


def unit_search(request):
    """Advanced search across Units, Applications, and Parts (8.x — Unit Search page)."""
    tab = request.GET.get("tab", "crossref")
    results: list = []
    results_count = 0

    has_search_params = any(k.startswith("q_") for k in request.GET)
    if request.method == "GET" and has_search_params:
        tab = request.GET.get("tab", "crossref")
        if tab == "units":
            qs = Unit.objects.select_related("unit_type").filter(is_active=True)
            for field in [
                "unit_number", "yt_number", "oem", "model_cat_number", "voltage",
            ]:
                val = request.GET.get(f"q_{field}", "").strip()
                if val:
                    qs = qs.filter(**{f"{field}__icontains": val})
            # Unit type category filter
            unit_type_val = request.GET.get("q_unit_type", "").strip()
            if unit_type_val:
                qs = qs.filter(unit_type_category=unit_type_val)
            # Dynamic spec fields from unit type category
            for key, val in request.GET.items():
                if key.startswith("q_spec_") and val.strip():
                    spec_name = key[7:]
                    qs = qs.filter(**{f"specifications__{spec_name}__icontains": val.strip()})
            results = list(qs[:100])
            results_count = len(results)
        elif tab == "applications":
            qs = Application.objects.filter(is_active=True)
            # Application type category filter
            app_type_val = request.GET.get("q_app_type", "").strip()
            if app_type_val:
                qs = qs.filter(application_type_category=app_type_val)
            for field in [
                "unit_number", "make", "model", "engine", "year", "mfr", "volt",
                "amp", "fuel_type", "vin", "alt_pulley", "unit_type_name",
                "other_number", "options", "notes",
            ]:
                val = request.GET.get(f"q_{field}", "").strip()
                if val:
                    qs = qs.filter(**{f"{field}__icontains": val})
            # Dynamic spec fields from application type
            for key, val in request.GET.items():
                if key.startswith("q_spec_") and val.strip():
                    spec_name = key[7:]
                    qs = qs.filter(**{f"type_specifications__{spec_name}__icontains": val.strip()})
            results = list(qs[:100])
            results_count = len(results)
        elif tab == "parts":
            qs = Part.objects.select_related("unit").filter(is_active=True)
            for field in [
                "part_number", "part_name", "manufacturer_number", "yt_number",
                "j_and_n", "oem_number", "voltage", "type", "oem", "primary_vendor",
                "category",
            ]:
                val = request.GET.get(f"q_{field}", "").strip()
                if not val:
                    continue
                broad = Q(**{f"{field}__icontains": val})
                if field == "part_number":
                    broad |= Q(item_no__icontains=val) | Q(catalog__icontains=val) | Q(plug_id__icontains=val)
                    broad |= _part_related_number_q(val)
                elif field == "part_name":
                    broad |= Q(description__icontains=val) | Q(foot_notes__icontains=val) | Q(superseding_notes__icontains=val)
                    broad |= (
                        Q(part_interchanges__notes__icontains=val)
                        | Q(supersedings__notes__icontains=val)
                        | Q(part_substitutes__notes__icontains=val)
                        | Q(bom_items__notes__icontains=val)
                    )
                elif field in ("manufacturer_number", "yt_number", "j_and_n", "oem_number"):
                    broad |= _part_related_number_q(val)
                elif field == "oem":
                    broad |= _part_related_number_q(val)
                qs = qs.filter(broad)
            qs = qs.distinct()
            # Dynamic spec fields from part category
            for key, val in request.GET.items():
                if key.startswith("q_spec_") and val.strip():
                    spec_name = key[7:]
                    qs = qs.filter(**{f"specifications__{spec_name}__icontains": val.strip()})
            results = list(qs[:100])
            results_count = len(results)
        elif tab == "crossref":
            xref_val = request.GET.get("q_cross_ref", "").strip()
            if xref_val:
                results = _global_reference_search_hits(xref_val, limit=200)
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

    # Build unit type category choices + field defs for Units tab
    unit_type_category_choices = []
    unit_type_fields_json = "{}"
    if tab == "units":
        unit_type_category_choices = list(
            UnitTypeCategory.objects.values_list("name", flat=True).order_by("name")
        )
        unit_type_fields_json = json.dumps(_get_unit_type_field_defs())

    # Build part category field defs for Parts tab
    part_category_fields_json = "{}"
    if tab == "parts":
        part_category_fields_json = json.dumps(_get_category_field_defs())

    # Build application type choices + field defs for Applications tab
    app_type_choices = []
    app_type_fields_json = "{}"
    if tab == "applications":
        app_type_choices = list(
            ApplicationType.objects.values_list("name", flat=True).order_by("name")
        )
        app_type_fields_json = json.dumps(_get_application_type_field_defs())

    return render(request, "catalog/unit_search.html", {
        "tab": tab,
        "results": results or [],
        "results_count": results_count,
        "get_params": request.GET,
        "part_category_choices": part_category_choices,
        "unit_type_category_choices": unit_type_category_choices,
        "unit_type_fields_json": unit_type_fields_json,
        "part_category_fields_json": part_category_fields_json,
        "app_type_choices": app_type_choices,
        "app_type_fields_json": app_type_fields_json,
    })


def unit_list(request):
    """List units with type tabs, search, and dropdown filters."""
    units = Unit.objects.select_related("unit_type").filter(is_active=True).annotate(
        _sort_yt=NullIf("yt_number", Value("")),
        _sort_un=NullIf("unit_number", Value("")),
    ).order_by(
        F("_sort_yt").asc(nulls_last=True),
        F("_sort_un").asc(nulls_last=True),
    )

    # --- Unit-type category tabs (from the Add New Unit dropdown) ---
    unit_type_cats = list(
        UnitTypeCategory.objects.values_list("name", "color")
    )
    unit_type_categories = [name for name, _color in unit_type_cats]
    category_color_map = {name: color for name, color in unit_type_cats}
    selected_type = request.GET.get("type", "")

    if selected_type == "__blank__":
        units = units.filter(unit_type_category="")
    elif selected_type:
        units = units.filter(unit_type_category=selected_type)

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
        units = units.filter(family__icontains=filter_family)

    # --- Build distinct value lists for dropdowns (cached 5 min) ---
    active_units = Unit.objects.filter(is_active=True)
    oem_choices = cache.get_or_set("unit_oem_choices",
        lambda: list(active_units.exclude(oem="").values_list("oem", flat=True).distinct().order_by("oem")),
        300)
    voltage_choices = cache.get_or_set("unit_voltage_choices",
        lambda: list(active_units.exclude(voltage="").values_list("voltage", flat=True).distinct().order_by("voltage")),
        300)
    def _build_family_choices():
        raw = active_units.exclude(family="").values_list("family", flat=True).distinct()
        parts = set()
        for fam in raw:
            for segment in fam.split("|"):
                segment = segment.strip()
                if segment:
                    parts.add(segment)
        return sorted(parts, key=str.lower)
    family_choices = cache.get_or_set("unit_family_choices", _build_family_choices, 300)

    # Resolve selected unit type name for section heading
    if selected_type == "__blank__":
        selected_unit_type_name = "No Type Assigned"
    else:
        selected_unit_type_name = selected_type if selected_type in unit_type_categories else None

    total_count = units.count()
    try:
        per_page = min(int(request.GET.get("per_page", 50)), 100)
    except (ValueError, TypeError):
        per_page = 50
    paginator = Paginator(units, per_page)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "units": page_obj,
        "page_obj": page_obj,
        "total_count": total_count,
        "per_page": per_page,
        "unit_type_categories": unit_type_categories,
        "category_color_map": category_color_map,
        "selected_type": selected_type,
        "selected_color": category_color_map.get(selected_type, ""),
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
    unit = get_object_or_404(
        Unit.objects.select_related("unit_type").prefetch_related("images"), pk=pk
    )

    # Build spec sections for the template (Identification = basics only)
    # Unit Number only shows when it differs from YT Number
    unit_number_display = (
        unit.unit_number
        if unit.unit_number and unit.unit_number != unit.yt_number
        else ""
    )
    spec_sections = [
        ("Identification", [
            ("Unit Number", unit_number_display),
            ("YT Number", unit.yt_number),
            ("OEM", unit.oem),
            ("J&N Number", unit.j_and_n_number),
            ("Manufacturer", unit.manufacturer),
            ("Description", unit.description),
        ]),
    ]

    # Filter out sections where every value is blank
    spec_sections = [
        (title, fields)
        for title, fields in spec_sections
        if any(val for _, val in fields)
    ]

    # Cross references — unit-to-unit (both directions) and manufacturer numbers
    # Sort: J&N first, then alphabetically by manufacturer/source, then by number
    cross_refs = CrossReference.objects.filter(
        Q(unit=unit) | Q(cross_ref_unit=unit)
    ).select_related(
        "unit", "cross_ref_unit", "unit__unit_type", "cross_ref_unit__unit_type"
    ).annotate(
        _is_jn=Case(
            When(interchange_type__istartswith="J&N", then=Value(0)),
            default=Value(1),
        ),
    ).order_by("_is_jn", "interchange_type", "cross_ref_number")

    cross_ref_all = []
    for cr in cross_refs:
        if cr.cross_ref_unit_id:
            other = cr.cross_ref_unit if cr.unit_id == unit.pk else cr.unit
            cross_ref_all.append({"ref": cr, "unit": other})
        else:
            cross_ref_all.append({"ref": cr, "unit": None})

    # Substitutes (both directions, including manual-number-only entries)
    subs_qs = Substitute.objects.filter(
        Q(unit=unit) | Q(substitute_unit=unit)
    ).select_related("unit", "substitute_unit", "unit__unit_type", "substitute_unit__unit_type")

    substitute_units = []
    seen_sub_units = set()
    for s in subs_qs:
        other = s.substitute_unit if s.unit_id == unit.pk else s.unit
        dedup_key = other.pk if other else s.substitute_number
        if dedup_key in seen_sub_units:
            continue
        seen_sub_units.add(dedup_key)
        substitute_units.append({"ref": s, "unit": other})

    # Gear Reduction Substitutions
    gear_reductions = GearReductionSubstitution.objects.filter(unit=unit).order_by("number")

    # Dynamic unit type specifications (from JSON specs, with model-field fallback)
    # Exclude fields already shown in the Identification section
    _identification_fields = {
        "yt_number", "oem", "manufacturer", "j_n_number", "j_and_n_number",
        "unit_number", "description",
    }
    unit_spec_display = []
    utc_fields = _get_unit_type_field_defs()
    field_defs = utc_fields.get(unit.unit_type_category, [])
    specs_json = unit.specifications or {}
    model_field_names = {f.name for f in unit._meta.get_fields() if hasattr(f, "column")}
    _spec_to_model = {"j_n_number": "j_and_n_number"}
    seen = set()
    for fd in field_defs:
        if fd["name"] in _identification_fields:
            seen.add(fd["name"])
            continue
        val = specs_json.get(fd["name"], "")
        if not val:
            model_name = _spec_to_model.get(fd["name"], fd["name"])
            if model_name in model_field_names:
                val = getattr(unit, model_name, "")
        if val:
            unit_spec_display.append({"label": fd["label"], "value": val})
        seen.add(fd["name"])
    for key, val in specs_json.items():
        if key not in seen and key not in _identification_fields and val:
            unit_spec_display.append({"label": key, "value": val})

    return render(request, "catalog/unit_detail.html", {
        "unit": unit,
        "spec_sections": spec_sections,
        "unit_spec_display": unit_spec_display,
        "cross_ref_all": cross_ref_all,
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
    """Add a cross-reference to a unit (unit-to-unit or manufacturer number)."""
    unit = get_object_or_404(Unit, pk=pk)

    if request.method == "POST":
        form = CrossReferenceForm(request.POST, unit=unit)
        if form.is_valid():
            cr = form.save(commit=False)
            cr.unit = unit
            cr.save()
            label = (
                cr.cross_ref_unit.unit_number
                if cr.cross_ref_unit
                else f"{cr.interchange_type} {cr.cross_ref_number}"
            )
            logger.info("[Unit] Added xref to %s on %s", label, unit)
            messages.success(request, f"Cross reference to {label} added.")
            return redirect("catalog:unit_detail", pk=unit.pk)
    else:
        form = CrossReferenceForm(unit=unit)

    return render(request, "catalog/cross_reference_add.html", {
        "form": form,
        "unit": unit,
    })


def cross_reference_detail(request, pk, cr_pk):
    """Read-only view of a single cross reference with Edit / Delete buttons."""
    unit = get_object_or_404(Unit, pk=pk)
    cr = get_object_or_404(CrossReference.objects.select_related("cross_ref_unit"), pk=cr_pk)
    return render(request, "catalog/cross_reference_detail.html", {
        "unit": unit,
        "cr": cr,
    })


def cross_reference_edit(request, pk, cr_pk):
    """Edit an existing cross reference."""
    unit = get_object_or_404(Unit, pk=pk)
    cr = get_object_or_404(CrossReference, pk=cr_pk)
    if request.method == "POST":
        form = CrossReferenceForm(request.POST, instance=cr, unit=unit)
        if form.is_valid():
            form.save()
            logger.info("[Unit] Updated xref on %s", cr.unit)
            messages.success(request, "Cross reference updated.")
            return redirect("catalog:unit_detail", pk=unit.pk)
    else:
        form = CrossReferenceForm(instance=cr, unit=unit)

    return render(request, "catalog/cross_reference_edit.html", {
        "form": form,
        "unit": unit,
        "cr": cr,
    })


def cross_reference_delete(request, pk, cr_pk):
    """Delete a cross reference."""
    unit = get_object_or_404(Unit, pk=pk)
    cr = get_object_or_404(CrossReference, pk=cr_pk)
    if request.method == "POST":
        cr.delete()
        logger.info("[Unit] Deleted xref from %s", unit)
        messages.success(request, "Cross reference deleted.")
    return redirect("catalog:unit_detail", pk=unit.pk)


def substitute_add(request, pk):
    """Add a substitute to a unit."""
    unit = get_object_or_404(Unit, pk=pk)

    if request.method == "POST":
        form = SubstituteForm(request.POST, unit=unit)
        if form.is_valid():
            sub = form.save(commit=False)
            sub.unit = unit
            sub.save()
            label = sub.substitute_unit.unit_number if sub.substitute_unit else sub.substitute_number
            logger.info("[Unit] Added substitute %s to %s", label, unit)
            messages.success(request, f"Substitute {label} added.")
            return redirect("catalog:unit_detail", pk=unit.pk)
    else:
        form = SubstituteForm(unit=unit)

    return render(request, "catalog/substitute_add.html", {
        "form": form,
        "unit": unit,
    })


def substitute_edit(request, pk, sub_pk):
    """Edit a substitute on a unit."""
    unit = get_object_or_404(Unit, pk=pk)
    obj = get_object_or_404(Substitute, pk=sub_pk, unit=unit)
    if request.method == "POST":
        form = SubstituteForm(request.POST, instance=obj, unit=unit)
        if form.is_valid():
            form.save()
            label = obj.substitute_unit.unit_number if obj.substitute_unit else obj.substitute_number
            logger.info("[Unit] Edited substitute %s on %s", label, unit)
            messages.success(request, f"Substitute {label} updated.")
            return redirect("catalog:unit_detail", pk=unit.pk)
    else:
        form = SubstituteForm(instance=obj, unit=unit)
    return render(request, "catalog/substitute_add.html", {
        "form": form,
        "unit": unit,
        "editing": True,
    })


def substitute_delete(request, pk, sub_pk):
    """Remove a substitute link from a unit."""
    unit = get_object_or_404(Unit, pk=pk)
    obj = get_object_or_404(Substitute, pk=sub_pk, unit=unit)
    if request.method == "POST":
        label = obj.substitute_unit.unit_number if obj.substitute_unit else obj.substitute_number
        obj.delete()
        logger.info("[Unit] Removed substitute %s from %s", label, unit)
        messages.success(request, f"Substitute {label} removed.")
    return redirect("catalog:unit_detail", pk=unit.pk)


def gear_reduction_add(request, pk):
    """Add a gear reduction substitution to a unit."""
    unit = get_object_or_404(Unit, pk=pk)

    if request.method == "POST":
        form = GearReductionForm(request.POST)
        if form.is_valid():
            gr = form.save(commit=False)
            gr.unit = unit
            gr.save()
            logger.info("[Unit] Added gear reduction '%s' to %s", gr.number, unit)
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
            logger.info("[Unit] Updated gear reduction '%s'", gr.number)
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
        logger.info("[Unit] Deleted gear reduction '%s' from %s", gr.number, unit)
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
    import json

    if request.method == "POST":
        form = UnitForm(request.POST, request.FILES)
        del form.fields["is_active"]
        if form.is_valid():
            form.save()
            logger.info("[Unit] Created '%s' (pk=%s)", form.instance.unit_number, form.instance.pk)
            messages.success(request, "Unit created successfully.")
            return redirect("catalog:unit_list")
    else:
        form = UnitForm()
        del form.fields["is_active"]

    utc_fields = _get_unit_type_field_defs()
    utc_pk_map = {c.name: c.pk for c in UnitTypeCategory.objects.all()}
    return render(request, "catalog/unit_form.html", {
        "form": form,
        "unit": None,
        "fieldsets": _build_fieldsets(form),
        "title": "Add New Unit",
        "category_fields_json": json.dumps(utc_fields),
        "existing_specs_json": "{}",
        "utc_pk_map_json": json.dumps(utc_pk_map),
    })


def unit_edit(request, pk):
    """Edit an existing unit."""
    import json

    unit = get_object_or_404(Unit, pk=pk)
    if request.method == "POST":
        form = UnitForm(request.POST, request.FILES, instance=unit)
        del form.fields["is_active"]
        if form.is_valid():
            form.save()
            logger.info("[Unit] Updated '%s' (pk=%s)", unit.unit_number, unit.pk)
            messages.success(request, f"Unit '{unit.unit_number}' updated.")
            return redirect("catalog:unit_detail", pk=unit.pk)
    else:
        form = UnitForm(instance=unit)
        del form.fields["is_active"]

    utc_fields = _get_unit_type_field_defs()
    existing_specs = dict(unit.specifications or {})

    spec_to_model = {"j_n_number": "j_and_n_number"}
    model_field_names = {f.name for f in unit._meta.get_fields() if hasattr(f, "column")}
    for cat_fields in utc_fields.values():
        for fd in cat_fields:
            fname = fd["name"]
            if fname in existing_specs and existing_specs[fname]:
                continue
            model_name = spec_to_model.get(fname, fname)
            if model_name in model_field_names:
                val = getattr(unit, model_name, "")
                if val:
                    existing_specs[fname] = str(val)

    utc_pk_map = {c.name: c.pk for c in UnitTypeCategory.objects.all()}
    return render(request, "catalog/unit_form.html", {
        "form": form,
        "unit": unit,
        "fieldsets": _build_fieldsets(form),
        "title": "Edit Unit",
        "category_fields_json": json.dumps(utc_fields),
        "existing_specs_json": json.dumps(existing_specs),
        "utc_pk_map_json": json.dumps(utc_pk_map),
    })


def unit_delete(request, pk):
    """Delete a unit."""
    unit = get_object_or_404(Unit, pk=pk)
    if request.method == "POST":
        unit_number = unit.unit_number
        unit.delete()
        logger.info("[Unit] Deleted '%s'", unit_number)
        messages.success(request, f"Unit '{unit_number}' deleted.")
        return redirect("catalog:unit_list")
    return redirect("catalog:unit_edit", pk=pk)


# ---------------------------------------------------------------------------
# Unit Type Category Settings (user-managed unit type categories & fields)
# ---------------------------------------------------------------------------
def unit_type_category_list(request):
    """List all unit type categories and their fields."""
    categories = UnitTypeCategory.objects.prefetch_related("fields").all()
    return render(request, "catalog/unit_type_category_list.html", {"categories": categories})


def unit_type_category_detail(request, pk):
    """View a unit type category and its fields (read-only)."""
    cat = get_object_or_404(UnitTypeCategory.objects.prefetch_related("fields"), pk=pk)
    return render(request, "catalog/unit_type_category_detail.html", {"category": cat})


def unit_type_category_create(request):
    """Create a new unit type category with its fields."""
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            messages.error(request, "Category name is required.")
            return redirect("catalog:unit_type_category_create")
        if UnitTypeCategory.objects.filter(name=name).exists():
            messages.error(request, f"Unit type '{name}' already exists.")
            return redirect("catalog:unit_type_category_create")

        cat = UnitTypeCategory.objects.create(name=name)
        field_names = request.POST.getlist("field_name")
        field_labels = request.POST.getlist("field_label")
        for i, (fname, flabel) in enumerate(zip(field_names, field_labels)):
            fname, flabel = fname.strip(), flabel.strip()
            if fname and flabel:
                UnitTypeCategoryField.objects.create(
                    category=cat, field_name=fname, field_label=flabel, display_order=i,
                )
        logger.info("[UnitType] Created '%s'", name)
        messages.success(request, f"Unit type '{name}' created.")
        return redirect("catalog:unit_type_category_list")

    default_fields = [{"field_label": fl, "field_name": fn} for fn, fl in UNIT_DEFAULT_FIELDS]
    return render(request, "catalog/unit_type_category_form.html", {
        "title": "Add New Unit Type",
        "category": None,
        "fields": default_fields,
        "default_field_names_json": json.dumps([fn for fn, _ in UNIT_DEFAULT_FIELDS]),
    })


def unit_type_category_edit(request, pk):
    """Edit an existing unit type category and its fields."""
    cat = get_object_or_404(UnitTypeCategory, pk=pk)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            messages.error(request, "Category name is required.")
            return redirect("catalog:unit_type_category_edit", pk=pk)
        if UnitTypeCategory.objects.filter(name=name).exclude(pk=pk).exists():
            messages.error(request, f"Unit type '{name}' already exists.")
            return redirect("catalog:unit_type_category_edit", pk=pk)

        cat.name = name
        cat.save()

        cat.fields.all().delete()
        field_names = request.POST.getlist("field_name")
        field_labels = request.POST.getlist("field_label")
        for i, (fname, flabel) in enumerate(zip(field_names, field_labels)):
            fname, flabel = fname.strip(), flabel.strip()
            if fname and flabel:
                UnitTypeCategoryField.objects.create(
                    category=cat, field_name=fname, field_label=flabel, display_order=i,
                )
        logger.info("[UnitType] Updated '%s'", name)
        messages.success(request, f"Unit type '{name}' updated.")
        return redirect("catalog:unit_type_category_list")

    existing_fields = list(cat.fields.values("field_name", "field_label"))
    return render(request, "catalog/unit_type_category_form.html", {
        "title": f"Edit Unit Type: {cat.name}",
        "category": cat,
        "fields": existing_fields,
        "default_field_names_json": json.dumps([fn for fn, _ in UNIT_DEFAULT_FIELDS]),
    })


def unit_type_category_delete(request, pk):
    """Delete a unit type category."""
    cat = get_object_or_404(UnitTypeCategory, pk=pk)
    if request.method == "POST":
        cat_name = cat.name
        cat.delete()
        logger.info("[UnitType] Deleted '%s'", cat_name)
        messages.success(request, f"Unit type '{cat_name}' deleted.")
        return redirect("catalog:unit_type_category_list")
    return redirect("catalog:unit_type_category_edit", pk=pk)


def unit_type_category_fields_api(request, type_name):
    """Return JSON field definitions for a given unit type category (AJAX)."""
    from django.http import JsonResponse

    category_fields = _get_unit_type_field_defs()
    fields = category_fields.get(type_name, [])
    return JsonResponse({"fields": fields})


def unit_type_custom_field_add_api(request):
    """AJAX endpoint to add a custom field to an existing UnitTypeCategory."""
    from django.http import JsonResponse

    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    category_name = request.POST.get("category_name", "").strip()
    field_label = request.POST.get("field_label", "").strip()
    field_name = request.POST.get("field_name", "").strip()
    if not category_name or not field_label or not field_name:
        return JsonResponse({"error": "category_name, field_label, and field_name are required."}, status=400)

    cat = UnitTypeCategory.objects.filter(name=category_name).first()
    if not cat:
        return JsonResponse({"error": f"Unit type '{category_name}' not found."}, status=404)
    if cat.fields.filter(field_name=field_name).exists():
        return JsonResponse({"error": f"Field '{field_name}' already exists."}, status=400)

    max_order = cat.fields.aggregate(m=Max("display_order"))["m"] or 0
    UnitTypeCategoryField.objects.create(
        category=cat, field_name=field_name, field_label=field_label, display_order=max_order + 1,
    )
    return JsonResponse({"ok": True, "field_name": field_name, "field_label": field_label})


# ---------------------------------------------------------------------------
# Application Type Settings (user-managed application types & fields)
# ---------------------------------------------------------------------------
def application_type_list(request):
    """Single-page Application Field Management: default fields + custom fields."""
    at, _ = ApplicationType.objects.get_or_create(name="Application")
    default_fields = [{"field_name": fn, "field_label": fl} for fn, fl in APPLICATION_DEFAULT_FIELDS]
    default_names = {fn for fn, _ in APPLICATION_DEFAULT_FIELDS}
    custom_fields = list(
        at.fields.exclude(field_name__in=default_names)
        .values("field_name", "field_label")
        .order_by("display_order")
    )
    return render(request, "catalog/application_type_list.html", {
        "app_type": at,
        "default_fields": default_fields,
        "custom_fields": custom_fields,
    })


def application_type_detail(request, pk):
    """View an application type and its fields (read-only)."""
    app_type = get_object_or_404(ApplicationType.objects.prefetch_related("fields"), pk=pk)
    return render(request, "catalog/application_type_detail.html", {"app_type": app_type})


def application_type_create(request):
    """Create a new application type with its fields."""
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            messages.error(request, "Application type name is required.")
            return redirect("catalog:application_type_create")
        if ApplicationType.objects.filter(name=name).exists():
            messages.error(request, f"Application type '{name}' already exists.")
            return redirect("catalog:application_type_create")

        at = ApplicationType.objects.create(name=name)
        field_names = request.POST.getlist("field_name")
        field_labels = request.POST.getlist("field_label")
        for i, (fname, flabel) in enumerate(zip(field_names, field_labels)):
            fname, flabel = fname.strip(), flabel.strip()
            if fname and flabel:
                ApplicationTypeField.objects.create(
                    application_type=at, field_name=fname, field_label=flabel, display_order=i,
                )
        logger.info("[AppType] Created '%s'", name)
        messages.success(request, f"Application type '{name}' created.")
        return redirect("catalog:application_type_list")

    default_fields = [{"field_label": fl, "field_name": fn} for fn, fl in APPLICATION_DEFAULT_FIELDS]
    return render(request, "catalog/application_type_form.html", {
        "title": "Add New Application Type",
        "app_type": None,
        "fields": default_fields,
        "default_field_names_json": json.dumps([fn for fn, _ in APPLICATION_DEFAULT_FIELDS]),
    })


def application_type_edit(request, pk):
    """Edit application fields: default fields are locked, custom fields are editable."""
    at = get_object_or_404(ApplicationType, pk=pk)

    if request.method == "POST":
        at.fields.all().delete()
        field_names = request.POST.getlist("field_name")
        field_labels = request.POST.getlist("field_label")
        for i, (fname, flabel) in enumerate(zip(field_names, field_labels)):
            fname, flabel = fname.strip(), flabel.strip()
            if fname and flabel:
                ApplicationTypeField.objects.create(
                    application_type=at, field_name=fname, field_label=flabel, display_order=i,
                )
        logger.info("[AppType] Updated fields for '%s'", at.name)
        messages.success(request, "Application fields updated.")
        return redirect("catalog:application_type_list")

    default_fields = [{"field_label": fl, "field_name": fn} for fn, fl in APPLICATION_DEFAULT_FIELDS]
    default_names = {fn for fn, _ in APPLICATION_DEFAULT_FIELDS}
    custom_fields = list(
        at.fields.exclude(field_name__in=default_names)
        .values("field_name", "field_label")
        .order_by("display_order")
    )
    all_fields = default_fields + custom_fields
    return render(request, "catalog/application_type_form.html", {
        "title": "Edit Application Fields",
        "app_type": at,
        "fields": all_fields,
        "default_field_names_json": json.dumps([fn for fn, _ in APPLICATION_DEFAULT_FIELDS]),
    })


def application_type_delete(request, pk):
    """Delete an application type."""
    at = get_object_or_404(ApplicationType, pk=pk)
    if request.method == "POST":
        at_name = at.name
        at.delete()
        logger.info("[AppType] Deleted '%s'", at_name)
        messages.success(request, f"Application type '{at_name}' deleted.")
        return redirect("catalog:application_type_list")
    return redirect("catalog:application_type_edit", pk=pk)


def application_type_fields_api(request, type_name):
    """Return JSON field definitions for a given application type (AJAX)."""
    from django.http import JsonResponse

    type_fields = _get_application_type_field_defs()
    fields = type_fields.get(type_name, [])
    return JsonResponse({"fields": fields})


def application_custom_field_add_api(request):
    """AJAX endpoint to create a new custom field for the Application type."""
    from django.http import JsonResponse

    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    field_label = request.POST.get("field_label", "").strip()
    field_name = request.POST.get("field_name", "").strip()
    if not field_label or not field_name:
        return JsonResponse({"error": "Both field_label and field_name are required."}, status=400)

    at, _ = ApplicationType.objects.get_or_create(name="Application")
    if at.fields.filter(field_name=field_name).exists():
        return JsonResponse({"error": f"Field '{field_name}' already exists."}, status=400)

    max_order = at.fields.aggregate(m=Max("display_order"))["m"] or 0
    ApplicationTypeField.objects.create(
        application_type=at,
        field_name=field_name,
        field_label=field_label,
        display_order=max_order + 1,
    )
    return JsonResponse({"ok": True, "field_name": field_name, "field_label": field_label})


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Unit CSV upload — dynamic field mapping
# ---------------------------------------------------------------------------
_UNIT_SKIP_FIELDS = {
    "id", "unit_type", "unit_type_category", "specifications",
    "unit_image", "plug_image", "applications", "is_active",
    "created_at", "updated_at",
}
_UNIT_DECIMAL_FIELDS = {"new_unit_price", "rebuilt_unit_price"}

def _get_unit_model_fields():
    """Return set of writable CharField/TextField/Decimal field names on Unit."""
    return {
        f.name for f in Unit._meta.get_fields()
        if hasattr(f, "column") and f.name not in _UNIT_SKIP_FIELDS
    }

_UNIT_CSV_ALIASES = {
    "unit_#": "unit_number",
    "unit_no": "unit_number",
    "unit_no.": "unit_number",
    "yt_#": "yt_number",
    "yt_no": "yt_number",
    "j&n": "j_and_n_number",
    "j&n_number": "j_and_n_number",
    "j&n_no": "j_and_n_number",
    "j_&_n": "j_and_n_number",
    "j_n": "j_and_n_number",
    "jn": "j_and_n_number",
    "jn_number": "j_and_n_number",
    "model_cat_#": "model_cat_number",
    "model_cat": "model_cat_number",
    "cat_number": "model_cat_number",
    "manufacture": "manufacturer",
    "mfr": "manufacturer",
    "desc": "description",
    "kw": "kw_hp",
    "hp": "kw_hp",
    "amp": "amp_rating",
    "amps": "amp_rating",
    "teeth": "tooth_quantity",
    "tooth_count": "tooth_quantity",
    "tooth_qty": "tooth_quantity",
}


def _normalise_unit_csv_header(raw_header):
    """Normalise a unit CSV header to a model field name via aliases."""
    norm = raw_header.strip().lower().replace(" ", "_")
    return _UNIT_CSV_ALIASES.get(norm, norm)


def _parse_unit_csv(decoded_text):
    """Parse unit CSV text and return (columns, rows, warnings, header_warning)."""
    reader = csv.DictReader(io.StringIO(decoded_text))
    columns_raw = [c.strip() for c in (reader.fieldnames or []) if c and c.strip()]
    columns = [_normalise_unit_csv_header(c) for c in columns_raw]

    has_unit_number_col = "unit_number" in columns
    header_warning = ""
    if not has_unit_number_col:
        header_warning = (
            f'No "unit_number" column detected. '
            f"Your CSV columns are: {', '.join(columns_raw)}. "
            f"Units will be created without a Unit Number."
        )

    rows = []
    warnings = []
    for row_num, raw_row in enumerate(reader, start=2):
        row = {}
        for orig_col, norm_col in zip(columns_raw, columns):
            row[norm_col] = (raw_row.get(orig_col) or "").strip()
        un = row.get("unit_number", "").strip()
        if un:
            existing = Unit.objects.filter(unit_number=un).first()
            if existing:
                warnings.append((row_num, f"Unit {un} already exists — will be updated."))
        elif has_unit_number_col:
            warnings.append((row_num, "Empty Unit Number — unit will be created without one."))
        rows.append(row)
    return columns, rows, warnings, header_warning


def unit_upload_csv(request):
    """Step 1: Upload CSV. Step 2: Preview & edit. Step 3: Confirm import with report."""
    step = request.POST.get("step", "upload")

    # ---- Step 3: Confirm import ----
    if request.method == "POST" and step == "confirm":
        columns_json = request.POST.get("columns", "[]")
        columns = json.loads(columns_json)
        row_count = int(request.POST.get("row_count", 0))
        logger.info("[Unit CSV Import] Confirm import — %d rows submitted", row_count)
        model_fields = _get_unit_model_fields()
        utc_lookup = {c.name.lower(): c.name for c in UnitTypeCategory.objects.all()}

        report = []
        created = updated = skipped = 0

        for i in range(row_count):
            row = {}
            for col in columns:
                row[col] = request.POST.get(f"row_{i}_{col}", "").strip()

            un = row.get("unit_number", "").strip() or None

            # Resolve unit_type FK and unit_type_category
            unit_type_obj = None
            unit_type_category = ""
            type_name = row.get("unit_type", "").strip()
            if type_name:
                unit_type_obj = UnitType.objects.filter(name__iexact=type_name).first()
                matched_cat = utc_lookup.get(type_name.lower(), "")
                if matched_cat:
                    unit_type_category = matched_cat

            defaults = {}
            specs = {}
            for col, val in row.items():
                if not val or col in ("unit_number", "unit_type"):
                    continue
                field_name = _UNIT_CSV_ALIASES.get(col, col)
                if field_name in model_fields:
                    defaults[field_name] = val
                else:
                    specs[field_name] = val

            if unit_type_obj:
                defaults["unit_type"] = unit_type_obj
            if unit_type_category:
                defaults["unit_type_category"] = unit_type_category

            for dec_field in _UNIT_DECIMAL_FIELDS:
                if dec_field in defaults:
                    try:
                        defaults[dec_field] = float(defaults[dec_field]) if defaults[dec_field] else None
                    except (ValueError, TypeError):
                        defaults[dec_field] = None

            if specs:
                if un:
                    existing_specs = Unit.objects.filter(unit_number=un).values_list("specifications", flat=True).first()
                    merged = dict(existing_specs or {})
                    merged.update(specs)
                    defaults["specifications"] = merged
                else:
                    defaults["specifications"] = specs

            try:
                if un:
                    obj, was_created = Unit.objects.update_or_create(
                        unit_number=un, defaults=defaults
                    )
                else:
                    obj = Unit.objects.create(unit_number=None, **defaults)
                    was_created = True
                action = "created" if was_created else "updated"
                if was_created:
                    created += 1
                else:
                    updated += 1
                detail_fields = {k: v for k, v in row.items() if v and k != "unit_number"}
                if specs:
                    detail_fields["custom_specs"] = specs
                report.append({"row": i + 2, "unit_number": un or "(none)", "action": action,
                               "reason": "", "details": detail_fields, "pk": obj.pk})
            except Exception as e:
                report.append({"row": i + 2, "unit_number": un or "(none)", "action": "error",
                               "reason": str(e), "details": {}})
                skipped += 1

        logger.info("[Unit CSV Import] Finished: %d created, %d updated, %d skipped",
                    created, updated, skipped)
        return render(request, "catalog/unit_upload_csv_report.html", {
            "report": report,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "total": row_count,
        })

    # ---- Step 2: Preview (file just uploaded) ----
    if request.method == "POST" and step == "upload":
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "Please select a CSV file.")
            return redirect("catalog:unit_upload_csv")
        if not csv_file.name.endswith(".csv"):
            messages.error(request, "File must be a .csv file.")
            return redirect("catalog:unit_upload_csv")
        try:
            decoded = csv_file.read().decode("utf-8-sig")
            columns, rows, warnings, header_warning = _parse_unit_csv(decoded)
            warnings_by_row = {w[0]: w[1] for w in warnings}
            return render(request, "catalog/unit_upload_csv_preview.html", {
                "columns": columns,
                "columns_json": json.dumps(columns),
                "rows": rows,
                "warnings_by_row": warnings_by_row,
                "header_warning": header_warning,
                "filename": csv_file.name,
            })
        except Exception as e:
            messages.error(request, f"Error reading CSV: {e}")
            return redirect("catalog:unit_upload_csv")

    # ---- Step 1: Show upload form ----
    model_fields = sorted(_get_unit_model_fields())
    unit_type_categories = list(UnitTypeCategory.objects.values_list("name", flat=True).order_by("name"))
    unit_type_field_defs = _get_unit_type_field_defs()
    return render(request, "catalog/unit_upload_csv.html", {
        "model_fields": model_fields,
        "unit_type_categories": unit_type_categories,
        "unit_type_field_defs_json": json.dumps(unit_type_field_defs),
    })


_UNIT_CSV_TEMPLATE_COLUMNS = [
    "unit_type", "unit_number", "yt_number", "oem", "j_and_n_number",
    "model_cat_number", "manufacturer", "family", "voltage", "kw_hp",
    "rpm", "rotation", "description", "notes",
    "new_unit_price", "rebuilt_unit_price",
]

_UNIT_CSV_LABELS = {
    "unit_number": "Unit Number",
    "unit_type": "Unit Type",
    "yt_number": "YT Number",
    "oem": "OEM",
    "j_and_n_number": "J&N Number",
    "model_cat_number": "Model / Cat Number",
    "manufacturer": "Manufacturer",
    "family": "Family",
    "voltage": "Voltage",
    "kw_hp": "kW / HP",
    "phase": "Phase",
    "fla": "FLA",
    "amp_rating": "Amp Rating",
    "full_load_eff": "Full Load Efficiency",
    "power_rating": "Power Rating",
    "rpm": "RPM",
    "frame": "Frame",
    "enclosure": "Enclosure",
    "rotation": "Rotation",
    "clock_position": "Clock Position",
    "mount_type": "Mount Type",
    "flange_type": "Flange Type",
    "housing_type": "Housing Type",
    "housing": "Housing",
    "weight": "Weight",
    "bearings": "Bearings",
    "design": "Design",
    "type": "Type",
    "starter_type": "Starter Type",
    "tooth_quantity": "Tooth Quantity",
    "nose_type": "Nose Type",
    "fan_type": "Fan Type",
    "regulator_type": "Regulator Type",
    "pulley_class": "Pulley Class",
    "drive": "Drive",
    "description": "Description",
    "notes": "Notes",
    "new_unit_price": "New Unit Price",
    "rebuilt_unit_price": "Rebuilt Unit Price",
}


def unit_download_csv_template(request):
    """Download a blank CSV template for unit imports.

    No type selected  → includes ALL custom fields from every unit type (master template).
    Specific type     → includes only that type's custom fields.
    """
    from django.http import HttpResponse

    selected_type = request.GET.get("unit_type", "").strip()
    columns = list(_UNIT_CSV_TEMPLATE_COLUMNS)
    type_defs = _get_unit_type_field_defs()
    default_names = set(columns)

    if selected_type:
        for field_def in type_defs.get(selected_type, []):
            if field_def["name"] not in default_names:
                columns.append(field_def["name"])
    else:
        seen = set(default_names)
        for type_fields in type_defs.values():
            for field_def in type_fields:
                if field_def["name"] not in seen:
                    columns.append(field_def["name"])
                    seen.add(field_def["name"])

    headers = [_UNIT_CSV_LABELS.get(c, c.replace("_", " ").title()) for c in columns]

    response = HttpResponse(content_type="text/csv")
    suffix = f"_{selected_type.replace(' ', '_')}" if selected_type else "_all_types"
    response["Content-Disposition"] = f'attachment; filename="unit_import_template{suffix}.csv"'

    writer = csv.writer(response)
    writer.writerow(headers)
    return response


# ── Autocomplete JSON endpoints (used by Tom Select AJAX) ──────────────

def _autocomplete_response(qs, label_fn, limit=30):
    from django.http import JsonResponse
    results = [{"value": str(obj.pk), "text": label_fn(obj)} for obj in qs[:limit]]
    return JsonResponse({"results": results})


def unit_autocomplete(request):
    q = request.GET.get("q", "").strip()
    qs = Unit.objects.filter(is_active=True).order_by(
        F("unit_number").asc(nulls_last=True), "yt_number"
    )
    if q:
        qs = qs.filter(
            Q(unit_number__icontains=q) | Q(yt_number__icontains=q)
        )
    exclude_app = request.GET.get("exclude_app")
    if exclude_app:
        linked = ApplicationUnit.objects.filter(application_id=exclude_app).values_list("unit_id", flat=True)
        qs = qs.exclude(pk__in=linked)
    return _autocomplete_response(
        qs,
        lambda u: u.unit_number or u.yt_number or f"Unit #{u.pk}",
    )


def part_autocomplete(request):
    q = request.GET.get("q", "").strip()
    qs = Part.objects.filter(is_active=True).annotate(
        _sort_yt=NullIf("yt_number", Value("")),
        _sort_pn=NullIf("part_number", Value("")),
    ).order_by(
        F("_sort_yt").asc(nulls_last=True),
        F("_sort_pn").asc(nulls_last=True),
    )
    if q:
        qs = qs.filter(
            Q(part_number__icontains=q)
            | Q(yt_number__icontains=q)
            | Q(part_name__icontains=q)
            | Q(manufacturer_number__icontains=q)
            | Q(oem_number__icontains=q)
            | Q(j_and_n__icontains=q)
        )
    exclude_bom = request.GET.get("exclude_bom")
    if exclude_bom:
        existing = BOMItem.objects.filter(bom_id=exclude_bom).values_list("part_id", flat=True)
        qs = qs.exclude(pk__in=existing)
    return _autocomplete_response(qs, lambda p: f"{_part_display_number(p)} – {p.part_name}")


def application_autocomplete(request):
    q = request.GET.get("q", "").strip()
    qs = Application.objects.filter(is_active=True).order_by("name")
    if q:
        qs = qs.filter(name__icontains=q)
    return _autocomplete_response(qs, lambda a: a.name)


def part_detail_api(request, pk):
    """Return part fields as JSON for auto-fill (used by BOM item form)."""
    part = get_object_or_404(Part, pk=pk)
    return JsonResponse({
        "part_number": part.part_number,
        "j_and_n": part.j_and_n,
        "yt_number": part.yt_number,
        "bin_number": part.bin_number,
        "oem_number": part.oem_number,
        "description": part.part_name,
        "stock_quantity": part.stock_quantity,
    })


# ---------------------------------------------------------------------------
# YouTech PDF import  (parts/import-pdf/)
# ---------------------------------------------------------------------------

def part_import_pdf(request):
    """
    3-step import flow for the YouTech "Our Numbers to Others" PDF.

    Step 1 (GET)       : Show upload form.
    Step 2 (POST/parse): Parse the uploaded PDF, render preview table.
    Step 3 (POST/confirm): Write Part + PartInterchange rows, show report.
    """
    from .pdf_utils import parse_youtech_pdf

    categories = list(PartCategory.objects.values_list("name", flat=True).order_by("name"))

    # ---- Step 3: Confirm import ----
    if request.method == "POST" and request.POST.get("step") == "confirm":
        from .youtech_import import import_youtech_rows

        row_count = int(request.POST.get("row_count", 0))
        logger.info("[PDF Import] Confirm import — %d rows submitted", row_count)
        rows = []
        for i in range(row_count):
            rows.append({
                "yt_number": request.POST.get(f"row_{i}_yt_number", "").strip(),
                "description": request.POST.get(f"row_{i}_description", "").strip(),
                "category": request.POST.get(f"row_{i}_category", "").strip(),
                "interchanges": request.POST.get(f"row_{i}_interchanges", "[]"),
            })
        result = import_youtech_rows(rows)
        return render(request, "catalog/part_import_pdf_report.html", {
            "report": result["report"],
            "created": result["created"],
            "updated": result["updated"],
            "skipped": result["skipped"],
            "total": row_count,
        })

    # ---- Step 2: Parse uploaded PDF, render preview ----
    if request.method == "POST" and request.POST.get("step") == "parse":
        pdf_file = request.FILES.get("pdf_file")
        if not pdf_file:
            messages.error(request, "Please select a PDF file.")
            return redirect("catalog:part_import_pdf")
        if not pdf_file.name.lower().endswith(".pdf"):
            messages.error(request, "File must be a .pdf file.")
            return redirect("catalog:part_import_pdf")
        logger.info("[PDF Import] Parsing '%s' ...", pdf_file.name)
        try:
            entries = parse_youtech_pdf(pdf_file)
        except Exception as exc:
            logger.error("[PDF Import] Parse error: %s", exc)
            messages.error(request, f"Error reading PDF: {exc}")
            return redirect("catalog:part_import_pdf")

        if not entries:
            logger.warning("[PDF Import] No entries found in '%s'", pdf_file.name)
            messages.warning(request, "No entries found in the PDF.")
            return redirect("catalog:part_import_pdf")

        issues_count = sum(len(e.get("issues", [])) for e in entries)
        logger.info("[PDF Import] Parsed %d entries from '%s' (%d issues)",
                    len(entries), pdf_file.name, issues_count)

        # Annotate with existing-part status and pre-serialised interchange JSON
        existing_yts = set(
            Part.objects.filter(yt_number__in=[e["yt_number"] for e in entries])
            .values_list("yt_number", flat=True)
        )
        for e in entries:
            e["exists"] = e["yt_number"] in existing_yts
            e["interchanges_json"] = json.dumps(e["interchanges"])

        return render(request, "catalog/part_import_pdf_preview.html", {
            "entries": entries,
            "categories": categories,
            "filename": pdf_file.name,
            "total": len(entries),
        })

    # ---- Step 1: Show upload form ----
    return render(request, "catalog/part_import_pdf.html", {
        "categories": categories,
    })
