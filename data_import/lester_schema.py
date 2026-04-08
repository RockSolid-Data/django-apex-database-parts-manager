"""
Lester CD schema constants and field mappings for import.
"""
from pathlib import Path

# Lester table -> Manchester Electric model mapping
LESTER_TO_ME = {
    "AltGenStrDetails": "catalog.Unit",
    "Applications": "catalog.Application",
    "ComponentPartDetails": "catalog.Part",
    "BillOfMaterials": "catalog.BOMItem",
    "Interchanges": "catalog.CrossReference",
}

# Suggested column mappings (Lester column -> ME field)
# Fields with no match will go in missing report
UNIT_MAPPING = {
    "PIC#": "unit_number",  # REQUIRED
    "UnitTypeID": "unit_type",  # FK, lookup via tblMasterUnitType
    "ManufacturerID": "oem",  # lookup via tblMasterManufacturer
    "Voltage": "voltage",
    "Rotation": "rotation",
    "Amperage": "amp_rating",
    "ClockPosition": "clock_position",
    "PulleyClass": "pulley_class",
    "Regulator": "regulator_type",  # alternator-specific
    "Teeth": "tooth_quantity",  # starter-specific
    "PowerSize": "power_rating",
    "PowerUnits": "kw_hp",
    "StarterTypeID": "starter_type",  # lookup tblMasterStarterType
    "LongNote": "unit_attributes",
    "ShortNote": "notes",
}

APPLICATION_MAPPING = {
    "ID": None,  # internal
    "MakeID": "make",  # lookup tblMasterMake
    "ModelID": "model",  # lookup tblMasterModel
    "SubModelID": "submodel",  # lookup tblMasterSubmodel
    "Engine": "engine",
    "FuelType": "fuel_type",
    "YearRange": "year",
    "VIN": "vin",
    "UnitTypeID": "unit_type_name",  # resolved via tblMasterUnitType
    "Options": "options",
    "ManufacturerID": "mfr",  # lookup
    "Lester#": "part_number",
    "PIC#": "unit_number",  # links to Unit
    "AltPulley": "alt_pulley",
    "PrimaryOE": "other_number",
    "Comment": "notes",
}

PART_MAPPING = {
    "Id": None,
    "PIC#": "part_number",  # REQUIRED
    "PartTypeID": "type",  # lookup tblMasterPartType
    "ManufacturerID": "oem",  # lookup
    "PartClass": "category",
    "Dimensions": "description",
    "LongNote": "foot_notes",
    "ShortNote": "description",  # append to description
}

INTERCHANGE_MAPPING = {
    "PIC#": "unit",  # FK to Unit
    "InterchangeNumber": "cross_ref_number",  # also sets cross_ref_unit when it matches a Unit
    "InterchangeTypeID": "interchange_type",  # lookup tblMasterInterchangeType
}

# Lester columns with NO Manchester Electric match (all resolved)
LESTER_UNMAPPED = {
    "AltGenStrDetails": [],
    "Applications": [],
    "ComponentPartDetails": [],
    "BillOfMaterials": [],
    "Interchanges": [],
}
