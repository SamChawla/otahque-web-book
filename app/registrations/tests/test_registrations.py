"""Tests for the registrations app."""
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest import mock

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.contrib.auth.models import Permission
from django.test import (
    TestCase, TransactionTestCase, skipUnlessDBFeature,
)
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile
from audit.models import AuditEvent
from events.models import (
    ORGANIZERS, Event, OrganizerAssignment,
)
from config.helpers import SAI_PASSWORD as PASSWORD
from config.helpers import (
    admin_url, as_sent, in_group, outcome,
)
from registrations.models import Registration

User = get_user_model()


class RegistrationTests(TestCase):
    """A registration links a member to an event."""

    @classmethod
    def setUpTestData(cls):
        cls.event = Event.objects.create(
            title='Python meetup',
            starts_at=datetime(2026, 11, 19, 18, 30,
                               tzinfo=UTC),
            ends_at=datetime(2026, 11, 19, 20, 30,
                             tzinfo=UTC),
            timezone='Europe/London',
            location='Leeds Central Library',
            capacity=40,
        )
        cls.member = User.objects.create_user(
            'sai@example.org', display_name='Sai'
        )
        cls.registration = Registration.objects.create(
            event=cls.event, member=cls.member
        )

    def test_registration_links_event_and_member(self):
        registration = self.registration
        self.assertEqual(registration.event, self.event)
        self.assertEqual(registration.member, self.member)
        self.assertEqual(
            registration.status, Registration.Status.ACTIVE
        )
        self.assertQuerySetEqual(
            self.event.registrations.all(), [registration]
        )
        self.assertQuerySetEqual(
            self.member.registrations.all(), [registration]
        )

    def test_event_with_registration_is_kept(self):
        with self.assertRaises(ProtectedError):
            self.event.delete()
        self.assertTrue(
            Event.objects.filter(pk=self.event.pk).exists()
        )

    def test_member_with_registration_is_kept(self):
        with self.assertRaises(ProtectedError):
            self.member.delete()
        self.assertTrue(
            User.objects.filter(pk=self.member.pk).exists()
        )

    def test_second_active_registration_is_refused(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Registration.objects.create(
                    event=self.event, member=self.member
                )
        self.assertEqual(
            self.event.registrations.count(), 1
        )

    def test_member_can_register_after_cancelling(self):
        self.registration.status = 'cancelled'
        self.registration.cancelled_at = timezone.now()
        self.registration.save()
        Registration.objects.create(
            event=self.event, member=self.member
        )
        active = self.event.registrations.filter(
            status=Registration.Status.ACTIVE
        )
        self.assertEqual(active.count(), 1)

    def test_cancelled_at_matches_status(self):
        rows = Registration.objects.filter(
            pk=self.registration.pk
        )
        for status, cancelled_at in [
            ('cancelled', None),
            ('active', timezone.now()),
        ]:
            with self.subTest(status=status):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        rows.update(
                            status=status,
                            cancelled_at=cancelled_at,
                        )

    def test_cancelled_never_before_registered(self):
        rows = Registration.objects.filter(
            pk=self.registration.pk
        )
        day = timedelta(days=1)
        before = self.registration.registered_at - day
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                rows.update(status='cancelled',
                            cancelled_at=before)

    def test_full_clean_explains_a_duplicate(self):
        duplicate = Registration(
            event=self.event, member=self.member
        )
        with self.assertRaises(ValidationError) as caught:
            duplicate.full_clean()
        self.assertEqual(
            caught.exception.messages,
            ['This member already has a place at '
             'this event.'],
        )

    def test_active_skips_cancelled_places(self):
        self.registration.status = 'cancelled'
        self.registration.cancelled_at = timezone.now()
        self.registration.save()
        again = Registration.objects.create(
            event=self.event, member=self.member
        )
        self.assertQuerySetEqual(
            self.event.registrations.active(), [again]
        )
        self.assertEqual(
            Registration.objects.active().count(), 1
        )


class RegistrationAdminTests(TestCase):
    """Registrations in the admin are view-only."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = User.objects.create_superuser(
            'sam@example.org', display_name='Sam'
        )
        for title in ('Python meetup', 'Django workshop'):
            event = Event.objects.create(
                title=title,
                starts_at=datetime(2026, 12, 3, 9,
                                   tzinfo=UTC),
                ends_at=datetime(2026, 12, 3, 12,
                                 tzinfo=UTC),
                timezone='UTC', location='Virtual',
                capacity=40,
            )
            for name in ('Sai', 'Raj'):
                member, _ = User.objects.get_or_create(
                    email=f'{name.lower()}@example.org',
                    defaults={'display_name': name},
                )
                Registration.objects.create(
                    event=event, member=member
                )

    def setUp(self):
        self.client.force_login(self.sam)

    def test_history_is_view_only(self):
        place = Registration.objects.first()
        add = self.client.get(admin_url(Registration, 'add'))
        self.assertEqual(add.status_code, 403)
        change = admin_url(Registration, 'change', place.pk)
        response = self.client.get(change)
        self.assertContains(response, 'sai@example.org')
        self.assertNotContains(response, 'name="_save"')
        response = self.client.post(
            change, {'status': 'cancelled'}
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            admin_url(Registration, 'delete', place.pk),
            {'post': 'yes'},
        )
        self.assertEqual(response.status_code, 403)

    def test_list_runs_a_fixed_number_of_queries(self):
        with self.assertNumQueries(6):
            self.client.get(
                admin_url(Registration, 'changelist')
            )


START = datetime(2027, 3, 4, 13, 30, tzinfo=UTC)
TICK = timedelta(microseconds=1)


def verified(email):
    """Create a member whose email address is confirmed."""
    name = email.split('@')[0].title()
    user = User.objects.create_user(email, display_name=name)
    EmailAddress.objects.create(user=user, email=email,
                                verified=True, primary=True)
    return user


def clinic(**changes):
    """Create Sam's published clinic, open for two places.

    Registration closes a day before the start; a cancel
    is late from two days before.
    """
    fields = {
        'title': 'Django clinic',
        'starts_at': START,
        'ends_at': START + timedelta(hours=2),
        'timezone': 'Asia/Kolkata',
        'location': 'Online',
        'capacity': 2,
        'status': Event.Status.PUBLISHED,
        'registration_opens_at': START - timedelta(days=14),
        'registration_closes_at': START - timedelta(days=1),
        'cancellation_deadline': START - timedelta(days=2),
    }
    return Event.objects.create(**(fields | changes))


class RegistrationRuleTests(TestCase):
    """Each reason a member cannot register, by code."""

    @classmethod
    def setUpTestData(cls):
        cls.event = clinic()
        cls.sai = verified('sai@example.org')
        cls.now = START - timedelta(days=5)

    def problems(self, member=None, now=None):
        """Ask the event why member cannot register."""
        return self.event.registration_problems(
            member or self.sai, now or self.now
        )

    def test_an_open_event_has_no_problems(self):
        self.assertEqual(self.problems(), [])

    def test_opening_is_inclusive(self):
        opens = self.event.registration_opens_at
        self.assertEqual(self.problems(now=opens - TICK),
                         ['not_open'])
        self.assertEqual(self.problems(now=opens), [])

    def test_closing_is_exclusive(self):
        closes = self.event.registration_closes_at
        self.assertEqual(self.problems(now=closes - TICK), [])
        self.assertEqual(self.problems(now=closes),
                         ['closed'])

    def test_a_blank_opening_means_open_now(self):
        self.event.registration_opens_at = None
        self.assertEqual(self.problems(), [])

    def test_only_published_events_take_places(self):
        for status in ('draft', 'cancelled'):
            with self.subTest(status=status):
                self.event.status = status
                self.assertEqual(self.problems(),
                                 ['not_published'])

    def test_a_past_event_is_closed(self):
        later = START + timedelta(days=1)
        self.assertEqual(self.problems(now=later),
                         ['closed'])

    def test_a_full_event_says_so(self):
        for email in ('raj@example.org', 'soni@example.org'):
            self.event.registrations.create(
                member=verified(email)
            )
        self.assertEqual(self.problems(), ['full'])

    def test_a_place_already_held_is_named(self):
        self.event.registrations.create(member=self.sai)
        self.assertEqual(self.problems(),
                         ['already_registered'])

    def test_an_unconfirmed_email_is_named(self):
        soni = User.objects.create_user(
            'soni@example.org', display_name='Soni'
        )
        self.assertEqual(self.problems(soni), ['unverified'])

    def test_a_missing_phone_is_named(self):
        self.event.phone_required = True
        self.assertEqual(self.problems(), ['phone_missing'])
        Profile.objects.create(user=self.sai,
                               phone='+919876543210')
        self.sai.refresh_from_db()
        self.assertEqual(self.problems(), [])

    def test_reasons_add_up(self):
        soni = User.objects.create_user(
            'soni@example.org', display_name='Soni'
        )
        closes = self.event.registration_closes_at
        self.assertEqual(self.problems(soni, closes),
                         ['closed', 'unverified'])


class RegisterTests(TestCase):
    """Event.register(): a place, or a named refusal."""

    @classmethod
    def setUpTestData(cls):
        cls.event = clinic()
        cls.sai = verified('sai@example.org')
        cls.now = START - timedelta(days=5)

    def test_a_place_is_made(self):
        place = self.event.register(self.sai, self.now)
        self.assertEqual(place.status, 'active')
        self.assertEqual(place.registered_at, self.now)
        self.assertEqual(self.event.places_taken(), 1)

    def test_a_refusal_names_why_and_saves_nothing(self):
        closes = self.event.registration_closes_at
        with self.assertRaises(ValidationError) as caught:
            self.event.register(self.sai, closes)
        self.assertEqual(caught.exception.messages,
                         ['Registration has closed.'])
        self.assertEqual(caught.exception.error_list[0].code,
                         'closed')
        self.assertFalse(Registration.objects.exists())

    def test_a_second_request_keeps_one_place(self):
        self.event.register(self.sai, self.now)
        with self.assertRaises(ValidationError) as caught:
            self.event.register(self.sai, self.now)
        self.assertEqual(caught.exception.error_list[0].code,
                         'already_registered')
        self.assertEqual(self.event.places_taken(), 1)

    def test_the_constraint_catches_a_missed_check(self):
        # A place appears after the checks ran.
        self.event.registrations.create(member=self.sai)
        with mock.patch.object(Event, 'registration_problems',
                               return_value=[]):
            with self.assertRaises(ValidationError) as caught:
                self.event.register(self.sai, self.now)
        self.assertEqual(caught.exception.error_list[0].code,
                         'already_registered')
        self.assertEqual(self.event.places_taken(), 1)

    def test_another_database_error_is_not_hidden(self):
        broken = IntegrityError('NOT NULL constraint failed')
        with mock.patch.object(Registration, 'save',
                               side_effect=broken):
            with self.assertRaises(IntegrityError):
                self.event.register(self.sai, self.now)

    def test_the_constraint_has_a_code(self):
        self.event.registrations.create(member=self.sai)
        again = Registration(event=self.event, member=self.sai)
        with self.assertRaises(ValidationError) as caught:
            again.full_clean()
        errors = caught.exception.error_dict['__all__']
        self.assertEqual(errors[0].code, 'already_registered')


class CancelTests(TestCase):
    """Registration.cancel(): a place released once."""

    @classmethod
    def setUpTestData(cls):
        cls.event = clinic()
        cls.raj = verified('raj@example.org')

    def setUp(self):
        self.place = self.event.register(
            self.raj, START - timedelta(days=5)
        )

    def test_cancel_releases_the_place_once(self):
        when = START - timedelta(days=3)
        self.assertTrue(self.place.cancel(when))
        self.assertEqual(self.place.status, 'cancelled')
        self.assertEqual(self.place.cancelled_at, when)
        self.assertEqual(self.event.places_taken(), 0)
        later = START - timedelta(days=2, hours=1)
        self.assertFalse(self.place.cancel(later))
        self.place.refresh_from_db()
        self.assertEqual(self.place.cancelled_at, when)

    def test_a_stale_copy_changes_nothing(self):
        other = Registration.objects.get(pk=self.place.pk)
        self.place.cancel(START - timedelta(days=3))
        self.assertFalse(other.cancel(START - TICK))
        self.assertEqual(
            Registration.objects.filter(
                status='cancelled').count(), 1,
        )

    def test_late_from_the_deadline(self):
        deadline = self.event.cancellation_deadline
        self.place.cancel(deadline - TICK)
        self.assertFalse(self.place.is_late())
        again = self.event.register(self.raj, deadline - TICK)
        again.cancel(deadline)
        self.assertTrue(again.is_late())

    def test_no_cancel_once_the_event_starts(self):
        with self.assertRaises(ValidationError) as caught:
            self.place.cancel(START)
        self.assertEqual(caught.exception.code, 'started')
        self.assertTrue(self.place.cancel(START - TICK))

    def test_a_member_may_register_again(self):
        self.place.cancel(START - timedelta(days=4))
        again = self.event.register(
            self.raj, START - timedelta(days=4)
        )
        self.assertNotEqual(again.pk, self.place.pk)
        self.assertEqual(self.event.places_taken(), 1)

    def test_a_cancelled_event_keeps_places(self):
        self.event.cancel()
        self.place.refresh_from_db()
        self.assertEqual(self.place.status, 'active')
        self.assertTrue(
            self.place.cancel(START - timedelta(days=3))
        )

    def test_counts_for_the_organizer(self):
        deadline = self.event.cancellation_deadline
        self.place.cancel(deadline - TICK)
        again = self.event.register(self.raj, deadline - TICK)
        again.cancel(deadline + TICK)
        self.assertEqual(
            self.event.registrations.cancellation_counts(),
            {'cancelled': 2, 'late': 1},
        )


def soon(**changes):
    """Create a clinic next week, open for registration now."""
    starts = timezone.now() + timedelta(days=7)
    return clinic(**{
        'starts_at': starts,
        'ends_at': starts + timedelta(hours=2),
        'registration_opens_at': None,
        'registration_closes_at': starts - timedelta(days=1),
        'cancellation_deadline': starts - timedelta(days=2),
    } | changes)


def url(name, *args):
    """Return the address of a registrations page."""
    return reverse(f'registrations:{name}', args=args)


class RegisterPageTests(TestCase):
    """The Register button and what it says back."""

    @classmethod
    def setUpTestData(cls):
        cls.event = soon()
        cls.sai = verified('sai@example.org')

    def test_a_visitor_signs_in_and_comes_back(self):
        page = self.event.get_absolute_url()
        response = self.client.get(page)
        sign_in = reverse('account_login')
        self.assertContains(
            response, f'href="{sign_in}?next={page}"'
        )
        self.assertNotContains(response, 'shares your name')
        self.sai.set_password(PASSWORD)
        self.sai.save()
        response = self.client.post(
            f'{sign_in}?next={page}',
            {'login': 'sai@example.org', 'password': PASSWORD},
        )
        self.assertRedirects(response, page,
                             fetch_redirect_response=False)

    def test_a_member_registers_with_one_post(self):
        self.client.force_login(self.sai)
        page = self.client.get(self.event.get_absolute_url())
        self.assertContains(page, 'phone number with this')
        response = self.client.post(
            url('register', self.event.pk), follow=True
        )
        self.assertRedirects(response,
                             self.event.get_absolute_url())
        self.assertContains(response, 'You have a place')
        self.assertEqual(self.event.places_taken(), 1)

    def test_register_is_post_only(self):
        self.client.force_login(self.sai)
        response = self.client.get(
            url('register', self.event.pk)
        )
        self.assertEqual(response.status_code, 405)
        self.assertFalse(Registration.objects.exists())

    def test_two_posts_make_one_place(self):
        self.client.force_login(self.sai)
        address = url('register', self.event.pk)
        self.client.post(address)
        response = self.client.post(address, follow=True)
        self.assertContains(response,
                            'You already have a place.')
        self.assertEqual(self.event.places_taken(), 1)

    def test_a_full_event_shows_why(self):
        for email in ('raj@example.org', 'soni@example.org'):
            self.event.registrations.create(
                member=verified(email)
            )
        self.client.force_login(self.sai)
        page = self.client.get(self.event.get_absolute_url())
        self.assertContains(page, 'This event is full.')
        self.assertNotContains(page,
                               url('register', self.event.pk))
        response = self.client.post(
            url('register', self.event.pk), follow=True
        )
        self.assertContains(response, 'This event is full.')
        self.assertEqual(self.event.places_taken(), 2)

    def test_an_unconfirmed_member_is_sent_to_confirm(self):
        soni = User.objects.create_user(
            'soni@example.org', display_name='Soni'
        )
        self.client.force_login(soni)
        page = self.client.get(self.event.get_absolute_url())
        self.assertContains(
            page, 'Confirm your email address to register.'
        )
        self.assertContains(page, reverse('account_email'))
        self.client.post(url('register', self.event.pk))
        self.assertFalse(Registration.objects.exists())

    def test_a_hidden_draft_is_missing(self):
        draft = soon(status=Event.Status.DRAFT)
        self.client.force_login(self.sai)
        response = self.client.post(url('register', draft.pk))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Registration.objects.exists())


class PhonePageTests(TestCase):
    """An event that asks for a phone number."""

    @classmethod
    def setUpTestData(cls):
        cls.event = soon(phone_required=True)
        cls.sai = verified('sai@example.org')

    def setUp(self):
        self.client.force_login(self.sai)

    def test_the_page_asks_for_the_number(self):
        page = self.client.get(self.event.get_absolute_url())
        self.assertContains(
            page, f'href="{url("phone", self.event.pk)}"'
        )
        response = self.client.post(
            url('register', self.event.pk)
        )
        self.assertRedirects(response,
                             url('phone', self.event.pk))
        self.assertFalse(Registration.objects.exists())

    def test_a_bad_number_saves_nothing(self):
        response = self.client.post(
            url('phone', self.event.pk), {'phone': '12345'}
        )
        self.assertContains(response, 'Enter a valid phone')
        self.assertFalse(Registration.objects.exists())
        self.assertFalse(Profile.objects.exists())

    def test_the_number_is_kept_and_the_place_made(self):
        response = self.client.post(
            url('phone', self.event.pk),
            {'phone': '98765 43210'},
        )
        self.assertRedirects(response,
                             self.event.get_absolute_url(),
                             fetch_redirect_response=False)
        self.assertEqual(Profile.of(self.sai).phone,
                         '+919876543210')
        self.assertEqual(self.event.places_taken(), 1)


class MyRegistrationsTests(TestCase):
    """A member's own places, and only theirs."""

    @classmethod
    def setUpTestData(cls):
        cls.event = soon()
        cls.sai = verified('sai@example.org')
        cls.raj = verified('raj@example.org')
        now = timezone.now()
        cls.sais = cls.event.register(cls.sai, now)
        cls.rajs = cls.event.register(cls.raj, now)

    def test_the_page_lists_upcoming_places(self):
        self.client.force_login(self.sai)
        response = self.client.get(url('mine'))
        self.assertContains(response, 'Django clinic')
        self.assertContains(response,
                            url('cancel', self.sais.pk))
        self.assertNotContains(response,
                               url('cancel', self.rajs.pk))

    def test_a_late_cancel_is_marked(self):
        self.client.force_login(self.raj)
        Event.objects.filter(pk=self.event.pk).update(
            cancellation_deadline=timezone.now()
        )
        response = self.client.post(
            url('cancel', self.rajs.pk), follow=True
        )
        self.assertContains(response, 'late cancellation')
        late = '<span class="badge">Cancelled late</span>'
        self.assertContains(response, late, html=True)

    def test_confirm_then_cancel(self):
        self.client.force_login(self.sai)
        address = url('cancel', self.sais.pk)
        page = self.client.get(address)
        self.assertContains(page, 'Cancel my place')
        self.assertEqual(self.event.places_taken(), 2)
        response = self.client.post(address)
        self.assertRedirects(response, url('mine'),
                             fetch_redirect_response=False)
        self.assertEqual(self.event.places_taken(), 1)
        again = self.client.post(address, follow=True)
        self.assertContains(again,
                            'This place was already cancelled.')
        self.assertEqual(self.event.places_taken(), 1)

    def test_someone_elses_place_is_missing(self):
        self.client.force_login(self.sai)
        address = url('cancel', self.rajs.pk)
        for response in (self.client.get(address),
                         self.client.post(address)):
            self.assertEqual(response.status_code, 404)
        self.rajs.refresh_from_db()
        self.assertEqual(self.rajs.status, 'active')
        refused = AuditEvent.objects.filter(
            action='cancel_registration', outcome='refused',
            actor=self.sai, target_id=self.rajs.pk,
        )
        self.assertEqual(refused.count(), 2)

    def test_the_page_refuses_after_the_start(self):
        past = timezone.now() - timedelta(minutes=5)
        Event.objects.filter(pk=self.event.pk).update(
            starts_at=past, registration_closes_at=past,
            cancellation_deadline=past,
        )
        self.client.force_login(self.sai)
        response = self.client.post(
            url('cancel', self.sais.pk), follow=True
        )
        self.assertContains(
            response, 'The event has started, so this place '
            'can no longer be cancelled.'
        )
        self.sais.refresh_from_db()
        self.assertEqual(self.sais.status, 'active')

    def test_a_repeated_cancel_is_information(self):
        self.client.force_login(self.sai)
        address = url('cancel', self.sais.pk)
        self.client.post(address, follow=True)
        again = self.client.post(address, follow=True)
        self.assertContains(again, 'alert-info')
        self.assertNotContains(again, 'alert-success')

    def test_a_visitor_is_sent_to_sign_in(self):
        response = self.client.get(url('mine'))
        self.assertRedirects(
            response,
            f"{reverse('account_login')}?next={url('mine')}",
            fetch_redirect_response=False,
        )


class AttendeeListTests(TestCase):
    """Sam's attendee list: who has a place, and contacts."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = in_group('sam@example.org', ORGANIZERS)
        cls.event = soon()
        cls.event.add_organizer(cls.sam)
        cls.sai = verified('sai@example.org')
        Profile.objects.create(user=cls.sai,
                               phone='+919876543210')
        cls.event.register(cls.sai, timezone.now())

    def test_the_list_shows_contacts_and_counts(self):
        raj = verified('raj@example.org')
        self.event.register(raj, timezone.now()).cancel(
            timezone.now()
        )
        self.client.force_login(self.sam)
        response = self.client.get(
            url('attendees', self.event.pk)
        )
        for text in ('Sai', 'sai@example.org',
                     '+91 98765 43210', 'Cancellations: 1',
                     'late: 0'):
            self.assertContains(response, text)
        self.assertNotContains(response, 'raj@example.org')

    def test_a_fixed_number_of_queries(self):
        self.client.force_login(self.sam)
        address = url('attendees', self.event.pk)
        with CaptureQueriesContext(connection) as one:
            self.client.get(address)
        for email in ('raj@example.org', 'soni@example.org'):
            self.event.registrations.create(
                member=verified(email)
            )
        with CaptureQueriesContext(connection) as three:
            self.client.get(address)
        self.assertEqual(len(three), len(one))

    def test_contacts_stay_off_the_event_page(self):
        soni = verified('soni@example.org')
        self.client.force_login(soni)
        page = self.client.get(self.event.get_absolute_url())
        self.assertNotContains(page, 'sai@example.org')
        self.assertNotContains(page, 'Attendee list')
        self.client.force_login(self.sam)
        page = self.client.get(self.event.get_absolute_url())
        self.assertContains(page, 'Attendee list')


# Who may open the attendee list (Chapter 31).
ATTENDEE_MATRIX = [
    # person, Sam's published event, Sam's draft
    ('visitor', 'sign in', 'sign in'),
    ('member', '403', '404'),
    ('staff only', '403', '404'),
    ('other organizer', '403', '404'),
    ('administrator', 'ok', 'ok'),
    ('superuser', 'ok', 'ok'),
    ('organizer', 'ok', 'ok'),
]


class AttendeeMatrixTests(TestCase):
    """Each person against the attendee list."""

    @classmethod
    def setUpTestData(cls):
        sam = in_group('sam@example.org', ORGANIZERS)
        raj = in_group('raj@example.org', ORGANIZERS)
        cls.events = [soon(), soon(status='draft')]
        for event in cls.events:
            event.add_organizer(sam)
        soon(title='Delhi clinic').add_organizer(raj)
        cls.people = {
            'visitor': None,
            'member': verified('sai@example.org'),
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

    def test_every_row(self):
        for person, *expected in ATTENDEE_MATRIX:
            self.client.logout()
            if self.people[person]:
                self.client.force_login(self.people[person])
            with self.subTest(person=person):
                answers = [outcome(self.client.get(
                    url('attendees', event.pk)))
                    for event in self.events]
                self.assertEqual(answers, expected)

    def test_refusals_are_recorded(self):
        raj = self.people['other organizer']
        self.client.force_login(raj)
        for event in self.events:
            self.client.get(url('attendees', event.pk))
        refused = AuditEvent.objects.filter(
            action='view_attendees', outcome='refused',
            actor=raj,
        )
        self.assertEqual(refused.count(), 2)


def at_once(*actions):
    """Run each action in its own thread; return outcomes.

    An outcome is what the action returned, or the codes
    of the ValidationError it raised. Each thread has its
    own database connection, closed at the end, as two
    requests would.
    """
    outcomes = [None] * len(actions)

    def run(n, action):
        try:
            outcomes[n] = action()
        except ValidationError as error:
            outcomes[n] = [e.code for e in error.error_list]
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(n, act))
               for n, act in enumerate(actions)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


@contextmanager
def meet_after_counting(timeout=2):
    """Make each request wait, after counting, for the other.

    Without a lock both count before either inserts, so
    the race happens every time. With the lock the other
    request is still waiting for the event row, so the
    meeting times out and the requests take turns. The
    lock's time limit is raised meanwhile: on a busy
    machine the wait for the row can pass 3 s, and these
    tests are about turns, not "busy".
    """
    barrier = threading.Barrier(2, timeout=timeout)
    count = Event.places_taken

    def counted(event):
        taken = count(event)
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return taken

    with mock.patch.object(Event, 'places_taken', counted):
        with mock.patch('events.models.LOCK_TIMEOUT', '30s'):
            yield


def organizer(event):
    """Create Sam, who may edit event, without any group.

    TransactionTestCase empties every table after a test,
    including the groups Chapter 30's migration made, so
    the permission is given to Sam directly.
    """
    sam = User.objects.create_user('sam@example.org',
                                   display_name='Sam')
    sam.user_permissions.add(
        Permission.objects.get(codename='change_event')
    )
    OrganizerAssignment.objects.create(event=event,
                                       member=sam)
    return sam


@skipUnlessDBFeature('has_select_for_update')
class RaceTests(TransactionTestCase):
    """Requests for one event at the same moment.

    PostgreSQL only. Each test commits its rows, so other
    threads see them, and the tables are emptied after it.
    """

    def setUp(self):
        self.event = soon(capacity=1)
        self.now = timezone.now()

    def register(self, member):
        """Return an action that registers, as a request does."""
        def action():
            event = Event.objects.get(pk=self.event.pk)
            event.register(member, self.now)
            return 'place'
        return action

    def test_the_last_place_goes_to_one_member(self):
        sai = verified('sai@example.org')
        raj = verified('raj@example.org')
        with meet_after_counting():
            outcomes = at_once(self.register(sai),
                               self.register(raj))
        self.assertCountEqual(outcomes, ['place', ['full']])
        self.assertEqual(self.event.places_taken(), 1)

    def test_the_same_member_twice_gets_one_place(self):
        Event.objects.filter(pk=self.event.pk).update(
            capacity=5
        )
        sai = verified('sai@example.org')
        with meet_after_counting():
            outcomes = at_once(self.register(sai),
                               self.register(sai))
        self.assertCountEqual(
            outcomes, ['place', ['already_registered']]
        )
        self.assertEqual(self.event.places_taken(), 1)

    def test_busy_while_another_request_holds_it(self):
        sai = verified('sai@example.org')
        held, finished = threading.Event(), threading.Event()

        def hold():
            with transaction.atomic():
                Event.objects.select_for_update().get(
                    pk=self.event.pk
                )
                held.set()
                finished.wait(5)

        def try_to_register():
            held.wait(5)
            try:
                return self.register(sai)()
            finally:
                finished.set()

        with mock.patch('events.models.LOCK_TIMEOUT',
                        '100ms', create=True):
            outcomes = at_once(hold, try_to_register)
        self.assertEqual(outcomes[1], ['busy'])
        self.assertEqual(self.event.places_taken(), 0)

    def test_capacity_edit_counts_a_place_being_made(self):
        Event.objects.filter(pk=self.event.pk).update(
            capacity=2
        )
        verified('raj@example.org').registrations.create(
            event=self.event, registered_at=self.now
        )
        sam = organizer(self.event)
        sai = verified('sai@example.org')

        def lower_capacity():
            client = self.client_class()
            client.force_login(sam)
            event = Event.objects.get(pk=self.event.pk)
            return client.post(
                reverse('events:edit', args=[event.pk]),
                as_sent(event, capacity='1'),
            ).status_code

        # The edit's capacity floor counts too, so it meets
        # the registration right after both have counted.
        with meet_after_counting():
            at_once(self.register(sai), lower_capacity)
        self.event.refresh_from_db()
        # Either order is fair: Sai's place, then the edit
        # refused; or the edit, then "full". Never both.
        self.assertLessEqual(self.event.places_taken(),
                             self.event.capacity)

    def test_a_cancel_during_a_request_only_refuses(self):
        raj = verified('raj@example.org')
        rajs = self.event.register(raj, self.now)
        sai = verified('sai@example.org')
        meet = threading.Barrier(2, timeout=5)
        count = Event.places_taken

        def counted(event):
            taken = count(event)
            meet.wait()  # Sai's request has counted...
            meet.wait()  # ...and Raj's cancel is saved.
            return taken

        def cancel():
            meet.wait()
            place = Registration.objects.get(pk=rajs.pk)
            done = place.cancel(self.now)
            meet.wait()
            return done

        with mock.patch.object(Event, 'places_taken',
                               counted):
            outcomes = at_once(cancel, self.register(sai))
        # Sai counted Raj's place, so she is told "full",
        # although it is free a moment later. A refusal,
        # never a place too many (PR-3).
        self.assertEqual(outcomes, [True, ['full']])
        self.assertEqual(self.event.places_taken(), 0)


class StaleCopyTests(TestCase):
    """Actions read the event again, not the page's copy."""

    def setUp(self):
        self.event = soon()
        # The copy a view loaded before someone else acted.
        self.copy = Event.objects.get(pk=self.event.pk)

    def test_register_sees_a_cancel_made_since(self):
        Event.objects.get(pk=self.event.pk).cancel()
        with self.assertRaises(ValidationError) as caught:
            self.copy.register(verified('sai@example.org'),
                               timezone.now())
        self.assertEqual(
            [e.code for e in caught.exception.error_list],
            ['not_published'],
        )

    def test_cancel_sees_a_cancel_made_since(self):
        Event.objects.get(pk=self.event.pk).cancel()
        with self.assertRaises(ValidationError):
            self.copy.cancel()

    def test_publish_sees_a_publish_made_since(self):
        Event.objects.filter(pk=self.event.pk).update(
            status=Event.Status.DRAFT, description='Notes.'
        )
        organizer(self.event)
        draft = Event.objects.get(pk=self.event.pk)
        Event.objects.get(pk=self.event.pk).publish()
        with self.assertRaises(ValidationError):
            draft.publish()
