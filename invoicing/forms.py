from collections import defaultdict
from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory
from django.forms.models import BaseInlineFormSet

from catalog.models import Part

from .models import (
    CompanySettings,
    Customer,
    Invoice,
    InvoiceItem,
    NetTerms,
)


class InvoiceCreateForm(forms.ModelForm):
    """Form for creating a new invoice."""

    class Meta:
        model = Invoice
        fields = [
            "customer", "customer_name", "contact_name", "phone", "email", "address",
            "date", "due_date", "tax_rate",
            "notes", "private_notes", "status",
        ]
        widgets = {
            "customer": forms.Select(attrs={"class": "form-select"}),
            "customer_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter customer name"}),
            "contact_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter contact name"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter phone number"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "Enter email address"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Enter customer address"}),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "due_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "tax_rate": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "notes": forms.Textarea(attrs={
                "class": "form-control", "rows": 2,
                "placeholder": "Enter notes that will appear on the invoice for the customer..."
            }),
            "private_notes": forms.Textarea(attrs={
                "class": "form-control", "rows": 2,
                "placeholder": "Enter internal notes (not visible to customer)..."
            }),
            "status": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        edit = kwargs.pop("edit", False)
        super().__init__(*args, **kwargs)
        self.fields["customer"].required = False
        self.fields["customer"].queryset = Customer.objects.filter(is_active=True).order_by("name")
        self.fields["customer"].empty_label = "— Create new (no link) —"
        self.fields["customer_name"].required = True
        if edit:
            self.fields["status"].choices = list(Invoice.Status.choices)
        else:
            self.fields["status"].choices = [
                (Invoice.Status.DRAFT, "Draft"),
                (Invoice.Status.SENT, "Sent"),
                (Invoice.Status.PAID, "Paid"),
            ]


class InvoiceItemForm(forms.ModelForm):
    """Form for one invoice line item."""

    class Meta:
        model = InvoiceItem
        fields = ["part", "unit", "description", "quantity", "unit_price"]
        widgets = {
            "part": forms.Select(attrs={"class": "form-select form-select-sm item-part"}),
            "unit": forms.Select(attrs={"class": "form-select form-select-sm item-unit"}),
            "description": forms.TextInput(attrs={"class": "form-control form-control-sm item-desc"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control form-control-sm item-qty", "min": 1}),
            "unit_price": forms.NumberInput(attrs={"class": "form-control form-control-sm item-price", "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from catalog.models import Part, Unit
        self.fields["part"].queryset = Part.objects.filter(is_active=True).order_by("part_number")
        self.fields["part"].required = False
        self.fields["part"].empty_label = "— Select part —"
        self.fields["unit"].queryset = Unit.objects.filter(is_active=True).order_by("unit_number")
        self.fields["unit"].required = False
        self.fields["unit"].empty_label = "— Select unit —"


class InvoiceItemFormSet(BaseInlineFormSet):
    """Formset that validates part stock before saving."""

    def clean(self):
        super().clean()
        if self.errors:
            return
        # Sum quantity delta per part (positive = stock to decrement)
        parts_delta = defaultdict(int)
        for form in self.forms:
            if form in self.deleted_forms or not form.cleaned_data:
                continue
            part = form.cleaned_data.get("part")
            qty = form.cleaned_data.get("quantity") or 0
            if not part:
                continue
            if form.instance.pk:
                delta = qty - form.instance.quantity
            else:
                delta = qty
            if delta > 0:
                parts_delta[part.pk] += delta
        for part_id, delta in parts_delta.items():
            part = Part.objects.get(pk=part_id)
            if part.stock_quantity < delta:
                raise forms.ValidationError(
                    f"Not enough stock for {part.part_number}. "
                    f"Available: {part.stock_quantity}, requested: {delta}."
                )


InvoiceItemFormSet = inlineformset_factory(
    Invoice,
    InvoiceItem,
    form=InvoiceItemForm,
    formset=InvoiceItemFormSet,
    extra=9,
    min_num=1,
    validate_min=True,
    can_delete=True,
)


class CompanySettingsForm(forms.ModelForm):
    """Form for company settings (singleton)."""

    class Meta:
        model = CompanySettings
        fields = [
            "company_name", "logo",
            "email", "phone", "address",
            "default_net_terms", "default_net_days",
            "default_tax_rate",
            "invoice_number_prefix", "invoice_number_include_year", "invoice_number_include_month", "invoice_number_padding",
            "invoice_paper_size", "invoice_layout_style", "invoice_date_format", "invoice_currency_symbol",
        ]
        widgets = {
            "company_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Company name"}),
            "logo": forms.FileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "Company email"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Company phone"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Company address"}),
            "default_net_terms": forms.Select(attrs={"class": "form-select"}, choices=NetTerms.CHOICES),
            "default_net_days": forms.NumberInput(attrs={"class": "form-control", "min": 0, "placeholder": "e.g. 15"}),
            "default_tax_rate": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0, "placeholder": "e.g. 0"}),
            "invoice_number_prefix": forms.TextInput(attrs={"class": "form-control", "placeholder": "INV-"}),
            "invoice_number_include_year": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "invoice_number_include_month": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "invoice_number_padding": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 10, "placeholder": "4"}),
            "invoice_paper_size": forms.Select(attrs={"class": "form-select"}),
            "invoice_layout_style": forms.Select(attrs={"class": "form-select"}),
            "invoice_date_format": forms.Select(attrs={"class": "form-select"}),
            "invoice_currency_symbol": forms.TextInput(attrs={"class": "form-control", "placeholder": "$"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            elif not isinstance(field.widget, (forms.Select, forms.FileInput)):
                field.widget.attrs.setdefault("class", "form-control")


class CustomerForm(forms.ModelForm):
    """Form for creating / editing a Customer."""

    class Meta:
        model = Customer
        fields = [
            "name", "email", "phone",
            "address_line1", "address_line2", "city", "state", "zip_code",
            "notes", "is_active",
            "net_terms", "net_days",
            "tax_rate",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "net_terms": forms.Select(attrs={"class": "form-select"}),
            "net_days": forms.NumberInput(attrs={"class": "form-control", "min": 0, "placeholder": "e.g. 15"}),
            "tax_rate": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0, "placeholder": "Use company default"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["net_terms"].choices = [("", "Use company default")] + list(NetTerms.CHOICES)
        self.fields["net_terms"].required = False
        self.fields["tax_rate"].required = False
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            elif not isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-control")
