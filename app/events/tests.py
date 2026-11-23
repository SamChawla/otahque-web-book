"""Tests for the events app."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.sessions.models import Session
from django.contrib.staticfiles import finders
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import (
    IntegrityError, connection, transaction,
)
from django.db.models import ProtectedError
from django.template.loader import render_to_string
from django.test import Client, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse
from django.utils import timezone

from . import views
from .forms import CopyForm, EventForm
from .models import ORGANIZERS, Event, OrganizerAssignment
from audit.models import AuditEvent
from registrations.models import Registration

User = get_user_model()


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


def admin_url(model, page, *args):
    """Return an admin page's address, such as an event's."""
    meta = model._meta
    name = f'admin:{meta.app_label}_{meta.model_name}_{page}'
    return reverse(name, args=args)


def layout_pages(event):
    """List the pages sharing the layout, for one event."""
    return [
        ('/', 'events/home.html', 'Otahque'),
        ('/events/', 'events/list.html',
         'Events | Otahque'),
        (f'/events/{event.pk}/', 'events/detail.html',
         'Python meetup | Otahque'),
    ]


class RoutingTests(TestCase):
    """Each address reaches its view; others are not found."""

    @classmethod
    def setUpTestData(cls):
        cls.event = save_event(title='Django workshop')

    def test_home(self):
        response = self.client.get('/')
        self.assertContains(
            response, 'Welcome to Otahque.'
        )
        self.assertEqual(reverse('events:home'), '/')
        self.assertIs(resolve('/').func, views.home)

    def test_event_list(self):
        response = self.client.get('/events/')
        self.assertContains(response, 'Django workshop')
        self.assertTemplateUsed(
            response, 'events/list.html'
        )
        self.assertContains(
            response, f'href="/events/{self.event.pk}/"'
        )
        self.assertEqual(
            reverse('events:list'), '/events/'
        )
        self.assertIs(
            resolve('/events/').func, views.event_list
        )

    def test_unknown_path(self):
        response = self.client.get('/does-not-exist/')
        self.assertEqual(response.status_code, 404)


class EventListTests(TestCase):
    """The list: upcoming first, then past, published only."""

    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        for title, days in [('Open lab', 0),
                            ('Django workshop', 14),
                            ('Python meetup', 7),
                            ('Leeds social', -7),
                            ('Autumn walk', -30)]:
            start = now + timedelta(days=days, hours=-1)
            save_event(title=title, starts_at=start)
        save_event(title='Spring planning',
                   status=Event.Status.DRAFT)
        save_event(title='Autumn social',
                   status=Event.Status.CANCELLED)

    def test_upcoming_first_then_past(self):
        with self.assertNumQueries(2):
            response = self.client.get('/events/')
        html = response.content.decode()
        titles = ['Open lab', 'Python meetup',
                  'Django workshop', 'Past events',
                  'Leeds social', 'Autumn walk']
        places = [html.index(title) for title in titles]
        self.assertEqual(places, sorted(places))
        self.assertNotContains(response, 'Spring planning')
        self.assertNotContains(response, 'Autumn social')

    def test_marks_current_and_past_events(self):
        response = self.client.get('/events/')
        self.assertContains(
            response, 'Happening now', count=1
        )
        self.assertContains(response, 'event-past', count=1)

    def test_empty_list(self):
        Event.objects.all().delete()
        response = self.client.get('/events/')
        self.assertContains(response, 'No upcoming events.')
        self.assertNotContains(response, 'Past events')


class EventDetailTests(TestCase):
    """One published event by number; 404 for any other."""

    @classmethod
    def setUpTestData(cls):
        cls.event = save_event()

    def test_published_event(self):
        response = self.client.get(
            f'/events/{self.event.pk}/'
        )
        self.assertContains(
            response, '<h1>Python meetup</h1>', html=True
        )
        self.assertContains(
            response, 'Thursday 19 November 2026, 18:30 GMT'
        )
        self.assertContains(
            response, 'Thursday 19 November 2026, 20:30 GMT'
        )
        self.assertContains(
            response, 'Leeds Central Library'
        )
        self.assertTemplateUsed(
            response, 'events/detail.html'
        )

    def test_time_in_event_time_zone(self):
        event = save_event(
            starts_at=datetime(2026, 12, 3, 9,
                               tzinfo=UTC),
            timezone='Asia/Kolkata',
        )
        response = self.client.get(f'/events/{event.pk}/')
        self.assertContains(
            response, 'Thursday 3 December 2026, 14:30 IST'
        )

    def test_drafts_are_hidden(self):
        response = self.client.get(
            f'/events/{self.event.pk}/'
        )
        self.assertContains(
            response, 'Leeds Central Library'
        )
        event = save_event(status=Event.Status.DRAFT)
        response = self.client.get(f'/events/{event.pk}/')
        self.assertEqual(response.status_code, 404)

    def test_missing_event(self):
        self.assertIs(
            resolve('/events/999/').func,
            views.event_detail,
        )
        response = self.client.get('/events/999/')
        self.assertEqual(response.status_code, 404)

    def test_invalid_id(self):
        response = self.client.get('/events/abc/')
        self.assertEqual(response.status_code, 404)


class TemplateSafetyTests(TestCase):
    """Templates escape titles; an empty list says so."""

    @classmethod
    def setUpTestData(cls):
        cls.event = save_event(
            title='<strong>Not a tag</strong>'
        )

    def test_list_escapes_title(self):
        response = self.client.get('/events/')
        self.assertContains(
            response, '&lt;strong&gt;'
        )
        self.assertNotContains(
            response, '<strong>Not a tag'
        )

    def test_detail_escapes_title(self):
        response = self.client.get(
            f'/events/{self.event.pk}/'
        )
        self.assertContains(
            response, '&lt;strong&gt;'
        )
        self.assertNotContains(
            response, '<strong>Not a tag'
        )


class LayoutTests(TestCase):
    """Every page shares the base layout and navigation."""

    @classmethod
    def setUpTestData(cls):
        cls.pages = layout_pages(save_event())

    def test_pages_extend_layout(self):
        for url, template, title in self.pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertTemplateUsed(response, template)
                self.assertTemplateUsed(
                    response, 'base.html'
                )
                self.assertContains(
                    response, f'<title>{title}</title>',
                    html=True,
                )

    def test_pages_include_navigation(self):
        for url, template, title in self.pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertTemplateUsed(
                    response, 'includes/site_nav.html'
                )
                self.assertContains(
                    response,
                    '<a href="/">Home</a>',
                    html=True,
                )
                self.assertContains(
                    response,
                    '<a href="/events/">Events</a>',
                    html=True,
                )


class EventRowPartialTests(SimpleTestCase):
    """The event row partial renders one event."""

    def test_row_renders_alone(self):
        start = datetime(2026, 11, 19, 18, 30, tzinfo=UTC)
        event = Event(pk=7, title='<b>Not a tag</b>',
                      starts_at=start,
                      ends_at=start + timedelta(hours=2),
                      timezone='Europe/London')
        html = render_to_string(
            'events/list.html#event-row', {'event': event}
        )
        self.assertIn('href="/events/7/"', html)
        self.assertIn('&lt;b&gt;Not a tag', html)
        self.assertIn('Thu 19 Nov 2026, 18:30 GMT', html)
        self.assertNotIn('<nav', html)


class StylesheetTests(TestCase):
    """Pages link the stylesheet, and Django can find it."""

    @classmethod
    def setUpTestData(cls):
        cls.pages = layout_pages(save_event())

    def test_pages_link_stylesheet(self):
        for url, template, title in self.pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(
                    response,
                    '<link rel="stylesheet"'
                    ' href="/static/otahque/site.css">',
                    html=True,
                )

    def test_finder_locates_stylesheet(self):
        self.assertIsNotNone(
            finders.find('otahque/site.css')
        )


class DesignSystemTests(SimpleTestCase):
    """The navigation uses the design system navbar."""

    def test_navigation_uses_navbar(self):
        response = self.client.get('/')
        self.assertContains(
            response, '<nav class="site-nav navbar'
        )

    def test_stylesheet_defines_navbar(self):
        found = finders.find('otahque/site.css')
        css = Path(found).read_text(encoding='utf-8')
        self.assertTrue(
            '.navbar {' in css,
            'site.css has no .navbar rule',
        )


class EventModelTests(TestCase):
    """The Event model's rules, checked with the database."""

    def make_event(self, **changes):
        """Make a valid unsaved event with these changes."""
        fields = {
            'title': 'Python meetup',
            'starts_at': datetime(2026, 11, 19, 18, 30,
                                  tzinfo=UTC),
            'ends_at': datetime(2026, 11, 19, 20, 30,
                                tzinfo=UTC),
            'timezone': 'Europe/London',
            'location': 'Virtual',
            'capacity': 40,
        }
        fields.update(changes)
        return Event(**fields)

    def test_str_is_title(self):
        event = self.make_event()
        self.assertEqual(str(event), 'Python meetup')

    def test_status_starts_draft_and_is_checked(self):
        event = self.make_event()
        self.assertEqual(event.status, Event.Status.DRAFT)
        event.full_clean()
        event.status = 'archived'
        with self.assertRaises(ValidationError) as caught:
            event.full_clean()
        self.assertEqual(
            caught.exception.message_dict,
            {'status': [
                "Value 'archived' is not a valid choice."
            ]},
        )


class OrganizerAssignmentTests(TestCase):
    """An assignment links an organizer to an event."""

    @classmethod
    def setUpTestData(cls):
        cls.event = save_event()
        cls.member = User.objects.create_user(
            'sam@example.org', display_name='Sam'
        )
        cls.assignment = OrganizerAssignment.objects.create(
            event=cls.event, member=cls.member
        )

    def test_assignment_links_event_and_member(self):
        assignment = self.assignment
        self.assertEqual(assignment.event, self.event)
        self.assertEqual(assignment.member, self.member)
        self.assertIsNone(assignment.revoked_at)
        self.assertQuerySetEqual(
            self.event.organizer_assignments.all(),
            [assignment],
        )
        self.assertQuerySetEqual(
            self.member.organizer_assignments.all(),
            [assignment],
        )

    def test_assigned_event_and_member_are_kept(self):
        for row in (self.event, self.member):
            model = type(row)
            with self.subTest(model=model.__name__):
                with self.assertRaises(ProtectedError):
                    row.delete()
                kept = model.objects.filter(pk=row.pk)
                self.assertTrue(kept.exists())

    def test_unlinked_event_can_be_deleted(self):
        spare = save_event(title='Spare event')
        self.assertEqual(
            spare.delete(), (1, {'events.Event': 1})
        )


