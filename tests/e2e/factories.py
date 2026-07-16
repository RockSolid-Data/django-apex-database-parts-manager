"""
Test data factories for every model in the project.
Uses factory_boy with Faker for realistic, isolated test data.
"""

import factory
from factory.django import DjangoModelFactory
from decimal import Decimal
from django.utils import timezone


# ---------------------------------------------------------------------------
# catalog factories
# ---------------------------------------------------------------------------

class UnitTypeFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.UnitType"
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Unit Type {n}")
    description = factory.Faker("sentence")


class ApplicationTypeFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.ApplicationType"
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"App Type {n}")


class ApplicationTypeFieldFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.ApplicationTypeField"

    application_type = factory.SubFactory(ApplicationTypeFactory)
    field_name = factory.Sequence(lambda n: f"field_{n}")
    field_label = factory.Sequence(lambda n: f"Field {n}")
    display_order = factory.Sequence(lambda n: n)


class ApplicationFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.Application"

    name = factory.Sequence(lambda n: f"Application {n}")
    make = factory.Faker("company")
    model = factory.Faker("word")
    engine = factory.Faker("word")
    year = factory.LazyFunction(lambda: "2024")
    mfr = factory.Faker("company")
    volt = "12V"
    is_active = True


class ApplicationSpecificationFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.ApplicationSpecification"

    application = factory.SubFactory(ApplicationFactory)
    category = factory.Faker("word")
    type = factory.Faker("word")
    specification = factory.Faker("sentence")


class UnitTypeCategoryFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.UnitTypeCategory"
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"UTC {n}")
    sort_order = factory.Sequence(lambda n: n)
    color = "#fd7e14"


class UnitTypeCategoryFieldFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.UnitTypeCategoryField"

    category = factory.SubFactory(UnitTypeCategoryFactory)
    field_name = factory.Sequence(lambda n: f"utc_field_{n}")
    field_label = factory.Sequence(lambda n: f"UTC Field {n}")
    display_order = factory.Sequence(lambda n: n)


class UnitFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.Unit"

    unit_number = factory.Sequence(lambda n: f"UN-{n:05d}")
    yt_number = factory.Sequence(lambda n: f"YT-{n:05d}")
    oem = factory.Faker("company")
    voltage = "12V"
    unit_type = factory.SubFactory(UnitTypeFactory)
    new_unit_price = Decimal("150.00")
    rebuilt_unit_price = Decimal("95.00")
    is_active = True


class UnitImageFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.UnitImage"

    unit = factory.SubFactory(UnitFactory)
    image = factory.django.ImageField(filename="test_unit.jpg")
    caption = factory.Faker("sentence")


class ApplicationUnitFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.ApplicationUnit"

    application = factory.SubFactory(ApplicationFactory)
    unit = factory.SubFactory(UnitFactory)
    position = "Front"
    notes = ""


class PartCategoryFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.PartCategory"
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Part Cat {n}")


class PartCategoryFieldFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.PartCategoryField"

    category = factory.SubFactory(PartCategoryFactory)
    field_name = factory.Sequence(lambda n: f"pc_field_{n}")
    field_label = factory.Sequence(lambda n: f"PC Field {n}")
    display_order = factory.Sequence(lambda n: n)


class PartFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.Part"

    part_number = factory.Sequence(lambda n: f"PN-{n:05d}")
    part_name = factory.Faker("catch_phrase")
    manufacturer_number = factory.Sequence(lambda n: f"MFR-{n}")
    yt_number = factory.Sequence(lambda n: f"YT-P-{n:05d}")
    category = "Brushes"
    cost_price = Decimal("25.00")
    markup_percent = Decimal("40.00")
    price = Decimal("35.00")
    stock_quantity = 10
    reorder_qty = 5
    track_inventory = True
    is_active = True


class PartImageFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.PartImage"

    part = factory.SubFactory(PartFactory)
    image = factory.django.ImageField(filename="test_part.jpg")


class PartSubstituteFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.PartSubstitute"

    part = factory.SubFactory(PartFactory)
    substitute_part = factory.SubFactory(PartFactory)
    substitute_number = factory.LazyAttribute(
        lambda o: o.substitute_part.part_number if o.substitute_part else "SUB-001"
    )
    notes = ""


class PartInterchangeFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.PartInterchange"

    part = factory.SubFactory(PartFactory)
    interchange_part = factory.SubFactory(PartFactory)
    interchange_number = factory.LazyAttribute(
        lambda o: o.interchange_part.part_number if o.interchange_part else "IX-001"
    )
    source_name = "OEM"
    notes = ""


class PartSupersedingFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.PartSuperseding"

    part = factory.SubFactory(PartFactory)
    old_part = factory.SubFactory(PartFactory)
    old_part_number = factory.LazyAttribute(
        lambda o: o.old_part.part_number if o.old_part else "OLD-001"
    )
    notes = ""


class CrossReferenceFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.CrossReference"

    unit = factory.SubFactory(UnitFactory)
    cross_ref_number = factory.Sequence(lambda n: f"XREF-{n:05d}")
    interchange_type = "Direct"
    price = Decimal("120.00")
    notes = ""


class SubstituteFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.Substitute"

    unit = factory.SubFactory(UnitFactory)
    substitute_unit = factory.SubFactory(UnitFactory)
    substitute_number = factory.LazyAttribute(
        lambda o: o.substitute_unit.unit_number if o.substitute_unit else "SUB-U-001"
    )
    notes = ""


class GearReductionSubstitutionFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.GearReductionSubstitution"

    unit = factory.SubFactory(UnitFactory)
    number = factory.Sequence(lambda n: f"GR-{n:04d}")
    unit_type = "Gear Reduction"
    supplier = factory.Faker("company")
    notes = ""


class BOMFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.BOM"

    name = factory.Sequence(lambda n: f"BOM {n}")
    description = factory.Faker("sentence")
    unit = factory.SubFactory(UnitFactory)


class BOMItemFactory(DjangoModelFactory):
    class Meta:
        model = "catalog.BOMItem"

    bom = factory.SubFactory(BOMFactory)
    part = factory.SubFactory(PartFactory)
    description = factory.Faker("sentence")
    unit_qty = 1
    stock_qty = 0


# ---------------------------------------------------------------------------
# invoicing factories
# ---------------------------------------------------------------------------

class CompanySettingsFactory(DjangoModelFactory):
    class Meta:
        model = "invoicing.CompanySettings"

    company_name = "Manchester Electric"
    email = "info@manchester-electric.com"
    phone = "555-0100"
    address = "123 Main St, Manchester, CT 06040"
    default_net_terms = "NET_30"
    default_net_days = 30
    default_tax_rate = Decimal("6.35")
    pricing_method = "markup"
    invoice_number_prefix = "INV-"
    invoice_number_include_year = True
    invoice_number_padding = 4


class CustomerFactory(DjangoModelFactory):
    class Meta:
        model = "invoicing.Customer"

    name = factory.Sequence(lambda n: f"Customer {n}")
    contact_name = factory.Faker("name")
    phone = factory.Faker("phone_number")
    email = factory.Faker("email")
    is_active = True


class CustomerContactFactory(DjangoModelFactory):
    class Meta:
        model = "invoicing.CustomerContact"

    customer = factory.SubFactory(CustomerFactory)
    name = factory.Faker("name")
    phone = factory.Faker("phone_number")
    email = factory.Faker("email")


class InvoiceFactory(DjangoModelFactory):
    class Meta:
        model = "invoicing.Invoice"

    invoice_number = factory.Sequence(lambda n: f"INV-2024-{n:04d}")
    customer = factory.SubFactory(CustomerFactory)
    customer_name = factory.LazyAttribute(lambda o: o.customer.name)
    date = factory.LazyFunction(timezone.now)
    status = "DRAFT"
    subtotal = Decimal("100.00")
    tax_rate = Decimal("6.35")
    tax_amount = Decimal("6.35")
    total = Decimal("106.35")


class InvoiceItemFactory(DjangoModelFactory):
    class Meta:
        model = "invoicing.InvoiceItem"

    invoice = factory.SubFactory(InvoiceFactory)
    part = factory.SubFactory(PartFactory)
    description = factory.LazyAttribute(lambda o: o.part.part_name)
    quantity = 1
    unit_price = Decimal("35.00")
    discount_pct = Decimal("0.00")
    line_total = Decimal("35.00")


# ---------------------------------------------------------------------------
# inventory factories
# ---------------------------------------------------------------------------

class VendorFactory(DjangoModelFactory):
    class Meta:
        model = "inventory.Vendor"

    name = factory.Sequence(lambda n: f"Vendor {n}")
    contact_name = factory.Faker("name")
    email = factory.Faker("email")
    phone = factory.Faker("phone_number")
    is_active = True


class VendorContactFactory(DjangoModelFactory):
    class Meta:
        model = "inventory.VendorContact"

    vendor = factory.SubFactory(VendorFactory)
    name = factory.Faker("name")
    phone = factory.Faker("phone_number")
    email = factory.Faker("email")


# ---------------------------------------------------------------------------
# backup factories
# ---------------------------------------------------------------------------

class BackupSettingsFactory(DjangoModelFactory):
    class Meta:
        model = "backup.BackupSettings"

    local_backup_path = ""
    external_backup_path = ""
    auto_backup_enabled = True
    backup_interval_hours = 2
    max_backups = 4
