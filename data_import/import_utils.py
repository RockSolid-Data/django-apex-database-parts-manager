"""Shared helpers for staging DB import commands."""

from collections import defaultdict

from django.db import models

from catalog.models import Part


SOURCE_CONFIG = {
    "jn_master": {
        "catalog": "J&N Master Catalog",
        "prefix": "JN",
        "part_number_field": "j_and_n",
    },
    "metro": {
        "catalog": "Metro Catalog",
        "prefix": "METRO",
        "part_number_field": "manufacturer_number",
    },
    "transpo": {
        "catalog": "Transpo Catalog",
        "prefix": "TRANSPO",
        "part_number_field": "manufacturer_number",
    },
}


def normalize_space(value):
    return " ".join((value or "").split())


def append_text(existing, extra):
    extra = normalize_space(extra)
    if not extra:
        return existing or ""
    if not existing:
        return extra
    lines = [line.strip() for line in existing.splitlines() if line.strip()]
    if extra in lines:
        return existing
    return f"{existing.rstrip()}\n{extra}"


def get_source_config(source_key):
    return SOURCE_CONFIG[source_key]


def source_catalog_label(source_key):
    return get_source_config(source_key)["catalog"]


def source_prefix(source_key):
    return get_source_config(source_key)["prefix"]


def source_number_field(source_key):
    return get_source_config(source_key)["part_number_field"]


def source_part_number(source_key, raw_number):
    raw_number = normalize_space(raw_number)
    if not raw_number:
        return ""
    return f"{source_prefix(source_key)}:{raw_number}"[:100]


def _dedup_parts(parts):
    seen = set()
    result = []
    for part in parts:
        if part.pk in seen:
            continue
        seen.add(part.pk)
        result.append(part)
    return result


def load_same_source_parts(source_key, source_numbers):
    """Return raw source number -> existing same-source Part."""
    source_numbers = sorted({normalize_space(value) for value in source_numbers if normalize_space(value)})
    if not source_numbers:
        return {}

    catalog = source_catalog_label(source_key)
    number_field = source_number_field(source_key)
    prefixed_numbers = [source_part_number(source_key, value) for value in source_numbers]
    query = models.Q(catalog=catalog) & (
        models.Q(part_number__in=prefixed_numbers)
        | models.Q(part_number__in=source_numbers)
        | models.Q(**{f"{number_field}__in": source_numbers})
    )
    parts = Part.objects.filter(query)

    mapping = {}
    for part in parts:
        identifiers = {
            normalize_space(part.part_number),
            normalize_space(getattr(part, number_field, "")),
        }
        for identifier in identifiers:
            if not identifier:
                continue
            if identifier in source_numbers or identifier in prefixed_numbers:
                raw_identifier = identifier
                if identifier.startswith(source_prefix(source_key) + ":"):
                    raw_identifier = identifier.split(":", 1)[1]
                mapping[raw_identifier] = part
    return mapping


def build_exact_part_lookup(identifier_values, exclude_catalogs=None):
    """Return exact identifier -> Part for unambiguous matches only."""
    identifier_values = {normalize_space(value) for value in identifier_values if normalize_space(value)}
    if not identifier_values:
        return {}

    matches = defaultdict(list)
    ordered_identifiers = sorted(identifier_values)
    chunk_size = 400
    for start in range(0, len(ordered_identifiers), chunk_size):
        chunk = ordered_identifiers[start:start + chunk_size]
        query = (
            models.Q(part_number__in=chunk)
            | models.Q(yt_number__in=chunk)
            | models.Q(j_and_n__in=chunk)
            | models.Q(oem_number__in=chunk)
            | models.Q(manufacturer_number__in=chunk)
        )
        parts = Part.objects.filter(query)
        if exclude_catalogs:
            parts = parts.exclude(catalog__in=exclude_catalogs)

        chunk_set = set(chunk)
        for part in parts:
            for identifier in {
                normalize_space(part.part_number),
                normalize_space(part.yt_number),
                normalize_space(part.j_and_n),
                normalize_space(part.oem_number),
                normalize_space(part.manufacturer_number),
            }:
                if identifier in chunk_set:
                    matches[identifier].append(part)

    resolved = {}
    for identifier, parts_for_identifier in matches.items():
        unique_parts = _dedup_parts(parts_for_identifier)
        if len(unique_parts) == 1:
            resolved[identifier] = unique_parts[0]
    return resolved
