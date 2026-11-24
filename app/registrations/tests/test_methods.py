"""How Register and the details page answer every method.

Written before the details page became a class (Chapter
35). Register stays a function; its table pins it for the
chapters that change how sign-in works (37 and 39).
"""
from django.test import TestCase

from config.helpers import answers
from events.models import Event

from .test_registrations import soon, url, verified

# A method, then the answer signed out and the answer
# signed in as a member with no phone number yet.
DETAILS = [
    ('GET', 'sign in', 'ok'),
    ('HEAD', '405 GET, POST', '405 GET, POST'),
    ('POST', 'sign in', 'ok'),
    ('PUT', '405 GET, POST', '405 GET, POST'),
    ('PATCH', '405 GET, POST', '405 GET, POST'),
    ('DELETE', '405 GET, POST', '405 GET, POST'),
    ('OPTIONS', '405 GET, POST', '405 GET, POST'),
    ('TRACE', '405 GET, POST', '405 GET, POST'),
]
DETAILS_HIDDEN = [
    ('GET', 'sign in', '404 recorded'),
    ('POST', 'sign in', '404 recorded'),
    ('PUT', '405 GET, POST', '405 GET, POST'),
]
REGISTER = [
    ('GET', '405 POST', '405 POST'),
    ('HEAD', '405 POST', '405 POST'),
    ('POST', 'sign in', 'ok'),
    ('PUT', '405 POST', '405 POST'),
    ('OPTIONS', '405 POST', '405 POST'),
]


class MethodTableTests(TestCase):
    """Each page's answer to each method, pinned."""

    @classmethod
    def setUpTestData(cls):
        cls.event = soon(phone_required=True)
        cls.draft = soon(phone_required=True,
                         status=Event.Status.DRAFT)
        cls.open = soon()
        cls.sai = verified('sai@example.org')

    def check(self, path, table):
        """Compare the page's answers with each row."""
        for method, signed_out, signed_in in table:
            with self.subTest(method):
                self.assertEqual(
                    answers(path, self.sai, method),
                    (signed_out, signed_in),
                )

    def test_the_details_page(self):
        self.check(url('phone', self.event.pk), DETAILS)

    def test_the_details_page_of_a_hidden_draft(self):
        self.check(url('phone', self.draft.pk),
                   DETAILS_HIDDEN)

    def test_register(self):
        self.check(url('register', self.open.pk), REGISTER)
