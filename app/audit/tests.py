"""Tests for the audit app."""
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from .models import AuditEvent, record

Action = AuditEvent.Action


class AuditEventTests(TestCase):
    """Audit rows: what they hold, and that they stay."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = User.objects.create_superuser(
            'sam@example.org', display_name='Sam'
        )

    def test_a_row_names_actor_action_and_target(self):
        row = record(self.sam, Action.JOIN_ORGANIZERS,
                     self.sam, note='by hand')
        self.assertEqual(
            (row.actor, row.action, row.outcome,
             row.target_type, row.target_id, row.detail),
            (self.sam, 'join_organizers', 'allowed',
             'user', self.sam.pk, {'note': 'by hand'}),
        )

    def test_visitors_and_scripts_have_no_actor(self):
        for actor in (AnonymousUser(), None):
            with self.subTest(actor=actor):
                row = record(actor, Action.VIEW_EVENT)
                self.assertIsNone(row.actor)
                self.assertEqual(row.target_type, '')

    def test_outcome_is_allowed_or_refused(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AuditEvent.objects.create(
                    action=Action.VIEW_EVENT,
                    outcome='maybe',
                )

    def test_the_admin_page_is_view_only(self):
        row = record(self.sam, Action.VIEW_EVENT)
        self.client.force_login(self.sam)
        name = 'admin:audit_auditevent'
        listing = self.client.get(
            reverse(f'{name}_changelist')
        )
        self.assertContains(listing, 'View an event')
        add = self.client.get(reverse(f'{name}_add'))
        self.assertEqual(add.status_code, 403)
        change = reverse(f'{name}_change', args=[row.pk])
        self.assertNotContains(self.client.get(change),
                               'name="_save"')
        delete = reverse(f'{name}_delete', args=[row.pk])
        response = self.client.post(delete, {'post': 'yes'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(AuditEvent.objects.count(), 1)
