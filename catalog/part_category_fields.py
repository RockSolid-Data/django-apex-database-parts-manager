"""
Category-specific field definitions for Parts.

To add a new category, just add an entry to CATEGORY_FIELD_DEFINITIONS.
Each field dict needs: name (internal key), label (display), type (text|checkbox|select).
For "select" types, include an "options" list.
No migrations required when adding new categories.
"""

CATEGORY_FIELD_DEFINITIONS = {
    "Bearings": [
        {"name": "id_dimension", "label": "ID", "type": "text"},
        {"name": "od_dimension", "label": "OD", "type": "text"},
        {"name": "width", "label": "W", "type": "text"},
        {"name": "side_type", "label": "Side Type", "type": "text"},
        {"name": "extended_inner_race", "label": "Extended Inner Race", "type": "text"},
        {"name": "snap_ring", "label": "Snap Ring", "type": "text"},
        {"name": "style", "label": "Style", "type": "text"},
        {"name": "which_end", "label": "Which End", "type": "text"},
        {"name": "family", "label": "Family", "type": "text"},
    ],
    "Bearing Retainers": [
        {"name": "id_dimension", "label": "ID", "type": "text"},
        {"name": "od_dimension", "label": "OD", "type": "text"},
        {"name": "width", "label": "W", "type": "text"},
        {"name": "family", "label": "Family", "type": "text"},
        {"name": "style", "label": "Style", "type": "text"},
    ],
    "Bushings": [
        {"name": "id_dimension", "label": "ID", "type": "text"},
        {"name": "od_dimension", "label": "OD", "type": "text"},
        {"name": "width", "label": "W", "type": "text"},
        {"name": "bushing_type", "label": "Type", "type": "text"},
        {"name": "style", "label": "Style", "type": "text"},
        {"name": "where_used", "label": "Where Used", "type": "text"},
        {"name": "family", "label": "Family", "type": "text"},
        {"name": "flange", "label": "Flange", "type": "text"},
    ],
}

MISC_FIELDS = [
    {"name": "misc_1", "label": "Misc 1", "type": "text"},
    {"name": "misc_2", "label": "Misc 2", "type": "text"},
    {"name": "misc_3", "label": "Misc 3", "type": "text"},
]
