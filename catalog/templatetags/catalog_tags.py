from django import template

register = template.Library()


@register.simple_tag
def static_cache_bust(path):
    """Append file mtime to static URL so edits trigger fresh browser fetch."""
    from django.conf import settings
    import os
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


@register.filter
def first_year_range(value):
    """Return only the first year range from a pipe-separated string.

    Single group  → shown as-is, e.g. "1978-1982"
    Multiple groups → first group + "....", e.g. "1978-1982...."
    """
    if not value:
        return ""
    text = str(value)
    if " | " in text:
        return text.split(" | ")[0].strip() + "...."
    return text


@register.inclusion_tag("includes/_page_window.html")
def page_window(page_obj, window_size=3):
    """
    Build a sliding window of page numbers for pagination display.
    Returns: list of ints and None (None = ellipsis gap).
    Example for page 6 of 100, window_size=3:
        [1, None, 3, 4, 5, 6, 7, 8, 9, None, 100]
    """
    num_pages = page_obj.paginator.num_pages
    current = page_obj.number

    if num_pages <= (2 * window_size + 5):
        pages = list(range(1, num_pages + 1))
    else:
        pages = []
        left = max(current - window_size, 1)
        right = min(current + window_size, num_pages)

        if left > 1:
            pages.append(1)
        if left > 2:
            pages.append(None)

        pages.extend(range(left, right + 1))

        if right < num_pages - 1:
            pages.append(None)
        if right < num_pages:
            pages.append(num_pages)

    return {"pages": pages, "current_page": current}