class EventRuleTests(TestCase):
    """Database constraints refuse impossible events."""

    def test_capacity_must_be_more_than_zero(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                save_event(capacity=0)
        self.assertFalse(Event.objects.exists())

    def test_end_must_be_after_start(self):
        start = datetime(2027, 2, 1, 18, tzinfo=UTC)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                save_event(starts_at=start, ends_at=start)
        self.assertFalse(Event.objects.exists())

    def test_only_listed_statuses_can_be_saved(self):
        for status in Event.Status.values:
            save_event(status=status)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                save_event(status='archived')
        self.assertEqual(Event.objects.count(), 3)

    def test_unknown_time_zone_fails_validation(self):
        event = save_event(timezone='Europe/Londn')
        with self.assertRaises(ValidationError) as caught:
            event.full_clean()
        self.assertEqual(
            caught.exception.message_dict,
            {'timezone': [
                'Europe/Londn is not a known time zone.'
            ]},
        )

    def test_one_current_assignment_per_event(self):
        event = save_event()
        sam = User.objects.create_user(
            'sam@example.org', display_name='Sam'
        )
        first = OrganizerAssignment.objects.create(
            event=event, member=sam
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OrganizerAssignment.objects.create(
                    event=event, member=sam
                )
        day = timedelta(days=1)
        first.revoked_at = first.assigned_at + day
        first.save()
        OrganizerAssignment.objects.create(
            event=event, member=sam
        )
        self.assertEqual(
            event.organizer_assignments.count(), 2
        )

    def test_revoked_never_before_assigned(self):
        event = save_event()
        sam = User.objects.create_user(
            'sam@example.org', display_name='Sam'
        )
        early = OrganizerAssignment.objects.create(
            event=event, member=sam
        )
        day = timedelta(days=1)
        early.revoked_at = early.assigned_at - day
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                early.save()


class EventQuerySetTests(TestCase):
    """The named questions EventQuerySet answers."""

    @classmethod
    def setUpTestData(cls):
        save_event(
            title='Django workshop',
            starts_at=datetime(2026, 12, 3, 9,
                               tzinfo=UTC),
            location='Virtual',
        )
        save_event(title='Python meetup')
        save_event(title='Spring planning',
                   status=Event.Status.DRAFT)
        save_event(title='Autumn social',
                   status=Event.Status.CANCELLED)

    def test_published_keeps_only_published(self):
        self.assertQuerySetEqual(
            Event.objects.published(),
            ['Python meetup', 'Django workshop'],
            transform=str,
        )

    def test_published_chains_with_other_methods(self):
        virtual = Event.objects.filter(location='Virtual')
        self.assertQuerySetEqual(
            virtual.published(), ['Django workshop'],
            transform=str,
        )
        self.assertQuerySetEqual(
            Event.objects.published().exclude(
                location='Virtual'
            ),
            ['Python meetup'],
            transform=str,
        )

    def test_upcoming_and_past_split_at_now(self):
        published = Event.objects.published()
        during = datetime(2026, 11, 19, 19, tzinfo=UTC)
        self.assertQuerySetEqual(
            published.upcoming(during),
            ['Python meetup', 'Django workshop'],
            transform=str,
        )
        later = datetime(2026, 11, 25, tzinfo=UTC)
        self.assertQuerySetEqual(
            published.upcoming(later), ['Django workshop'],
            transform=str,
        )
        self.assertQuerySetEqual(
            published.past(later), ['Python meetup'],
            transform=str,
        )


class PlacesLeftTests(TestCase):
    """Places left, counted in one query, on list and page."""

    @classmethod
    def setUpTestData(cls):
        start = timezone.now() + timedelta(days=7)
        cls.meetup = save_event(starts_at=start, capacity=2)
        full = save_event(title='Django workshop',
                          starts_at=start, capacity=1)
        save_event(title='Leeds social', capacity=5,
                   starts_at=start - timedelta(days=30))
        sai = User.objects.create_user(
            'sai@example.org', display_name='Sai'
        )
        raj = User.objects.create_user(
            'raj@example.org', display_name='Raj'
        )
        Registration.objects.create(event=cls.meetup,
                                    member=sai)
        Registration.objects.create(
            event=cls.meetup, member=raj,
            status=Registration.Status.CANCELLED,
            cancelled_at=start,
        )
        Registration.objects.create(event=full, member=sai)

    def test_with_places_counts_active_places(self):
        left = {event.title: event.places_left for event
                in Event.objects.with_places()}
        self.assertEqual(left, {'Python meetup': 1,
                                'Django workshop': 0,
                                'Leeds social': 5})

    def test_pages_show_places_left(self):
        with self.assertNumQueries(2):
            response = self.client.get('/events/')
        # The words, not the markup: the meter's look may
        # change from chapter to chapter (Chapter 33).
        self.assertContains(response, '1 of 2 places left')
        self.assertContains(
            response, '<span class="places badge '
            'badge-warning">Full</span>', html=True,
        )
        self.assertNotContains(response, 'of 5 places left')
        # The registration panel counts places again.
        with self.assertNumQueries(3):
            response = self.client.get(
                f'/events/{self.meetup.pk}/'
            )
        self.assertContains(response, '1 of 2 places left')


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


class EventAdminTests(TestCase):
    """The event pages: list, UTC times, rules, history."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = User.objects.create_superuser(
            'sam@example.org', display_name='Sam'
        )
        cls.workshop = save_event(
            title='Django workshop',
            starts_at=datetime(2026, 12, 3, 9, tzinfo=UTC),
            timezone='Asia/Kolkata',
            location='Virtual',
        )
        save_event(title='Spring planning',
                   status=Event.Status.DRAFT)
        sai = User.objects.create_user(
            'sai@example.org', display_name='Sai'
        )
        cls.place = Registration.objects.create(
            event=cls.workshop, member=sai
        )

    def setUp(self):
        self.client.force_login(self.sam)
        self.url = admin_url(Event, 'change',
                             self.workshop.pk)

    def test_list_shows_drafts_local_start_and_places(self):
        response = self.client.get(
            admin_url(Event, 'changelist')
        )
        self.assertContains(response, 'Spring planning')
        self.assertContains(
            response, 'Thu 03 Dec 2026, 14:30 IST'
        )
        self.assertContains(
            response, '<td class="field-places">39</td>',
            html=True,
        )
        self.assertNotContains(response, 'delete_selected')

    def test_times_are_typed_in_utc(self):
        self.client.post(self.url, event_form(
            self.workshop, starts_at_1='15:00',
            ends_at_1='17:00',
        ))
        self.workshop.refresh_from_db()
        self.assertEqual(
            self.workshop.starts_at,
            datetime(2026, 12, 3, 15, tzinfo=UTC),
        )
        response = self.client.get(self.url)
        self.assertContains(
            response, 'Thu 03 Dec 2026, 20:30 IST'
        )

    def test_rule_messages_reach_the_page(self):
        for changes, message in [
            ({'capacity': 0},
             'Capacity must be more than 0.'),
            ({'ends_at_1': '08:00'},
             'An event must end after it starts.'),
            ({'timezone': 'Mars/Base'},
             'Mars/Base is not a known time zone.'),
        ]:
            form = event_form(self.workshop, **changes)
            response = self.client.post(self.url, form)
            self.assertContains(response, message)
        self.workshop.refresh_from_db()
        self.assertEqual(self.workshop.capacity, 40)

    def test_registrations_are_read_only_history(self):
        with self.assertNumQueries(5):
            response = self.client.get(self.url)
        self.assertContains(response, 'sai@example.org')
        self.assertNotContains(
            response, 'name="registrations-0-status"'
        )
        forged = {
            'registrations-TOTAL_FORMS': 1,
            'registrations-INITIAL_FORMS': 1,
            'registrations-0-id': self.place.pk,
            'registrations-0-event': self.workshop.pk,
            'registrations-0-status': 'cancelled',
        }
        self.client.post(
            self.url, event_form(self.workshop, **forged)
        )
        self.place.refresh_from_db()
        self.assertEqual(self.place.status, 'active')

    def test_history_blocks_delete_drafts_may_go(self):
        response = self.client.post(
            admin_url(Event, 'delete', self.workshop.pk),
            {'post': 'yes'},
        )
        self.assertContains(response, 'Cannot delete event')
        draft = Event.objects.get(title='Spring planning')
        self.client.post(
            admin_url(Event, 'delete', draft.pk),
            {'post': 'yes'},
        )
        self.assertQuerySetEqual(
            Event.objects.all(), ['Django workshop'],
            transform=str,
        )


def remove_selected(client, *assignments):
    """Run the admin's Remove selected organizers action."""
    return client.post(
        admin_url(OrganizerAssignment, 'changelist'),
        {'action': 'remove_selected',
         '_selected_action': [a.pk for a in assignments]},
        follow=True,
    )


class OrganizerAssignmentAdminTests(TestCase):
    """Assign and revoke organizers; never delete."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = User.objects.create_superuser(
            'sam@example.org', display_name='Sam'
        )
        cls.event = save_event()
        cls.sai = User.objects.create_user(
            'sai@example.org', display_name='Sai'
        )
        # Chapter 30: only the Organizers group organizes.
        organizers = Group.objects.get(name=ORGANIZERS)
        cls.sai.groups.add(organizers)

    def setUp(self):
        self.client.force_login(self.sam)

    def add(self, member=None):
        """Assign member, Sai by default, in the admin."""
        member = member or self.sai
        return self.client.post(
            admin_url(OrganizerAssignment, 'add'),
            {'event': self.event.pk, 'member': member.pk},
        )

    def test_add_and_remove_but_never_delete(self):
        self.event.add_organizer(self.sam)
        self.add()
        assignment = OrganizerAssignment.objects.get(
            member=self.sai
        )
        remove_selected(self.client, assignment)
        assignment.refresh_from_db()
        self.assertIsNotNone(assignment.revoked_at)
        response = self.client.post(
            admin_url(OrganizerAssignment, 'delete',
                      assignment.pk),
            {'post': 'yes'},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            OrganizerAssignment.objects.count(), 2
        )

    def test_rule_messages_reach_the_page(self):
        self.add()
        self.assertContains(
            self.add(),
            'This member already organizes this event.',
        )
        self.assertContains(
            self.add(self.sam),
            'Only members of the Organizers group can '
            'organize events.',
        )

    def test_list_runs_a_fixed_number_of_queries(self):
        for title in ('Python meetup', 'Spring planning'):
            OrganizerAssignment.objects.create(
                event=save_event(title=title),
                member=self.sai,
            )
        with self.assertNumQueries(5):
            self.client.get(
                admin_url(OrganizerAssignment, 'changelist')
            )


NEW_EVENT = {
    'title': 'Online Django clinic',
    'timezone': 'America/New_York',
    'starts_at': '2026-12-03T19:00',
    'ends_at': '2026-12-03T20:30',
    'location': 'Online',
    'capacity': '50',
}


def new_event_form(**changes):
    """Return an EventForm holding NEW_EVENT with changes."""
    return EventForm(NEW_EVENT | changes)


class EventFormTests(TestCase):
    """EventForm's fields and the rules it reports."""

    def test_status_is_not_a_field(self):
        self.assertNotIn('status', EventForm().fields)
        form = new_event_form(status='published')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().status,
                         Event.Status.DRAFT)

    def test_missing_title_is_refused(self):
        form = new_event_form(title='')
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['title'],
                         ['This field is required.'])

    def test_zero_capacity_is_shown_on_capacity(self):
        form = new_event_form(capacity='0')
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['capacity'],
                         ['Capacity must be more than 0.'])
        self.assertEqual(form.non_field_errors(), [])

    def test_unknown_zone_is_refused(self):
        form = new_event_form(timezone='Mars/Olympus')
        self.assertFalse(form.is_valid())
        self.assertIn('timezone', form.errors)


