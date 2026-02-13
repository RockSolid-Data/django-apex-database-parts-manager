from datetime import date, datetime, timedelta

from decimal import Decimal

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from catalog.models import Part, Unit

from .forms import CompanySettingsForm, CustomerForm, InvoiceCreateForm, InvoiceItemFormSet
from .models import CompanySettings, Customer, Invoice, InvoiceItem


def _format_customer_address(customer):
    """Format customer address fields into inline text for Invoice.address."""
    parts = []
    if customer.address_line1:
        parts.append(customer.address_line1)
    if customer.address_line2:
        parts.append(customer.address_line2)
    if customer.city or customer.state or customer.zip_code:
        line = ", ".join(
            x for x in [customer.city, customer.state, customer.zip_code] if x
        )
        if line:
            parts.append(line)
    return "\n".join(parts) if parts else ""


def invoice_list(request):
    """Invoice list with search, filters, table with View/Edit actions."""
    # Auto-update overdue: past due_date and not PAID/CANCELLED → OVERDUE
    today = date.today()
    Invoice.objects.filter(
        due_date__lt=today,
        status__in=[Invoice.Status.DRAFT, Invoice.Status.SENT]
    ).update(status=Invoice.Status.OVERDUE)

    invoices = Invoice.objects.select_related("customer").order_by("-date")

    # --- Text search (invoice #, customer, supplier via items) ---
    q = request.GET.get("q", "").strip()
    if q:
        invoices = invoices.filter(
            Q(invoice_number__icontains=q)
            | Q(customer_name__icontains=q)
            | Q(customer__name__icontains=q)
            | Q(items__part__primary_vendor__icontains=q)
        ).distinct()

    # --- Status filter ---
    filter_status = request.GET.get("status", "").strip()
    if filter_status:
        invoices = invoices.filter(status=filter_status)

    # --- Date From filter ---
    filter_date_from = request.GET.get("date_from", "").strip()
    if filter_date_from:
        invoices = invoices.filter(date__gte=filter_date_from)

    # --- Supplier filter (invoices with items from this supplier) ---
    filter_supplier = request.GET.get("supplier", "").strip()
    if filter_supplier:
        invoices = invoices.filter(
            items__part__primary_vendor=filter_supplier
        ).distinct()

    # --- Build filter choices ---
    status_choices = Invoice.Status.choices
    supplier_choices = (
        Part.objects.filter(invoice_items__isnull=False)
        .exclude(primary_vendor="")
        .values_list("primary_vendor", flat=True)
        .distinct()
        .order_by("primary_vendor")
    )

    due_soon_end = today + timedelta(days=7)
    context = {
        "invoices": invoices,
        "q": q,
        "filter_status": filter_status,
        "filter_date_from": filter_date_from,
        "filter_supplier": filter_supplier,
        "status_choices": status_choices,
        "supplier_choices": supplier_choices,
        "today": today,
        "due_soon_end": due_soon_end,
        "company_settings": CompanySettings.get(),
    }
    if request.GET.get("print") == "1":
        return render(request, "invoicing/invoice_list_print.html", context)
    return render(request, "invoicing/invoice_list.html", context)


def invoice_report(request):
    """Print-friendly invoice report with status, date range, and report type filters."""
    invoices = Invoice.objects.select_related("customer").order_by("-date")

    # --- Status filter (multi-select) ---
    filter_statuses = request.GET.getlist("status")
    filter_statuses = [s.strip() for s in filter_statuses if s.strip()]
    if filter_statuses:
        invoices = invoices.filter(status__in=filter_statuses)

    # --- Date range ---
    filter_date_from = request.GET.get("date_from", "").strip()
    filter_date_to = request.GET.get("date_to", "").strip()
    if filter_date_from:
        invoices = invoices.filter(date__gte=filter_date_from)
    if filter_date_to:
        invoices = invoices.filter(date__lte=filter_date_to)

    report_type = request.GET.get("report_type", "detailed").strip() or "detailed"
    if report_type not in ("detailed", "customer_summary"):
        report_type = "detailed"

    # Always group by customer for per-customer sections
    from collections import defaultdict

    by_customer = defaultdict(lambda: {"invoices": [], "total": Decimal("0")})
    for inv in invoices:
        name = inv.get_bill_to_name() or "—"
        by_customer[name]["invoices"].append(inv)
        by_customer[name]["total"] += inv.total
    customer_summary = [
        {"name": name, "invoices": data["invoices"], "total": data["total"], "count": len(data["invoices"])}
        for name, data in sorted(by_customer.items())
    ]

    grand_total = sum(inv.total for inv in invoices)
    company_settings = CompanySettings.get()

    def _fmt_date(s):
        if not s:
            return ""
        try:
            dt = datetime.strptime(s, "%Y-%m-%d")
            return dt.strftime("%m/%d/%Y")
        except ValueError:
            return s

    context = {
        "invoices": list(invoices),
        "customer_summary": customer_summary,
        "report_type": report_type,
        "filter_statuses": filter_statuses,
        "filter_date_from": filter_date_from,
        "filter_date_to": filter_date_to,
        "date_from_display": _fmt_date(filter_date_from),
        "date_to_display": _fmt_date(filter_date_to),
        "status_choices": Invoice.Status.choices,
        "grand_total": grand_total,
        "company_settings": company_settings,
    }
    return render(request, "invoicing/invoice_report.html", context)


