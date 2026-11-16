from datetime import UTC
from zoneinfo import ZoneInfo, available_timezones

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Event

ZONE_CHOICES = [('', 'Choose a time zone')] + [
    (name, name) for name in sorted(available_timezones())
]


def local_input():
    """A date-and-time box that the browser fills in."""
    return forms.DateTimeInput(
        attrs={'type': 'datetime-local'},
        format='%Y-%m-%dT%H:%M',
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


class EventForm(forms.ModelForm):
    """Sam's new event. Status is not one of its fields."""

    timezone = forms.ChoiceField(
        choices=ZONE_CHOICES,
        label='Time zone',
        help_text='Starts and Ends are read in this zone.',
    )

    class Meta:
        model = Event
        fields = ['title', 'timezone', 'starts_at',
                  'ends_at', 'location', 'capacity']
        labels = {'starts_at': 'Starts', 'ends_at': 'Ends'}
        help_texts = {
            'location': 'A venue address, or Online.',
        }
        widgets = {'starts_at': local_input(),
                   'ends_at': local_input()}

    def clean(self):
        data = super().clean()
        zone = data.get('timezone')
        for name in ('starts_at', 'ends_at'):
            if zone and data.get(name):
                try:
                    data[name] = in_zone(data[name], zone)
                except ValidationError as error:
                    self.add_error(name, error)
        starts = data.get('starts_at')
        ends = data.get('ends_at')
        if starts and ends and ends <= starts:
            self.add_error(
                'ends_at',
                'An event must end after it starts.',
            )
        return data
