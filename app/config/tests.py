from datetime import timedelta
from io import StringIO

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from events.models import Event, OrganizerAssignment
from events.tests import (
    admin_url, event_form, revoke_form, save_event,
)

PASSWORD = 'correct horse battery'
REFUSED = (
    'Please enter the correct email address and password '
    'for a staff account.'
)


class MigrationTests(TestCase):
    def test_every_model_change_has_a_migration(self):
        output = StringIO()
        try:
            call_command(
                'makemigrations', '--check', '--dry-run',
                stdout=output,
            )
        except SystemExit:
            self.fail(
                'Missing migrations:\n' + output.getvalue()
            )


class AdminAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.event = save_event()

    def sign_in(self, email, **flags):
        User.objects.create_user(
            email, PASSWORD, display_name='Test', **flags
        )
        return self.client.post(
            reverse('admin:login'),
            {'username': email, 'password': PASSWORD},
        )

    def staff(self):
        return User.objects.create_user(
            'helper@example.org', display_name='Helper',
            is_staff=True,
        )

    def test_visitor_is_sent_to_sign_in(self):
        index = reverse('admin:index')
        self.assertRedirects(
            self.client.get(index),
            f"{reverse('admin:login')}?next={index}",
        )

    def test_member_is_refused(self):
        response = self.sign_in('raj@example.org')
        self.assertContains(response, REFUSED)

    def test_inactive_staff_is_refused(self):
        response = self.sign_in(
            'old@example.org', is_staff=True,
            is_active=False,
        )
        self.assertContains(response, REFUSED)

    def test_staff_flag_alone_grants_nothing(self):
        helper = self.staff()
        self.client.force_login(helper)
        response = self.client.get(reverse('admin:index'))
        self.assertContains(
            response, 'permission to view or edit anything'
        )
        response = self.client.get(
            admin_url(Event, 'changelist')
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            helper.organizer_assignments.exists()
        )

    def test_view_permission_has_no_save(self):
        helper = self.staff()
        helper.user_permissions.add(
            Permission.objects.get(codename='view_event')
        )
        self.client.force_login(helper)
        url = admin_url(Event, 'change', self.event.pk)
        response = self.client.get(url)
        self.assertContains(response, 'Python meetup')
        self.assertNotContains(response, 'name="_save"')
        response = self.client.post(url, {'capacity': 1})
        self.assertEqual(response.status_code, 403)


class AuditLogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sam = User.objects.create_superuser(
            'sam@example.org', display_name='Sam'
        )
        cls.event = save_event()
        cls.assignment = OrganizerAssignment.objects.create(
            event=cls.event, member=cls.sam
        )

    def setUp(self):
        self.client.force_login(self.sam)

    def edit_location(self):
        self.client.post(
            admin_url(Event, 'change', self.event.pk),
            event_form(self.event, location='Room 2'),
        )

    def test_admin_changes_are_logged(self):
        self.edit_location()
        tomorrow = timezone.now() + timedelta(days=1)
        self.client.post(
            admin_url(OrganizerAssignment, 'change',
                      self.assignment.pk),
            revoke_form(tomorrow),
        )
        self.assertEqual(
            [(entry.user, entry.action_flag,
              entry.get_change_message())
             for entry in LogEntry.objects.order_by('id')],
            [(self.sam, CHANGE, 'Changed Location.'),
             (self.sam, CHANGE, 'Changed Revoked at.')],
        )

    def test_log_cannot_be_edited(self):
        self.edit_location()
        entry = LogEntry.objects.get()
        add = self.client.get(admin_url(LogEntry, 'add'))
        self.assertEqual(add.status_code, 403)
        change = admin_url(LogEntry, 'change', entry.pk)
        response = self.client.get(change)
        self.assertContains(response, 'Python meetup')
        self.assertNotContains(response, 'name="_save"')
        self.assertEqual(
            self.client.post(change, {}).status_code, 403
        )
        response = self.client.post(
            admin_url(LogEntry, 'delete', entry.pk),
            {'post': 'yes'},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(LogEntry.objects.count(), 1)