def add_to_invoice(request):
    """
    Add a unit or part to an invoice (8.1, 8.2).
    GET: Show choose page (create new invoice or add to existing).
    POST: Add item to selected invoice and redirect to edit.
    """
    unit_pk = request.GET.get("unit") or request.POST.get("unit")
    part_pk = request.GET.get("part") or request.POST.get("part")

    unit = None
    part = None
    item_label = None
    item_description = ""
    item_price = Decimal("0")

    if unit_pk:
        unit = get_object_or_404(Unit, pk=unit_pk)
        item_label = f"Unit {unit.unit_number}"
        item_description = unit.unit_number
        if unit.unit_type:
            item_description = f"{unit.unit_type.name} — {unit.unit_number}"
        item_price = unit.rebuilt_unit_price or unit.new_unit_price or Decimal("0")
    elif part_pk:
        part = get_object_or_404(Part, pk=part_pk)
        item_label = f"Part {part.part_number}"
        item_description = part.part_name or part.part_number
        item_price = part.price or Decimal("0")
    else:
        messages.error(request, "Please specify a unit or part to add.")
        return redirect("invoicing:invoice_list")

    if request.method == "POST":
        invoice_pk = request.POST.get("invoice")
        if not invoice_pk:
            messages.error(request, "Please select an invoice.")
            qs = f"?unit={unit_pk}" if unit_pk else f"?part={part_pk}"
            return redirect(request.path + qs)
        invoice = get_object_or_404(Invoice, pk=invoice_pk)
        qty = 1
        if part and part.stock_quantity < qty:
            messages.error(
                request,
                f"Not enough stock. {part.part_number} has {part.stock_quantity} in stock, "
                f"but {qty} requested.",
            )
            qs = f"?part={part_pk}"
            return redirect(request.path + qs)
        InvoiceItem.objects.create(
            invoice=invoice,
            part=part,
            unit=unit,
            description=item_description[:500],
            quantity=qty,
            unit_price=item_price,
        )
        invoice.recalculate_totals()
        messages.success(request, f"{item_label} added to {invoice.invoice_number}.")
        return redirect("invoicing:invoice_edit", pk=invoice.pk)

    # GET: show choose page
    invoices = Invoice.objects.filter(
        status__in=[Invoice.Status.DRAFT, Invoice.Status.SENT]
    ).select_related("customer").order_by("-date")[:50]

    create_new_url = reverse("invoicing:invoice_create")
    if unit_pk:
        create_new_url += f"?unit={unit_pk}"
    else:
        create_new_url += f"?part={part_pk}"

    return render(request, "invoicing/add_to_invoice.html", {
        "unit": unit,
        "part": part,
        "item_label": item_label,
        "item_price": item_price,
        "invoices": invoices,
        "create_new_url": create_new_url,
    })


def invoice_cancel(request, pk):
    """Cancel an invoice (set status to CANCELLED). POST only."""
    if request.method != "POST":
        return redirect("invoicing:invoice_list")
    invoice = get_object_or_404(Invoice, pk=pk)
    if invoice.status != Invoice.Status.CANCELLED:
        invoice.status = Invoice.Status.CANCELLED
        invoice.save(update_fields=["status", "updated_at"])
        messages.success(request, f"Invoice {invoice.invoice_number} cancelled.")
    return redirect(reverse("invoicing:invoice_list") + "?status=CANCELLED")


