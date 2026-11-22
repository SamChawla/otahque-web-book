"""Which time zone to show a viewer, and times in it."""
from zoneinfo import ZoneInfo, available_timezones

from django.utils import timezone

from .models import Profile

# The cookie site.js writes with the browser's time zone.
COOKIE = 'otahque_tz'
KNOWN = frozenset(available_timezones())
UTC = ZoneInfo('UTC')


def resolve_timezone(request):
    """Return the zone to show times in.

    The member's profile, then the browser's cookie,
    then UTC.
    """
    user = request.user
    if user.is_authenticated:
        saved = Profile.objects.filter(
            user=user
        ).values_list('timezone', flat=True).first()
        if saved:
            return ZoneInfo(saved)
    name = request.COOKIES.get(COOKIE, '')
    if name in KNOWN:
        return ZoneInfo(name)
    return UTC


def to_user_time(value, request):
    """value, an aware datetime, in the viewer's zone."""
    zone = resolve_timezone(request)
    return timezone.localtime(value, zone)
