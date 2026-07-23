import logging

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import Part

log = logging.getLogger(__name__)

BULK_ACTIONS = {
    "change_category": {"field": "category", "type": "text"},
    "change_vendor": {"field": "primary_vendor", "type": "text"},
    "change_voltage": {"field": "voltage", "type": "text"},
    "toggle_track_inventory": {"field": "track_inventory", "type": "bool"},
    "delete": {"field": None, "type": "delete"},
}


@require_POST
def bulk_action(request):
    qs = request.GET.urlencode()
    redirect_url = reverse("catalog:part_list")
    if qs:
        redirect_url += "?" + qs

    action = request.POST.get("action", "")
    raw_ids = request.POST.get("ids", "").strip()
    value = request.POST.get("value", "").strip()

    if action not in BULK_ACTIONS:
        messages.error(request, "Invalid bulk action.")
        return redirect(redirect_url)

    pk_list = [int(x) for x in raw_ids.split(",") if x.strip().isdigit()]
    if not pk_list:
        messages.error(request, "No parts selected.")
        return redirect(redirect_url)

    spec = BULK_ACTIONS[action]
    parts = Part.objects.filter(pk__in=pk_list)
    count = parts.count()

    if spec["type"] == "text":
        parts.update(**{spec["field"]: value})
        label = spec["field"].replace("_", " ").title()
        messages.success(request, f"Updated {label} to \u2018{value}\u2019 on {count} part{'s' if count != 1 else ''}.")

    elif spec["type"] == "bool":
        bool_val = value.lower() in ("true", "1", "on", "yes")
        parts.update(**{spec["field"]: bool_val})
        state = "on" if bool_val else "off"
        messages.success(request, f"Set Track Inventory {state} for {count} part{'s' if count != 1 else ''}.")

    elif spec["type"] == "delete":
        confirm = request.POST.get("confirm", "")
        if confirm != "1":
            messages.error(request, "Delete requires confirm.")
            return redirect(redirect_url)
        parts.delete()
        messages.success(request, f"Deleted {count} part{'s' if count != 1 else ''}.")

    log.info("Bulk %s on %d parts", action, count)
    return redirect(redirect_url)
