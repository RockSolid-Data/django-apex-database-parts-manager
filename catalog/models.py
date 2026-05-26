from django.db import models


# ---------------------------------------------------------------------------
# 1. UnitType
# ---------------------------------------------------------------------------
class UnitType(models.Model):
    """Lookup table for unit categories (AC Motor, DC Motor, etc.)."""

    seed_id = models.IntegerField(null=True, blank=True, db_index=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["name"]
        verbose_name = "Unit Type"
        verbose_name_plural = "Unit Types"

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# 2. Application
# ---------------------------------------------------------------------------
class Application(models.Model):
    """Machine, engine, or vehicle that units are installed on."""

    seed_id = models.IntegerField(null=True, blank=True, db_index=True)
    name = models.CharField(max_length=255)
    make = models.CharField(max_length=150, blank=True, default="")
    model = models.CharField(max_length=150, blank=True, default="")
    engine = models.CharField(max_length=150, blank=True, default="")
    year = models.CharField(max_length=50, blank=True, default="")
    mfr = models.CharField("Manufacturer", max_length=150, blank=True, default="")
    volt = models.CharField("Voltage", max_length=50, blank=True, default="")
    amp = models.CharField("Amps", max_length=50, blank=True, default="")
    kw = models.CharField("KW", max_length=50, blank=True, default="")
    fuel_type = models.CharField("Fuel Type", max_length=50, blank=True, default="")
    vin = models.CharField("VIN", max_length=50, blank=True, default="")
    alt_pulley = models.CharField("Alt Pulley", max_length=100, blank=True, default="")
    unit_type_name = models.CharField("Unit Type", max_length=100, blank=True, default="")
    part_number = models.CharField(max_length=100, blank=True, default="")
    other_number = models.CharField(max_length=100, blank=True, default="")
    unit_number = models.CharField(max_length=100, blank=True, default="")
    options = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")

    # -- Application type category (user-managed dynamic fields) --
    application_type_category = models.CharField(max_length=100, blank=True, default="")
    type_specifications = models.JSONField(default=dict, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["make"]),
            models.Index(fields=["engine"]),
            models.Index(fields=["year"]),
            models.Index(fields=["mfr"]),
            models.Index(fields=["volt"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["is_active", "name"]),
            models.Index(fields=["unit_number"]),
            models.Index(fields=["model"]),
            models.Index(fields=["part_number"]),
            models.Index(fields=["unit_type_name"]),
        ]

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# 2a. ApplicationSpecification (8.7)
# ---------------------------------------------------------------------------
class ApplicationSpecification(models.Model):
    """Application Specifications table: Category, Type, Specification."""

    seed_id = models.IntegerField(null=True, blank=True, db_index=True)
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="specifications"
    )
    category = models.CharField(max_length=100, blank=True, default="")
    type = models.CharField(max_length=100, blank=True, default="")
    specification = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "type"]
        verbose_name = "Application Specification"
        verbose_name_plural = "Application Specifications"
        indexes = [
            models.Index(fields=["application", "category"]),
        ]

    def __str__(self):
        return f"{self.category} / {self.type} — {self.specification}"


