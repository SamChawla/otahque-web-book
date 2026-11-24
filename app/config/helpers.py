"""Helpers that more than one app's tests use.

Not a test module: its name does not start with "test",
so the test runner never collects it. Each helper makes
data or a request the way the earlier chapters' tests
did; one copy here replaces the imports from
events.tests that broke when the tests moved.
"""
from datetime import UTC, datetime, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse

from audit.models import AuditEvent
from events.forms import EventForm
from events.models import Event, OrganizerAssignment

User = get_user_model()

SAI_PASSWORD = 'a-long-safe-pass-123'


def save_event(**changes):
    """Save a published event; keywords replace defaults."""
    fields = {
        'title': 'Python meetup',
        'starts_at': datetime(2026, 11, 19, 18, 30,
                              tzinfo=UTC),
        'timezone': 'Europe/London',
        'location': 'Leeds Central Library',
        'capacity': 40,
        'status': Event.Status.PUBLISHED,
    }
    fields.update(changes)
    fields.setdefault(
        'ends_at', fields['starts_at'] + timedelta(hours=2)
    )
    return Event.objects.create(**fields)


def in_group(email, group, **flags):
    """Add a member with SAI_PASSWORD to the named group."""
    name = email.split('@')[0].title()
    user = User.objects.create_user(
        email, SAI_PASSWORD, display_name=name, **flags
    )
    user.groups.add(Group.objects.get(name=group))
    return user


def admin_url(model, page, *args):
    """Return an admin page's address, such as an event's."""
    meta = model._meta
    name = f'admin:{meta.app_label}_{meta.model_name}_{page}'
    return reverse(name, args=args)


def event_form(event, **changes):
    """Build what the admin's event page sends; UTC times."""
    data = {
        'title': event.title,
        'status': event.status,
        'starts_at_0': f'{event.starts_at:%Y-%m-%d}',
        'starts_at_1': f'{event.starts_at:%H:%M}',
        'ends_at_0': f'{event.ends_at:%Y-%m-%d}',
        'ends_at_1': f'{event.ends_at:%H:%M}',
        'timezone': event.timezone,
        'location': event.location,
        'capacity': event.capacity,
        'registrations-TOTAL_FORMS': 0,
        'registrations-INITIAL_FORMS': 0,
        'seen_version': event.version,
    }
    data.update(changes)
    return data


def remove_selected(client, *assignments):
    """Run the admin's Remove selected organizers action."""
    return client.post(
        admin_url(OrganizerAssignment, 'changelist'),
        {'action': 'remove_selected',
         '_selected_action': [a.pk for a in assignments]},
        follow=True,
    )


def as_sent(event, **changes):
    """Return what the edit page sends, before any change."""
    form = EventForm(instance=event)
    data = {}
    for name in form.fields:
        value = form[name].value()
        if isinstance(value, datetime):
            value = f'{value:%Y-%m-%dT%H:%M}'
        # A blank time is sent as an empty box.
        data[name] = '' if value is None else value
    # The version the page was opened at (Chapter 33).
    data['version'] = event.version
    return data | changes


def outcome(response):
    """Name a response as the permission matrix names it."""
    code = response.status_code
    if code == 302 and response.url.startswith(
            reverse('account_login')):
        return 'sign in'
    return {200: 'ok', 302: 'ok'}.get(code, str(code))


def answer(client, method, path):
    """Name how a page answered one request, for a table.

    First outcome()'s name ('sign in', 'ok', or the status
    code), then the Allow header if there is one, then
    'recorded' if a refused attempt was recorded.
    """
    refused = AuditEvent.objects.filter(
        outcome=AuditEvent.Outcome.REFUSED
    )
    before = refused.count()
    response = client.generic(method, path)
    words = [outcome(response)]
    if response.has_header('Allow'):
        words.append(response['Allow'])
    if refused.count() > before:
        words.append('recorded')
    return ' '.join(words)


def answers(path, member, method):
    """Return a page's answers signed out and as member."""
    signed_in = Client()
    signed_in.force_login(member)
    return (answer(Client(), method, path),
            answer(signed_in, method, path))
