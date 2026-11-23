"""The events app's forms."""
from datetime import UTC
from zoneinfo import ZoneInfo, available_timezones

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import CAPACITY_MESSAGE, Event

ZONE_CHOICES = [('', 'Choose a time zone')] + [
    (name, name) for name in sorted(available_timezones())
]


BOX_FORMAT = '%Y-%m-%dT%H:%M'
# Every time the event form reads in the event's zone.
TIMES = ['starts_at', 'ends_at', 'registration_opens_at',
         'registration_closes_at', 'cancellation_deadline']


def local_input():
    """Make a date-and-time box that the browser fills in."""
    return forms.DateTimeInput(
        attrs={'type': 'datetime-local'},
        format=BOX_FORMAT,
    )


def in_zone(value, zone_name):
    """Read a typed time as a time in the named zone."""
    typed = timezone.make_naive(value)
    zone = ZoneInfo(zone_name)
    first = typed.replace(tzinfo=zone)
    second = typed.replace(tzinfo=zone, fold=1)
    if first.utcoffset() == second.utcoffset():
        return first
    params = {'time': typed.strftime('%H:%M'),
              'zone': zone_name}
    back = first.astimezone(UTC).astimezone(zone)
    if back.replace(tzinfo=None) != typed:
        raise ValidationError(
            '%(time)s does not exist in %(zone)s that '
            'day: the clocks go forward.',
            code='skipped_time', params=params,
        )
    raise ValidationError(
        '%(time)s happens twice in %(zone)s that day: '
        'the clocks go back.',
        code='repeated_time', params=params,
    )


def reading(moment, zone_name):
    """Say when moment is, in zone_name and in UTC."""
    local = moment.astimezone(ZoneInfo(zone_name))
    utc = moment.astimezone(UTC)
    return (f'{local.day} {local:%B %Y, %H:%M} {zone_name}'
            f' ({utc.day} {utc:%B, %H:%M} UTC)')


class UtcCleaning:
    """Clean typed times under UTC.

    UTC has no clock changes; in_zone() then reads them in
    the event's zone, whatever zone the viewer's page uses.
    """

    def full_clean(self):
        """Run every check with UTC as the current zone."""
        with timezone.override(UTC):
            super().full_clean()


