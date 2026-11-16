from datetime import UTC, datetime, timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.template.loader import render_to_string
from django.test import Client, SimpleTestCase, TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from . import views
from .forms import EventForm
from .models import Event, OrganizerAssignment
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
    """An admin page's address, such as an event's page."""
    meta = model._meta
    name = f'admin:{meta.app_label}_{meta.model_name}_{page}'
    return reverse(name, args=args)


def layout_pages(event):
    return [
        ('/', 'events/home.html', 'Otahque'),
        ('/events/', 'events/list.html',
         'Events | Otahque'),
        (f'/events/{event.pk}/', 'events/detail.html',
         'Python meetup | Otahque'),
    ]


class RoutingTests(TestCase):
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

    def test_unpublished_events_are_hidden(self):
        response = self.client.get(
            f'/events/{self.event.pk}/'
        )
        self.assertContains(
            response, 'Leeds Central Library'
        )
        for status in (Event.Status.DRAFT,
                       Event.Status.CANCELLED):
            with self.subTest(status=status):
                event = save_event(status=status)
                response = self.client.get(
                    f'/events/{event.pk}/'
                )
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
    def make_event(self, **changes):
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
        self.assertContains(
            response, '<span class="places text-sm">'
            '1 of 2 places left</span>', html=True,
        )
        self.assertContains(
            response, '<span class="places badge">'
            'Full</span>', html=True,
        )
        self.assertNotContains(response, 'of 5 places left')
        with self.assertNumQueries(1):
            response = self.client.get(
                f'/events/{self.meetup.pk}/'
            )
        self.assertContains(response, '1 of 2 places left')


def event_form(event, **changes):
    """What the admin's event page sends; times in UTC."""
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
    }
    data.update(changes)
    return data


class EventAdminTests(TestCase):
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


def revoke_form(when):
    """What the assignment page sends to revoke at when."""
    return {'revoked_at_0': f'{when:%Y-%m-%d}',
            'revoked_at_1': f'{when:%H:%M:%S}'}


class OrganizerAssignmentAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sam = User.objects.create_superuser(
            'sam@example.org', display_name='Sam'
        )
        cls.event = save_event()
        cls.sai = User.objects.create_user(
            'sai@example.org', display_name='Sai'
        )

    def setUp(self):
        self.client.force_login(self.sam)

    def add(self):
        return self.client.post(
            admin_url(OrganizerAssignment, 'add'),
            {'event': self.event.pk, 'member': self.sai.pk},
        )

    def test_add_and_revoke_but_never_delete(self):
        self.add()
        assignment = OrganizerAssignment.objects.get()
        change = admin_url(OrganizerAssignment, 'change',
                           assignment.pk)
        tomorrow = timezone.now() + timedelta(days=1)
        self.client.post(change, revoke_form(tomorrow))
        assignment.refresh_from_db()
        self.assertIsNotNone(assignment.revoked_at)
        response = self.client.post(
            admin_url(OrganizerAssignment, 'delete',
                      assignment.pk),
            {'post': 'yes'},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            OrganizerAssignment.objects.count(), 1
        )

    def test_rule_messages_reach_the_page(self):
        self.add()
        self.assertContains(
            self.add(),
            'This member already organizes this event.',
        )
        assignment = OrganizerAssignment.objects.get()
        change = admin_url(OrganizerAssignment, 'change',
                           assignment.pk)
        early = datetime(2026, 1, 1, tzinfo=UTC)
        self.assertContains(
            self.client.post(change, revoke_form(early)),
            'An assignment cannot be revoked before it '
            'starts.',
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
    """An EventForm holding NEW_EVENT with changes."""
    return EventForm(NEW_EVENT | changes)


class EventFormTests(TestCase):
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

    def test_zero_capacity_uses_the_model_rule(self):
        form = new_event_form(capacity='0')
        self.assertFalse(form.is_valid())
        self.assertEqual(form.non_field_errors(),
                         ['Capacity must be more than 0.'])

    def test_unknown_zone_is_refused(self):
        form = new_event_form(timezone='Mars/Olympus')
        self.assertFalse(form.is_valid())
        self.assertIn('timezone', form.errors)


def in_utc(form, name):
    """A cleaned time from form, shown in UTC."""
    return form.cleaned_data[name].astimezone(UTC)


class EventZoneTests(TestCase):
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
    """A member holding the named permissions."""
    name = email.split('@')[0].title()
    user = User.objects.create_user(email, display_name=name)
    user.user_permissions.add(*Permission.objects.filter(
        codename__in=codenames
    ))
    return user


class NewEventPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sam = member('sam@example.org', 'add_event')
        cls.sai = member('sai@example.org')
        cls.url = reverse('events:create')

    def test_visitor_is_sent_to_sign_in(self):
        response = self.client.get(self.url)
        sign_in = reverse('admin:login')
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
    @classmethod
    def setUpTestData(cls):
        cls.sam = member('sam@example.org', 'add_event')
        cls.url = reverse('events:create')

    def setUp(self):
        self.client.force_login(self.sam)

    def test_fields_use_otahque_styles_and_script(self):
        response = self.client.get(self.url)
        for text, count in (('class="fieldset"', 6),
                            ('class="input w-full"', 5),
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