def in_utc(form, name):
    """Return a cleaned time from form, shown in UTC."""
    return form.cleaned_data[name].astimezone(UTC)


class EventZoneTests(TestCase):
    """Times are read in the event's own time zone."""

    def test_times_are_read_in_the_event_zone(self):
        form = new_event_form()
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            in_utc(form, 'starts_at'),
            datetime(2026, 12, 4, 0, 0, tzinfo=UTC),
        )

    def test_same_time_elsewhere_is_another_instant(self):
        form = new_event_form(timezone='Asia/Kolkata')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            in_utc(form, 'starts_at'),
            datetime(2026, 12, 3, 13, 30, tzinfo=UTC),
        )

    def test_end_before_start_is_shown_on_ends(self):
        form = new_event_form(ends_at='2026-12-03T18:00')
        self.assertFormError(
            form, 'ends_at',
            'An event must end after it starts.',
        )

    def test_skipped_time_is_refused(self):
        form = new_event_form(
            starts_at='2027-03-14T02:30',
            ends_at='2027-03-14T04:00',
        )
        self.assertFormError(
            form, 'starts_at',
            '02:30 does not exist in America/New_York '
            'that day: the clocks go forward.',
        )

    def test_repeated_time_is_refused(self):
        form = new_event_form(
            starts_at='2026-11-01T01:30',
            ends_at='2026-11-01T03:00',
        )
        self.assertFormError(
            form, 'starts_at',
            '01:30 happens twice in America/New_York '
            'that day: the clocks go back.',
        )


def member(email, *codenames):
    """Create a member holding the named permissions."""
    name = email.split('@')[0].title()
    user = User.objects.create_user(email, display_name=name)
    user.user_permissions.add(*Permission.objects.filter(
        codename__in=codenames
    ))
    return user


class NewEventPageTests(TestCase):
    """Who may open the new-event page; what it saves."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = member('sam@example.org', 'add_event')
        cls.sai = member('sai@example.org')
        cls.url = reverse('events:create')

    def test_visitor_is_sent_to_sign_in(self):
        response = self.client.get(self.url)
        sign_in = reverse('account_login')
        self.assertRedirects(
            response, f'{sign_in}?next={self.url}',
            fetch_redirect_response=False,
        )

    def test_member_without_permission_is_refused(self):
        self.client.force_login(self.sai)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_form_page_has_labelled_fields(self):
        self.client.force_login(self.sam)
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, 'events/form.html')
        for name in ('title', 'timezone', 'starts_at',
                     'ends_at', 'location', 'capacity'):
            self.assertContains(response, f'for="id_{name}"')
        self.assertNotContains(response, 'name="status"')
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertContains(response, f'href="{self.url}"')

    def test_invalid_post_keeps_values_saves_nothing(self):
        self.client.force_login(self.sam)
        response = self.client.post(
            self.url, NEW_EVENT | {'title': ''}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response,
                            'This field is required.')
        self.assertContains(response, 'value="Online"')
        self.assertContains(response,
                            'value="2026-12-03T19:00"')
        self.assertFalse(Event.objects.exists())

    def test_valid_post_saves_draft_and_organizer(self):
        self.client.force_login(self.sam)
        response = self.client.post(self.url, NEW_EVENT)
        event = Event.objects.get()
        self.assertRedirects(
            response,
            reverse('events:detail', args=[event.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(event.status, Event.Status.DRAFT)
        organizers = [assignment.member for assignment
                      in event.organizer_assignments.all()]
        self.assertEqual(organizers, [self.sam])


class DraftPageTests(TestCase):
    """Who may see a draft, and the saved message."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = member('sam@example.org', 'add_event')
        cls.sai = member('sai@example.org')
        cls.admin = member('admin@example.org', 'view_event')
        cls.draft = save_event(status=Event.Status.DRAFT)
        cls.draft.add_organizer(cls.sam)
        cls.url = reverse('events:detail',
                          args=[cls.draft.pk])

    def test_draft_is_hidden_from_visitors_and_members(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.client.force_login(self.sai)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_organizer_and_administrator_see_it(self):
        for person in (self.sam, self.admin):
            with self.subTest(person=person.email):
                self.client.force_login(person)
                response = self.client.get(self.url)
                self.assertContains(
                    response, 'Draft: only its organizers'
                )

    def test_saved_draft_opens_with_message(self):
        self.client.force_login(self.sam)
        response = self.client.post(
            reverse('events:create'), NEW_EVENT, follow=True
        )
        self.assertContains(response, 'Draft saved.')
        self.assertContains(
            response, '<h1>Online Django clinic</h1>',
            html=True,
        )


class FormMarkupTests(TestCase):
    """Form fields use Otahque's templates and styles."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = member('sam@example.org', 'add_event')
        cls.url = reverse('events:create')

    def setUp(self):
        self.client.force_login(self.sam)

    def test_fields_use_otahque_styles_and_script(self):
        response = self.client.get(self.url)
        for text, count in (('class="fieldset"', 11),
                            ('class="input w-full"', 8),
                            ('class="textarea w-full"', 1),
                            ('class="select w-full"', 1)):
            self.assertContains(response, text, count=count)
        script = 'otahque/event-zone.js'
        self.assertContains(response, script)
        self.assertTrue(finders.find(script))

    def test_errors_and_help_are_linked(self):
        response = self.client.post(
            self.url, NEW_EVENT | {'title': ''}
        )
        help_id = 'id_location_helptext'
        for text in ('aria-invalid="true"',
                     'aria-describedby="id_title_error"',
                     'id="id_title_error"',
                     f'aria-describedby="{help_id}"',
                     f'id="{help_id}"'):
            self.assertContains(response, text, count=1)


class CsrfTests(TestCase):
    """A post without the CSRF token is refused."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = member('sam@example.org', 'add_event')
        cls.url = reverse('events:create')

    def test_a_post_without_the_token_is_refused(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.sam)
        refused = browser.post(self.url, NEW_EVENT)
        self.assertEqual(refused.status_code, 403)
        self.assertFalse(Event.objects.exists())
        page = browser.get(self.url)
        token = str(page.context['csrf_token'])
        saved = browser.post(
            self.url,
            NEW_EVENT | {'csrfmiddlewaretoken': token},
        )
        self.assertEqual(saved.status_code, 302)


def editor(email='sam@example.org'):
    """Make a member who may create and change events."""
    return member(email, 'add_event', 'change_event')


def save_clinic(organizer):
    """Sam's clinic, saved as a draft through EventForm."""
    clinic = EventForm(NEW_EVENT).save()
    clinic.add_organizer(organizer)
    return clinic


def edit_url(event):
    """Return the edit page's address for event."""
    return reverse('events:edit', args=[event.pk])


class EditAccessTests(TestCase):
    """Who may open an event's edit page."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()
        cls.sai = member('sai@example.org')
        cls.admin = member('admin@example.org',
                           'view_event', 'change_event')
        cls.clinic = save_clinic(cls.sam)
        cls.meetup = save_event()

    def test_visitor_is_sent_to_sign_in(self):
        url = edit_url(self.clinic)
        response = self.client.get(url)
        sign_in = reverse('account_login')
        self.assertRedirects(
            response, f'{sign_in}?next={url}',
            fetch_redirect_response=False,
        )

    def test_member_may_see_but_not_edit(self):
        self.client.force_login(self.sai)
        response = self.client.get(edit_url(self.meetup))
        self.assertEqual(response.status_code, 403)

    def test_hidden_draft_is_not_found(self):
        self.client.force_login(self.sai)
        response = self.client.get(edit_url(self.clinic))
        self.assertEqual(response.status_code, 404)

    def test_organizer_gets_the_form(self):
        self.client.force_login(self.sam)
        response = self.client.get(edit_url(self.clinic))
        self.assertTemplateUsed(response, 'events/edit.html')
        self.assertContains(
            response, 'value="Online Django clinic"'
        )

    def test_revoked_organizer_is_refused(self):
        place = self.meetup.add_organizer(self.sam)
        self.client.force_login(self.sam)
        url = edit_url(self.meetup)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        place.revoked_at = timezone.now()
        place.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_administrator_who_is_no_organizer(self):
        self.client.force_login(self.admin)
        response = self.client.get(edit_url(self.clinic))
        self.assertEqual(response.status_code, 403)

    def test_edit_link_only_for_who_may_edit(self):
        page = reverse('events:detail',
                       args=[self.clinic.pk])
        link = f'href="{edit_url(self.clinic)}"'
        for person, count in ((self.sam, 1),
                              (self.admin, 0)):
            with self.subTest(person=person.email):
                self.client.force_login(person)
                response = self.client.get(page)
                self.assertContains(response, link,
                                    count=count)


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


def edit_form(event, **changes):
    """Return the edit form for event, sent with changes."""
    data = as_sent(event, **changes)
    return EventForm(data, instance=event)


SAVED_NOW = ('Saved now: 3 December 2026, 19:00 '
             'America/New_York (4 December, 00:00 UTC). ')


class EditFormTests(TestCase):
    """Editing times and the event's time zone."""

    @classmethod
    def setUpTestData(cls):
        cls.clinic = save_clinic(editor())

    def test_saved_times_are_shown_in_the_event_zone(self):
        form = EventForm(instance=self.clinic)
        self.assertIn('value="2026-12-03T19:00"',
                      str(form['starts_at']))
        self.assertEqual(
            form.fields['starts_at'].help_text,
            'Saved: 3 December 2026, 19:00 America/New_York '
            '(4 December, 00:00 UTC)',
        )

    def test_unchanged_times_keep_their_stored_value(self):
        stored = datetime(2026, 12, 4, 0, 0, 30, tzinfo=UTC)
        Event.objects.filter(pk=self.clinic.pk).update(
            starts_at=stored
        )
        self.clinic.refresh_from_db()
        form = edit_form(self.clinic, title='Django clinic')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().starts_at, stored)

    def test_a_repeated_hour_saves_unchanged(self):
        event = save_event(
            timezone='America/New_York',
            starts_at=datetime(2026, 11, 1, 6, 30,
                               tzinfo=UTC),
            ends_at=datetime(2026, 11, 1, 8, 0, tzinfo=UTC),
        )
        stored = event.starts_at
        form = edit_form(event, location='Room 2')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().starts_at, stored)

    def test_changing_the_end_moves_only_the_end(self):
        form = edit_form(self.clinic,
                         ends_at='2026-12-03T21:00')
        self.assertTrue(form.is_valid(), form.errors)
        event = form.save()
        self.assertEqual(
            event.starts_at,
            datetime(2026, 12, 4, 0, 0, tzinfo=UTC),
        )
        self.assertEqual(
            event.ends_at,
            datetime(2026, 12, 4, 2, 0, tzinfo=UTC),
        )

    def test_a_new_zone_needs_the_tick_box(self):
        form = edit_form(self.clinic,
                         timezone='Europe/London')
        self.assertIn('confirm_zone', form.fields)
        self.assertFormError(
            form, 'timezone',
            SAVED_NOW + 'With this zone: 3 December 2026, '
            '19:00 Europe/London (3 December, 19:00 UTC). '
            'Tick the box to save the new zone.',
        )

    def test_a_ticked_new_zone_reads_the_typed_time(self):
        form = edit_form(self.clinic,
                         timezone='Europe/London',
                         confirm_zone='on')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.save().starts_at,
            datetime(2026, 12, 3, 19, 0, tzinfo=UTC),
        )

    def test_no_tick_box_when_the_zone_is_kept(self):
        for form in (EventForm(instance=self.clinic),
                     edit_form(self.clinic),
                     new_event_form()):
            self.assertNotIn('confirm_zone', form.fields)


