"""The event lock's other answers (found with coverage)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import OperationalError
from django.test import TestCase
from django.urls import reverse
from psycopg import errors

from config.helpers import as_sent, save_event
from events.models import Event, OrganizerAssignment, refusal

User = get_user_model()


def database_error(sqlstate):
    """Return Django's error for a psycopg one with sqlstate."""
    error = OperationalError('the row could not be locked')
    error.__cause__ = errors.lookup(sqlstate)()
    return error


class LockErrorTests(TestCase):
    """locked() calls only a lock timeout "busy"."""

    def setUp(self):
        self.event = save_event()

    def lock_fails_with(self, sqlstate):
        """Make the row lock fail with that database code."""
        rows = mock.Mock()
        rows.get.side_effect = database_error(sqlstate)
        return mock.patch.object(
            Event.objects, 'select_for_update',
            return_value=rows,
        )

    def test_a_lock_timeout_is_busy(self):
        with self.lock_fails_with('55P03'):
            with self.assertRaises(ValidationError) as caught:
                self.event.locked()
        self.assertEqual(caught.exception.error_list[0].code,
                         'busy')

    def test_any_other_database_error_is_raised(self):
        # 53100 is PostgreSQL's "disk full".
        with self.lock_fails_with('53100'):
            with self.assertRaises(OperationalError):
                self.event.locked()


class BusyEditTests(TestCase):
    """The edit page while another request holds the row."""

    def test_a_busy_edit_says_so_and_saves_nothing(self):
        event = save_event()
        sam = User.objects.create_user('sam@example.org',
                                       display_name='Sam')
        sam.user_permissions.add(
            Permission.objects.get(codename='change_event')
        )
        OrganizerAssignment.objects.create(event=event,
                                           member=sam)
        self.client.force_login(sam)
        busy = refusal(['busy'])
        with mock.patch.object(Event, 'locked',
                               side_effect=busy):
            response = self.client.post(
                reverse('events:edit', args=[event.pk]),
                as_sent(event, location='Room 2'),
            )
        self.assertContains(
            response, 'Otahque is busy. Please try again.'
        )
        event.refresh_from_db()
        self.assertEqual(event.location,
                         'Leeds Central Library')
