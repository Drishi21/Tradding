# marketdata/templatetags/dict_extras.py
from django import template

register = template.Library()

@register.filter
def dict_get(d, key):
    """Safely get a key from a dict in templates"""
    if d is None:
        return None
    return d.get(key)