class EditPageTests(TestCase):
    """Saving an edit: message, errors, and counts."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()
        cls.clinic = save_clinic(cls.sam)
        cls.url = edit_url(cls.clinic)

    def setUp(self):
        self.client.force_login(self.sam)

    def test_a_saved_edit_redirects_with_a_message(self):
        data = as_sent(self.clinic, title='Django clinic')
        response = self.client.post(self.url, data,
                                    follow=True)
        self.assertRedirects(response, reverse(
            'events:detail', args=[self.clinic.pk]))
        self.assertContains(response, 'Changes saved.')
        self.assertContains(
            response, '<h1>Django clinic</h1>', html=True
        )

    def test_invalid_edit_keeps_values_saves_nothing(self):
        data = as_sent(self.clinic, title='Django clinic',
                       ends_at='2026-12-03T18:00')
        response = self.client.post(self.url, data)
        self.assertContains(
            response, 'An event must end after it starts.'
        )
        self.assertContains(response,
                            'value="Django clinic"')
        self.assertContains(
            response, '<h1>Edit Online Django clinic</h1>',
            html=True,
        )
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.title,
                         'Online Django clinic')

    def test_saved_times_are_on_the_page(self):
        response = self.client.get(self.url)
        self.assertContains(
            response, 'Saved: 3 December 2026, 19:00 '
            'America/New_York (4 December, 00:00 UTC)'
        )
        helptext = 'aria-describedby="id_starts_at_helptext"'
        self.assertContains(response, helptext)

    def test_places_taken_are_counted(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, 'Places taken')
        for email in ('sai@example.org', 'raj@example.org',
                      'soni@example.org'):
            Registration.objects.create(event=self.clinic,
                                        member=member(email))
        Registration.objects.filter(
            member__email='soni@example.org'
        ).update(status='cancelled',
                 cancelled_at=timezone.now())
        response = self.client.get(self.url)
        self.assertContains(response, 'Places taken: 2.')


BELOW = ('Capacity cannot be below the places already '
         'taken: 2.')


class CapacityTests(TestCase):
    """Capacity may not drop below the places taken."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = User.objects.create_superuser(
            'sam@example.org', display_name='Sam'
        )
        cls.clinic = save_clinic(cls.sam)
        for email in ('sai@example.org', 'raj@example.org'):
            Registration.objects.create(event=cls.clinic,
                                        member=member(email))

    def test_zero_is_one_message_on_capacity(self):
        form = edit_form(self.clinic, capacity='0')
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors, {
            'capacity': ['Capacity must be more than 0.'],
        })
        self.clinic.capacity = 0
        with self.assertRaises(ValidationError):
            self.clinic.full_clean()

    def test_below_the_places_taken_is_refused(self):
        form = edit_form(self.clinic, capacity='1')
        self.assertFormError(form, 'capacity', BELOW)

    def test_the_admin_refuses_it_too(self):
        self.client.force_login(self.sam)
        response = self.client.post(
            admin_url(Event, 'change', self.clinic.pk),
            event_form(self.clinic, capacity=1),
        )
        self.assertContains(response, BELOW)
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.capacity, 50)

    def test_the_places_taken_are_enough(self):
        soni = Registration.objects.create(
            event=self.clinic,
            member=member('soni@example.org'),
        )
        soni.status = Registration.Status.CANCELLED
        soni.cancelled_at = timezone.now()
        soni.save()
        form = edit_form(self.clinic, capacity='2')
        self.assertTrue(form.is_valid(), form.errors)


class CraftedFieldTests(TestCase):
    """Fields the form lacks cannot change an event."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()
        cls.clinic = save_clinic(cls.sam)
        cls.url = edit_url(cls.clinic)

    def setUp(self):
        self.client.force_login(self.sam)

    def test_fields_off_the_list_change_nothing(self):
        data = as_sent(self.clinic, status='published',
                       id='999', pk='999', owner='1')
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        event = Event.objects.get()
        self.assertEqual(event.pk, self.clinic.pk)
        self.assertEqual(event.status, Event.Status.DRAFT)

    def test_a_missing_field_is_refused_not_kept(self):
        data = as_sent(self.clinic, title='Django clinic')
        del data['location']
        response = self.client.post(self.url, data)
        self.assertContains(response,
                            'This field is required.')
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.title,
                         'Online Django clinic')

    def test_editing_never_changes_organizers(self):
        sai = member('sai@example.org')
        data = as_sent(self.clinic, member=sai.pk,
                       organizer_assignments=sai.pk)
        self.client.post(self.url, data)
        assignments = self.clinic.organizer_assignments
        organizers = [assignment.member for assignment
                      in assignments.all()]
        self.assertEqual(organizers, [self.sam])


class EditMarkupTests(TestCase):
    """The zone tick box is styled and labelled."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()
        cls.clinic = save_clinic(cls.sam)

    def test_tick_box_is_styled_and_linked(self):
        self.client.force_login(self.sam)
        data = as_sent(self.clinic, timezone='Europe/London')
        response = self.client.post(edit_url(self.clinic),
                                    data)
        described = ('aria-describedby="id_timezone_helptext'
                     ' id_timezone_error"')
        # Two tick boxes: the new zone and the phone setting.
        self.assertContains(response, 'class="checkbox"',
                            count=2)
        for text in ('for="id_confirm_zone"',
                     'aria-invalid="true"', described):
            self.assertContains(response, text, count=1)


class EditCsrfTests(TestCase):
    """An edit without the CSRF token is refused."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()
        cls.clinic = save_clinic(cls.sam)

    def test_an_edit_without_the_token_is_refused(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.sam)
        url = edit_url(self.clinic)
        data = as_sent(self.clinic, title='Forged')
        refused = browser.post(url, data)
        self.assertEqual(refused.status_code, 403)
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.title,
                         'Online Django clinic')
        token = str(browser.get(url).context['csrf_token'])
        saved = browser.post(
            url, data | {'csrfmiddlewaretoken': token}
        )
        self.assertEqual(saved.status_code, 302)


class DescriptionTests(TestCase):
    """Descriptions: optional for drafts, shown on pages."""

    def test_a_draft_saves_without_one(self):
        form = new_event_form()
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().description, '')

    def test_it_follows_the_title_and_is_saved(self):
        names = list(EventForm().fields)
        self.assertEqual(names[:2], ['title', 'description'])
        form = new_event_form(description='For beginners.')
        saved = form.save()
        self.assertEqual(saved.description, 'For beginners.')

    def test_the_page_keeps_line_breaks(self):
        event = save_event(description='One.\nTwo & three.')
        url = reverse('events:detail', args=[event.pk])
        response = self.client.get(url)
        self.assertContains(
            response, 'One.<br>Two &amp; three.'
        )


class AbsoluteUrlTests(TestCase):
    """An event knows the address of its own page."""

    def test_an_event_knows_its_page(self):
        event = save_event()
        self.assertEqual(event.get_absolute_url(),
                         f'/events/{event.pk}/')

    def test_the_admin_offers_view_on_site(self):
        boss = member('admin@example.org')
        boss.is_staff = boss.is_superuser = True
        boss.save()
        event = save_event()
        self.client.force_login(boss)
        response = self.client.get(
            admin_url(Event, 'change', event.pk)
        )
        self.assertContains(response, 'View on site')


def future_draft(organizer=None, **changes):
    """Create a complete draft that starts next week.

    Registration and cancellation close at the start.
    """
    fields = {
        'status': Event.Status.DRAFT,
        'starts_at': timezone.now() + timedelta(days=7),
        'description': 'Bring a laptop and a question.',
    } | changes
    fields.setdefault('registration_closes_at',
                      fields['starts_at'])
    fields.setdefault('cancellation_deadline',
                      fields['starts_at'])
    event = save_event(**fields)
    if organizer:
        event.add_organizer(organizer)
    return event


def action_url(name, event):
    """Return the address of the named action on event."""
    return reverse(f'events:{name}', args=[event.pk])


class MyEventsTests(TestCase):
    """My events lists what a member organizes now."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()
        cls.sai = member('sai@example.org')
        cls.url = reverse('events:manage')
        cls.draft = future_draft(cls.sam, title='Clinic')
        cls.live = save_event(title='Meetup')
        cls.live.add_organizer(cls.sam)
        cls.off = save_event(
            title='Walk', status=Event.Status.CANCELLED
        )
        cls.off.add_organizer(cls.sam)
        save_event(title='Run by someone else')

    def test_the_address(self):
        self.assertEqual(self.url, '/events/manage/')

    def test_visitor_and_plain_member_are_kept_out(self):
        response = self.client.get(self.url)
        sign_in = reverse('account_login')
        self.assertRedirects(
            response, f'{sign_in}?next={self.url}',
            fetch_redirect_response=False,
        )
        self.client.force_login(self.sai)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_drafts_first_with_tags_and_only_his_own(self):
        self.client.force_login(self.sam)
        response = self.client.get(self.url)
        html = response.content.decode()
        order = [html.index(t) for t in
                 ('Clinic', 'Meetup', 'Walk')]
        self.assertEqual(order, sorted(order))
        self.assertNotContains(response, 'someone else')
        for tag in ('Draft', 'Published', 'Cancelled'):
            self.assertContains(response, f'{tag}</span>')

    def test_a_revoked_assignment_leaves_the_list(self):
        place = self.live.organizer_assignments.get()
        place.revoked_at = timezone.now()
        place.save()
        self.client.force_login(self.sam)
        response = self.client.get(self.url)
        self.assertNotContains(response, 'Meetup')

    def test_more_events_do_not_mean_more_queries(self):
        self.client.force_login(self.sam)
        with CaptureQueriesContext(connection) as few:
            self.client.get(self.url)
        for number in range(5):
            future_draft(self.sam, title=f'Extra {number}')
        with CaptureQueriesContext(connection) as many:
            self.client.get(self.url)
        self.assertEqual(len(few), len(many))


