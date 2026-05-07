from django import forms

from .models import Application, ApplicationUnit, ApplicationSpecification, BOM, BOMItem, CrossReference, GearReductionSubstitution, Part, PartInterchange, PartSubstitute, PartSuperseding, Substitute, Unit, UnitType


class ApplicationForm(forms.ModelForm):
    """Form for creating / editing an Application."""

    class Meta:
        model = Application
        fields = [
            "unit_number", "make", "model", "engine", "year",
            "mfr", "volt", "amp", "fuel_type", "vin",
            "alt_pulley", "unit_type_name", "other_number",
            "options", "notes",
            "is_active",
        ]
        widgets = {
            "options": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    FIELDSETS = [
        ("Notes", ["options", "notes"]),
        ("Status", ["is_active"]),
    ]

    DETAIL_FIELDS = [
        "unit_number", "make", "model", "engine",
        "year", "mfr", "volt",
        "amp", "fuel_type", "vin",
        "alt_pulley", "unit_type_name", "other_number",
    ]

    CHECKABLE_FIELDS = [
        "unit_number", "make", "model", "engine", "year",
        "mfr", "volt", "amp", "fuel_type", "vin",
        "alt_pulley", "unit_type_name", "other_number",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        if not any(cleaned.get(f) for f in self.CHECKABLE_FIELDS):
            raise forms.ValidationError("Please fill in at least one field before saving.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        name_parts = filter(None, [
            instance.unit_number, instance.make, instance.model, instance.engine,
        ])
        instance.name = " ".join(name_parts) or "Unnamed Application"

        from .models import ApplicationType
        specs = {}
        default_names = {
            "unit_number", "make", "model", "engine", "year", "mfr", "volt",
            "amp", "fuel_type", "vin", "alt_pulley", "unit_type_name",
            "other_number", "options", "notes",
        }
        try:
            at = ApplicationType.objects.prefetch_related("fields").get(name="Application")
            for f in at.fields.all():
                if f.field_name in default_names:
                    continue
                val = self.data.get(f"spec_{f.field_name}", "")
                specs[f.field_name] = val
        except ApplicationType.DoesNotExist:
            pass
        instance.type_specifications = specs

        if commit:
            instance.save()
            self._save_m2m()
        return instance


class UnitForm(forms.ModelForm):
    """Form for creating / editing a Unit, with fields grouped by category."""

    class Meta:
        model = Unit
        fields = [
            # Identification (always-visible)
            "unit_number", "yt_number", "oem", "model_cat_number",
            "voltage",
            # Unit type category (dropdown for dynamic fields)
            "unit_type_category",
            # Notes
            "description", "notes",
            # Attributes
            "unit_attributes",
            # Pricing
            "new_unit_price", "rebuilt_unit_price",
            # Images
            "unit_image", "plug_image",
            # Metadata
            "is_active",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "unit_attributes": forms.Textarea(attrs={"rows": 3}),
        }

    FIELDSETS = [
        ("Notes", [
            "description", "notes",
        ]),
        ("Attributes", [
            "unit_attributes",
        ]),
        ("Pricing", [
            "new_unit_price", "rebuilt_unit_price",
        ]),
        ("Images", [
            "unit_image", "plug_image",
        ]),
    ]

    UNIT_ALWAYS_VISIBLE = {
        "unit_number", "yt_number", "oem", "model_cat_number", "voltage",
    }

    CHECKABLE_FIELDS = [
        "unit_number", "yt_number", "oem", "j_and_n_number",
        "model_cat_number", "unit_type", "manufacturer", "family",
        "voltage", "description", "notes",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit_number"].required = False

        from .models import UnitTypeCategory
        db_categories = list(UnitTypeCategory.objects.values_list("name", flat=True))
        cat_choices = [("", "— Select Unit Type —")]
        cat_choices += [(k, k) for k in db_categories]

        current_val = self.initial.get("unit_type_category", "") or (self.instance.unit_type_category if self.instance.pk else "")
        known_keys = {c[0] for c in cat_choices}
        if current_val and current_val not in known_keys:
            cat_choices.append((current_val, current_val))

        self.fields["unit_type_category"].widget = forms.Select(choices=cat_choices)
        self.fields["unit_type_category"].widget.attrs.update({
            "class": "form-select",
            "id": "id_unit_type_category",
            "style": "min-width: 200px;",
        })

        for field_name, field in self.fields.items():
            if field_name == "unit_type_category":
                continue
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            elif isinstance(field.widget, forms.FileInput):
                field.widget.attrs.setdefault("class", "form-control")
            else:
                field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        if not any(cleaned.get(f) for f in self.CHECKABLE_FIELDS):
            raise forms.ValidationError("Please fill in at least one field before saving.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)

        from .models import UnitTypeCategory

        specs = {}
        utc = instance.unit_type_category
        field_defs = []
        try:
            cat_obj = UnitTypeCategory.objects.prefetch_related("fields").get(name=utc)
            field_defs = [
                {"name": f.field_name, "type": "text"}
                for f in cat_obj.fields.all()
            ]
        except UnitTypeCategory.DoesNotExist:
            pass
        protected = {"id", "pk", "created_at", "updated_at", "is_active"}
        model_field_names = {f.name for f in instance._meta.get_fields() if hasattr(f, "column")} - protected
        spec_to_model = {"j_n_number": "j_and_n_number"}
        for fd in field_defs:
            if fd["name"] in self.UNIT_ALWAYS_VISIBLE:
                continue
            post_key = f"spec_{fd['name']}"
            val = self.data.get(post_key, "")
            specs[fd["name"]] = val
            model_name = spec_to_model.get(fd["name"], fd["name"])
            if model_name in model_field_names:
                setattr(instance, model_name, val)
        instance.specifications = specs

        if commit:
            instance.save()
            self._save_m2m()
        return instance


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
        if self.is_bound and self.data.get("unit"):
            self.fields["unit"].queryset = Unit.objects.filter(pk=self.data["unit"])
        else:
            self.fields["unit"].queryset = Unit.objects.none()
        self.fields["unit"].widget.attrs.update({
            "class": "form-select js-ajax-select",
            "data-url": "/api/units/autocomplete/",
            "data-placeholder": "Search units...",
        })
        if application:
            self.fields["unit"].widget.attrs["data-exclude-app"] = application.pk
        self.fields["position"].widget.attrs["class"] = "form-control"
        self.fields["notes"].widget.attrs["class"] = "form-control"


class PartForm(forms.ModelForm):
    """Form for creating / editing a Part."""

    units = forms.ModelMultipleChoiceField(
        queryset=Unit.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={
            "class": "form-select js-ajax-select",
            "multiple": "multiple",
            "data-url": "/api/units/autocomplete/",
            "data-placeholder": "Search units...",
        }),
    )

    class Meta:
        model = Part
        fields = [
            "part_number", "part_name", "manufacturer_number", "yt_number", "j_and_n", "oem_number",
            "voltage", "item_no", "category", "type", "oem_type", "item_typ", "oem",
            "primary_vendor", "catalog", "plug_id",
            "cost_price", "markup_percent", "price",
            "track_inventory", "stock_quantity", "reorder_qty", "bin_number",
            "description", "foot_notes", "superseding_notes",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "foot_notes": forms.Textarea(attrs={"rows": 2}),
            "superseding_notes": forms.Textarea(attrs={"rows": 2}),
        }

    CHECKABLE_FIELDS = [
        "part_number", "part_name", "manufacturer_number", "yt_number",
        "j_and_n", "oem_number", "voltage", "type", "oem",
        "primary_vendor", "description",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["part_number"].required = False
        self.fields["stock_quantity"].required = False
        self.fields["reorder_qty"].required = False

        from .models import PartCategory
        db_categories = list(PartCategory.objects.values_list("name", flat=True))
        category_choices = [("", "— Select Category —")]
        category_choices += [(k, k) for k in db_categories]

        current_val = self.initial.get("category", "") or (self.instance.category if self.instance.pk else "")
        known_keys = {c[0] for c in category_choices}
        if current_val and current_val not in known_keys:
            category_choices.append((current_val, current_val))

        self.fields["category"].widget = forms.Select(choices=category_choices)
        self.fields["category"].widget.attrs["class"] = "form-select"
        self.fields["category"].widget.attrs["id"] = "id_category"
        self.fields["category"].widget.attrs["style"] = "min-width: 200px;"

        self.fields["part_number"].label = "Part Number"

        if self.is_bound:
            submitted_ids = self.data.getlist("units")
            if submitted_ids:
                self.fields["units"].queryset = Unit.objects.filter(pk__in=submitted_ids).only("pk", "unit_number")
            else:
                self.fields["units"].queryset = Unit.objects.none()
        elif self.instance.pk:
            selected_units = self.instance.units.all().only("pk", "unit_number")
            self.fields["units"].queryset = selected_units
            self.fields["units"].initial = selected_units
        else:
            self.fields["units"].queryset = Unit.objects.none()

        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(field.widget, (forms.Select, forms.SelectMultiple)):
                field.widget.attrs.setdefault("class", "form-select")
            elif isinstance(field.widget, forms.FileInput):
                field.widget.attrs.setdefault("class", "form-control")
            else:
                field.widget.attrs.setdefault("class", "form-control")

    ALWAYS_VISIBLE_FIELDS = {
        "part_number", "part_name", "manufacturer_number", "yt_number",
        "j_and_n", "oem_number", "voltage", "type", "oem", "primary_vendor",
    }

    def clean_stock_quantity(self):
        val = self.cleaned_data.get("stock_quantity")
        return val if val is not None else 0

    def clean_reorder_qty(self):
        val = self.cleaned_data.get("reorder_qty")
        return val if val is not None else 0

    def clean(self):
        cleaned = super().clean()
        if not any(cleaned.get(f) for f in self.CHECKABLE_FIELDS):
            raise forms.ValidationError("Please fill in at least one field before saving.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        from .models import PartCategory

        specs = {}
        category = instance.category
        field_defs = []
        try:
            cat_obj = PartCategory.objects.prefetch_related("fields").get(name=category)
            field_defs = [
                {"name": f.field_name, "label": f.field_label, "type": "text"}
                for f in cat_obj.fields.all()
            ]
        except PartCategory.DoesNotExist:
            pass
        protected = {"id", "pk", "created_at", "updated_at", "is_active"}
        model_field_names = {f.name for f in instance._meta.get_fields() if hasattr(f, "column")} - protected
        for fd in field_defs:
            if fd["name"] in self.ALWAYS_VISIBLE_FIELDS:
                continue
            post_key = f"spec_{fd['name']}"
            if fd["type"] == "checkbox":
                val = post_key in self.data
            else:
                val = self.data.get(post_key, "")
            specs[fd["name"]] = val
            if fd["name"] in model_field_names and not isinstance(val, bool):
                setattr(instance, fd["name"], val)
        instance.specifications = specs

        if commit:
            instance.save()
            self._save_m2m()
            instance.units.set(self.cleaned_data.get("units", []))
        return instance


class BOMForm(forms.ModelForm):
    """Form for creating / editing a BOM."""

    unit_type = forms.ModelChoiceField(
        queryset=UnitType.objects.all(),
        required=False,
        empty_label="— Select Unit Type —",
        widget=forms.Select(attrs={"class": "form-select js-searchable-select"}),
        label="Unit Type",
    )

    class Meta:
        model = BOM
        fields = ["name", "description", "unit", "application"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "name": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = False

        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            elif not isinstance(field.widget, forms.HiddenInput):
                field.widget.attrs.setdefault("class", "form-control")

        self.fields["unit"].label = "Unit Number"
        if self.is_bound and self.data.get("unit"):
            self.fields["unit"].queryset = Unit.objects.filter(pk=self.data["unit"])
        elif self.instance.pk and self.instance.unit_id:
            self.fields["unit"].queryset = Unit.objects.filter(pk=self.instance.unit_id)
        else:
            self.fields["unit"].queryset = Unit.objects.none()
        self.fields["unit"].widget.attrs.update({
            "class": "form-select js-ajax-select",
            "data-url": "/api/units/autocomplete/",
            "data-placeholder": "Search by unit number...",
        })

        if self.is_bound and self.data.get("application"):
            self.fields["application"].queryset = Application.objects.filter(pk=self.data["application"])
        elif self.instance.pk and self.instance.application_id:
            self.fields["application"].queryset = Application.objects.filter(pk=self.instance.application_id)
        else:
            self.fields["application"].queryset = Application.objects.none()
        self.fields["application"].widget.attrs.update({
            "class": "form-select js-ajax-select",
            "data-url": "/api/applications/autocomplete/",
            "data-placeholder": "Search applications...",
        })

        if self.instance.pk and self.instance.unit and self.instance.unit.unit_type_id:
            self.fields["unit_type"].initial = self.instance.unit.unit_type_id

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.unit:
            instance.name = str(instance.unit)
        if commit:
            instance.save()
        return instance


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

        part_key = self.add_prefix("part")
        if self.is_bound and self.data.get(part_key):
            self.fields["part"].queryset = Part.objects.filter(pk=self.data[part_key])
        elif self.instance.pk and self.instance.part_id:
            self.fields["part"].queryset = Part.objects.filter(pk=self.instance.part_id)
        else:
            self.fields["part"].queryset = Part.objects.none()

        self.fields["stock_qty"].required = False
        self.fields["unit_qty"].required = False

        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["part"].widget.attrs.update({
            "class": "form-select js-ajax-select",
            "data-url": "/api/parts/autocomplete/",
            "data-placeholder": "Search parts...",
        })
        if bom:
            self.fields["part"].widget.attrs["data-exclude-bom"] = bom.pk

    def clean_stock_qty(self):
        val = self.cleaned_data.get("stock_qty")
        return val if val is not None else 0

    def clean_unit_qty(self):
        val = self.cleaned_data.get("unit_qty")
        return val if val is not None else 1


class BOMItemInlineForm(forms.ModelForm):
    """Simplified part + qty row for inline BOM creation."""

    class Meta:
        model = BOMItem
        fields = ["part", "unit_qty"]

    def __init__(self, *args, **kwargs):
        kwargs.pop("bom", None)
        super().__init__(*args, **kwargs)
        self.fields["part"].required = False
        self.fields["unit_qty"].required = False

        part_key = self.add_prefix("part")
        if self.is_bound and self.data.get(part_key):
            self.fields["part"].queryset = Part.objects.filter(pk=self.data[part_key])
        else:
            self.fields["part"].queryset = Part.objects.none()

        self.fields["part"].widget.attrs.update({
            "class": "form-select js-ajax-select",
            "data-url": "/api/parts/autocomplete/",
            "data-placeholder": "Search parts...",
        })
        self.fields["unit_qty"].widget.attrs.update({
            "class": "form-control",
        })
        self.fields["unit_qty"].initial = 1


class CrossReferenceForm(forms.ModelForm):
    """Form for adding a cross-reference — either a unit or a manufacturer number."""

    class Meta:
        model = CrossReference
        fields = ["cross_ref_unit", "cross_ref_number", "interchange_type", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {
            "cross_ref_unit": "Cross-Reference Unit (optional)",
            "cross_ref_number": "Manufacturer Part Number",
            "interchange_type": "Cross Ref Name",
        }

    def __init__(self, *args, unit=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.unit = unit
        if self.is_bound and self.data.get("cross_ref_unit"):
            self.fields["cross_ref_unit"].queryset = Unit.objects.filter(pk=self.data["cross_ref_unit"])
        elif self.instance.pk and self.instance.cross_ref_unit_id:
            self.fields["cross_ref_unit"].queryset = Unit.objects.filter(pk=self.instance.cross_ref_unit_id)
        else:
            self.fields["cross_ref_unit"].queryset = Unit.objects.none()
        self.fields["cross_ref_unit"].required = False
        self.fields["cross_ref_unit"].widget.attrs.update({
            "class": "form-select js-ajax-select",
            "data-url": "/api/units/autocomplete/",
            "data-placeholder": "Search units...",
        })
        self.fields["cross_ref_number"].widget.attrs["class"] = "form-control"
        self.fields["interchange_type"].widget.attrs["class"] = "form-control"
        self.fields["notes"].widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned = super().clean()
        ref_unit = cleaned.get("cross_ref_unit")
        ref_number = cleaned.get("cross_ref_number", "").strip()
        if not ref_unit and not ref_number:
            raise forms.ValidationError(
                "Provide either a cross-reference unit or a manufacturer part number."
            )
        if ref_unit and not ref_number:
            cleaned["cross_ref_number"] = ref_unit.unit_number
        return cleaned


class SubstituteForm(forms.ModelForm):
    """Form for adding a substitute unit."""

    class Meta:
        model = Substitute
        fields = ["substitute_unit", "substitute_number", "substitute_unit_type", "substitute_supplier", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {
            "substitute_unit": "Substitute Unit (optional)",
            "substitute_number": "Unit Number",
            "substitute_unit_type": "Unit Type",
            "substitute_supplier": "Supplier",
        }

    def __init__(self, *args, unit=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.unit = unit
        self.fields["substitute_unit"].required = False
        if self.is_bound and self.data.get("substitute_unit"):
            self.fields["substitute_unit"].queryset = Unit.objects.filter(pk=self.data["substitute_unit"])
        elif self.instance.pk and self.instance.substitute_unit_id:
            self.fields["substitute_unit"].queryset = Unit.objects.filter(pk=self.instance.substitute_unit_id)
        else:
            self.fields["substitute_unit"].queryset = Unit.objects.none()
        self.fields["substitute_unit"].widget.attrs.update({
            "class": "form-select js-ajax-select",
            "data-url": "/api/units/autocomplete/",
            "data-placeholder": "Search units...",
        })
        for fname in ("substitute_number", "substitute_unit_type", "substitute_supplier", "notes"):
            self.fields[fname].widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned = super().clean()
        ref_unit = cleaned.get("substitute_unit")
        ref_number = cleaned.get("substitute_number", "").strip()
        if not ref_unit and not ref_number:
            raise forms.ValidationError(
                "Provide either a substitute unit or a unit number."
            )
        if ref_unit and not ref_number:
            cleaned["substitute_number"] = ref_unit.unit_number
        return cleaned


class GearReductionForm(forms.ModelForm):
    """Form for adding / editing a gear reduction substitution."""

    class Meta:
        model = GearReductionSubstitution
        fields = ["number", "unit_type", "supplier", "description", "notes"]
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


class PartSubstituteForm(forms.ModelForm):
    """Form for adding a substitute part link."""

    class Meta:
        model = PartSubstitute
        fields = ["substitute_part", "substitute_number", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}
        labels = {
            "substitute_part": "Substitute Part (optional)",
            "substitute_number": "Part Number",
        }

    def __init__(self, *args, part=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.part = part
        self.fields["substitute_part"].required = False
        if self.is_bound and self.data.get("substitute_part"):
            self.fields["substitute_part"].queryset = Part.objects.filter(pk=self.data["substitute_part"])
        elif self.instance.pk and self.instance.substitute_part_id:
            self.fields["substitute_part"].queryset = Part.objects.filter(pk=self.instance.substitute_part_id)
        else:
            self.fields["substitute_part"].queryset = Part.objects.none()
        self.fields["substitute_part"].widget.attrs.update({
            "class": "form-select js-ajax-select",
            "data-url": "/api/parts/autocomplete/",
            "data-placeholder": "Search parts...",
        })
        self.fields["substitute_number"].widget.attrs["class"] = "form-control"
        self.fields["notes"].widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned = super().clean()
        ref_part = cleaned.get("substitute_part")
        ref_number = cleaned.get("substitute_number", "").strip()
        if not ref_part and not ref_number:
            raise forms.ValidationError(
                "Provide either a substitute part or a part number."
            )
        if ref_part and not ref_number:
            cleaned["substitute_number"] = ref_part.part_number
        return cleaned


class PartInterchangeForm(forms.ModelForm):
    """Form for adding an interchange part link."""

    class Meta:
        model = PartInterchange
        fields = ["interchange_part", "interchange_number", "source_name", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}
        labels = {
            "interchange_part": "Interchange Part (optional)",
            "interchange_number": "Reference Number",
            "source_name": "Source / Name",
        }

    def __init__(self, *args, part=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.part = part
        self.fields["interchange_part"].required = False
        if self.is_bound and self.data.get("interchange_part"):
            self.fields["interchange_part"].queryset = Part.objects.filter(pk=self.data["interchange_part"])
        elif self.instance.pk and self.instance.interchange_part_id:
            self.fields["interchange_part"].queryset = Part.objects.filter(pk=self.instance.interchange_part_id)
        else:
            self.fields["interchange_part"].queryset = Part.objects.none()
        self.fields["interchange_part"].widget.attrs.update({
            "class": "form-select js-ajax-select",
            "data-url": "/api/parts/autocomplete/",
            "data-placeholder": "Search parts...",
        })
        self.fields["interchange_number"].widget.attrs["class"] = "form-control"
        self.fields["source_name"].widget.attrs["class"] = "form-control"
        self.fields["notes"].widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned = super().clean()
        ref_part = cleaned.get("interchange_part")
        ref_number = cleaned.get("interchange_number", "").strip()
        if not ref_part and not ref_number:
            raise forms.ValidationError(
                "Provide either an interchange part or a reference number."
            )
        if ref_part and not ref_number:
            cleaned["interchange_number"] = ref_part.part_number or ref_part.yt_number or ""
        return cleaned


class PartSupersedingForm(forms.ModelForm):
    """Form for adding a superseded (old) part number to the current part."""

    class Meta:
        model = PartSuperseding
        fields = ["old_part", "old_part_number", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}
        labels = {
            "old_part": "Link to Existing Part (optional)",
            "old_part_number": "Old Part Number",
        }

    def __init__(self, *args, part=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.part = part
        if self.is_bound and self.data.get("old_part"):
            self.fields["old_part"].queryset = Part.objects.filter(pk=self.data["old_part"])
        elif self.instance.pk and self.instance.old_part_id:
            self.fields["old_part"].queryset = Part.objects.filter(pk=self.instance.old_part_id)
        else:
            self.fields["old_part"].queryset = Part.objects.none()
        self.fields["old_part"].required = False
        self.fields["old_part"].widget.attrs.update({
            "class": "form-select js-ajax-select",
            "data-url": "/api/parts/autocomplete/",
            "data-placeholder": "Search parts...",
        })
        self.fields["old_part_number"].widget.attrs["class"] = "form-control"
        self.fields["notes"].widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned = super().clean()
        old_part = cleaned.get("old_part")
        old_number = cleaned.get("old_part_number", "").strip()
        if old_part and not old_number:
            cleaned["old_part_number"] = old_part.part_number
        if not old_part and not old_number:
            raise forms.ValidationError("Provide an old part number or select an existing part.")
        return cleaned