# ---------------------------------------------------------------------------
# 3. Unit
# ---------------------------------------------------------------------------
class Unit(models.Model):
    """
    Component / assembly (motor, alternator, starter, etc.) that goes on
    an Application.  One table for all unit types; type-specific fields
    can be blank.
    """

    seed_id = models.IntegerField(null=True, blank=True, db_index=True)

    # -- Identification --
    unit_number = models.CharField(max_length=100, unique=True, blank=True, null=True, default=None)
    yt_number = models.CharField("YT Number", max_length=100, blank=True, default="")
    oem = models.CharField("OEM", max_length=200, blank=True, default="")
    j_and_n_number = models.CharField("J&N Number", max_length=100, blank=True, default="")
    model_cat_number = models.CharField("Model/Cat Number", max_length=100, blank=True, default="")
    unit_type = models.ForeignKey(
        UnitType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="units",
    )
    manufacturer = models.CharField(max_length=200, blank=True, default="")
    family = models.CharField(max_length=100, blank=True, default="")

    # -- Electrical --
    voltage = models.CharField(max_length=50, blank=True, default="")
    kw_hp = models.CharField("kW / HP", max_length=50, blank=True, default="")
    phase = models.CharField(max_length=20, blank=True, default="")
    fla = models.CharField("FLA", max_length=50, blank=True, default="")
    amp_rating = models.CharField("Amp Rating", max_length=50, blank=True, default="")
    full_load_eff = models.CharField("Full Load Efficiency", max_length=50, blank=True, default="")
    power_rating = models.CharField(max_length=50, blank=True, default="")

    # -- Mechanical --
    rpm = models.CharField("RPM", max_length=50, blank=True, default="")
    frame = models.CharField(max_length=50, blank=True, default="")
    enclosure = models.CharField(max_length=100, blank=True, default="")
    rotation = models.CharField(max_length=50, blank=True, default="")
    clock_position = models.CharField("Clock Position", max_length=50, blank=True, default="")
    mount_type = models.CharField(max_length=100, blank=True, default="")
    flange_type = models.CharField(max_length=100, blank=True, default="")
    housing_type = models.CharField(max_length=100, blank=True, default="")
    housing = models.CharField(max_length=100, blank=True, default="")
    weight = models.CharField(max_length=50, blank=True, default="")
    bearings = models.CharField(max_length=100, blank=True, default="")
    design = models.CharField(max_length=100, blank=True, default="")
    type = models.CharField(max_length=100, blank=True, default="")
    service_factor = models.CharField(max_length=50, blank=True, default="")
    duty_cycle = models.CharField(max_length=50, blank=True, default="")
    speed_ratio = models.CharField(max_length=50, blank=True, default="")
    grounding = models.CharField(max_length=50, blank=True, default="")
    insulation_class = models.CharField(max_length=50, blank=True, default="")
    overload_protection = models.CharField(max_length=100, blank=True, default="")
    c_dimension = models.CharField("C Dimension", max_length=50, blank=True, default="")
    u_dimension = models.CharField("U Dimension", max_length=50, blank=True, default="")

    # -- Starter-specific --
    starter_type = models.CharField("Starter Type", max_length=100, blank=True, default="")
    tooth_quantity = models.CharField(max_length=50, blank=True, default="")
    nose_type = models.CharField(max_length=100, blank=True, default="")
    over_crank_protection = models.CharField(max_length=100, blank=True, default="")
    solenoid_attached = models.CharField(max_length=50, blank=True, default="")

    # -- Generator-specific --
    circuit_type = models.CharField(max_length=100, blank=True, default="")
    brush_type = models.CharField(max_length=100, blank=True, default="")
    regulation_type = models.CharField(max_length=100, blank=True, default="")

    # -- Alternator-specific --
    fan_type = models.CharField(max_length=100, blank=True, default="")
    regulator_type = models.CharField(max_length=100, blank=True, default="")
    pulley_class = models.CharField("Pulley Class", max_length=100, blank=True, default="")

    # -- Other --
    reclockable_flange = models.CharField(max_length=50, blank=True, default="")
    with_mounting_shims = models.CharField(max_length=50, blank=True, default="")
    with_hardware = models.CharField(max_length=50, blank=True, default="")
    bolt_holes = models.CharField(max_length=50, blank=True, default="")
    clocking_degrees = models.CharField(max_length=50, blank=True, default="")
    drive = models.CharField(max_length=100, blank=True, default="")

    # -- Notes --
    description = models.TextField("Description", blank=True, default="")
    notes = models.TextField(blank=True, default="")

    # -- Attributes --
    unit_attributes = models.TextField(blank=True, default="")

    # -- Pricing --
    new_unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    rebuilt_unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    new_price_updated_at = models.DateTimeField(
        "New Price Updated", null=True, blank=True
    )
    rebuilt_price_updated_at = models.DateTimeField(
        "Rebuilt Price Updated", null=True, blank=True
    )

    # -- Images --
    unit_image = models.ImageField(upload_to="units/", blank=True)
    plug_image = models.ImageField(upload_to="units/", blank=True)

    # -- Relationships --
    applications = models.ManyToManyField(
        Application,
        through="ApplicationUnit",
        related_name="units",
        blank=True,
    )

    # -- Unit type category (user-managed dynamic fields) --
    unit_type_category = models.CharField(max_length=100, blank=True, default="")
    specifications = models.JSONField(default=dict, blank=True)

    # -- Metadata --
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["unit_number"]
        indexes = [
            models.Index(fields=["unit_number"]),
            models.Index(fields=["yt_number"]),
            models.Index(fields=["oem"]),
            models.Index(fields=["voltage"]),
            models.Index(fields=["family"]),
            models.Index(fields=["manufacturer"]),
            models.Index(fields=["j_and_n_number"]),
            models.Index(fields=["model_cat_number"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["unit_type_category"]),
        ]

    def __str__(self):
        return self.unit_number or self.yt_number or f"Unit #{self.pk}"


# ---------------------------------------------------------------------------
# 3b. UnitImage
# ---------------------------------------------------------------------------
class UnitImage(models.Model):
    """Multiple images per unit."""

    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="units/")
    caption = models.CharField(max_length=200, blank=True, default="")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]

    def __str__(self):
        return f"Image for {self.unit}"