class ReadinessTests(TestCase):
    """What stops a draft from being published."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()

    def test_a_complete_draft_has_no_problems(self):
        event = future_draft(self.sam)
        self.assertEqual(event.readiness_problems(), [])

    def test_every_missing_detail_is_named(self):
        event = future_draft(
            description='  ',
            starts_at=timezone.now() - timedelta(days=1),
        )
        self.assertEqual(event.readiness_problems(), [
            'Add a description.',
            'Move the start to a time in the future.',
            'Assign at least one current organizer.',
        ])

    def test_a_refused_publish_changes_nothing(self):
        event = future_draft(self.sam, description='')
        with self.assertRaises(ValidationError) as caught:
            event.publish()
        self.assertEqual(caught.exception.messages,
                         ['Add a description.'])
        event.refresh_from_db()
        self.assertEqual(event.status, Event.Status.DRAFT)


class PublishTests(TestCase):
    """Who may publish, and what publishing needs."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()
        cls.sai = member('sai@example.org')

    def post(self, event, person):
        """Sign in as person and publish event."""
        self.client.force_login(person)
        return self.client.post(action_url('publish', event))

    def status(self, url):
        """Return the status code of a GET to url."""
        return self.client.get(url).status_code

    def test_an_organizer_publishes_a_complete_draft(self):
        event = future_draft(self.sam)
        response = self.post(event, self.sam)
        self.assertRedirects(
            response, event.get_absolute_url(),
            fetch_redirect_response=False,
        )
        event.refresh_from_db()
        self.assertEqual(
            event.status, Event.Status.PUBLISHED
        )
        page = self.client.get(event.get_absolute_url())
        self.assertContains(page, 'Published.')

    def test_missing_details_are_shown_and_it_stays_a_draft(
            self):
        event = future_draft(
            self.sam, description='',
            starts_at=timezone.now() - timedelta(days=1),
        )
        self.post(event, self.sam)
        page = self.client.get(event.get_absolute_url())
        self.assertContains(page, 'Add a description.')
        self.assertContains(
            page, 'Move the start to a time in the future.'
        )
        event.refresh_from_db()
        self.assertEqual(event.status, Event.Status.DRAFT)

    def test_a_member_who_may_not_edit_is_refused(self):
        event = future_draft(
            self.sam, status=Event.Status.PUBLISHED
        )
        response = self.post(event, self.sai)
        self.assertEqual(response.status_code, 403)

    def test_a_hidden_draft_is_not_found(self):
        event = future_draft(self.sam)
        response = self.post(event, self.sai)
        self.assertEqual(response.status_code, 404)
        event.refresh_from_db()
        self.assertEqual(event.status, Event.Status.DRAFT)

    def test_a_published_event_is_not_published_again(self):
        event = future_draft(
            self.sam, status=Event.Status.PUBLISHED
        )
        response = self.post(event, self.sam)
        page = self.client.get(response['Location'])
        self.assertContains(
            page, 'Only a draft can be published.'
        )

    def test_a_get_does_not_publish(self):
        event = future_draft(self.sam)
        self.client.force_login(self.sam)
        response = self.client.get(
            action_url('publish', event)
        )
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response['Allow'], 'POST')
        event.refresh_from_db()
        self.assertEqual(event.status, Event.Status.DRAFT)

    def test_visitors_see_it_once_it_is_published(self):
        event = future_draft(self.sam)
        url = event.get_absolute_url()
        self.assertEqual(self.status(url), 404)
        self.post(event, self.sam)
        self.client.logout()
        self.assertEqual(self.status(url), 200)

    def test_the_button_is_for_organizers_of_drafts(self):
        draft = future_draft(self.sam)
        live = future_draft(
            self.sam, status=Event.Status.PUBLISHED
        )
        self.client.force_login(self.sam)
        page = self.client.get(draft.get_absolute_url())
        self.assertContains(
            page, f'action="{action_url("publish", draft)}"'
        )
        page = self.client.get(live.get_absolute_url())
        self.assertNotContains(
            page, f'action="{action_url("publish", live)}"'
        )


class CancelTests(TestCase):
    """Cancelling published events, and who may."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()
        cls.sai = member('sai@example.org')

    def cancel(self, event, person):
        """Sign in as person and cancel event."""
        self.client.force_login(person)
        return self.client.post(action_url('cancel', event))

    def test_an_organizer_cancels_a_published_event(self):
        event = future_draft(
            self.sam, status=Event.Status.PUBLISHED
        )
        response = self.cancel(event, self.sam)
        self.assertRedirects(
            response, event.get_absolute_url(),
            fetch_redirect_response=False,
        )
        event.refresh_from_db()
        self.assertEqual(
            event.status, Event.Status.CANCELLED
        )

    def test_a_draft_cannot_be_cancelled(self):
        event = future_draft(self.sam)
        response = self.cancel(event, self.sam)
        page = self.client.get(response['Location'])
        self.assertContains(
            page, 'Only a published event can be cancelled.'
        )
        event.refresh_from_db()
        self.assertEqual(event.status, Event.Status.DRAFT)

    def test_everyone_sees_the_tag_and_no_places(self):
        event = future_draft(
            self.sam, status=Event.Status.PUBLISHED
        )
        self.cancel(event, self.sam)
        self.client.logout()
        page = self.client.get(event.get_absolute_url())
        self.assertContains(page, '>Cancelled</span>')
        self.assertNotContains(page, 'places')

    def test_registrations_are_kept(self):
        event = future_draft(
            self.sam, status=Event.Status.PUBLISHED
        )
        place = Registration.objects.create(
            event=event, member=self.sai
        )
        self.cancel(event, self.sam)
        place.refresh_from_db()
        self.assertEqual(place.status,
                         Registration.Status.ACTIVE)
        self.client.force_login(self.sai)
        page = self.client.get(event.get_absolute_url())
        self.assertContains(page, '>Cancelled</span>')

    def test_it_leaves_the_event_list(self):
        event = future_draft(
            self.sam, status=Event.Status.PUBLISHED,
            title='Gone',
        )
        page = self.client.get('/events/')
        self.assertContains(page, 'Gone')
        self.cancel(event, self.sam)
        self.client.logout()
        page = self.client.get('/events/')
        self.assertNotContains(page, 'Gone')

    def test_a_non_organizer_and_a_get_are_refused(self):
        event = future_draft(
            self.sam, status=Event.Status.PUBLISHED
        )
        response = self.cancel(event, self.sai)
        self.assertEqual(response.status_code, 403)
        self.client.force_login(self.sam)
        response = self.client.get(
            action_url('cancel', event)
        )
        self.assertEqual(response.status_code, 405)
        event.refresh_from_db()
        self.assertEqual(
            event.status, Event.Status.PUBLISHED
        )


class DeleteTests(TestCase):
    """Only a draft nobody registered for is deleted."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()
        cls.sai = member('sai@example.org')

    def setUp(self):
        self.client.force_login(self.sam)

    def kept(self, event):
        """Return whether event is still in the database."""
        return Event.objects.filter(pk=event.pk).exists()

    def test_a_get_shows_the_page_and_deletes_nothing(self):
        draft = future_draft(self.sam)
        response = self.client.get(
            action_url('delete', draft)
        )
        self.assertTemplateUsed(
            response, 'events/delete.html'
        )
        self.assertContains(response, 'cannot be undone')
        self.assertTrue(self.kept(draft))

    def test_a_post_deletes_the_draft_and_assignments(self):
        draft = future_draft(self.sam)
        response = self.client.post(
            action_url('delete', draft)
        )
        self.assertRedirects(
            response, reverse('events:manage'),
            fetch_redirect_response=False,
        )
        self.assertFalse(self.kept(draft))
        self.assertFalse(
            OrganizerAssignment.objects.exists()
        )
        page = self.client.get(reverse('events:manage'))
        self.assertContains(page, 'Draft deleted.')

    def test_a_draft_with_registrations_is_kept(self):
        draft = future_draft(self.sam)
        Registration.objects.create(
            event=draft, member=self.sai
        )
        response = self.client.post(
            action_url('delete', draft)
        )
        page = self.client.get(response['Location'])
        self.assertContains(page, 'has registrations')
        self.assertTrue(self.kept(draft))
        places = draft.organizer_assignments.count()
        self.assertEqual(places, 1)

    def test_published_and_cancelled_events_are_kept(self):
        for status in (Event.Status.PUBLISHED,
                       Event.Status.CANCELLED):
            with self.subTest(status=status):
                event = future_draft(self.sam, status=status)
                for send in (self.client.get,
                             self.client.post):
                    response = send(
                        action_url('delete', event)
                    )
                    code = response.status_code
                    self.assertEqual(code, 302)
                self.assertTrue(self.kept(event))

    def test_a_non_organizer_is_refused(self):
        event = future_draft(
            self.sam, status=Event.Status.PUBLISHED
        )
        self.client.force_login(self.sai)
        for send in (self.client.get, self.client.post):
            response = send(action_url('delete', event))
            self.assertEqual(response.status_code, 403)
        self.assertTrue(self.kept(event))

    def test_another_method_is_refused(self):
        draft = future_draft(self.sam)
        url = action_url('delete', draft)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 405)
        self.assertTrue(self.kept(draft))


