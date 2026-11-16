from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib import admin
from django.utils import timezone

from registrations.models import Registration

from .models import Event, OrganizerAssignment

UTC_HELP = "In UTC, not the event's own time zone."


class RegistrationInline(admin.TabularInline):
    """An event's registrations, shown as history."""

    model = Registration
    fields = ['member', 'status', 'registered_at',
              'cancelled_at']
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('member')


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['title', 'status', 'start_utc',
                    'local_start', 'places', 'capacity']
    list_filter = ['status']
    search_fields = ['title', 'location']
    ordering = ['-starts_at']
    fields = ['title', 'status', 'starts_at', 'ends_at',
              'timezone', 'local_start', 'location',
              'capacity']
    readonly_fields = ['local_start']
    inlines = [RegistrationInline]
    actions = None

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.with_places()

    def get_form(self, request, obj=None, **kwargs):
        kwargs['help_texts'] = {
            'starts_at': UTC_HELP, 'ends_at': UTC_HELP,
        }
        return super().get_form(request, obj, **kwargs)

    @admin.display(description='Start (UTC)',
                   ordering='starts_at')
    def start_utc(self, event):
        return event.starts_at

    @admin.display(description='Local start')
    def local_start(self, event):
        try:
            zone = ZoneInfo(event.timezone)
        except (ValueError, ZoneInfoNotFoundError):
            return None
        if event.starts_at is None:
            return None
        local = timezone.localtime(event.starts_at, zone)
        return local.strftime('%a %d %b %Y, %H:%M %Z')

    @admin.display(description='Places left',
                   ordering='places_left')
    def places(self, event):
        return event.places_left


@admin.register(OrganizerAssignment)
class OrganizerAssignmentAdmin(admin.ModelAdmin):
    list_display = ['event', 'member', 'assigned_at',
                    'revoked_at']
    list_filter = [
        ('revoked_at', admin.EmptyFieldListFilter),
    ]
    list_select_related = ['event', 'member']

    def get_fields(self, request, obj=None):
        if obj is None:
            return ['event', 'member']
        return ['event', 'member', 'assigned_at',
                'revoked_at']

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return []
        return ['event', 'member', 'assigned_at']

    def has_delete_permission(self, request, obj=None):
        return False
