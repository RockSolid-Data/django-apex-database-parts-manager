from django import template

register = template.Library()


@register.filter
def margin_pct(part):
    """Return margin % as ((price - cost) / cost) * 100, or None if not calculable."""
    cost = part.cost_price
    price = part.price
    if cost is None or cost <= 0 or price is None:
        return None
    return round(float((price - cost) / cost * 100), 1)


@register.filter
def total_value(part):
    """Return cost_price * stock_quantity, or 0 if cost is None."""
    cost = part.cost_price
    qty = part.stock_quantity or 0
    if cost is None:
        return None
    return cost * qty