class CopyTests(TestCase):
    """A copy is a new draft starting when asked."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()
        cls.sai = member('sai@example.org')
        cls.raj = editor('raj@example.org')

    def test_a_copy_is_a_new_draft_with_form_details(self):
        event = future_draft(
            self.sam, status=Event.Status.PUBLISHED,
            title='Weekly clinic', timezone='Asia/Kolkata',
            capacity=25, location='Online',
        )
        event.add_organizer(self.raj)
        Registration.objects.create(
            event=event, member=self.sai
        )
        self.client.force_login(self.sam)
        response = self.client.post(
            action_url('copy', event),
            {'starts_at': '2027-02-04T19:00'},
        )
        copy = Event.objects.exclude(pk=event.pk).get()
        self.assertRedirects(
            response, reverse('events:edit', args=[copy.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(copy.status, Event.Status.DRAFT)
        self.assertEqual(
            (copy.title, copy.description, copy.location,
             copy.timezone, copy.capacity),
            (event.title, event.description, event.location,
             event.timezone, event.capacity),
        )
        self.assertEqual(copy.ends_at - copy.starts_at,
                         event.ends_at - event.starts_at)
        self.assertEqual(
            copy.starts_at,
            datetime(2027, 2, 4, 13, 30, tzinfo=UTC),
        )
        self.assertFalse(copy.registrations.exists())
        members = [a.member for a in
                   copy.organizer_assignments.all()]
        self.assertEqual(members, [self.sam])

    def test_a_cancelled_event_can_be_copied(self):
        event = future_draft(
            self.sam, status=Event.Status.CANCELLED
        )
        self.client.force_login(self.sam)
        self.client.post(action_url('copy', event),
                         {'starts_at': '2027-02-04T19:00'})
        self.assertEqual(Event.objects.count(), 2)
        event.refresh_from_db()
        self.assertEqual(
            event.status, Event.Status.CANCELLED
        )

    def test_a_bad_start_copies_nothing(self):
        event = future_draft(self.sam)
        self.client.force_login(self.sam)
        page = self.client.get(action_url('copy', event))
        self.assertContains(page, 'type="datetime-local"')
        response = self.client.post(
            action_url('copy', event), {'starts_at': ''}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Event.objects.count(), 1)

    def test_a_non_organizer_is_refused(self):
        event = future_draft(
            self.sam, status=Event.Status.PUBLISHED
        )
        self.client.force_login(self.sai)
        for send in (self.client.get, self.client.post):
            response = send(action_url('copy', event))
            self.assertEqual(response.status_code, 403)
        self.assertEqual(Event.objects.count(), 1)


class ActionCsrfTests(TestCase):
    """Each action refuses a post without the token."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()

    def send(self, name, event, data=None):
        """Post without, then with, the page's token."""
        data = data or {}
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.sam)
        url = action_url(name, event)
        refused = browser.post(url, data)
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(Event.objects.count(), 1)
        page = browser.get(url if name == 'copy'
                           else event.get_absolute_url())
        token = str(page.context['csrf_token'])
        sent = browser.post(
            url, data | {'csrfmiddlewaretoken': token}
        )
        self.assertEqual(sent.status_code, 302)

    def test_publish_needs_the_token(self):
        event = future_draft(self.sam)
        self.send('publish', event)
        event.refresh_from_db()
        self.assertEqual(
            event.status, Event.Status.PUBLISHED
        )

    def test_cancel_needs_the_token(self):
        event = future_draft(
            self.sam, status=Event.Status.PUBLISHED
        )
        self.send('cancel', event)
        event.refresh_from_db()
        self.assertEqual(
            event.status, Event.Status.CANCELLED
        )

    def test_delete_needs_the_token(self):
        event = future_draft(self.sam)
        self.send('delete', event)
        self.assertFalse(Event.objects.exists())

    def test_copy_needs_the_token(self):
        event = future_draft(self.sam)
        self.send('copy', event,
                  {'starts_at': '2027-02-04T19:00'})
        self.assertEqual(Event.objects.count(), 2)


class OrganizedByTests(TestCase):
    """An event's page names its current organizers."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()
        cls.event = save_event()
        cls.place = cls.event.add_organizer(cls.sam)

    def page(self):
        """Return the address of the event's own page."""
        return self.client.get(self.event.get_absolute_url())

    def test_the_organizer_is_named(self):
        self.assertContains(self.page(), 'Organized by Sam')

    def test_the_name_follows_the_profile(self):
        self.sam.display_name = 'Sam Chen'
        self.sam.save()
        page = self.page()
        self.assertContains(page, 'Organized by Sam Chen')

    def test_a_revoked_organizer_is_not_named(self):
        self.place.revoked_at = timezone.now()
        self.place.save()
        self.assertNotContains(self.page(), 'Organized by')


SAI_PASSWORD = 'a-long-safe-pass-123'


class SessionCookieTests(TestCase):
    """What the session cookie keeps, and when it ends."""

    @classmethod
    def setUpTestData(cls):
        cls.sai = User.objects.create_user(
            'sai@example.org', SAI_PASSWORD,
            display_name='Sai',
        )

    def sign_in(self, **extra):
        """Sign Sai in, with any extra form fields."""
        return self.client.post('/accounts/login/', {
            'login': 'sai@example.org',
            'password': SAI_PASSWORD, **extra,
        })

    def test_the_cookie_is_kept_from_scripts(self):
        response = self.sign_in(remember='on')
        cookie = response.cookies['sessionid']
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax')
        self.assertEqual(cookie['max-age'], 1209600)
        self.assertFalse(cookie['secure'])

    def test_without_remember_me_it_ends_with_the_browser(
            self):
        cookie = self.sign_in().cookies['sessionid']
        self.assertEqual(cookie['max-age'], '')
        self.assertTrue(self.client.session
                        .get_expire_at_browser_close())

    def test_the_row_holds_the_data(self):
        self.sign_in()
        key = self.client.cookies['sessionid'].value
        row = Session.objects.get(session_key=key)
        data = row.get_decoded()
        self.assertEqual(data['_auth_user_id'],
                         str(self.sai.pk))
        self.assertNotIn(SAI_PASSWORD, str(data))


