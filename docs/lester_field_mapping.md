# Lester CD to Manchester Electric Field Mapping

See `lester_missing_fields_report.txt` for the full report (run `python manage.py import_lester --report-only` to regenerate).

## Summary

| Lester Table | Manchester Electric Model |
|--------------|---------------------------|
| AltGenStrDetails | catalog.Unit |
| Applications | catalog.Application |
| ComponentPartDetails | catalog.Part |
| BillOfMaterials | catalog.BOM + catalog.BOMItem |
| Interchanges | catalog.CrossReference (when both PIC# are Units) |

## Unit Type Mapping

| Lester UnitTypeID | Lester Name | Manchester Electric UnitType |
|------------------|-------------|-----------------------------|
| 1 | ALTERNATOR | Alternator |
| 2 | GENERATOR | Generator |
| 3 | MOTOR | AC Motor |
| 4 | STARTER | Starter |