def invoice_detail(request, pk):
    """Invoice detail (full implementation in 7.6)."""
    invoice = get_object_or_404(
        Invoice.objects.select_related("customer").prefetch_related("items"),
        pk=pk,
    )
    return render(request, "invoicing/invoice_detail.html", {
        "invoice": invoice,
        "company_settings": CompanySettings.get(),
    })


def invoice_print(request, pk):
    """Print-friendly invoice view (8.4). Auto-sets status to Sent when printing Draft."""
    invoice = get_object_or_404(
        Invoice.objects.select_related("customer").prefetch_related("items"),
        pk=pk,
    )
    if invoice.status == Invoice.Status.DRAFT:
        invoice.status = Invoice.Status.SENT
        invoice.save(update_fields=["status", "updated_at"])
    company_settings = CompanySettings.get()
    return render(request, "invoicing/invoice_print.html", {
        "invoice": invoice,
        "company_settings": company_settings,
    })


def invoice_edit(request, pk):
    """Edit existing invoice (same fields as create); recalc totals on save."""
    invoice = get_object_or_404(
        Invoice.objects.select_related("customer").prefetch_related("items"),
        pk=pk,
    )
    if request.method == "POST":
        form = InvoiceCreateForm(request.POST, instance=invoice, edit=True)
        formset = InvoiceItemFormSet(request.POST, instance=invoice)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            invoice.recalculate_totals()
            messages.success(request, f"Invoice {invoice.invoice_number} updated.")
            return redirect("invoicing:invoice_detail", pk=invoice.pk)
    else:
        form = InvoiceCreateForm(instance=invoice, edit=True)
        formset = InvoiceItemFormSet(instance=invoice)

    parts_data = list(
        Part.objects.filter(is_active=True)
        .values("id", "part_number", "part_name", "price")
        .order_by("part_number")
    )
    for p in parts_data:
        p["price"] = str(p["price"]) if p["price"] is not None else "0"

    return render(request, "invoicing/invoice_edit.html", {
        "form": form,
        "formset": formset,
        "invoice": invoice,
        "parts_data": parts_data,
        "company_settings": CompanySettings.get(),
    })