class MessageTests(TestCase):
    """Messages: shown once, in a signed cookie."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()

    def setUp(self):
        self.client.force_login(self.sam)

    def save_draft(self, **kw):
        """Post the new-event form, with any options."""
        return self.client.post(reverse('events:create'),
                                NEW_EVENT, **kw)

    def test_a_message_is_shown_once(self):
        response = self.save_draft()
        page = self.client.get(response['Location'])
        self.assertContains(page, 'Draft saved.', count=1)
        again = self.client.get(response['Location'])
        self.assertNotContains(again, 'Draft saved.')

    def test_it_waits_in_a_signed_cookie(self):
        response = self.save_draft()
        cookie = response.cookies['messages']
        self.assertIn(':', cookie.value)
        self.assertTrue(cookie['httponly'])
        shown = self.client.get(response['Location'])
        self.assertEqual(
            shown.cookies['messages']['max-age'], 0
        )

    def test_a_changed_cookie_is_ignored(self):
        response = self.save_draft()
        value = response.cookies['messages'].value
        self.client.cookies['messages'] = 'x' + value
        page = self.client.get(response['Location'])
        self.assertNotContains(page, 'Draft saved.')

    def test_a_message_can_be_closed(self):
        page = self.save_draft(follow=True)
        self.assertContains(page, 'alert-success')
        self.assertContains(page, 'data-close')
        self.assertContains(page, 'otahque/site.js')

    def test_an_error_has_the_error_style(self):
        draft = future_draft(self.sam, description='')
        page = self.client.post(
            action_url('publish', draft), follow=True
        )
        self.assertContains(page, 'alert-error')
        self.assertContains(page, 'Add a description.')


class PlacesFilterTests(TestCase):
    """The places filter, remembered in the session."""

    @classmethod
    def setUpTestData(cls):
        start = timezone.now() + timedelta(days=7)
        save_event(starts_at=start, capacity=2)
        cls.full = save_event(title='Django workshop',
                              starts_at=start, capacity=1)
        sai = User.objects.create_user(
            'sai@example.org', display_name='Sai'
        )
        Registration.objects.create(event=cls.full,
                                    member=sai)

    def test_the_filter_is_remembered(self):
        self.client.get('/events/?places=1')
        page = self.client.get('/events/')
        self.assertContains(page, 'Python meetup')
        self.assertNotContains(page, 'Django workshop')
        self.assertContains(
            page, 'Showing only events with places left.'
        )

    def test_show_all_clears_it(self):
        self.client.get('/events/?places=1')
        self.client.get('/events/?places=0')
        page = self.client.get('/events/')
        self.assertContains(page, 'Django workshop')
        self.assertFalse(self.client.session['places_only'])

    def test_viewing_alone_saves_no_session(self):
        response = self.client.get('/events/')
        self.assertNotIn('sessionid', response.cookies)
        self.assertFalse(Session.objects.exists())

    def test_places_are_read_from_the_database(self):
        self.client.get('/events/?places=1')
        self.assertNotContains(self.client.get('/events/'),
                               'Django workshop')
        self.full.registrations.update(
            status=Registration.Status.CANCELLED,
            cancelled_at=timezone.now(),
        )
        page = self.client.get('/events/')
        self.assertContains(page, 'Django workshop')


class SessionEndTests(TestCase):
    """What signing out and expiry forget."""

    @classmethod
    def setUpTestData(cls):
        start = timezone.now() + timedelta(days=7)
        full = save_event(title='Django workshop',
                          starts_at=start, capacity=1)
        cls.sai = User.objects.create_user(
            'sai@example.org', display_name='Sai'
        )
        Registration.objects.create(event=full,
                                    member=cls.sai)

    def test_sign_out_clears_the_filter_not_the_zone(self):
        self.client.force_login(self.sai)
        self.client.cookies['otahque_tz'] = 'Asia/Kolkata'
        self.client.get('/events/?places=1')
        self.client.post('/accounts/logout/')
        page = self.client.get('/events/')
        self.assertContains(page, 'Django workshop')
        self.assertEqual(
            self.client.cookies['otahque_tz'].value,
            'Asia/Kolkata',
        )

    def test_an_expired_session_is_forgotten(self):
        self.client.get('/events/?places=1')
        session = self.client.session
        session.set_expiry(-1)
        session.save()
        page = self.client.get('/events/')
        self.assertContains(page, 'Django workshop')


NEW_YORK = ZoneInfo('America/New_York')


class ViewerZoneFormTests(TestCase):
    """Typed times belong to the event's zone.

    That holds whatever zone the viewer's page uses.
    """

    def test_a_new_york_viewer_creates_a_delhi_event(self):
        with timezone.override(NEW_YORK):
            form = new_event_form(
                timezone='Asia/Kolkata',
                starts_at='2027-03-14T02:30',
                ends_at='2027-03-14T04:00',
            )
            self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            in_utc(form, 'starts_at'),
            datetime(2027, 3, 13, 21, 0, tzinfo=UTC),
        )

    def test_the_event_zone_still_refuses_its_own_gap(self):
        with timezone.override(NEW_YORK):
            form = new_event_form(
                timezone='Europe/London',
                starts_at='2027-03-28T01:30',
                ends_at='2027-03-28T03:00',
            )
            self.assertFormError(
                form, 'starts_at',
                '01:30 does not exist in Europe/London '
                'that day: the clocks go forward.',
            )

    def test_the_copy_form_too(self):
        event = save_event(timezone='Asia/Kolkata')
        with timezone.override(NEW_YORK):
            form = CopyForm(
                {'starts_at': '2027-11-07T01:30'},
                event=event,
            )
            self.assertTrue(form.is_valid(), form.errors)

    def test_the_new_event_page_with_a_new_york_cookie(self):
        self.client.force_login(editor())
        self.client.cookies['otahque_tz'] = str(NEW_YORK)
        self.client.post(reverse('events:create'), {
            **NEW_EVENT, 'timezone': 'Asia/Kolkata',
            'starts_at': '2027-03-14T02:30',
            'ends_at': '2027-03-14T04:00',
        })
        self.assertTrue(Event.objects.exists())


class BothTimesTests(TestCase):
    """When an event shows the viewer's time as well."""

    @classmethod
    def setUpTestData(cls):
        cls.clinic = save_event(
            title='Delhi clinic', timezone='Asia/Kolkata',
            starts_at=datetime(2026, 12, 3, 12, 30,
                               tzinfo=UTC),
        )

    def page(self, zone):
        """Open the clinic's page for a viewer in zone."""
        self.client.cookies['otahque_tz'] = zone
        url = self.clinic.get_absolute_url()
        return self.client.get(url)

    def test_the_venue_zone_shows_one_time(self):
        page = self.page('Asia/Kolkata')
        self.assertContains(
            page, 'Thursday 3 December 2026, 18:00 IST'
        )
        self.assertNotContains(page, 'Your time')

    def test_another_zone_shows_both(self):
        page = self.page('America/New_York')
        self.assertContains(
            page, 'Thursday 3 December 2026, 18:00 IST'
        )
        self.assertContains(
            page,
            'Your time: Thursday 3 December 2026, 07:30 EST',
        )

    def test_an_alias_shows_one_time(self):
        page = self.page('Asia/Calcutta')
        self.assertNotContains(page, 'Your time')

    def test_summer_time_counts(self):
        july = save_event(
            starts_at=datetime(2027, 7, 1, 17, tzinfo=UTC)
        )
        winter = save_event(
            starts_at=datetime(2027, 1, 14, 18, tzinfo=UTC)
        )
        utc = ZoneInfo('UTC')
        self.assertTrue(july.differs_for(utc))
        self.assertFalse(winter.differs_for(utc))


def in_group(email, group, **flags):
    """Add a member with SAI_PASSWORD to the named group."""
    name = email.split('@')[0].title()
    user = User.objects.create_user(
        email, SAI_PASSWORD, display_name=name, **flags
    )
    user.groups.add(Group.objects.get(name=group))
    return user


class PermissionCacheTests(TestCase):
    """A user's permissions are cached until refetched."""

    def test_a_new_group_needs_a_fresh_user(self):
        soni = member('soni@example.org')
        self.assertFalse(soni.has_perm('events.add_event'))
        soni.groups.add(Group.objects.get(name=ORGANIZERS))
        self.assertFalse(soni.has_perm('events.add_event'))
        soni.refresh_from_db()
        self.assertFalse(soni.has_perm('events.add_event'))
        soni = User.objects.get(pk=soni.pk)
        self.assertTrue(soni.has_perm('events.add_event'))


class ActiveOrganizerTests(TestCase):
    """Only active, current organizers count."""

    def test_an_inactive_organizer_sees_no_draft(self):
        sam = in_group('sam@example.org', ORGANIZERS)
        draft = future_draft(sam)
        self.assertTrue(draft.is_visible_to(sam))
        sam.is_active = False
        sam.save()
        self.assertFalse(draft.has_organizer(sam))
        self.assertFalse(draft.is_visible_to(sam))


# What each person gets on Sam's draft (Chapter 30).
MATRIX = [
    # person, view, edit, publish, create
    ('visitor', '404', 'sign in', 'sign in', 'sign in'),
    ('member', '404', '404', '404', '403'),
    ('staff only', '404', '404', '404', '403'),
    ('other organizer', '404', '404', '404', 'ok'),
    ('administrator', 'ok', '403', '403', '403'),
    ('superuser', 'ok', '403', '403', 'ok'),
    # Last: this row publishes the draft.
    ('organizer', 'ok', 'ok', 'ok', 'ok'),
]


def outcome(response):
    """Name a response as the matrix names it."""
    code = response.status_code
    if code == 302 and response.url.startswith(
            reverse('account_login')):
        return 'sign in'
    return {200: 'ok', 302: 'ok'}.get(code, str(code))


class PermissionMatrixTests(TestCase):
    """Each person against each page: the full matrix."""

    @classmethod
    def setUpTestData(cls):
        sam = in_group('sam@example.org', ORGANIZERS)
        raj = in_group('raj@example.org', ORGANIZERS)
        cls.draft = future_draft(sam)
        future_draft(raj, title='Delhi clinic')
        cls.people = {
            'visitor': None,
            'member': member('sai@example.org'),
            'staff only': User.objects.create_user(
                'staff@example.org', display_name='Staff',
                is_staff=True,
            ),
            'other organizer': raj,
            'administrator': in_group(
                'admin@example.org', 'Administrators',
                is_staff=True,
            ),
            'superuser': User.objects.create_superuser(
                'root@example.org', display_name='Root'
            ),
            'organizer': sam,
        }

    def answers(self):
        """List this person's outcomes, page by page."""
        draft = self.draft
        return [
            outcome(self.client.get(
                draft.get_absolute_url())),
            outcome(self.client.get(edit_url(draft))),
            outcome(self.client.post(
                action_url('publish', draft))),
            outcome(self.client.get(
                reverse('events:create'))),
        ]

    def test_every_row(self):
        for person, *expected in MATRIX:
            self.client.logout()
            if self.people[person]:
                self.client.force_login(self.people[person])
            with self.subTest(person=person):
                self.assertEqual(self.answers(), expected)


