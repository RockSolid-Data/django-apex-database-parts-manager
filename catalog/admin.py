from django.contrib import admin

from .models import (
    UnitType,
    Application,
    ApplicationSpecification,
    Unit,
    UnitImage,
    ApplicationUnit,
    CrossReference,
    Substitute,
    GearReductionSubstitution,
    Part,
    BOM,
    BOMItem,
)


@admin.register(UnitType)
class UnitTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "description"]
    search_fields = ["name"]


class ApplicationSpecificationInline(admin.TabularInline):
    """Manage application specifications (8.7)."""

    model = ApplicationSpecification
    extra = 1
    fields = ["category", "type", "specification"]


class ApplicationUnitInline(admin.TabularInline):
    """Manage linked units from the Application edit page (Linked Units)."""

    model = ApplicationUnit
    fk_name = "application"
    extra = 1
    autocomplete_fields = ["unit"]
    fields = ["unit", "position", "notes"]


class UnitImageInline(admin.TabularInline):
    model = UnitImage
    extra = 1


class ApplicationUnitInlineForUnit(admin.TabularInline):
    """Manage linked applications from the Unit edit page (Applications)."""

    model = ApplicationUnit
    fk_name = "unit"
    extra = 1
    autocomplete_fields = ["application"]
    fields = ["application", "position", "notes"]


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ["name", "make", "engine", "year", "mfr", "volt", "is_active"]
    list_filter = ["is_active", "make"]
    search_fields = ["name", "make", "engine"]
    inlines = [ApplicationSpecificationInline, ApplicationUnitInline]


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ["unit_number", "yt_number", "oem", "unit_type", "voltage", "rpm", "is_active"]
    list_filter = ["is_active", "unit_type"]
    search_fields = ["unit_number", "yt_number", "oem"]
    inlines = [UnitImageInline, ApplicationUnitInlineForUnit]


@admin.register(ApplicationUnit)
class ApplicationUnitAdmin(admin.ModelAdmin):
    list_display = ["application", "unit", "position"]
    search_fields = ["application__name", "unit__unit_number"]


@admin.register(CrossReference)
class CrossReferenceAdmin(admin.ModelAdmin):
    list_display = ["unit", "cross_ref_unit", "cross_ref_number", "interchange_type"]
    search_fields = ["unit__unit_number", "cross_ref_unit__unit_number", "cross_ref_number", "interchange_type"]
    list_filter = ["interchange_type"]


@admin.register(Substitute)
class SubstituteAdmin(admin.ModelAdmin):
    list_display = ["unit", "substitute_unit"]
    search_fields = ["unit__unit_number", "substitute_unit__unit_number"]


@admin.register(GearReductionSubstitution)
class GearReductionSubstitutionAdmin(admin.ModelAdmin):
    list_display = ["unit", "number", "description"]
    search_fields = ["unit__unit_number", "number", "description"]


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = [
        "part_number", "part_name", "oem_number", "j_and_n",
        "stock_quantity", "is_active",
    ]
    list_filter = ["is_active", "category"]
    search_fields = ["part_number", "part_name", "oem_number", "j_and_n", "yt_number"]


@admin.register(BOM)
class BOMAdmin(admin.ModelAdmin):
    list_display = ["name", "unit", "application", "created_at"]
    search_fields = ["name"]


@admin.register(BOMItem)
class BOMItemAdmin(admin.ModelAdmin):
    list_display = ["bom", "part", "unit_qty", "stock_qty"]
    search_fields = ["bom__name", "part__part_number"]