# ---------------------------------------------------------------------------
# 4. ApplicationUnit (junction)
# ---------------------------------------------------------------------------
class ApplicationUnit(models.Model):
    """Links Applications to Units (M:M with extra data)."""

    seed_id = models.IntegerField(null=True, blank=True, db_index=True)
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="application_units"
    )
    unit = models.ForeignKey(
        Unit, on_delete=models.CASCADE, related_name="application_units"
    )
    position = models.CharField(max_length=100, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("application", "unit")]
        verbose_name = "Application–Unit Link"
        verbose_name_plural = "Application–Unit Links"

    def __str__(self):
        return f"{self.application} — {self.unit}"


# ---------------------------------------------------------------------------
# 5. CrossReference
# ---------------------------------------------------------------------------
class CrossReference(models.Model):
    """
    Links a unit to an equivalent part number.  When the cross-referenced
    number is also a Unit in the system, cross_ref_unit is populated as a
    FK for easy navigation.  Otherwise the manufacturer number is stored as
    a plain string in cross_ref_number.
    """

    seed_id = models.IntegerField(null=True, blank=True, db_index=True)
    unit = models.ForeignKey(
        Unit, on_delete=models.CASCADE, related_name="cross_references"
    )
    cross_ref_unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="cross_referenced_by",
    )
    cross_ref_number = models.CharField(max_length=100, blank=True, default="")
    interchange_type = models.CharField(
        "Cross Ref Name",
        max_length=150,
        blank=True,
        default="",
    )
    price = models.DecimalField(
        "Price", max_digits=10, decimal_places=2, null=True, blank=True
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["interchange_type", "cross_ref_number"]
        unique_together = [("unit", "cross_ref_number", "interchange_type")]
        verbose_name = "Cross Reference"
        verbose_name_plural = "Cross References"
        indexes = [
            models.Index(fields=["cross_ref_number"]),
            models.Index(fields=["interchange_type"]),
        ]

    def __str__(self):
        if self.cross_ref_unit:
            return f"{self.unit} ↔ {self.cross_ref_unit}"
        return f"{self.unit} ↔ {self.interchange_type} {self.cross_ref_number}"


# ---------------------------------------------------------------------------
# 6. Substitute
# ---------------------------------------------------------------------------
class Substitute(models.Model):
    """Interchangeable / substitute units."""

    seed_id = models.IntegerField(null=True, blank=True, db_index=True)
    unit = models.ForeignKey(
        Unit, on_delete=models.CASCADE, related_name="substitutes"
    )
    substitute_unit = models.ForeignKey(
        Unit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="substituted_by",
    )
    substitute_number = models.CharField(max_length=100, blank=True, default="")
    substitute_unit_type = models.CharField("Unit Type", max_length=100, blank=True, default="")
    substitute_supplier = models.CharField("Supplier", max_length=200, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("unit", "substitute_unit")]
        indexes = [
            models.Index(fields=["substitute_number"]),
        ]

    def __str__(self):
        label = self.substitute_unit.unit_number if self.substitute_unit else self.substitute_number
        return f"{self.unit} → {label}"


# ---------------------------------------------------------------------------
# 7. GearReductionSubstitution
# ---------------------------------------------------------------------------
class GearReductionSubstitution(models.Model):
    """Gear-reduction options for a unit."""

    seed_id = models.IntegerField(null=True, blank=True, db_index=True)
    unit = models.ForeignKey(
        Unit, on_delete=models.CASCADE, related_name="gear_reductions"
    )
    number = models.CharField("Unit Number", max_length=50, blank=True, default="")
    unit_type = models.CharField("Unit Type", max_length=100, blank=True, default="")
    supplier = models.CharField("Supplier", max_length=200, blank=True, default="")
    description = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Gear Reduction Substitution"
        verbose_name_plural = "Gear Reduction Substitutions"

    def __str__(self):
        return f"{self.number} – {self.description}"


# ---------------------------------------------------------------------------
# 7a. ApplicationType / ApplicationTypeField (user-managed via Settings)
# ---------------------------------------------------------------------------
class ApplicationType(models.Model):
    """User-defined application type shown in the Add New Application dropdown."""

    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Application Type"
        verbose_name_plural = "Application Types"

    def __str__(self):
        return self.name


class ApplicationTypeField(models.Model):
    """One field belonging to an ApplicationType, shown in the application form."""

    application_type = models.ForeignKey(
        ApplicationType, on_delete=models.CASCADE, related_name="fields"
    )
    field_name = models.CharField(max_length=100)
    field_label = models.CharField(max_length=100)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "pk"]
        unique_together = [("application_type", "field_name")]

    def __str__(self):
        return f"{self.application_type.name} → {self.field_label}"


