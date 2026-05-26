from django import template

register = template.Library()


@register.simple_tag
def static_cache_bust(path):
    """Append file mtime to static URL so edits trigger fresh browser fetch."""
    from django.templatetags.static import static
    from django.conf import settings
    import os
    import sys
    full_path = os.path.join(settings.BASE_DIR, "static", path)
    if os.path.exists(full_path):
        mtime = int(os.path.getmtime(full_path))
        return f"/static/{path}?v={mtime}"
    return f"/static/{path}"


@register.filter
def get_field(form, field_name):
    """Look up a form field by name. Usage: {{ form|get_field:'voltage' }}"""
    try:
        return form[field_name]
    except KeyError:
        return ""


@register.filter
def get_item(dictionary, key):
    """Look up a dict value by key. Usage: {{ mydict|get_item:'foo' }}"""
    if isinstance(dictionary, dict):
        return dictionary.get(key, "")
    return ""


@register.filter
def first_jn(value):
    """Return the first J&N number from a pipe- or comma-separated string."""
    if not value:
        return ""
    text = str(value)
    if "|" in text:
        items = [p.strip() for p in text.split("|") if p.strip()]
    else:
        items = [p.strip() for p in text.split(",") if p.strip()]
    return items[0] if items else ""


@register.filter
def jn_items(value):
    """Split a pipe- or comma-separated J&N string into a list of individual numbers."""
    if not value:
        return []
    text = str(value)
    if "|" in text:
        return [p.strip() for p in text.split("|") if p.strip()]
    return [p.strip() for p in text.split(",") if p.strip()]
