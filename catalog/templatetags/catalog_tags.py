from django import template

register = template.Library()


@register.simple_tag
def static_cache_bust(path):
    """Append file mtime to static URL so edits trigger fresh browser fetch."""
    from django.templatetags.static import static
    from django.conf import settings
    import os
    full_path = os.path.join(settings.BASE_DIR, "static", path)
    if os.path.exists(full_path):
        mtime = int(os.path.getmtime(full_path))
        return f"{static(path)}?v={mtime}"
    return static(path)


@register.filter
def get_field(form, field_name):
    """Look up a form field by name. Usage: {{ form|get_field:'voltage' }}"""
    try:
        return form[field_name]
    except KeyError:
        return ""