# ---------------------------------------------------------------------------
# 7b. PartCategory / PartCategoryField (user-managed via Settings)
# ---------------------------------------------------------------------------
class PartCategory(models.Model):
    """User-defined part category shown in the Add New Part dropdown."""

    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Part Category"
        verbose_name_plural = "Part Categories"

    def __str__(self):
        return self.name


class PartCategoryField(models.Model):
    """One field belonging to a PartCategory, shown in the Identification section."""

    category = models.ForeignKey(
        PartCategory, on_delete=models.CASCADE, related_name="fields"
    )
    field_name = models.CharField(max_length=100)
    field_label = models.CharField(max_length=100)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "pk"]
        unique_together = [("category", "field_name")]

    def __str__(self):
        return f"{self.category.name} → {self.field_label}"


# ---------------------------------------------------------------------------
# 7c. UnitTypeCategory / UnitTypeCategoryField (user-managed via Settings)
# ---------------------------------------------------------------------------
class UnitTypeCategory(models.Model):
    """User-defined unit type category shown in the Add New Unit dropdown."""

    DEFAULT_COLOR = "#fd7e14"

    name = models.CharField(max_length=100, unique=True)
    sort_order = models.IntegerField(default=0)
    color = models.CharField(max_length=7, default=DEFAULT_COLOR)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Unit Type Category"
        verbose_name_plural = "Unit Type Categories"

    def __str__(self):
        return self.name


class UnitTypeCategoryField(models.Model):
    """One field belonging to a UnitTypeCategory, shown in the unit form."""

    category = models.ForeignKey(
        UnitTypeCategory, on_delete=models.CASCADE, related_name="fields"
    )
    field_name = models.CharField(max_length=100)
    field_label = models.CharField(max_length=100)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "pk"]
        unique_together = [("category", "field_name")]

    def __str__(self):
        return f"{self.category.name} → {self.field_label}"


