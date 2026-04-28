"""
Data migration to:
1. Categorize 23,323 uncategorized parts based on part_name patterns.
2. Delete empty PartCategory management entries.
"""
from django.db import migrations


HARDWARE_NAMES = [
    "Retainer - Str", "Bracket - Alt", "Bracket - Str",
    "Strap - Alt", "Starter Shim", "Thrust",
]

STARTSWITH_MAP = {
    "Starter Drive Housing":    "Housings",
    "DE Frame":                 "Housings",
    "Slip Ring End Frame":      "Housings",
    "CE Frame - Str":           "Housings",
    "Starter Housing":          "Housings",

    "Starter Solenoid":         "Starter Solenoids & Parts",
    "Solenoid Cap":             "Starter Solenoids & Parts",
    "Solenoid Switch":          "Starter Solenoids & Parts",
    "Solenoid Coil":            "Starter Solenoids & Parts",
    "Solenoid Terminal":        "Starter Solenoids & Parts",
    "Solenoid Housing":         "Starter Solenoids & Parts",
    "Solenoid Repair":          "Starter Solenoids & Parts",
    "Solenoid Insulator":       "Starter Solenoids & Parts",
    "Solenoid Gasket":          "Starter Solenoids & Parts",
    "Solenoid Spacer":          "Starter Solenoids & Parts",
    "Solenoid Plunger":         "Starter Solenoids & Parts",
    "Solenoid Clamp":           "Starter Solenoids & Parts",

    "Starter Drive":            "Drives, Clutches & Drive Parts",
    "Drive Gear":               "Drives, Clutches & Drive Parts",
    "Drive Part":               "Drives, Clutches & Drive Parts",
    "Drive Cover":              "Drives, Clutches & Drive Parts",
    "Planetary":                "Drives, Clutches & Drive Parts",
    "Stationary Gear":          "Drives, Clutches & Drive Parts",
    "Stop Collar":              "Drives, Clutches & Drive Parts",
    "Collar Kit":               "Drives, Clutches & Drive Parts",
    "Gear Track":               "Drives, Clutches & Drive Parts",
    "Clutch":                   "Drives, Clutches & Drive Parts",
    "Brake Kit":                "Drives, Clutches & Drive Parts",
    "Idler Shaft":              "Drives, Clutches & Drive Parts",

    "Starter Armature":         "Shafts & Armatures",
    "Armature Shaft":           "Shafts & Armatures",
    "Starter Drive Shaft":      "Shafts & Armatures",
    "Commutator":               "Shafts & Armatures",

    "Alternator Stator":        "Stators",

    "Alternator Rotor":         "Rotors",
    "Rotor Coil":               "Rotors",
    "Rotor Shaft":              "Slip Rings & Rotor Shafts",

    "Charging System Voltage":  "Regulators & Regulator Parts",

    "Starter Field Coil":       "Field Coils",

    "Alternator Cover":         "Cover Bands & Covers",
    "CE Frame Cover":           "Cover Bands & Covers",
    "Cover - Starter":          "Cover Bands & Covers",

    "Slip Ring":                "Slip Rings & Rotor Shafts",

    "Starter Lever":            "Shift Levers",

    "Alternator Fan":           "Fans & Baffles",
    "Baffle":                   "Fans & Baffles",

    "Terminal - Str":           "Electrical",
    "Terminal - Alt":           "Electrical",
    "Battery Terminal":         "Electrical",
    "Alternator Battery":       "Electrical",
    "Alternator Connector":     "Electrical",
    "Connector - Str":          "Electrical",
    "Lead":                     "Electrical",

    "IMS Switch":               "Relays, Solenoids & Switches",
    "Starter Relay":            "Relays, Solenoids & Switches",
    "Battery Disconnect":       "Relays, Solenoids & Switches",
    "Battery Switch":           "Relays, Solenoids & Switches",
    "Switch - Motor":           "Relays, Solenoids & Switches",

    "Insulator - Alt":          "Insulators & Kits",
    "Insulator - Str":          "Insulators & Kits",
    "Repair Kit":               "Insulators & Kits",
    "Alternator Repair Kit":    "Insulators & Kits",

    "Grommet":                  "Gaskets, Grommets & Seals",
    "O-Ring":                   "Gaskets, Grommets & Seals",
    "Gasket":                   "Gaskets, Grommets & Seals",
    "Boot":                     "Gaskets, Grommets & Seals",
    "Sealant":                  "Gaskets, Grommets & Seals",

    "Starter Field Frame":      "Starter Field Housings",
    "Field Housing":            "Starter Field Housings",

    "Pole Shoe":                "Pole Shoes",

    "Retainer - Str":           "Hardware",
    "Bracket":                  "Hardware",
    "Strap - Alt":              "Hardware",
    "Starter Shim":             "Hardware",
    "Thrust":                   "Hardware",

    "Misc - Alt":               "Misc",
    "Plug":                     "Misc",
    "Drain Tube":               "Misc",
    "Magnet":                   "Misc",
    "Thermal Protector":        "Misc",
    "Spring - Str":             "Misc",
    "Generator Bracket":        "Misc",
    "Spacer":                   "Misc",
    "Expansion Plug":           "Misc",
    "Plate":                    "Misc",
    "Starter":                  "Misc",
}

EXACT_MAP = {
    "Solenoid": "Starter Solenoids & Parts",
}

EMPTY_CATS_TO_DELETE = [
    "Bearing Retainers",
    "Capacitors - AC & DC Motors",
    "Capacitors - Alternator",
    "Center Support & Lever Housing",
    "Diodes & Trios",
    "Mechanical Shaft Seals",
    "Pulleys",
    "Rectifiers",
]


def forwards(apps, schema_editor):
    Part = apps.get_model("catalog", "Part")
    PartCategory = apps.get_model("catalog", "PartCategory")

    prefixes_sorted = sorted(STARTSWITH_MAP.keys(), key=len, reverse=True)

    uncat = Part.objects.filter(category="Uncategorized")
    total = uncat.count()
    moved = 0

    for part in uncat.iterator():
        name = (part.part_name or "").strip()
        target = None

        if name in EXACT_MAP:
            target = EXACT_MAP[name]
        else:
            for prefix in prefixes_sorted:
                if name.startswith(prefix):
                    target = STARTSWITH_MAP[prefix]
                    break

        if target:
            part.category = target
            part.save(update_fields=["category"])
            moved += 1

    deleted = PartCategory.objects.filter(name__in=EMPTY_CATS_TO_DELETE).delete()[0]

    print(f"  Categorized {moved}/{total} parts; deleted {deleted} empty categories")


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0037_fix_part_categories"),
    ]
    operations = [
        migrations.RunPython(forwards, backwards),
    ]
