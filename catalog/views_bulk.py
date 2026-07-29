import logging

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import Application, Part, Unit

log = logging.getLogger(__name__)

PART_BULK_ACTIONS = {
    "change_category": {"field": "category", "type": "text"},
    "change_vendor": {"field": "primary_vendor", "type": "text"},
    "change_voltage": {"field": "voltage", "type": "text"},
    "toggle_track_inventory": {"field": "track_inventory", "type": "bool", "label": "Track Inventory"},
    "delete": {"field": None, "type": "delete"},
}

UNIT_BULK_ACTIONS = {
    "change_unit_type": {"field": "unit_type_category", "type": "text", "label": "Unit Type"},
    "change_family": {"field": "family", "type": "text"},
    "change_oem": {"field": "oem", "type": "text", "label": "OEM"},
    "change_voltage": {"field": "voltage", "type": "text"},
    "delete": {"field": None, "type": "delete"},
}

APPLICATION_BULK_ACTIONS = {
    "change_make": {"field": "make", "type": "text"},
    "change_year": {"field": "year", "type": "text"},
    "change_unit_type": {"field": "unit_type_name", "type": "text", "label": "Unit Type"},
    "change_volt": {"field": "volt", "type": "text", "label": "Volt"},
    "delete": {"field": None, "type": "delete"},
}

# Backward-compatible alias used by existing parts tests / imports.
BULK_ACTIONS = PART_BULK_ACTIONS


def _redirect_with_query(list_url_name, request):
    qs = request.GET.urlencode()
    redirect_url = reverse(list_url_name)
    if qs:
        redirect_url += "?" + qs
    return redirect_url


def _parse_ids(raw_ids):
    return [int(x) for x in raw_ids.split(",") if x.strip().isdigit()]


def _field_label(spec):
    if spec.get("label"):
        return spec["label"]
    field = spec.get("field") or ""
    return field.replace("_", " ").title()


def _run_bulk_action(request, *, model, actions, list_url_name, noun):
    redirect_url = _redirect_with_query(list_url_name, request)

    action = request.POST.get("action", "")
    raw_ids = request.POST.get("ids", "").strip()
    value = request.POST.get("value", "").strip()

    if action not in actions:
        messages.error(request, "Invalid bulk action.")
        return redirect(redirect_url)

    pk_list = _parse_ids(raw_ids)
    if not pk_list:
        messages.error(request, f"No {noun}s selected.")
        return redirect(redirect_url)

    spec = actions[action]
    qs = model.objects.filter(pk__in=pk_list)
    count = qs.count()

    if spec["type"] == "text":
        qs.update(**{spec["field"]: value})
        label = _field_label(spec)
        messages.success(
            request,
            f"Updated {label} to \u2018{value}\u2019 on {count} {noun}{'s' if count != 1 else ''}.",
        )

    elif spec["type"] == "bool":
        bool_val = value.lower() in ("true", "1", "on", "yes")
        qs.update(**{spec["field"]: bool_val})
        state = "on" if bool_val else "off"
        label = _field_label(spec)
        messages.success(
            request,
            f"Set {label} {state} for {count} {noun}{'s' if count != 1 else ''}.",
        )

    elif spec["type"] == "delete":
        confirm = request.POST.get("confirm", "")
        if confirm != "1":
            messages.error(request, "Delete requires confirm.")
            return redirect(redirect_url)
        qs.delete()
        messages.success(request, f"Deleted {count} {noun}{'s' if count != 1 else ''}.")

    log.info("Bulk %s on %d %ss", action, count, noun)
    return redirect(redirect_url)


@require_POST
def bulk_action(request):
    return _run_bulk_action(
        request,
        model=Part,
        actions=PART_BULK_ACTIONS,
        list_url_name="catalog:part_list",
        noun="part",
    )


@require_POST
def unit_bulk_action(request):
    return _run_bulk_action(
        request,
        model=Unit,
        actions=UNIT_BULK_ACTIONS,
        list_url_name="catalog:unit_list",
        noun="unit",
    )


@require_POST
def application_bulk_action(request):
    return _run_bulk_action(
        request,
        model=Application,
        actions=APPLICATION_BULK_ACTIONS,
        list_url_name="catalog:application_list",
        noun="application",
    )