class EventForm(UtcCleaning, forms.ModelForm):
    """Sam's new event. Status is not one of its fields."""

    timezone = forms.ChoiceField(
        choices=ZONE_CHOICES,
        label='Time zone',
        help_text='Starts and Ends are read in this zone.',
    )

    class Meta:
        model = Event
        fields = ['title', 'description', 'timezone',
                  'starts_at', 'ends_at', 'location',
                  'capacity', 'registration_opens_at',
                  'registration_closes_at',
                  'cancellation_deadline', 'phone_required']
        labels = {'starts_at': 'Starts', 'ends_at': 'Ends'}
        help_texts = {
            'description': 'Needed before the event can be '
                           'published.',
            'location': 'A venue address, or Online.',
        }
        widgets = {
            'description': forms.Textarea(attrs={'rows': 5}),
        } | {name: local_input() for name in TIMES}

    def __init__(self, *args, **kwargs):
        """Show saved times; ask before a zone change."""
        super().__init__(*args, **kwargs)
        self.saved_zone = self.instance.timezone
        self.shown = {}
        if self.instance.pk:
            self.show_saved_times()
        if self.zone_changed():
            self.fields['confirm_zone'] = forms.BooleanField(
                required=False,
                label='Yes, move the event to this zone',
            )
            self.order_fields(
                ['title', 'timezone', 'confirm_zone']
            )

    def show_saved_times(self):
        """Show stored times as typed in the event's zone."""
        zone = ZoneInfo(self.saved_zone)
        for name in TIMES:
            moment = getattr(self.instance, name)
            if moment is None:
                continue
            local = moment.astimezone(zone)
            local = local.replace(tzinfo=None)
            self.initial[name] = local
            self.shown[name] = local.strftime(BOX_FORMAT)
            self.fields[name].help_text = (
                'Saved: ' + reading(moment, self.saved_zone)
            )

    def zone_changed(self):
        """Return whether an edit changes the saved zone."""
        if not self.is_bound or self.instance.pk is None:
            return False
        return self.data.get('timezone') != self.saved_zone

    def clean_capacity(self):
        """Refuse a capacity below 1 with one message."""
        capacity = self.cleaned_data['capacity']
        if capacity < 1:
            raise ValidationError(CAPACITY_MESSAGE,
                                  code='capacity_too_small')
        return capacity

    def clean(self):
        """Read times in the zone; ask before a new zone."""
        data = super().clean()
        zone = data.get('timezone')
        for name in TIMES:
            if zone and data.get(name):
                try:
                    data[name] = self.read_time(
                        name, data[name], zone
                    )
                except ValidationError as error:
                    self.add_error(name, error)
        starts = data.get('starts_at')
        ends = data.get('ends_at')
        if starts and ends and ends <= starts:
            self.add_error(
                'ends_at',
                'An event must end after it starts.',
            )
        if self.zone_changed() and not data.get(
                'confirm_zone'):
            self.ask_about_zone(data)
        return data

    def read_time(self, name, value, zone):
        """Keep a time left alone; read others in zone."""
        typed = timezone.make_naive(value)
        unchanged = (zone == self.saved_zone and
                     typed.strftime(BOX_FORMAT)
                     == self.shown.get(name))
        if unchanged:
            return getattr(self.instance, name)
        return in_zone(value, zone)

    def ask_about_zone(self, data):
        """Show both readings before a new zone is saved."""
        zone = data.get('timezone')
        starts = data.get('starts_at')
        if not zone:
            return
        message = 'Tick the box to save the new zone.'
        params = {}
        if starts:
            message = ('Saved now: %(saved)s. With this '
                       'zone: %(new)s. ' + message)
            params = {
                'saved': reading(self.instance.starts_at,
                                 self.saved_zone),
                'new': reading(starts, zone),
            }
        self.add_error('timezone', ValidationError(
            message, code='zone_changed', params=params,
        ))


class CopyForm(UtcCleaning, forms.Form):
    """The one thing a copy asks for: when it starts."""

    starts_at = forms.DateTimeField(
        label='New start', widget=local_input(),
    )

    def __init__(self, *args, event, **kwargs):
        """Say which zone the new start is read in."""
        super().__init__(*args, **kwargs)
        self.event = event
        self.fields['starts_at'].help_text = (
            f'Read in {event.timezone}. The copy lasts as '
            'long as the original.'
        )

    def clean_starts_at(self):
        """Read the new start in the event's time zone."""
        return in_zone(self.cleaned_data['starts_at'],
                       self.event.timezone)


class OrganizerForm(forms.Form):
    """An administrator names a member by email."""

    email = forms.EmailField(
        label='Member’s email address'
    )

    def clean_email(self):
        """Find the member with this email, or refuse."""
        email = self.cleaned_data['email'].lower()
        User = get_user_model()
        try:
            self.member = User.objects.get(email=email)
        except User.DoesNotExist:
            raise ValidationError(
                'No member has this email address.'
            ) from None
        return email


class RemoveOrganizerForm(forms.Form):
    """Which current organizer of this event to remove.

    Choices from other events are not valid.
    """

    assignment = forms.ModelChoiceField(queryset=None)

    def __init__(self, *args, event, **kwargs):
        """Offer only this event's current organizers."""
        super().__init__(*args, **kwargs)
        current = event.organizer_assignments.filter(
            revoked_at__isnull=True
        )
        self.fields['assignment'].queryset = current


class VersionForm(forms.Form):
    """The event version the edit page was opened at."""

    version = forms.IntegerField(min_value=1,
                                 widget=forms.HiddenInput)