def invoice_create(request, invoice=None):
    """Create new invoice with customer, items, totals.
    Accepts ?unit=<pk> or ?part=<pk> to pre-fill the first line item (8.1, 8.2).
    Accepts ?customer=<pk> to pre-fill customer info and due_date from customer net terms.
    """
    prefill_unit = None
    prefill_part = None
    prefill_customer = None
    if request.method == "GET":
        unit_pk = request.GET.get("unit")
        part_pk = request.GET.get("part")
        customer_pk = request.GET.get("customer")
        if unit_pk:
            prefill_unit = Unit.objects.filter(pk=unit_pk).first()
        if part_pk:
            prefill_part = Part.objects.filter(pk=part_pk).first()
        if customer_pk:
            prefill_customer = Customer.objects.filter(pk=customer_pk).first()

    if request.method == "POST":
        form = InvoiceCreateForm(request.POST, instance=invoice)
        if form.is_valid():
            inv = form.save(commit=False)
            if not inv.pk:
                inv.invoice_number = CompanySettings.get().get_next_invoice_number()
            inv.save()
            formset = InvoiceItemFormSet(request.POST, instance=inv)
            if formset.is_valid():
                formset.save()
                inv.recalculate_totals()
                messages.success(request, f"Invoice {inv.invoice_number} created.")
                return redirect("invoicing:invoice_detail", pk=inv.pk)
            else:
                invoice = inv
        else:
            formset = InvoiceItemFormSet(request.POST, instance=invoice) if invoice else InvoiceItemFormSet(instance=Invoice())
    else:
        today = date.today()
        if invoice:
            form = InvoiceCreateForm(instance=invoice)
        else:
            # Compute due_date from net terms (customer override or company default)
            if prefill_customer:
                due_date = prefill_customer.get_due_date(today)
                tax_rate = prefill_customer.get_effective_tax_rate()
                initial = {
                    "customer": prefill_customer.pk,
                    "date": today,
                    "due_date": due_date,
                    "tax_rate": tax_rate,
                    "status": Invoice.Status.DRAFT,
                    "customer_name": prefill_customer.name,
                    "contact_name": "",
                    "phone": prefill_customer.phone or "",
                    "email": prefill_customer.email or "",
                    "address": _format_customer_address(prefill_customer),
                }
            else:
                company_settings = CompanySettings.get()
                due_date = company_settings.get_due_date(today)
                initial = {
                    "date": today,
                    "due_date": due_date,
                    "tax_rate": company_settings.default_tax_rate,
                    "status": Invoice.Status.DRAFT,
                }
            form = InvoiceCreateForm(initial=initial)

        inv_instance = invoice or Invoice()
        initial_forms = []
        if prefill_unit:
            desc = prefill_unit.unit_number
            if prefill_unit.unit_type:
                desc = f"{prefill_unit.unit_type.name} — {prefill_unit.unit_number}"
            price = prefill_unit.rebuilt_unit_price or prefill_unit.new_unit_price or Decimal("0")
            initial_forms.append({
                "unit": prefill_unit,
                "description": desc[:500],
                "unit_price": price,
            })
        elif prefill_part:
            desc = prefill_part.part_name or prefill_part.part_number
            price = prefill_part.price or Decimal("0")
            initial_forms.append({
                "part": prefill_part,
                "description": (desc or "")[:500],
                "unit_price": price,
            })
        formset = InvoiceItemFormSet(instance=inv_instance, initial=initial_forms if initial_forms else None)

    parts_data = list(
        Part.objects.filter(is_active=True)
        .values("id", "part_number", "part_name", "price")
        .order_by("part_number")
    )
    for p in parts_data:
        p["price"] = str(p["price"]) if p["price"] is not None else "0"

    return render(request, "invoicing/invoice_create.html", {
        "form": form,
        "formset": formset,
        "invoice": invoice,
        "parts_data": parts_data,
        "prefill_customer": prefill_customer,
        "company_settings": CompanySettings.get(),
    })


def customer_list(request):
    """List customers with search."""
    customers = Customer.objects.order_by("name")

    q = request.GET.get("q", "").strip()
    if q:
        customers = customers.filter(
            Q(name__icontains=q)
            | Q(email__icontains=q)
            | Q(phone__icontains=q)
            | Q(city__icontains=q)
            | Q(state__icontains=q)
            | Q(notes__icontains=q)
        )

    show_inactive = request.GET.get("inactive", "").lower() == "1"
    if not show_inactive:
        customers = customers.filter(is_active=True)

    context = {"customers": customers, "q": q, "show_inactive": show_inactive}
    if request.GET.get("print") == "1":
        return render(request, "invoicing/customer_list_print.html", context)
    return render(request, "invoicing/customer_list.html", context)


def customer_create(request):
    """Create a new customer."""
    if request.method == "POST":
        form = CustomerForm(request.POST)
        if form.is_valid():
            customer = form.save()
            messages.success(request, f"Customer '{customer.name}' created.")
            return redirect("invoicing:customer_list")
    else:
        form = CustomerForm()

    return render(request, "invoicing/customer_form.html", {
        "form": form,
        "customer": None,
        "title": "Add New Customer",
    })


def customer_edit(request, pk):
    """Edit a customer."""
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == "POST":
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, f"Customer '{customer.name}' updated.")
            return redirect("invoicing:customer_list")
    else:
        form = CustomerForm(instance=customer)

    return render(request, "invoicing/customer_form.html", {
        "form": form,
        "customer": customer,
        "title": "Edit Customer",
    })


def customer_delete(request, pk):
    """Delete a customer."""
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == "POST":
        name = customer.name
        customer.delete()
        messages.success(request, f"Customer '{name}' deleted.")
        return redirect("invoicing:customer_list")
    return redirect("invoicing:customer_edit", pk=pk)


def settings_view(request):
    """Company settings: name, logo, contact info, default net terms."""
    settings_obj = CompanySettings.get()
    if request.method == "POST":
        form = CompanySettingsForm(request.POST, request.FILES, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Settings saved.")
            return redirect("invoicing:settings")
    else:
        form = CompanySettingsForm(instance=settings_obj)

    return render(request, "invoicing/settings.html", {
        "form": form,
        "settings_obj": settings_obj,
    })
