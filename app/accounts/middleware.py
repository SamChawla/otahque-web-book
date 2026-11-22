"""Middleware that shows pages in the viewer's zone."""
from django.urls import reverse
from django.utils import timezone

from .timezones import resolve_timezone


class TimezoneMiddleware:
    """Show every page in the viewer's zone.

    The admin is the exception: it stays in UTC (Chapter 23).
    """

    def __init__(self, get_response):
        """Keep the next handler in the chain."""
        self.get_response = get_response

    def __call__(self, request):
        """Turn on the viewer's zone for this request."""
        if request.path.startswith(reverse('admin:index')):
            timezone.deactivate()
        else:
            timezone.activate(resolve_timezone(request))
        return self.get_response(request)
