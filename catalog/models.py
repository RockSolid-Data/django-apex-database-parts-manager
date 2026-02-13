from django.db import models


# ---------------------------------------------------------------------------
# 1. UnitType
# ---------------------------------------------------------------------------
class UnitType(models.Model):
    """Lookup table for unit categories (AC Motor, DC Motor, etc.)."""

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

    name = models.CharField(max_length=255)
    make = models.CharField(max_length=150, blank=True, default="")
    engine = models.CharField(max_length=150, blank=True, default="")
    year = models.CharField(max_length=50, blank=True, default="")
    mfr = models.CharField("Manufacturer", max_length=150, blank=True, default="")
    volt = models.CharField("Voltage", max_length=50, blank=True, default="")
    amp = models.CharField("Amps", max_length=50, blank=True, default="")
    part_number = models.CharField(max_length=100, blank=True, default="")
    other_number = models.CharField(max_length=100, blank=True, default="")
    unit_number = models.CharField(max_length=100, blank=True, default="")
    options = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["make"]),
            models.Index(fields=["engine"]),
        ]

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# 2a. ApplicationSpecification (8.7)
# ---------------------------------------------------------------------------
class ApplicationSpecification(models.Model):
    """Application Specifications table: Category, Type, Specification."""

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

    # -- Identification --
    unit_number = models.CharField(max_length=100, unique=True)
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

    # -- Other --
    reclockable_flange = models.CharField(max_length=50, blank=True, default="")
    with_mounting_shims = models.CharField(max_length=50, blank=True, default="")
    with_hardware = models.CharField(max_length=50, blank=True, default="")
    bolt_holes = models.CharField(max_length=50, blank=True, default="")
    clocking_degrees = models.CharField(max_length=50, blank=True, default="")
    drive = models.CharField(max_length=100, blank=True, default="")

    # -- Descriptive --
    unit_attributes = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")

    # -- Pricing --
    new_unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    rebuilt_unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
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
        ]

    def __str__(self):
        return self.unit_number


# ---------------------------------------------------------------------------
# 4. ApplicationUnit (junction)
# ---------------------------------------------------------------------------
class ApplicationUnit(models.Model):
    """Links Applications to Units (M:M with extra data)."""

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
    """Links a unit to equivalent units across brands."""

    unit = models.ForeignKey(
        Unit, on_delete=models.CASCADE, related_name="cross_references"
    )
    cross_ref_unit = models.ForeignKey(
        Unit, on_delete=models.CASCADE, related_name="cross_referenced_by"
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("unit", "cross_ref_unit")]
        verbose_name = "Cross Reference"
        verbose_name_plural = "Cross References"

    def __str__(self):
        return f"{self.unit} ↔ {self.cross_ref_unit}"


# ---------------------------------------------------------------------------
# 6. Substitute
# ---------------------------------------------------------------------------
class Substitute(models.Model):
    """Interchangeable / substitute units."""

    unit = models.ForeignKey(
        Unit, on_delete=models.CASCADE, related_name="substitutes"
    )
    substitute_unit = models.ForeignKey(
        Unit, on_delete=models.CASCADE, related_name="substituted_by"
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("unit", "substitute_unit")]

    def __str__(self):
        return f"{self.unit} → {self.substitute_unit}"


# ---------------------------------------------------------------------------
# 7. GearReductionSubstitution
# ---------------------------------------------------------------------------
class GearReductionSubstitution(models.Model):
    """Gear-reduction options for a unit."""

    unit = models.ForeignKey(
        Unit, on_delete=models.CASCADE, related_name="gear_reductions"
    )
    number = models.CharField(max_length=50, blank=True, default="")
    description = models.CharField(max_length=255)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Gear Reduction Substitution"
        verbose_name_plural = "Gear Reduction Substitutions"

    def __str__(self):
        return f"{self.number} – {self.description}"


# ---------------------------------------------------------------------------
# 8. Part
# ---------------------------------------------------------------------------
class Part(models.Model):
    """Individual part / component with multiple numbering systems."""

    part_number = models.CharField(max_length=100, unique=True)
    part_name = models.CharField(max_length=255, blank=True, default="")
    key = models.CharField(max_length=100, blank=True, default="")
    yt_number = models.CharField("YT Number", max_length=100, blank=True, default="")
    j_and_n = models.CharField("J&N", max_length=100, blank=True, default="")
    oem_number = models.CharField("OEM #", max_length=100, blank=True, default="")
    item_no = models.CharField("Item No", max_length=100, blank=True, default="")
    category = models.CharField(max_length=100, blank=True, default="")
    type = models.CharField(max_length=100, blank=True, default="")
    oem_type = models.CharField("OEM Type", max_length=100, blank=True, default="")
    item_typ = models.CharField("Item Type", max_length=100, blank=True, default="")
    oem = models.CharField("OEM", max_length=200, blank=True, default="")
    primary_vendor = models.CharField(max_length=200, blank=True, default="")
    catalog = models.CharField(max_length=100, blank=True, default="")
    plug_id = models.CharField("Plug ID", max_length=100, blank=True, default="")

    # -- Pricing --
    price = models.DecimalField(
        "Sell Price", max_digits=10, decimal_places=2, null=True, blank=True
    )
    cost_price = models.DecimalField(
        "Cost Price", max_digits=10, decimal_places=2, null=True, blank=True
    )

    # -- Stock / Inventory --
    stock_quantity = models.IntegerField(default=0)
    reorder_qty = models.IntegerField("Reorder Threshold", default=0)
    bin_number = models.CharField("Bin Location", max_length=50, blank=True, default="")

    # -- Descriptive --
    description = models.TextField(blank=True, default="")
    foot_notes = models.TextField("Footnotes", blank=True, default="")
    superseding_notes = models.TextField(blank=True, default="")

    # -- Flags --
    has_picture = models.BooleanField(default=False)
    has_interchange = models.BooleanField(default=False)
    has_superseding = models.BooleanField(default=False)

    # -- Image --
    image = models.ImageField(upload_to="parts/", blank=True)

    # -- Relationships --
    unit = models.ForeignKey(
        Unit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parts",
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
        ]

    def __str__(self):
        return f"{self.part_number} – {self.part_name}"


# ---------------------------------------------------------------------------
# 9. BOM
# ---------------------------------------------------------------------------
class BOM(models.Model):
    """Bill of Materials header. Optional link to Unit and/or Application."""

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

    bom = models.ForeignKey(BOM, on_delete=models.CASCADE, related_name="items")
    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name="bom_items")
    description = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    unit_qty = models.PositiveIntegerField("Unit Qty", default=1)
    stock_qty = models.IntegerField("Stock Qty", default=0)
    bin_number = models.CharField(max_length=50, blank=True, default="")
    oem_number = models.CharField("OEM #", max_length=100, blank=True, default="")
    j_and_n = models.CharField("J&N", max_length=100, blank=True, default="")
    yt_number = models.CharField("YT Number", max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "BOM Item"
        verbose_name_plural = "BOM Items"

    def __str__(self):
        return f"{self.bom.name} — {self.part.part_number}"
