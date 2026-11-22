"""Template filters for Otahque's form widgets."""
from django import template
from django.forms.utils import flatatt

register = template.Library()


@register.filter
def with_class(attrs, classes):
    """Render a widget's attributes with one class attribute.

    Otahque's classes come first, then the widget's own, so
    the admin keeps selectfilter, vDateField, and the rest.
    """
    own = attrs.get('class')
    merged = dict(attrs)
    merged['class'] = f'{classes} {own}' if own else classes
    return flatatt(merged)
