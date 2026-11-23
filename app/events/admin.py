"""Admin pages for events and their organizers."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils import timezone

from audit.models import AuditEvent, record
from registrations.models import Registration

from .models import (
    Event, OrganizerAssignment, organizer_problem,
)

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
        """Members register on the site, not here."""
        return False

    def has_change_permission(self, request, obj=None):
        """Registrations are history: never edited."""
        return False

    def get_queryset(self, request):
        """Fetch each registration's member at once."""
        queryset = super().get_queryset(request)
        return queryset.select_related('member')


class EventAdminForm(forms.ModelForm):
    """The admin's event form, with the version check."""

    seen_version = forms.IntegerField(
        widget=forms.HiddenInput, required=False
    )

    def __init__(self, *args, **kwargs):
        """Send the version the page is opened at."""
        super().__init__(*args, **kwargs)
        self.fields['seen_version'].initial = (
            self.instance.version
        )

    def clean(self):
        """Refuse a save from an out-of-date page."""
        cleaned = super().clean()
        if (self.instance.pk is not None
                and cleaned.get('seen_version')
                != self.instance.version):
            raise ValidationError(
                'This event was changed after you opened '
                'this page. Reload it and make your changes '
                'again.', code='stale',
            )
        return cleaned


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    """Events, with local start times and places left."""

    list_display = ['title', 'status', 'start_utc',
                    'local_start', 'places', 'capacity']
    list_filter = ['status']
    search_fields = ['title', 'location']
    ordering = ['-starts_at']
    fields = ['title', 'description', 'status',
              'starts_at', 'ends_at',
              'timezone', 'local_start', 'location',
              'capacity', 'registration_opens_at',
              'registration_closes_at',
              'cancellation_deadline', 'phone_required',
              'seen_version']
    readonly_fields = ['local_start']
    form = EventAdminForm
    inlines = [RegistrationInline]
    actions = None

    def get_queryset(self, request):
        """Count places left in the same query."""
        queryset = super().get_queryset(request)
        return queryset.with_places()

    def get_form(self, request, obj=None, **kwargs):
        """Say on the form that its times are in UTC."""
        kwargs['help_texts'] = dict.fromkeys(
            ['starts_at', 'ends_at', 'registration_opens_at',
             'registration_closes_at',
             'cancellation_deadline'], UTC_HELP,
        )
        return super().get_form(request, obj, **kwargs)

    def get_object(self, request, object_id, from_field=None):
        """Lock the event while a change is saved.

        The admin saves inside a transaction, so the lock
        lasts until the save is committed.
        """
        event = super().get_object(request, object_id,
                                   from_field)
        if event is not None and request.method == 'POST':
            return Event.objects.select_for_update().get(
                pk=event.pk
            )
        return event

    def save_model(self, request, obj, form, change):
        """Count this save as a new version of the event."""
        if change:
            obj.version += 1
        super().save_model(request, obj, form, change)

    @admin.display(description='Start (UTC)',
                   ordering='starts_at')
    def start_utc(self, event):
        """Return the start as stored, in UTC."""
        return event.starts_at

    @admin.display(description='Local start')
    def local_start(self, event):
        """Return the start in the event's zone, or None."""
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
        """Places left, counted by the queryset."""
        return event.places_left


class AssignmentForm(forms.ModelForm):
    """The admin's add form, with the page's rules."""

    def clean_member(self):
        """Refuse and record a member who cannot organize."""
        member = self.cleaned_data['member']
        problem = organizer_problem(member)
        if problem:
            event = self.cleaned_data.get('event')
            record(self.request.user,
                   AuditEvent.Action.ADD_ORGANIZER, event,
                   AuditEvent.Outcome.REFUSED,
                   member=member.pk)
            raise ValidationError(problem)
        return member


@admin.register(OrganizerAssignment)
class OrganizerAssignmentAdmin(admin.ModelAdmin):
    """Assign organizers; revoke, but never delete."""

    list_display = ['event', 'member', 'assigned_at',
                    'revoked_at']
    list_filter = [
        ('revoked_at', admin.EmptyFieldListFilter),
    ]
    list_select_related = ['event', 'member']
    form = AssignmentForm
    actions = ['remove_selected']

    def get_fields(self, request, obj=None):
        """Event and member to add; every field after."""
        if obj is None:
            return ['event', 'member']
        return ['event', 'member', 'assigned_at',
                'revoked_at']

    def get_readonly_fields(self, request, obj=None):
        """After adding, every field is read-only."""
        if obj is None:
            return []
        return ['event', 'member', 'assigned_at',
                'revoked_at']

    def get_form(self, request, obj=None, **kwargs):
        """Give the form the request, for its record."""
        form = super().get_form(request, obj, **kwargs)
        form.request = request
        return form

    def save_model(self, request, obj, form, change):
        """Record each organizer added here."""
        super().save_model(request, obj, form, change)
        if not change:
            record(request.user,
                   AuditEvent.Action.ADD_ORGANIZER,
                   obj.event, member=obj.member_id)

    def has_delete_permission(self, request, obj=None):
        """Revoke an assignment instead of deleting it."""
        return False

    @admin.action(description='Remove selected organizers',
                  permissions=['change'])
    def remove_selected(self, request, queryset):
        """Revoke each current assignment chosen."""
        current = queryset.filter(revoked_at__isnull=True)
        for assignment in current.select_related('event'):
            try:
                assignment.revoke(request.user)
            except ValidationError as error:
                self.message_user(
                    request,
                    f'{assignment}: {error.messages[0]}',
                    messages.ERROR,
                )
            else:
                self.log_change(request, assignment,
                                'Removed.')
                self.message_user(
                    request, f'Removed: {assignment}.'
                )
