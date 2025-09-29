# marketdata/templatetags/heatmap_filters.py
from django import template
register = template.Library()

@register.filter
def opacity(value):
    try:
        v = float(value)
        # if value looks like 0..100 convert to 0..1
        if abs(v) > 1:
            v = v / 100.0
        if v < 0:
            v = 0.0
        if v > 1:
            v = 1.0
        return v
    except:
        return 0.0


@register.filter
def subtract(value, arg):
    """Subtract arg from value"""
    return value - arg