# ---------------------------------------------------------------------------
# 8. Part
# ---------------------------------------------------------------------------
class Part(models.Model):
    """Individual part / component with multiple numbering systems."""

    seed_id = models.IntegerField(null=True, blank=True, db_index=True)
    part_number = models.CharField(max_length=100, unique=True, blank=True, null=True, default=None)
    part_name = models.CharField(max_length=255, blank=True, default="")
    manufacturer_number = models.CharField("Manufacturer Number", max_length=100, blank=True, default="")
    yt_number = models.CharField("YT Number", max_length=100, blank=True, default="")
    j_and_n = models.CharField("J&N", max_length=100, blank=True, default="")
    oem_number = models.CharField("OEM #", max_length=100, blank=True, default="")
    item_no = models.CharField("Item No", max_length=100, blank=True, default="")
    category = models.CharField(max_length=100, blank=True, default="")
    type = models.CharField(max_length=100, blank=True, default="")
    oem_type = models.CharField("OEM Type", max_length=100, blank=True, default="")
    item_typ = models.CharField("Item Type", max_length=100, blank=True, default="")
    oem = models.CharField("OEM", max_length=200, blank=True, default="")
    primary_vendor = models.CharField("Primary Supplier", max_length=200, blank=True, default="")
    catalog = models.CharField(max_length=100, blank=True, default="")
    plug_id = models.CharField("Plug ID", max_length=100, blank=True, default="")

    # -- Pricing --
    cost_price = models.DecimalField(
        "Cost Price", max_digits=10, decimal_places=2, null=True, blank=True
    )
    markup_percent = models.DecimalField(
        "Markup", max_digits=5, decimal_places=2, null=True, blank=True
    )
    price = models.DecimalField(
        "Sell Price", max_digits=10, decimal_places=2, null=True, blank=True
    )
    price_updated_at = models.DateTimeField(
        "Price Updated", null=True, blank=True
    )

    # -- Stock / Inventory --
    track_inventory = models.BooleanField("Track Inventory", default=False)
    stock_quantity = models.IntegerField(default=0)
    reorder_qty = models.IntegerField("Reorder Threshold", default=0)
    bin_number = models.CharField("Bin Location", max_length=50, blank=True, default="")

    # -- Electrical --
    voltage = models.CharField("Voltage", max_length=50, blank=True, default="")

    # -- Notes --
    notes = models.TextField("Notes", blank=True, default="")
    foot_notes = models.TextField("Footnotes", blank=True, default="")
    superseding_notes = models.TextField(blank=True, default="")

    # -- Flags --
    has_picture = models.BooleanField(default=False)
    has_interchange = models.BooleanField(default=False)
    has_superseding = models.BooleanField(default=False)

    # -- Category-specific specifications (stored as JSON) --
    specifications = models.JSONField(default=dict, blank=True)

    # -- Image (legacy single image, kept for backward compat) --
    image = models.ImageField(upload_to="parts/", blank=True)

    # -- Relationships --
    unit = models.ForeignKey(
        Unit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parts",
    )
    units = models.ManyToManyField(
        Unit,
        blank=True,
        related_name="linked_parts",
    )

    # -- Metadata --
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["part_number"]
        indexes = [
            models.Index(fields=["part_number"]),
            models.Index(fields=["part_name"]),
            models.Index(fields=["oem_number"]),
            models.Index(fields=["j_and_n"]),
            models.Index(fields=["yt_number"]),
            models.Index(fields=["manufacturer_number"]),
            models.Index(fields=["item_no"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["category"]),
        ]

    def __str__(self):
        label = self.part_number or self.yt_number or f"Part #{self.pk}"
        return f"{label} – {self.part_name}"


# ---------------------------------------------------------------------------
# 8b. PartImage
# ---------------------------------------------------------------------------
class PartImage(models.Model):
    """Multiple images per part."""

    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="parts/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]

    def __str__(self):
        return f"Image for {self.part.part_number}"


# ---------------------------------------------------------------------------
# 8c. PartSubstitute
# ---------------------------------------------------------------------------
class PartSubstitute(models.Model):
    """Links a part to another existing part as a substitute."""

    seed_id = models.IntegerField(null=True, blank=True, db_index=True)
    part = models.ForeignKey(
        Part, on_delete=models.CASCADE, related_name="part_substitutes"
    )
    substitute_part = models.ForeignKey(
        Part,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="substituted_by_parts",
    )
    substitute_number = models.CharField(max_length=100, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("part", "substitute_part")]

    def __str__(self):
        label = self.substitute_part.part_number if self.substitute_part else self.substitute_number
        return f"{self.part.part_number} → {label}"


# ---------------------------------------------------------------------------
# 8d. PartInterchange
# ---------------------------------------------------------------------------
class PartInterchange(models.Model):
    """Links a part to another existing part as an interchange."""

    seed_id = models.IntegerField(null=True, blank=True, db_index=True)
    part = models.ForeignKey(
        Part, on_delete=models.CASCADE, related_name="part_interchanges"
    )
    interchange_part = models.ForeignKey(
        Part,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="interchanged_by_parts",
    )
    source_name = models.CharField("Source / Name", max_length=150, blank=True, default="")
    interchange_number = models.CharField(max_length=100, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("part", "interchange_part")]
        constraints = [
            models.UniqueConstraint(
                fields=["part", "interchange_number", "source_name"],
                name="unique_part_xref_number_source",
            ),
        ]
        indexes = [
            models.Index(fields=["interchange_number"]),
        ]

    def __str__(self):
        part_label = self.part.part_number or self.part.yt_number or f"Part #{self.part_id}"
        other_label = (
            self.interchange_part.part_number
            or self.interchange_part.yt_number
            if self.interchange_part
            else self.interchange_number
        )
        return f"{part_label} ↔ {other_label}"


# ---------------------------------------------------------------------------
# 8e. PartSuperseding
# ---------------------------------------------------------------------------
class PartSuperseding(models.Model):
    """Links an old/superseded part number to the current part."""

    seed_id = models.IntegerField(null=True, blank=True, db_index=True)
    part = models.ForeignKey(
        Part, on_delete=models.CASCADE, related_name="supersedings"
    )
    old_part = models.ForeignKey(
        Part,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    old_part_number = models.CharField(max_length=100)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("part", "old_part_number")]
        indexes = [
            models.Index(fields=["old_part_number"]),
        ]

    def __str__(self):
        return f"{self.old_part_number} → {self.part.part_number}"


# ---------------------------------------------------------------------------
# 9. BOM
# ---------------------------------------------------------------------------
class BOM(models.Model):
    """Bill of Materials header. Optional link to Unit and/or Application."""

    seed_id = models.IntegerField(null=True, blank=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    unit = models.ForeignKey(
        Unit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="boms",
    )
    application = models.ForeignKey(
        Application,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="boms",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "BOM"
        verbose_name_plural = "BOMs"

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# 10. BOMItem
# ---------------------------------------------------------------------------
class BOMItem(models.Model):
    """One line on a BOM: part, quantity, and optional override fields."""

    seed_id = models.IntegerField(null=True, blank=True, db_index=True)
    bom = models.ForeignKey(BOM, on_delete=models.CASCADE, related_name="items")
    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name="bom_items")
    description = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    unit_qty = models.PositiveIntegerField("Part Qty", default=1)
    stock_qty = models.IntegerField("Stock Qty", default=0)
    bin_number = models.CharField(max_length=50, blank=True, default="")
    oem_number = models.CharField("OEM #", max_length=100, blank=True, default="")
    j_and_n = models.CharField("J&N", max_length=100, blank=True, default="")
    yt_number = models.CharField("YT Number", max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "BOM Item"
        verbose_name_plural = "BOM Items"
        indexes = [
            models.Index(fields=["bom", "part"]),
            models.Index(fields=["oem_number"]),
            models.Index(fields=["j_and_n"]),
            models.Index(fields=["yt_number"]),
        ]

    def __str__(self):
        return f"{self.bom.name} — {self.part.part_number}"
