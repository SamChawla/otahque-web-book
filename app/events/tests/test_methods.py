"""How the event page answers every HTTP method.

Written before the page became a class (Chapter 35), so
that any change in its answers fails a test.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from config.helpers import answers, save_event
from events.models import Event

User = get_user_model()

# A method, then the answer signed out and the answer
# signed in as a member who organizes nothing. Since
# Chapter 35, Django refuses methods the page does not
# handle, and answers OPTIONS itself (D35.4).
ALLOW = 'GET, HEAD, OPTIONS'
PUBLISHED = [
    ('GET', 'ok', 'ok'),
    ('HEAD', 'ok', 'ok'),
    ('POST', f'405 {ALLOW}', f'405 {ALLOW}'),
    ('PUT', f'405 {ALLOW}', f'405 {ALLOW}'),
    ('PATCH', f'405 {ALLOW}', f'405 {ALLOW}'),
    ('DELETE', f'405 {ALLOW}', f'405 {ALLOW}'),
    ('OPTIONS', f'ok {ALLOW}', f'ok {ALLOW}'),
    ('TRACE', f'405 {ALLOW}', f'405 {ALLOW}'),
]
HIDDEN = [
    ('GET', '404', '404 recorded'),
    ('HEAD', '404', '404 recorded'),
    ('POST', f'405 {ALLOW}', f'405 {ALLOW}'),
    ('PUT', f'405 {ALLOW}', f'405 {ALLOW}'),
    ('OPTIONS', f'ok {ALLOW}', f'ok {ALLOW}'),
]


class EventPageMethodTests(TestCase):
    """The event page's answer to each method, pinned."""

    @classmethod
    def setUpTestData(cls):
        cls.event = save_event()
        cls.draft = save_event(status=Event.Status.DRAFT)
        cls.sai = User.objects.create_user(
            'sai@example.org', display_name='Sai'
        )

    def check(self, event, table):
        """Compare the page's answers with each row."""
        path = event.get_absolute_url()
        for method, signed_out, signed_in in table:
            with self.subTest(method):
                self.assertEqual(
                    answers(path, self.sai, method),
                    (signed_out, signed_in),
                )

    def test_a_published_event(self):
        self.check(self.event, PUBLISHED)

    def test_a_hidden_draft(self):
        self.check(self.draft, HIDDEN)
