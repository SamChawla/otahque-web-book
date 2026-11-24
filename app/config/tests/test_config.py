"""Tests that cover the whole project."""
from io import StringIO

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from audit.models import AuditEvent
from events.models import (
    ORGANIZERS, Event, OrganizerAssignment,
)
from config.helpers import (
    admin_url, event_form, remove_selected, save_event,
)

PASSWORD = 'correct horse battery'


class MigrationTests(TestCase):
    """Every model change has a migration."""

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
    """Who may enter the admin, and what staff may do."""

    @classmethod
    def setUpTestData(cls):
        cls.event = save_event()

    def sign_in(self, email, **flags):
        """Create a member and sign in on allauth's page."""
        # Chapter 29: staff sign in on allauth's page.
        User.objects.create_user(
            email, PASSWORD, display_name='Test', **flags
        )
        return self.client.post(
            reverse('account_login'),
            {'login': email, 'password': PASSWORD},
        )

    def staff(self):
        """Create a staff member with no permissions."""
        return User.objects.create_user(
            'helper@example.org', display_name='Helper',
            is_staff=True,
        )

    def test_visitor_is_sent_to_sign_in(self):
        index = reverse('admin:index')
        self.assertRedirects(
            self.client.get(index),
            f"{reverse('admin:login')}?next={index}",
            fetch_redirect_response=False,
        )
        self.assertRedirects(
            self.client.get(index, follow=True),
            f"{reverse('account_login')}?next={index}",
        )

    def test_member_is_refused(self):
        self.sign_in('raj@example.org')
        response = self.client.get(reverse('admin:login'))
        self.assertEqual(response.status_code, 403)

    def test_inactive_staff_is_refused(self):
        self.sign_in(
            'old@example.org', is_staff=True,
            is_active=False,
        )
        self.assertNotIn(
            '_auth_user_id', self.client.session)
        response = self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code, 302)

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
    """Admin saves are logged; the log is read-only."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = User.objects.create_superuser(
            'sam@example.org', display_name='Sam'
        )
        cls.event = save_event()
        cls.assignment = OrganizerAssignment.objects.create(
            event=cls.event, member=cls.sam
        )
        # Chapter 30: the last organizer cannot be removed.
        OrganizerAssignment.objects.create(
            event=cls.event,
            member=User.objects.create_user(
                'raj@example.org', display_name='Raj'
            ),
        )

    def setUp(self):
        self.client.force_login(self.sam)

    def edit_location(self):
        """Change the event's location through the admin."""
        self.client.post(
            admin_url(Event, 'change', self.event.pk),
            event_form(self.event, location='Room 2'),
        )

    def test_admin_changes_are_logged(self):
        self.edit_location()
        remove_selected(self.client, self.assignment)
        self.assertEqual(
            [(entry.user, entry.action_flag,
              entry.get_change_message())
             for entry in LogEntry.objects.order_by('id')],
            [(self.sam, CHANGE, 'Changed Location.'),
             (self.sam, CHANGE, 'Removed.')],
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


class AdministratorAdminTests(TestCase):
    """What an administrator may do in the admin."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            'admin@example.org', display_name='Admin',
            is_staff=True,
        )
        cls.admin.groups.add(
            Group.objects.get(name='Administrators')
        )
        cls.soni = User.objects.create_user(
            'soni@example.org', display_name='Soni'
        )
        cls.event = save_event()

    def setUp(self):
        self.client.force_login(self.admin)

    def trail(self):
        """List the audit rows so far: action and outcome."""
        return list(AuditEvent.objects.order_by('id')
                    .values_list('action', 'outcome'))

    def save_soni(self, *groups, **fields):
        """Save Soni's admin page with these groups."""
        return self.client.post(
            admin_url(User, 'change', self.soni.pk),
            {'email': self.soni.email,
             'display_name': 'Soni', 'is_active': 'on',
             'groups': [Group.objects.get(name=name).pk
                        for name in groups]} | fields,
        )

    def test_organizers_membership_is_recorded(self):
        self.save_soni(ORGANIZERS)
        self.save_soni()
        self.assertEqual(self.trail(), [
            ('join_organizers', 'allowed'),
            ('leave_organizers', 'allowed'),
        ])

    def test_an_administrator_cannot_promote_anyone(self):
        response = self.save_soni('Administrators')
        self.assertContains(
            response,
            'Only the Organizers group can be changed here.',
        )
        perm = Permission.objects.get(codename='add_event')
        self.save_soni(is_staff='on', user_permissions=[
            perm.pk])
        self.soni.refresh_from_db()
        self.assertFalse(self.soni.is_staff)
        self.assertFalse(self.soni.user_permissions.exists())

    def test_adds_only_organizers_and_keeps_the_last(self):
        add = admin_url(OrganizerAssignment, 'add')
        form = {'event': self.event.pk,
                'member': self.soni.pk}
        self.assertContains(
            self.client.post(add, form),
            'Only members of the Organizers group',
        )
        self.save_soni(ORGANIZERS)
        self.client.post(add, form)
        place = OrganizerAssignment.objects.get()
        response = remove_selected(self.client, place)
        self.assertContains(
            response, 'Assign another organizer before '
                      'removing the last one.',
        )
        self.assertEqual(self.trail(), [
            ('add_organizer', 'refused'),
            ('join_organizers', 'allowed'),
            ('add_organizer', 'allowed'),
            ('remove_organizer', 'refused'),
        ])

    def test_removal_is_an_action_not_a_typed_date(self):
        place = OrganizerAssignment.objects.create(
            event=self.event, member=self.soni
        )
        page = self.client.get(admin_url(
            OrganizerAssignment, 'change', place.pk
        ))
        self.assertNotContains(page, 'name="revoked_at_0"')
        listing = self.client.get(
            admin_url(OrganizerAssignment, 'changelist')
        )
        self.assertContains(listing,
                            'Remove selected organizers')


class WidgetClassTests(TestCase):
    """Otahque's widget classes keep the admin's own."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = User.objects.create_superuser(
            'sam@example.org', display_name='Sam'
        )
        cls.event = save_event()

    def setUp(self):
        self.client.force_login(self.sam)

    def test_the_pickers_keep_selectfilter(self):
        response = self.client.get(
            admin_url(User, 'change', self.sam.pk)
        )
        self.assertContains(
            response, 'class="select w-full selectfilter"',
            count=2,
        )

    def test_event_times_keep_their_shortcuts(self):
        response = self.client.get(
            admin_url(Event, 'change', self.event.pk)
        )
        for name in ('vDateField', 'vTimeField'):
            self.assertContains(
                response, f'class="input w-full {name}"',
                count=5,
            )
