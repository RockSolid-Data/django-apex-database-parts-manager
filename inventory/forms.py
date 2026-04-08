from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory

from catalog.models import Part
from .models import Vendor, VendorContact


class InventoryItemForm(forms.Form):
    """Form for adding an inventory item (creates or updates Part)."""

    item_name = forms.CharField(
        label="Item Name",
        max_length=255,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    part_number = forms.CharField(
        label="Part Number",
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )
    supplier = forms.ModelChoiceField(
        label="Supplier",
        queryset=Vendor.objects.filter(is_active=True).order_by("name"),
        required=True,
        empty_label="Select supplier...",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    cost = forms.DecimalField(
        label="Cost",
        max_digits=10,
        decimal_places=2,
        required=True,
        min_value=Decimal("0"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    margin_pct = forms.DecimalField(
        label="Margin %",
        max_digits=5,
        decimal_places=2,
        required=True,
        min_value=Decimal("-100"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    quantity_purchased = forms.IntegerField(
        label="Quantity Purchased",
        required=True,
        min_value=0,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )
    quantity_available = forms.IntegerField(
        label="Quantity Available",
        required=True,
        min_value=0,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )

    def clean_part_number(self):
        part_number = self.cleaned_data.get("part_number", "").strip()
        if not part_number:
            raise forms.ValidationError("Part number is required.")
        return part_number



class VendorForm(forms.ModelForm):
    """Form for creating / editing a Vendor."""

    class Meta:
        model = Vendor
        fields = [
            "name", "contact_name", "email", "phone", "fax", "account_number",
            "address_line1", "address_line2", "city", "state", "zip_code",
            "remit_line1", "remit_line2", "remit_city", "remit_state", "remit_zip",
            "notes", "is_active",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            else:
                field.widget.attrs.setdefault("class", "form-control")


class VendorContactForm(forms.ModelForm):
    """Form for one vendor contact."""

    class Meta:
        model = VendorContact
        fields = ["name", "phone", "email", "fax", "department"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Contact name"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Phone"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "Email"}),
            "fax": forms.TextInput(attrs={"class": "form-control", "placeholder": "Fax"}),
            "department": forms.TextInput(attrs={"class": "form-control", "placeholder": "Department"}),
        }


VendorContactFormSet = inlineformset_factory(
    Vendor,
    VendorContact,
    form=VendorContactForm,
    extra=1,
    can_delete=True,
)
