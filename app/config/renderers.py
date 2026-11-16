from django.forms.renderers import TemplatesSetting


class OtahqueFormRenderer(TemplatesSetting):
    """Look for form templates in TEMPLATES, so the
    project's own field and widget templates win."""

    field_template_name = 'forms/field.html'