class OrganizerRuleTests(TestCase):
    """Granting and revoking organizers, with records."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = in_group(
            'admin@example.org', 'Administrators',
            is_staff=True,
        )
        cls.sam = in_group('sam@example.org', ORGANIZERS)
        cls.soni = in_group('soni@example.org', ORGANIZERS)
        cls.event = future_draft(cls.sam)

    def test_an_organizer_is_added_and_recorded(self):
        self.event.grant_organizer(self.soni, self.admin)
        self.assertTrue(self.event.has_organizer(self.soni))
        row = AuditEvent.objects.get()
        self.assertEqual(
            (row.actor, row.action, row.outcome,
             row.target_id, row.detail),
            (self.admin, 'add_organizer', 'allowed',
             self.event.pk, {'member': self.soni.pk}),
        )

    def test_only_the_organizers_group_may_organize(self):
        sai = member('sai@example.org')
        with self.assertRaisesMessage(
                ValidationError,
                'Only members of the Organizers group'):
            self.event.grant_organizer(sai, self.admin)
        self.assertFalse(self.event.has_organizer(sai))
        self.assertEqual(AuditEvent.objects.get().outcome,
                         'refused')

    def test_an_inactive_member_is_refused(self):
        self.soni.is_active = False
        self.soni.save()
        with self.assertRaisesMessage(
                ValidationError, 'account is not active'):
            self.event.grant_organizer(self.soni, self.admin)

    def test_the_last_organizer_stays(self):
        for status in ('draft', 'published'):
            event = future_draft(self.sam, status=status)
            place = event.organizer_assignments.get()
            with self.subTest(status=status):
                with self.assertRaisesMessage(
                        ValidationError,
                        'Assign another organizer'):
                    place.revoke(self.admin)
                place.refresh_from_db()
                self.assertIsNone(place.revoked_at)

    def test_a_cancelled_event_may_lose_them_all(self):
        event = future_draft(self.sam, status='cancelled')
        place = event.organizer_assignments.get()
        place.revoke(self.admin)
        self.assertIsNotNone(place.revoked_at)

    def test_one_of_two_may_go_and_is_refused_next(self):
        self.event.grant_organizer(self.soni, self.admin)
        self.client.force_login(self.sam)
        url = edit_url(self.event)
        self.assertEqual(
            self.client.get(url).status_code, 200
        )
        place = self.event.organizer_assignments.get(
            member=self.sam
        )
        place.revoke(self.admin)
        self.assertEqual(
            self.client.get(url).status_code, 404
        )


class OrganizerPageTests(TestCase):
    """The organizers page: who may use it, and rules."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = in_group(
            'admin@example.org', 'Administrators',
            is_staff=True,
        )
        cls.sam = in_group('sam@example.org', ORGANIZERS)
        cls.soni = in_group('soni@example.org', ORGANIZERS)
        cls.event = future_draft(cls.sam)
        cls.url = action_url('organizers', cls.event)
        cls.remove = action_url('remove_organizer',
                                cls.event)

    def setUp(self):
        cache.clear()

    def confirm(self, user):
        """Sign in, then confirm the password.

        allauth asks for it before a change on this page.
        """
        self.client.force_login(user)
        self.client.post(reverse('account_reauthenticate'),
                         {'password': SAI_PASSWORD})

    def place(self, user, event=None):
        """Return user's assignment to event, or to ours."""
        event = event or self.event
        return event.organizer_assignments.get(member=user)

    def test_a_visitor_is_sent_to_sign_in(self):
        self.assertRedirects(
            self.client.get(self.url),
            f"{reverse('account_login')}?next={self.url}",
            fetch_redirect_response=False,
        )

    def test_others_get_403_and_are_recorded(self):
        for user in (self.sam, member('sai@example.org')):
            self.client.force_login(user)
            with self.subTest(user=user.email):
                for response in (
                    self.client.get(self.url),
                    self.client.get(
                        reverse('events:organizer_events')),
                    self.client.post(self.remove, {}),
                ):
                    self.assertEqual(
                        response.status_code, 403
                    )
        refused = AuditEvent.objects.filter(
            action='manage_organizers', outcome='refused'
        )
        self.assertEqual(refused.count(), 6)

    def test_changes_need_a_recent_sign_in(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.url),
                            'Add an organizer')
        response = self.client.post(
            self.url, {'email': self.soni.email}
        )
        self.assertTrue(response.url.startswith(
            reverse('account_reauthenticate')))
        self.assertFalse(self.event.has_organizer(self.soni))

    def test_an_administrator_adds_an_organizer(self):
        self.confirm(self.admin)
        response = self.client.post(
            self.url, {'email': 'SONI@example.org'}
        )
        self.assertRedirects(response, self.url)
        self.assertTrue(self.event.has_organizer(self.soni))

    def test_the_page_refuses_what_the_rules_refuse(self):
        member('sai@example.org')
        self.confirm(self.admin)
        for email, message in [
            ('sai@example.org', 'Only members of the '
                                'Organizers group'),
            ('nobody@example.org', 'No member has this'),
            ('sam@example.org', 'already organizes'),
        ]:
            with self.subTest(email=email):
                self.assertContains(self.client.post(
                    self.url, {'email': email}), message)

    def test_remove_one_but_keep_the_last(self):
        self.event.grant_organizer(self.soni, self.admin)
        self.confirm(self.admin)
        for user, message in [
            (self.soni, 'Organizer removed.'),
            (self.sam, 'Assign another organizer before '
                       'removing the last one.'),
        ]:
            response = self.client.post(self.remove, {
                'assignment': self.place(user).pk,
            }, follow=True)
            self.assertContains(response, message)
        self.assertTrue(self.event.has_organizer(self.sam))

    def test_another_events_organizer_is_not_a_choice(self):
        swap = future_draft(self.soni, title='Book swap')
        self.confirm(self.admin)
        response = self.client.post(self.remove, {
            'assignment': self.place(self.soni, swap).pk,
        })
        self.assertEqual(response.status_code, 404)
        self.assertTrue(swap.has_organizer(self.soni))

    def test_the_list_runs_a_fixed_number_of_queries(self):
        for title in ('Book swap', 'Delhi clinic'):
            future_draft(self.soni, title=title)
        self.client.force_login(self.admin)
        url = reverse('events:organizer_events')
        with self.assertNumQueries(7):
            self.client.get(url)


class AuditTrailTests(TestCase):
    """Each action leaves the right audit rows."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = in_group('sam@example.org', ORGANIZERS)
        cls.raj = in_group('raj@example.org', ORGANIZERS)

    def trail(self):
        """List the audit rows so far: action and outcome."""
        return list(AuditEvent.objects.order_by('id')
                    .values_list('action', 'outcome'))

    def test_each_event_action_is_recorded(self):
        self.client.force_login(self.sam)
        self.client.post(reverse('events:create'), NEW_EVENT)
        clinic = Event.objects.get(title=NEW_EVENT['title'])
        self.client.post(edit_url(clinic),
                         as_sent(clinic, location='Room 2'))
        event = future_draft(self.sam)
        for name in ('publish', 'cancel'):
            self.client.post(action_url(name, event))
        self.client.post(action_url('copy', event),
                         {'starts_at': '2027-02-04T19:00'})
        copy = Event.objects.latest('pk')
        self.client.post(action_url('delete', copy))
        self.assertEqual(self.trail(), [
            (action, 'allowed') for action in (
                'create_event', 'edit_event',
                'publish_event', 'cancel_event',
                'copy_event', 'delete_event',
            )
        ])
        edit = AuditEvent.objects.get(action='edit_event')
        self.assertEqual(edit.detail,
                         {'fields': ['location']})

    def test_refusals_by_members_are_recorded(self):
        draft = future_draft(self.sam)
        published = future_draft(
            self.sam, status='published'
        )
        self.client.get(draft.get_absolute_url())
        self.client.force_login(self.raj)
        self.client.get(draft.get_absolute_url())
        self.client.get(edit_url(draft))
        self.client.post(action_url('cancel', published))
        self.client.force_login(member('sai@example.org'))
        self.client.get(reverse('events:create'))
        self.assertEqual(self.trail(), [
            ('view_event', 'refused'),
            ('edit_event', 'refused'),
            ('cancel_event', 'refused'),
            ('create_event', 'refused'),
        ])

    def test_a_rule_or_an_unknown_event_adds_nothing(self):
        draft = future_draft(self.sam, description='')
        self.client.force_login(self.sam)
        self.client.post(action_url('publish', draft))
        self.client.get(reverse('events:edit', args=[999]))
        self.assertEqual(self.trail(), [])


class RegistrationWindowTests(TestCase):
    """The registration times and their database rules."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()
        cls.event = future_draft(cls.sam)

    def test_the_order_holds_in_the_database(self):
        rows = Event.objects.filter(pk=self.event.pk)
        start = self.event.starts_at
        hour = timedelta(hours=1)
        for changes in (
            {'registration_closes_at': start + hour},
            {'cancellation_deadline': start + hour},
            {'registration_opens_at': start,
             'registration_closes_at': start - hour},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        rows.update(**changes)

    def test_blank_times_pass_the_rules(self):
        Event.objects.filter(pk=self.event.pk).update(
            registration_opens_at=None,
            registration_closes_at=None,
            cancellation_deadline=None,
        )
        self.event.refresh_from_db()
        self.event.full_clean()


class WindowFormTests(TestCase):
    """Readiness, copies, and the form learn the window."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()
        cls.event = future_draft(cls.sam)

    def test_publishing_needs_both_times(self):
        event = future_draft(
            self.sam, registration_closes_at=None,
            cancellation_deadline=None,
        )
        self.assertEqual(event.readiness_problems(), [
            'Set when registration closes.',
            'Set a cancellation deadline.',
        ])

    def test_a_copy_moves_the_window(self):
        week = timedelta(days=7)
        self.event.registration_opens_at = (
            self.event.starts_at - week
        )
        self.event.save()
        copy = self.event.copy_as_draft(
            self.sam, self.event.starts_at + week
        )
        for name in ('registration_opens_at',
                     'registration_closes_at',
                     'cancellation_deadline'):
            with self.subTest(name=name):
                self.assertEqual(
                    getattr(copy, name),
                    getattr(self.event, name) + week,
                )

    def test_the_form_reads_times_in_the_event_zone(self):
        form = new_event_form(
            registration_closes_at='2026-12-03T12:00',
            cancellation_deadline='2026-12-02T18:00',
            phone_required='on',
        )
        self.assertTrue(form.is_valid(), form.errors)
        event = form.save()
        self.assertEqual(
            event.registration_closes_at,
            datetime(2026, 12, 3, 17, 0, tzinfo=UTC),
        )
        self.assertIsNone(event.registration_opens_at)
        self.assertTrue(event.phone_required)

    def test_the_form_refuses_a_late_closing(self):
        form = new_event_form(
            registration_closes_at='2026-12-03T20:00'
        )
        self.assertFalse(form.is_valid())
        self.assertEqual(form.non_field_errors(),
                         ['Registration must close by the '
                          'start.'])


class SortOrderTests(TestCase):
    """Text sorts the same way on every database and computer."""

    def test_titles_sort_by_code_point(self):
        for title in ('apple day', 'Zebra talk', 'Émile meets'):
            save_event(title=title)
        titles = Event.objects.order_by('title').values_list(
            'title', flat=True
        )
        self.assertEqual(
            list(titles),
            ['Zebra talk', 'apple day', 'Émile meets'],
        )


class EditVersionTests(TestCase):
    """A save from an out-of-date page is refused."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = editor()
        cls.clinic = save_clinic(cls.sam)

    def setUp(self):
        self.client.force_login(self.sam)
        self.url = reverse('events:edit',
                           args=[self.clinic.pk])

    def test_the_page_sends_the_version(self):
        response = self.client.get(self.url)
        self.assertContains(
            response, '<input type="hidden" name="version" '
            'value="1">', html=True,
        )

    def test_a_save_counts_a_new_version(self):
        self.client.post(self.url, as_sent(
            self.clinic, title='Clinic, room 2'))
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.title, 'Clinic, room 2')
        self.assertEqual(self.clinic.version, 2)

    def test_a_save_from_an_old_page_is_refused(self):
        title = self.clinic.title
        opened = as_sent(self.clinic, title='Clinic, room 2')
        # Raj saves the event after Sam opened the page.
        Event.objects.filter(pk=self.clinic.pk).update(
            capacity=60, version=2
        )
        response = self.client.post(self.url, opened)
        self.assertContains(response, 'your changes were not '
                                      'saved')
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.title, title)
        self.assertEqual(self.clinic.capacity, 60)

    def test_the_admin_refuses_an_old_page_too(self):
        admin = User.objects.create_superuser(
            'admin@example.org', display_name='Admin'
        )
        self.client.force_login(admin)
        opened = event_form(self.clinic, location='Room 2')
        Event.objects.filter(pk=self.clinic.pk).update(
            version=2
        )
        response = self.client.post(
            admin_url(Event, 'change', self.clinic.pk), opened
        )
        self.assertContains(response, 'Reload it')
        self.clinic.refresh_from_db()
        self.assertNotEqual(self.clinic.location, 'Room 2')
