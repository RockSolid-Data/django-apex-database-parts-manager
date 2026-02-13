from django import forms

from .models import Application, ApplicationUnit, ApplicationSpecification, BOM, BOMItem, CrossReference, GearReductionSubstitution, Part, Substitute, Unit


class ApplicationForm(forms.ModelForm):
    """Form for creating / editing an Application."""

    class Meta:
        model = Application
        fields = [
            "name", "make", "engine", "year", "mfr", "volt", "amp",
            "part_number", "other_number", "unit_number", "options", "notes",
            "is_active",
        ]
        widgets = {
            "options": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            else:
                field.widget.attrs.setdefault("class", "form-control")


class UnitForm(forms.ModelForm):
    """Form for creating / editing a Unit, with fields grouped by category."""

    class Meta:
        model = Unit
        fields = [
            # Identification
            "unit_number", "yt_number", "oem", "j_and_n_number",
            "model_cat_number", "unit_type", "manufacturer", "family",
            # Electrical
            "voltage", "kw_hp", "phase", "fla", "amp_rating",
            "full_load_eff", "power_rating",
            # Mechanical
            "rpm", "frame", "enclosure", "rotation", "mount_type",
            "flange_type", "housing_type", "housing", "weight", "bearings",
            "design", "type", "service_factor", "duty_cycle", "speed_ratio",
            "grounding", "insulation_class", "overload_protection",
            "c_dimension", "u_dimension",
            # Starter-specific
            "tooth_quantity", "nose_type", "over_crank_protection",
            "solenoid_attached",
            # Generator-specific
            "circuit_type", "brush_type", "regulation_type",
            # Alternator-specific
            "fan_type", "regulator_type",
            # Other
            "reclockable_flange", "with_mounting_shims", "with_hardware",
            "bolt_holes", "clocking_degrees", "drive",
            # Descriptive
            "unit_attributes", "notes",
            # Pricing
            "new_unit_price", "rebuilt_unit_price",
            # Images
            "unit_image", "plug_image",
            # Metadata
            "is_active",
        ]
        widgets = {
            "unit_attributes": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    # Fieldset definitions used by the template to render grouped sections
    FIELDSETS = [
        ("Identification", [
            "unit_number", "yt_number", "oem", "j_and_n_number",
            "model_cat_number", "unit_type", "manufacturer", "family",
        ]),
        ("Electrical", [
            "voltage", "kw_hp", "phase", "fla", "amp_rating",
            "full_load_eff", "power_rating",
        ]),
        ("Mechanical", [
            "rpm", "frame", "enclosure", "rotation", "mount_type",
            "flange_type", "housing_type", "housing", "weight", "bearings",
            "design", "type", "service_factor", "duty_cycle", "speed_ratio",
            "grounding", "insulation_class", "overload_protection",
            "c_dimension", "u_dimension",
        ]),
        ("Starter-Specific", [
            "tooth_quantity", "nose_type", "over_crank_protection",
            "solenoid_attached",
        ]),
        ("Generator-Specific", [
            "circuit_type", "brush_type", "regulation_type",
        ]),
        ("Alternator-Specific", [
            "fan_type", "regulator_type",
        ]),
        ("Other", [
            "reclockable_flange", "with_mounting_shims", "with_hardware",
            "bolt_holes", "clocking_degrees", "drive",
        ]),
        ("Descriptive", [
            "unit_attributes", "notes",
        ]),
        ("Pricing", [
            "new_unit_price", "rebuilt_unit_price",
        ]),
        ("Images", [
            "unit_image", "plug_image",
        ]),
        ("Status", [
            "is_active",
        ]),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add Bootstrap classes to all fields
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            elif isinstance(field.widget, forms.FileInput):
                field.widget.attrs.setdefault("class", "form-control")
            else:
                field.widget.attrs.setdefault("class", "form-control")


class ApplicationUnitLinkForm(forms.ModelForm):
    """Form for linking a unit to an application."""

    class Meta:
        model = ApplicationUnit
        fields = ["unit", "position", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {
            "unit": "Unit",
        }

    def __init__(self, *args, application=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.application = application
        if application:
            # Exclude units already linked to this application
            linked_ids = application.units.values_list("pk", flat=True)
            self.fields["unit"].queryset = (
                Unit.objects.filter(is_active=True).exclude(pk__in=linked_ids).order_by("unit_number")
            )
        self.fields["unit"].widget.attrs["class"] = "form-select"
        self.fields["position"].widget.attrs["class"] = "form-control"
        self.fields["notes"].widget.attrs["class"] = "form-control"


class PartForm(forms.ModelForm):
    """Form for creating / editing a Part."""

    class Meta:
        model = Part
        fields = [
            "part_number", "part_name", "key", "yt_number", "j_and_n", "oem_number",
            "item_no", "category", "type", "oem_type", "item_typ", "oem",
            "primary_vendor", "catalog", "plug_id",
            "price", "cost_price",
            "stock_quantity", "reorder_qty", "bin_number",
            "description", "foot_notes", "superseding_notes",
            "has_picture", "has_interchange", "has_superseding",
            "image", "unit", "is_active",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "foot_notes": forms.Textarea(attrs={"rows": 2}),
            "superseding_notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            elif isinstance(field.widget, forms.FileInput):
                field.widget.attrs.setdefault("class", "form-control")
            else:
                field.widget.attrs.setdefault("class", "form-control")


class BOMForm(forms.ModelForm):
    """Form for creating / editing a BOM."""

    class Meta:
        model = BOM
        fields = ["name", "description", "unit", "application"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")
        self.fields["unit"].queryset = Unit.objects.filter(is_active=True).order_by("unit_number")
        self.fields["application"].queryset = Application.objects.filter(is_active=True).order_by("name")


class BOMItemForm(forms.ModelForm):
    """Form for adding a part to a BOM (BOMItem)."""

    class Meta:
        model = BOMItem
        fields = [
            "part", "description", "notes",
            "unit_qty", "stock_qty", "bin_number",
            "oem_number", "j_and_n", "yt_number",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, bom=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.bom = bom
        if bom:
            # Exclude parts already in this BOM (when adding); when editing, include current part
            existing_part_ids = list(bom.items.values_list("part_id", flat=True))
            if self.instance and self.instance.pk:
                existing_part_ids = [pid for pid in existing_part_ids if pid != self.instance.part_id]
            self.fields["part"].queryset = (
                Part.objects.filter(is_active=True)
                .exclude(pk__in=existing_part_ids)
                .order_by("part_number")
            )
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["part"].widget.attrs["class"] = "form-select"


class CrossReferenceForm(forms.ModelForm):
    """Form for adding a cross-reference unit."""

    class Meta:
        model = CrossReference
        fields = ["cross_ref_unit", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {
            "cross_ref_unit": "Cross-Reference Unit",
        }

    def __init__(self, *args, unit=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.unit = unit
        # Exclude the current unit from the dropdown
        if unit:
            self.fields["cross_ref_unit"].queryset = (
                Unit.objects.filter(is_active=True).exclude(pk=unit.pk)
            )
        self.fields["cross_ref_unit"].widget.attrs["class"] = "form-select"
        self.fields["notes"].widget.attrs["class"] = "form-control"


class SubstituteForm(forms.ModelForm):
    """Form for adding a substitute unit."""

    class Meta:
        model = Substitute
        fields = ["substitute_unit", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {
            "substitute_unit": "Substitute Unit",
        }

    def __init__(self, *args, unit=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.unit = unit
        if unit:
            self.fields["substitute_unit"].queryset = (
                Unit.objects.filter(is_active=True).exclude(pk=unit.pk)
            )
        self.fields["substitute_unit"].widget.attrs["class"] = "form-select"
        self.fields["notes"].widget.attrs["class"] = "form-control"


class GearReductionForm(forms.ModelForm):
    """Form for adding / editing a gear reduction substitution."""

    class Meta:
        model = GearReductionSubstitution
        fields = ["number", "description", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class ApplicationSpecificationForm(forms.ModelForm):
    """Form for adding / editing an application specification (8.7)."""

    class Meta:
        model = ApplicationSpecification
        fields = ["category", "type", "specification"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
