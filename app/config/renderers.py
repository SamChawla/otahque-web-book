"""How Otahque draws its form fields."""
from django.forms.renderers import TemplatesSetting


class OtahqueFormRenderer(TemplatesSetting):
    """Use the project's own field and widget templates."""

    field_template_name = 'forms/field.html'
