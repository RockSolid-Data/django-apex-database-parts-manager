"""
Seed mock data for Manchester Electric: vendors, customers, units, applications,
parts, and invoices with DRAFT, SENT, PAID, OVERDUE, CANCELLED statuses.
Clears existing app data and replaces with 5 coherent datasets.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import (
    Application,
    ApplicationSpecification,
    ApplicationUnit,
    BOM,
    BOMItem,
    CrossReference,
    GearReductionSubstitution,
    Part,
    Substitute,
    Unit,
    UnitType,
)
from inventory.models import Vendor
from invoicing.models import CompanySettings, Customer, Invoice, InvoiceItem, NetTerms


class Command(BaseCommand):
    help = "Clear existing data and seed 5 mock datasets (vendors, customers, units, parts, applications, invoices)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear-only",
            action="store_true",
            help="Only clear data, do not seed.",
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            self._clear_data()
            if not options.get("clear_only"):
                self._seed_data()
                self.stdout.write(self.style.SUCCESS("Mock data seeded successfully."))
            else:
                self._reset_company_settings()
                self.stdout.write(self.style.SUCCESS("Data cleared."))

    def _clear_data(self):
        """Delete in reverse dependency order. Preserve UnitType and CompanySettings."""
        InvoiceItem.objects.all().delete()
        Invoice.objects.all().delete()
        BOMItem.objects.all().delete()
        BOM.objects.all().delete()
        GearReductionSubstitution.objects.all().delete()
        Substitute.objects.all().delete()
        CrossReference.objects.all().delete()
        ApplicationUnit.objects.all().delete()
        ApplicationSpecification.objects.all().delete()
        Part.objects.all().delete()
        Unit.objects.all().delete()
        Application.objects.all().delete()
        Customer.objects.all().delete()
        Vendor.objects.all().delete()
        self.stdout.write("Cleared existing data.")

    def _reset_company_settings(self):
        """Reset CompanySettings to factory defaults for clean delivery."""
        settings = CompanySettings.get()
        settings.company_name = ""
        settings.tagline = ""
        settings.email = ""
        settings.phone = ""
        settings.address = ""
        settings.default_net_terms = NetTerms.NET_30
        settings.default_net_days = 30
        settings.default_tax_rate = Decimal("0")
        settings.invoice_number_prefix = "INV-"
        settings.invoice_number_include_year = True
        settings.invoice_number_include_month = False
        settings.invoice_number_padding = 4
        settings.invoice_paper_size = CompanySettings.PAPER_LETTER
        settings.invoice_layout_style = CompanySettings.LAYOUT_STANDARD
        settings.invoice_date_format = CompanySettings.DATE_FMT_FULL
        settings.invoice_currency_symbol = "$"
        if settings.logo:
            settings.logo.delete(save=False)
        settings.logo = None
        settings.save()
        self.stdout.write("Reset company settings to defaults.")

    def _seed_data(self):
        today = date.today()

        # Ensure UnitType and CompanySettings exist
        settings = CompanySettings.get()
        settings.default_tax_rate = Decimal("8.5")
        settings.save()

        unit_types = {ut.name: ut for ut in UnitType.objects.all()}
        ac_motor = unit_types.get("AC Motor")
        alternator = unit_types.get("Alternator")
        generator = unit_types.get("Generator")
        starter = unit_types.get("Starter")
        pump = unit_types.get("Pump")

        # Vendors (5)
        vendors_data = [
            ("Acme Electrical Supply", "Mike Johnson", "mike@acme-electrical.com", "555-101-1000",
             "1200 Industrial Blvd", "Suite A", "Manchester", "NH", "03101"),
            ("Delta Parts Co.", "Sarah Chen", "sarah@deltaparts.com", "555-102-2000",
             "450 Commerce Dr", "", "Nashua", "NH", "03060"),
            ("Midwest Bearings", "Tom Williams", "tom@midwestbearings.com", "555-103-3000",
             "890 Bearing Way", "", "Chicago", "IL", "60601"),
            ("Grainger Industrial", "Lisa Park", "lpark@grainger.com", "555-104-4000",
             "100 Grainger Pkwy", "", "Boston", "MA", "02101"),
            ("Rexel Electrical", "Dave Miller", "dmiller@rexel.com", "555-105-5000",
             "200 Wire Rd", "Bldg 3", "Portsmouth", "NH", "03801"),
        ]
        vendors = []
        for v in vendors_data:
            vendor = Vendor.objects.create(
                name=v[0],
                contact_name=v[1],
                email=v[2],
                phone=v[3],
                address_line1=v[4],
                address_line2=v[5],
                city=v[6],
                state=v[7],
                zip_code=v[8],
            )
            vendors.append(vendor)

        # Customers (5)
        customers_data = [
            ("Industrial Motors Inc.", "billing@indmotors.com", "555-201-1000",
             "500 Factory Row", "", "Manchester", "NH", "03102", NetTerms.NET_30, 0, None),
            ("Central Power LLC", "orders@centralpower.com", "555-202-2000",
             "100 Power Ave", "Unit 10", "Concord", "NH", "03301", NetTerms.NET_10, 0, Decimal("6.0")),
            ("Fleet Services Co.", "ap@fleetservices.com", "555-203-3000",
             "300 Truck Lane", "", "Nashua", "NH", "03061", NetTerms.NET_30, 0, None),
            ("Municipal Utilities Dist.", "finance@mud.gov", "555-204-4000",
             "50 City Hall Plaza", "", "Portsmouth", "NH", "03802", NetTerms.CUSTOM, 45, Decimal("0")),
            ("Horizon Mining Corp.", "procurement@horizonmining.com", "555-205-5000",
             "800 Mine Rd", "Bldg A", "Keene", "NH", "03431", NetTerms.NET_30, 0, None),
        ]
        customers = []
        for c in customers_data:
            cust = Customer.objects.create(
                name=c[0],
                bill_to_line1=c[3],
                bill_to_line2=c[4],
                bill_to_city=c[5],
                bill_to_state=c[6],
                bill_to_zip=c[7],
                net_terms=c[8],
                net_days=c[9],
                tax_rate=c[10],
            )
            from invoicing.models import CustomerContact
            CustomerContact.objects.create(
                customer=cust,
                name="Contact for " + c[0],
                phone=c[2],
                email=c[1],
                is_primary=True,
            )
            customers.append(cust)

        # Applications (5)
        apps_data = [
            ("Caterpillar 3208", "Caterpillar", "3208", "1985"),
            ("John Deere 4045", "John Deere", "4045", "2010"),
            ("Cummins 6BT", "Cummins", "6BT", "1995"),
            ("Detroit Diesel 8.2L", "Detroit Diesel", "8.2L", "1982"),
            ("Perkins 4.236", "Perkins", "4.236", "1978"),
        ]
        applications = []
        for a in apps_data:
            app = Application.objects.create(
                name=a[0],
                make=a[1],
                engine=a[2],
                year=a[3],
            )
            applications.append(app)

        # Units (5-8)
        units_data = [
            ("MTR-AC-001", "YT-M001", "Baldor", ac_motor, "230", "5 HP", "1800", "TEFC"),
            ("ALT-STD-101", "YT-A101", "Leece Neville", alternator, "12", "65A", "", ""),
            ("GEN-15KW-01", "YT-G01", "Onyan", generator, "120/240", "15 kW", "3600", ""),
            ("STR-12V-500", "YT-S500", "Bosch", starter, "12", "", "", ""),
            ("PMP-HYD-200", "YT-P200", "Thompson", pump, "", "2 HP", "1750", ""),
            ("MTR-AC-002", "YT-M002", "WEG", ac_motor, "480", "10 HP", "3600", "ODP"),
            ("ALT-STD-102", "YT-A102", "Delco", alternator, "12", "90A", "", ""),
        ]
        units = []
        for u in units_data:
            unit = Unit.objects.create(
                unit_number=u[0],
                yt_number=u[1],
                oem=u[2],
                unit_type=u[3],
                voltage=u[4],
                kw_hp=u[5],
                rpm=u[6],
                enclosure=u[7] or "",
                new_unit_price=Decimal("450.00") if u[3] == ac_motor else Decimal("350.00"),
                rebuilt_unit_price=Decimal("275.00") if u[3] == ac_motor else Decimal("225.00"),
            )
            units.append(unit)

        # Link some units to applications
        ApplicationUnit.objects.create(application=applications[0], unit=units[0], position="1")
        ApplicationUnit.objects.create(application=applications[0], unit=units[1], position="2")
        ApplicationUnit.objects.create(application=applications[1], unit=units[2], position="1")

        # Parts (10-15) with stock for invoice items
        parts_data = [
            ("BRG-6205", "Ball Bearing 6205", "6205", "NSK", vendors[2].name, Decimal("12.50"), Decimal("8.00"), 100),
            ("WND-AC-220V", "AC Winding 220V", "WND-220", "Copper Wind", vendors[0].name, Decimal("85.00"), Decimal("52.00"), 100),
            ("BRSH-CARBON", "Carbon Brush Set", "CB-4", "Morganite", vendors[0].name, Decimal("24.00"), Decimal("14.00"), 100),
            ("SEAL-SHAFT-25", "Shaft Seal 25mm", "25x42x7", "SKF", vendors[2].name, Decimal("18.75"), Decimal("11.00"), 100),
            ("BELT-V-3L", "V-Belt 3L", "3L360", "Gates", vendors[1].name, Decimal("9.99"), Decimal("5.50"), 100),
            ("CAP-RUN-50", "Run Capacitor 50uF", "50/370", "AmRad", vendors[0].name, Decimal("22.00"), Decimal("12.00"), 100),
            ("SWITCH-PB", "Push Button Switch", "PB-1", "Allen Bradley", vendors[4].name, Decimal("45.00"), Decimal("28.00"), 100),
            ("RELAY-24V", "24V Relay", "RL-24", "Omron", vendors[0].name, Decimal("32.50"), Decimal("19.00"), 100),
            ("GUARD-FAN", "Fan Guard", "FG-8", "MetalFab", vendors[3].name, Decimal("15.00"), Decimal("8.50"), 100),
            ("GASKET-HD", "Head Gasket", "HG-3208", "Fel-Pro", vendors[1].name, Decimal("42.00"), Decimal("26.00"), 100),
        ]
        parts = []
        for p in parts_data:
            part = Part.objects.create(
                part_number=p[0],
                part_name=p[1],
                oem_number=p[2],
                oem=p[3],
                primary_vendor=p[4],
                price=p[5],
                cost_price=p[6],
                stock_quantity=p[7],
            )
            parts.append(part)

        # Invoices: 2 DRAFT, 2 SENT, 2 PAID, 2 OVERDUE, 1 CANCELLED
        prefix = settings.invoice_number_prefix or "INV-"
        padding = max(1, min(10, settings.invoice_number_padding or 4))
        include_year = settings.invoice_number_include_year
        include_month = getattr(settings, "invoice_number_include_month", False)
        seq_per_year = {}
        seq_per_year_month = {}
        global_seq = 0

        def make_inv(customer, inv_date, due_date, status, items_desc):
            nonlocal global_seq
            if include_year:
                year = inv_date.year
                if include_month:
                    month = inv_date.month
                    key = (year, month)
                    seq_per_year_month[key] = seq_per_year_month.get(key, 0) + 1
                    seq = seq_per_year_month[key]
                    inv_num = f"{prefix}{year}{month:02d}-{seq:0{padding}d}"
                else:
                    seq_per_year[year] = seq_per_year.get(year, 0) + 1
                    seq = seq_per_year[year]
                    inv_num = f"{prefix}{year}-{seq:0{padding}d}"
            else:
                global_seq += 1
                inv_num = f"{prefix}{global_seq:0{padding}d}"
            inv = Invoice.objects.create(
                invoice_number=inv_num,
                customer=customer,
                customer_name=customer.name,
                contact_name="",
                phone="",
                email="",
                address="\n".join(filter(None, [customer.bill_to_line1, customer.bill_to_line2,
                    f"{customer.bill_to_city or ''}, {customer.bill_to_state or ''} {customer.bill_to_zip or ''}".strip().strip(",")])),
                date=inv_date,
                due_date=due_date,
                status=status,
                tax_rate=customer.get_effective_tax_rate() if customer else settings.default_tax_rate,
                subtotal=Decimal("0"),
                tax_amount=Decimal("0"),
                total=Decimal("0"),
            )
            for item in items_desc:
                if item[0] == "part":
                    part_obj = item[1]
                    qty = item[2]
                    InvoiceItem.objects.create(
                        invoice=inv,
                        part=part_obj,
                        unit=None,
                        description=part_obj.part_name or part_obj.part_number,
                        quantity=qty,
                        unit_price=part_obj.price or Decimal("0"),
                    )
                else:
                    unit_obj = item[1]
                    InvoiceItem.objects.create(
                        invoice=inv,
                        part=None,
                        unit=unit_obj,
                        description=f"{unit_obj.unit_type.name if unit_obj.unit_type else 'Unit'} — {unit_obj.unit_number}",
                        quantity=1,
                        unit_price=unit_obj.rebuilt_unit_price or unit_obj.new_unit_price or Decimal("0"),
                    )
            inv.recalculate_totals()
            return inv

        # DRAFT (2): current date, due in future
        make_inv(customers[0], today, today + timedelta(days=30), Invoice.Status.DRAFT,
                 [("part", parts[0], 2), ("part", parts[1], 1)])
        make_inv(customers[1], today, today + timedelta(days=10), Invoice.Status.DRAFT,
                 [("part", parts[2], 4), ("unit", units[0], 1)])

        # SENT (2): past date, due in future
        past = today - timedelta(days=14)
        make_inv(customers[2], past, past + timedelta(days=30), Invoice.Status.SENT,
                 [("part", parts[3], 2), ("part", parts[4], 3)])
        make_inv(customers[3], past, past + timedelta(days=45), Invoice.Status.SENT,
                 [("unit", units[1], 1), ("part", parts[5], 2)])

        # PAID (2): past date, completed
        older = today - timedelta(days=45)
        make_inv(customers[0], older, older + timedelta(days=30), Invoice.Status.PAID,
                 [("part", parts[6], 1), ("part", parts[7], 2)])
        make_inv(customers[4], older, older + timedelta(days=30), Invoice.Status.PAID,
                 [("unit", units[2], 1)])

        # OVERDUE (2): past date, due_date in past
        overdue_date = today - timedelta(days=20)
        due_past = today - timedelta(days=5)
        make_inv(customers[1], overdue_date, due_past, Invoice.Status.OVERDUE,
                 [("part", parts[8], 3), ("part", parts[9], 1)])
        make_inv(customers[2], overdue_date, due_past, Invoice.Status.OVERDUE,
                 [("unit", units[3], 1), ("part", parts[0], 1)])

        # CANCELLED (1)
        make_inv(customers[4], past, past + timedelta(days=30), Invoice.Status.CANCELLED,
                 [("part", parts[0], 5)])
