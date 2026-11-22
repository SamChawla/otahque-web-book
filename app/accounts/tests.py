"""Tests for the accounts app."""
import base64
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from allauth.account.models import EmailAddress
from allauth.core.context import request_context
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal import auth as totp
from allauth.socialaccount.adapter import (
    get_adapter as get_social_adapter,
)
from allauth.socialaccount.helpers import (
    complete_social_login,
)
from allauth.socialaccount.models import (
    SocialAccount, SocialLogin,
)
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.contrib.auth.password_validation import (
    validate_password,
)
from django.contrib.auth.tokens import (
    PasswordResetTokenGenerator,
)
from django.contrib.messages.storage.fallback import (
    FallbackStorage,
)
from django.contrib.sessions.backends.db import SessionStore
from django.core import mail, signing
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import (
    Client, RequestFactory, SimpleTestCase, TestCase,
    override_settings,
)
from django.urls import reverse

from events.models import Event
from events.tests import admin_url, event_form, save_event
from .adapter import DISPOSABLE
from .models import Profile, User
from .timezones import (
    COOKIE, resolve_timezone, to_user_time,
)


class UserModelTests(SimpleTestCase):
    """The custom user: email, password hash, required fields."""

    def test_user_model_is_accounts_user(self):
        self.assertIs(get_user_model(), User)
        self.assertEqual(User.USERNAME_FIELD, 'email')

    def test_password_is_stored_as_a_hash(self):
        user = User(email='sai@example.org',
                    display_name='Sai')
        user.set_password('correct horse')
        self.assertNotEqual(user.password, 'correct horse')
        self.assertTrue(
            user.password.startswith('pbkdf2_sha256$')
        )
        self.assertTrue(user.check_password('correct horse'))
        self.assertFalse(user.check_password('wrong horse'))

    def test_email_and_display_name_are_required(self):
        user = User()
        user.set_password('correct horse')
        with self.assertRaises(ValidationError) as caught:
            user.full_clean(validate_unique=False)
        self.assertEqual(
            sorted(caught.exception.message_dict),
            ['display_name', 'email'],
        )


class UserManagerTests(SimpleTestCase):
    """The manager's rules for members and superusers."""

    def test_create_user_requires_an_email(self):
        with self.assertRaisesMessage(
            ValueError, 'An email address is required.'
        ):
            User.objects.create_user(
                email='', password='correct horse',
                display_name='Sai',
            )

    def test_superuser_flags_must_be_true(self):
        with self.assertRaisesMessage(
            ValueError, 'needs is_superuser=True.'
        ):
            User.objects.create_superuser(
                email='sam@example.org',
                password='correct horse',
                display_name='Sam',
                is_superuser=False,
            )


class UserCreationTests(TestCase):
    """Members saved through the manager, in the database."""

    def test_create_user_saves_a_member(self):
        user = User.objects.create_user(
            email='Sai@EXAMPLE.org',
            password='correct horse',
            display_name='Sai',
        )
        saved = User.objects.get(pk=user.pk)
        self.assertEqual(saved.email, 'sai@example.org')
        self.assertTrue(
            saved.check_password('correct horse')
        )
        self.assertTrue(saved.is_active)
        self.assertFalse(saved.is_staff)
        self.assertFalse(saved.is_superuser)

    def test_create_superuser_saves_both_flags(self):
        user = User.objects.create_superuser(
            email='sam@example.org',
            password='correct horse',
            display_name='Sam',
        )
        saved = User.objects.get(pk=user.pk)
        self.assertTrue(saved.is_staff)
        self.assertTrue(saved.is_superuser)

    def test_email_is_unique_in_the_database(self):
        User.objects.create_user(
            email='raj@example.org',
            password='correct horse',
            display_name='Raj',
        )
        with self.assertRaises(IntegrityError):
            User.objects.create_user(
                email='raj@example.org',
                password='another horse',
                display_name='Raj K.',
            )

    def test_email_differing_in_case_is_refused(self):
        User.objects.create_user(
            'sai@example.org', display_name='Sai'
        )
        with self.assertRaises(IntegrityError):
            User.objects.create_user(
                'SAI@example.org', display_name='Sai'
            )

    def test_upper_case_email_cannot_be_saved(self):
        user = User(
            email='Sai@example.org', display_name='Sai'
        )
        with self.assertRaises(IntegrityError):
            user.save()

    def test_full_clean_lower_cases_the_email(self):
        user = User(
            email='Sai@Example.ORG', display_name='Sai'
        )
        user.set_unusable_password()
        user.full_clean()
        self.assertEqual(user.email, 'sai@example.org')

    def test_sign_in_lookup_ignores_case(self):
        sai = User.objects.create_user(
            'sai@example.org', display_name='Sai'
        )
        found = User.objects.get_by_natural_key(
            'SAI@Example.org'
        )
        self.assertEqual(found, sai)


class UserAdminTests(TestCase):
    """No adding or deleting; passwords stay hidden."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = User.objects.create_superuser(
            'sam@example.org', display_name='Sam'
        )
        cls.sai = User.objects.create_user(
            'sai@example.org', 'correct horse battery',
            display_name='Sai',
        )

    def setUp(self):
        self.client.force_login(self.sam)
        self.url = admin_url(User, 'change', self.sai.pk)

    def test_no_add_and_no_delete(self):
        add = self.client.get(admin_url(User, 'add'))
        self.assertEqual(add.status_code, 403)
        response = self.client.post(
            admin_url(User, 'delete', self.sai.pk),
            {'post': 'yes'},
        )
        self.assertEqual(response.status_code, 403)

    def test_page_never_shows_or_sets_the_password(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'sai@example.org')
        self.assertNotContains(response, 'name="password"')
        self.assertNotContains(response, self.sai.password)
        self.assertNotContains(response, 'is_superuser')
        self.client.post(self.url, {
            'email': 'sai@example.org',
            'display_name': 'Sai K',
            'is_active': 'on',
        })
        self.sai.refresh_from_db()
        self.assertEqual(self.sai.display_name, 'Sai K')
        self.assertTrue(
            self.sai.check_password('correct horse battery')
        )


PASSWORD = 'a-long-safe-pass-123'


class ProfileTests(TestCase):
    """The profile page: your own name and time zone."""

    url = '/accounts/profile/'

    @classmethod
    def setUpTestData(cls):
        cls.sai = User.objects.create_user(
            'sai@example.org', PASSWORD, display_name='Sai'
        )

    def test_a_visitor_is_sent_to_sign_in(self):
        response = self.client.get(self.url)
        sign_in = reverse('account_login')
        self.assertRedirects(
            response, f'{sign_in}?next={self.url}',
            fetch_redirect_response=False,
        )

    def test_a_profile_is_made_the_first_time(self):
        self.assertFalse(Profile.objects.exists())
        self.client.force_login(self.sai)
        response = self.client.get(self.url)
        self.assertContains(response, 'value="Sai"')
        made = Profile.objects.get()
        self.assertEqual(made.user, self.sai)

    def test_name_and_zone_are_saved(self):
        self.client.force_login(self.sai)
        response = self.client.post(self.url, {
            'display_name': 'Sai K',
            'timezone': 'Europe/London',
        })
        self.assertRedirects(response, self.url,
                             fetch_redirect_response=False)
        self.sai.refresh_from_db()
        self.assertEqual(self.sai.display_name, 'Sai K')
        self.assertEqual(self.sai.profile.timezone,
                         'Europe/London')

    def test_an_unknown_zone_is_refused(self):
        self.client.force_login(self.sai)
        response = self.client.post(self.url, {
            'display_name': 'Sai', 'timezone': 'Mars/Base',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Profile.objects.filter(
            timezone='Mars/Base').exists())

    def test_crafted_fields_change_nothing(self):
        self.client.force_login(self.sai)
        self.client.post(self.url, {
            'display_name': 'Sai', 'timezone': '',
            'email': 'boss@example.org', 'is_staff': 'on',
            'user': '999',
        })
        self.sai.refresh_from_db()
        self.assertEqual(self.sai.email, 'sai@example.org')
        self.assertFalse(self.sai.is_staff)

    def test_profile_csrf_is_checked(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.sai)
        data = {'display_name': 'Forged', 'timezone': ''}
        refused = browser.post(self.url, data)
        self.assertEqual(refused.status_code, 403)
        page = browser.get(self.url)
        token = str(page.context['csrf_token'])
        sent = browser.post(
            self.url, data | {'csrfmiddlewaretoken': token}
        )
        self.assertEqual(sent.status_code, 302)


class SignInTests(TestCase):
    """Signing in with an email and password."""

    @classmethod
    def setUpTestData(cls):
        cls.sai = User.objects.create_user(
            'sai@example.org', PASSWORD, display_name='Sai'
        )

    def sign_in(self, email, password=PASSWORD):
        """Post the sign-in form for email."""
        return self.client.post('/accounts/login/', {
            'login': email, 'password': password,
        })

    def test_any_letter_case_signs_in(self):
        response = self.sign_in('Sai@EXAMPLE.org')
        self.assertRedirects(
            response, reverse('accounts:profile'),
            fetch_redirect_response=False,
        )

    def test_a_wrong_password_is_refused(self):
        response = self.sign_in('sai@example.org', 'wrong')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id',
                         self.client.session)

    def test_the_session_key_changes(self):
        self.client.get('/accounts/login/')
        session = self.client.session
        session['seen'] = True
        session.save()
        before = session.session_key
        self.sign_in('sai@example.org')
        self.assertNotEqual(self.client.session.session_key,
                            before)

    def test_sign_out_needs_a_post(self):
        self.client.force_login(self.sai)
        self.client.get('/accounts/logout/')
        self.assertIn('_auth_user_id', self.client.session)
        self.client.post('/accounts/logout/')
        self.assertNotIn('_auth_user_id',
                         self.client.session)


def signup_data(**changes):
    """Return what the sign-up page sends."""
    return {'email': 'sai@example.org',
            'display_name': 'Sai',
            'timezone': 'Asia/Kolkata',
            'password1': PASSWORD,
            'password2': PASSWORD} | changes


class SignUpTests(TestCase):
    """Signing up: what is asked, and what is saved."""

    url = '/accounts/signup/'

    def test_the_page_asks_for_name_and_zone(self):
        response = self.client.get(self.url)
        for name in ('email', 'display_name', 'timezone',
                     'password1', 'password2'):
            self.assertContains(response, f'name="{name}"')

    def test_sign_up_saves_name_zone_and_lower_case(self):
        response = self.client.post(
            self.url, signup_data(email='SAI@Example.ORG')
        )
        self.assertRedirects(
            response, reverse('accounts:profile'),
            fetch_redirect_response=False,
        )
        sai = User.objects.get()
        self.assertEqual(sai.email, 'sai@example.org')
        self.assertEqual(sai.display_name, 'Sai')
        self.assertEqual(sai.profile.timezone,
                         'Asia/Kolkata')
        self.assertTrue(sai.check_password(PASSWORD))

    def test_a_display_name_is_required(self):
        response = self.client.post(
            self.url, signup_data(display_name='')
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_a_confirmation_email_is_sent(self):
        self.client.post(self.url, signup_data())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to,
                         ['sai@example.org'])

    def test_an_address_in_use_is_refused(self):
        User.objects.create_user('sai@example.org',
                                 display_name='Sai')
        response = self.client.post(
            self.url, signup_data(email='Sai@example.org')
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 1)


class AddressCheckTests(TestCase):
    """Disposable email domains are refused."""

    url = '/accounts/signup/'

    def errors(self, email):
        """Return the sign-up page's errors for email."""
        response = self.client.post(
            self.url, signup_data(email=email)
        )
        return response.context['form'].errors.get('email')

    def test_an_invalid_address_is_refused(self):
        self.assertEqual(self.errors('not-an-email'),
                         ['Enter a valid email address.'])

    def test_a_disposable_address_is_refused(self):
        self.assertEqual(self.errors('raj@mailinator.com'),
                         [DISPOSABLE])
        self.assertFalse(User.objects.exists())

    @override_settings(
        EMAIL_DOMAINS_ALLOWED=['mailinator.com']
    )
    def test_an_allowed_domain_is_accepted(self):
        self.client.post(
            self.url, signup_data(email='raj@mailinator.com')
        )
        self.assertTrue(User.objects.exists())


PROVIDERS = {
    'google': {'APPS': [{'client_id': 'test-id',
                         'secret': 'test-secret'}]},
    'github': {'APPS': [{'client_id': 'test-id',
                         'secret': 'test-secret'}]},
}


def provider_sign_in(provider, email, uid='1'):
    """Sign in as if the provider confirmed this email.

    Returns the response and a client on that session.
    """
    request = RequestFactory().get('/')
    request.session = SessionStore()
    request.session.save()
    request._messages = FallbackStorage(request)
    request.user = AnonymousUser()
    found = get_social_adapter().get_provider(request,
                                              provider)
    login = SocialLogin(
        user=User(email=email),
        account=SocialAccount(provider=provider, uid=uid,
                              extra_data={'email': email}),
        email_addresses=[EmailAddress(
            email=email, verified=True, primary=True,
        )],
        provider=found,
    )
    with request_context(request):
        response = complete_social_login(request, login)
    request.session.save()
    browser = Client()
    key = request.session.session_key
    browser.cookies['sessionid'] = key
    return response, browser


@override_settings(SOCIALACCOUNT_PROVIDERS=PROVIDERS)
class SocialSignInTests(TestCase):
    """Signing in through a provider."""

    def test_buttons_for_configured_providers(self):
        response = self.client.get('/accounts/login/')
        for name in ('Google', 'GitHub'):
            self.assertContains(response, name)

    def test_a_new_member_still_gives_name_and_zone(self):
        response, browser = provider_sign_in(
            'google', 'soni@example.org'
        )
        self.assertEqual(response['Location'],
                         '/accounts/3rdparty/signup/')
        page = browser.get(response['Location'])
        self.assertContains(page, 'name="display_name"')
        browser.post(response['Location'], {
            'email': 'soni@example.org',
            'display_name': 'Soni', 'timezone': '',
        })
        soni = User.objects.get()
        self.assertEqual(soni.display_name, 'Soni')
        account = soni.socialaccount_set.get()
        self.assertEqual(account.provider, 'google')

    def test_a_registered_email_is_asked_to_sign_in(self):
        User.objects.create_user('sam@example.org', PASSWORD,
                                 display_name='Sam')
        response, browser = provider_sign_in(
            'github', 'sam@example.org'
        )
        page = browser.post(response['Location'], {
            'email': 'sam@example.org',
            'display_name': 'Sam', 'timezone': '',
        })
        self.assertContains(
            page, 'An account already exists with this email'
        )
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(SocialAccount.objects.exists())

    def test_a_signed_in_member_may_connect(self):
        sam = User.objects.create_user(
            'sam@example.org', PASSWORD, display_name='Sam'
        )
        self.client.force_login(sam)
        response = self.client.get('/accounts/3rdparty/')
        self.assertContains(response, 'GitHub')
        self.assertContains(response, 'Google')


def request_with(cookie=None, user=None):
    """Build a request as the middleware sees it."""
    request = RequestFactory().get('/')
    if cookie is not None:
        request.COOKIES[COOKIE] = cookie
    request.user = user or AnonymousUser()
    return request


class BrowserZoneTests(TestCase):
    """Which zone a viewer gets: profile, cookie, UTC."""

    def test_a_real_zone_is_used(self):
        zone = resolve_timezone(request_with('Asia/Kolkata'))
        self.assertEqual(zone, ZoneInfo('Asia/Kolkata'))

    def test_an_alias_is_a_real_zone(self):
        request = request_with('Asia/Calcutta')
        zone = resolve_timezone(request)
        self.assertEqual(str(zone), 'Asia/Calcutta')

    def test_anything_else_means_utc(self):
        for value in (None, '', 'Mars/Base',
                      '../../etc/passwd'):
            with self.subTest(value=value):
                zone = resolve_timezone(request_with(value))
                self.assertEqual(zone, ZoneInfo('UTC'))

    def test_the_profile_zone_comes_first(self):
        sai = User.objects.create_user(
            'sai@example.org', display_name='Sai'
        )
        Profile.objects.create(user=sai,
                               timezone='Europe/London')
        request = request_with('Asia/Kolkata', sai)
        self.assertEqual(resolve_timezone(request),
                         ZoneInfo('Europe/London'))

    def test_to_user_time(self):
        moment = datetime(2026, 12, 3, 12, 30, tzinfo=UTC)
        request = request_with('Asia/Kolkata')
        local = to_user_time(moment, request)
        self.assertEqual(f'{local:%H:%M %Z}', '18:00 IST')


class TimezoneMiddlewareTests(TestCase):
    """Pages in the viewer's zone; the admin in UTC."""

    @classmethod
    def setUpTestData(cls):
        cls.sam = User.objects.create_superuser(
            'sam@example.org', PASSWORD, display_name='Sam'
        )
        Profile.objects.create(user=cls.sam,
                               timezone='Asia/Kolkata')

    def setUp(self):
        self.client.force_login(self.sam)

    def test_it_runs_after_authentication(self):
        names = settings.MIDDLEWARE
        ours = 'accounts.middleware.TimezoneMiddleware'
        auth = ('django.contrib.auth.middleware.'
                'AuthenticationMiddleware')
        self.assertGreater(names.index(ours),
                           names.index(auth))

    def test_pages_use_the_profile_zone(self):
        page = self.client.get('/accounts/profile/')
        self.assertRegex(page.content.decode(),
                         r'shown to you in\s+Asia/Kolkata')

    def test_the_admin_stays_in_utc(self):
        event = save_event(
            starts_at=datetime(2026, 12, 3, 9, tzinfo=UTC),
            timezone='Asia/Kolkata',
        )
        url = admin_url(Event, 'change', event.pk)
        self.client.post(url, event_form(
            event, starts_at_1='15:00', ends_at_1='17:00',
        ))
        event.refresh_from_db()
        typed = datetime(2026, 12, 3, 15, tzinfo=UTC)
        self.assertEqual(event.starts_at, typed)


SALT = 'otahque.demo'


class SigningTests(SimpleTestCase):
    """Signed values: read, refused if changed, expire."""

    def test_a_signed_value_can_be_read(self):
        value = signing.dumps({'places_only': True},
                              salt=SALT)
        data = value.split(':')[0]
        data += '=' * (-len(data) % 4)
        self.assertEqual(base64.urlsafe_b64decode(data),
                         b'{"places_only":true}')

    def test_a_changed_value_is_refused(self):
        value = signing.dumps({'places_only': True},
                              salt=SALT)
        signature = value.split(':', 1)[1]
        forged = base64.urlsafe_b64encode(
            b'{"places_only":false}'
        ).decode().rstrip('=')
        with self.assertRaises(signing.BadSignature):
            signing.loads(f'{forged}:{signature}', salt=SALT)

    def test_an_old_value_expires(self):
        two_minutes_ago = time.time() - 120
        with mock.patch('time.time',
                        return_value=two_minutes_ago):
            value = signing.dumps('x', salt=SALT)
        with self.assertRaises(signing.SignatureExpired):
            signing.loads(value, salt=SALT, max_age=60)
        self.assertEqual(
            signing.loads(value, salt=SALT, max_age=600), 'x'
        )

    def test_a_new_key_needs_the_old_one_as_fallback(self):
        value = signing.dumps('x', salt=SALT)
        old = settings.SECRET_KEY
        new = 'a-new-secret-key-' + 'n' * 40
        with override_settings(SECRET_KEY=new):
            with self.assertRaises(signing.BadSignature):
                signing.loads(value, salt=SALT)
        with override_settings(SECRET_KEY=new,
                               SECRET_KEY_FALLBACKS=[old]):
            self.assertEqual(signing.loads(value, salt=SALT),
                             'x')


NEW_PASSWORD = 'violet kettle harbour'


def member(email='sai@example.org', **flags):
    """Create a member with the test password."""
    return User.objects.create_user(
        email, PASSWORD, display_name='Sai', **flags)


def sign_in(client, email='sai@example.org',
            password=PASSWORD):
    """Sign in on allauth's page with a password."""
    return client.post(reverse('account_login'), {
        'login': email, 'password': password})


def subjects():
    """Return the subjects of the emails sent so far."""
    return [message.subject for message in mail.outbox]


class PasswordRuleTests(SimpleTestCase):
    """Passwords need at least 15 characters."""

    def test_fourteen_characters_are_refused(self):
        with self.assertRaisesMessage(
                ValidationError, 'at least 15 characters'):
            validate_password('harbour kettle')

    def test_fifteen_characters_are_accepted(self):
        validate_password('harbour kettles')


class PasswordChangeTests(TestCase):
    """Changing a password; other browsers sign out."""

    def setUp(self):
        cache.clear()
        self.sai = member()
        sign_in(self.client)
        mail.outbox.clear()

    def change(self, current):
        """Post the change form, giving current."""
        return self.client.post(
            reverse('account_change_password'), {
                'oldpassword': current,
                'password1': NEW_PASSWORD,
                'password2': NEW_PASSWORD})

    def test_wrong_current_password_is_refused(self):
        response = self.change('not my password')
        self.assertContains(
            response, 'Please type your current password.')
        self.sai.refresh_from_db()
        self.assertTrue(self.sai.check_password(PASSWORD))

    def test_other_browsers_are_signed_out(self):
        laptop = Client()
        sign_in(laptop)
        self.change(PASSWORD)
        profile = reverse('accounts:profile')
        self.assertEqual(
            self.client.get(profile).status_code, 200)
        self.assertEqual(
            laptop.get(profile).status_code, 302)


LINK = re.compile(
    r'http://testserver(/accounts/password/reset/key/\S+/)')


class ResetCase(TestCase):
    """A member, Sai, and helpers for password resets."""

    def setUp(self):
        cache.clear()
        self.sai = member()
        member('old@example.org', is_active=False)

    def ask(self, email='sai@example.org'):
        """Ask for a reset email for email."""
        mail.outbox.clear()
        return self.client.post(
            reverse('account_reset_password'),
            {'email': email})

    def link(self):
        """Return the reset link in the first email."""
        return LINK.search(mail.outbox[0].body).group(1)

    def set_new_password(self, client, link):
        """Follow link and set the new password."""
        # The key moves from the address into the session.
        page = client.get(link)
        return client.post(page.url, {
            'password1': NEW_PASSWORD,
            'password2': NEW_PASSWORD})


class ResetTests(ResetCase):
    """Resets: the same page for all, one-hour links."""

    def test_every_address_gets_the_same_page(self):
        done = reverse('account_reset_password_done')
        for email in ('sai@example.org',
                      'nobody@example.org',
                      'old@example.org'):
            self.assertRedirects(self.ask(email), done)

    def test_only_a_member_gets_an_email(self):
        self.ask()
        self.assertEqual(len(mail.outbox), 1)
        for email in ('nobody@example.org',
                      'old@example.org'):
            self.ask(email)
            self.assertEqual(mail.outbox, [])

    def test_the_link_works_once(self):
        self.ask()
        link = self.link()
        self.assertRedirects(
            self.set_new_password(self.client, link),
            reverse('account_reset_password_from_key_done'))
        response = Client().get(link, follow=True)
        self.assertTrue(response.context['token_fail'])

    def test_the_link_lasts_one_hour(self):
        self.ask()
        link = self.link()
        for minutes, fails in ((59, False), (61, True)):
            later = (datetime.now()
                     + timedelta(minutes=minutes))
            with mock.patch.object(
                    PasswordResetTokenGenerator, '_now',
                    return_value=later):
                response = Client().get(link, follow=True)
            failed = response.context.get('token_fail')
            self.assertEqual(bool(failed), fails)

    def test_a_reset_does_not_sign_in(self):
        self.ask()
        self.set_new_password(self.client, self.link())
        self.assertNotIn(
            '_auth_user_id', self.client.session)
        self.sai.refresh_from_db()
        self.assertFalse(self.sai.check_password(PASSWORD))
        sign_in(self.client, password=NEW_PASSWORD)
        self.assertIn('_auth_user_id', self.client.session)


class AccountEmailTests(ResetCase):
    """Otahque's reset email and its change notices."""

    def test_the_reset_email_is_otahques(self):
        self.ask()
        self.assertEqual(
            subjects(), ['[Otahque] Password Reset Email'])
        body = mail.outbox[0].body
        self.assertIn('Hello from Otahque.', body)
        self.assertIn('one hour', body)
        self.assertNotIn('testserver!', body)

    def test_a_change_sends_a_notice(self):
        sign_in(self.client)
        mail.outbox.clear()
        self.client.post(
            reverse('account_change_password'), {
            'oldpassword': PASSWORD,
            'password1': NEW_PASSWORD,
            'password2': NEW_PASSWORD})
        self.assertEqual(
            subjects(), ['[Otahque] Password Changed'])
        self.assertIn('A notice about your Otahque account',
                      mail.outbox[0].body)

    def test_a_reset_sends_a_notice(self):
        self.ask()
        link = self.link()
        mail.outbox.clear()
        self.set_new_password(self.client, link)
        self.assertEqual(
            subjects(), ['[Otahque] Password Reset'])


class SetPasswordTests(TestCase):
    """Members without a password may set one."""

    def setUp(self):
        self.raj = User.objects.create_user(
            'raj@example.org', None, display_name='Raj')

    def test_profile_offers_change_or_set(self):
        self.client.force_login(member())
        page = self.client.get(reverse('accounts:profile'))
        self.assertContains(page, 'Change password')
        self.assertNotContains(page, 'Set a password')
        self.client.force_login(self.raj)
        page = self.client.get(reverse('accounts:profile'))
        self.assertContains(page, 'Set a password')

    def test_a_member_without_one_can_set_a_password(self):
        self.assertFalse(self.raj.has_usable_password())
        self.client.force_login(self.raj)
        self.client.post(reverse('account_set_password'), {
            'password1': NEW_PASSWORD,
            'password2': NEW_PASSWORD})
        self.raj.refresh_from_db()
        self.assertTrue(
            self.raj.check_password(NEW_PASSWORD))
        self.assertEqual(
            subjects(), ['[Otahque] Password Set'])


CODE = re.compile(r'^([A-Z0-9]{4}-[A-Z0-9]{4})$', re.M)


class CodeSignInTests(TestCase):
    """Signing in with a code sent by email."""

    def setUp(self):
        cache.clear()
        self.sai = member()

    def ask(self, client, email='sai@example.org'):
        """Ask for a sign-in code for email."""
        mail.outbox.clear()
        return client.post(
            reverse('account_request_login_code'),
            {'email': email})

    def code(self):
        """Return the code in the first email."""
        return CODE.search(mail.outbox[0].body).group(1)

    def confirm(self, client, code):
        """Post code on the confirm-code page."""
        return client.post(
            reverse('account_confirm_login_code'),
            {'code': code})

    def test_the_sign_in_page_offers_a_code(self):
        page = self.client.get(reverse('account_login'))
        self.assertContains(
            page, reverse('account_request_login_code'))

    def test_a_code_signs_in_once(self):
        self.ask(self.client)
        self.assertEqual(
            subjects(), ['[Otahque] Sign-In Code'])
        self.assertIn('ten minutes', mail.outbox[0].body)
        code = self.code()
        self.confirm(self.client, code)
        self.assertIn('_auth_user_id', self.client.session)
        self.client.post(reverse('account_logout'))
        self.confirm(self.client, code)
        self.assertNotIn(
            '_auth_user_id', self.client.session)

    def test_only_the_asking_browser_can_use_it(self):
        self.ask(self.client)
        other = Client()
        self.confirm(other, self.code())
        self.assertNotIn('_auth_user_id', other.session)

    def test_three_wrong_codes_discard_it(self):
        self.ask(self.client)
        code = self.code()
        for _ in range(3):
            self.confirm(self.client, 'ZZZZ-ZZZZ')
        self.confirm(self.client, code)
        self.assertNotIn(
            '_auth_user_id', self.client.session)

    def test_the_code_lasts_ten_minutes(self):
        for minutes, works in ((9, True), (11, False)):
            client = Client()
            self.ask(client)
            later = time.time() + minutes * 60
            with mock.patch('time.time', return_value=later):
                self.confirm(client, self.code())
            self.assertEqual(
                '_auth_user_id' in client.session, works)

    def test_an_unknown_address_gets_no_email(self):
        response = self.ask(
            self.client, 'nobody@example.org')
        self.assertRedirects(
            response, reverse('account_confirm_login_code'),
            fetch_redirect_response=False)
        self.assertEqual(mail.outbox, [])


def code_at(secret, moment):
    """Return the authenticator app's code at moment."""
    counter = int(moment) // 30
    return totp.format_hotp_value(
        totp.hotp_value(secret, counter))


def turn_on_totp(client, at=None):
    """Turn on an authenticator app, as a member does.

    The code is typed at moment `at` (default: now).
    """
    page = client.get(reverse('mfa_activate_totp'))
    if page.status_code == 302:  # the password, again
        client.post(page.url, {'password': PASSWORD})
        page = client.get(reverse('mfa_activate_totp'))
    secret = page.context['form'].secret
    moment = time.time() if at is None else at
    with mock.patch('time.time', return_value=moment):
        client.post(reverse('mfa_activate_totp'),
                    {'code': code_at(secret, moment)})
    return secret


def confirmed(email='sai@example.org', **flags):
    """Create a member whose email address is verified."""
    user = member(email, **flags)
    EmailAddress.objects.create(
        user=user, email=email, verified=True, primary=True)
    return user


class TwoFactorCase(TestCase):
    """Helpers for members with an authenticator app."""

    def setUp(self):
        cache.clear()

    def two_factor_on(self):
        """Give Sai two-factor sign-in; sign out again."""
        sai = confirmed()
        sign_in(self.client)
        secret = turn_on_totp(self.client)
        self.client.post(reverse('account_logout'))
        return sai, secret

    def second_factor(self, client, code, at=None):
        """Type a code at moment `at` (default: 31 s on)."""
        moment = time.time() + 31 if at is None else at
        with mock.patch('time.time', return_value=moment):
            client.post(reverse('mfa_authenticate'),
                        {'code': code})
        return '_auth_user_id' in client.session


class TwoFactorTests(TwoFactorCase):
    """Turning on an authenticator app."""

    def test_turning_it_on_asks_for_the_password(self):
        confirmed()
        sign_in(self.client)
        page = self.client.get(reverse('mfa_activate_totp'))
        self.assertTrue(page.url.startswith(
            reverse('account_reauthenticate')))

    def test_an_unconfirmed_address_blocks_it(self):
        sai = member()
        EmailAddress.objects.create(
            user=sai, email=sai.email, verified=False,
            primary=True)
        sign_in(self.client)
        profile = self.client.get(
            reverse('accounts:profile'))
        self.assertContains(
            profile, 'Confirm your email address first')
        page = self.client.get(reverse('mfa_activate_totp'))
        self.client.post(page.url, {'password': PASSWORD})
        page = self.client.get(reverse('mfa_activate_totp'),
                               follow=True)
        self.assertContains(
            page, 'verified your email address')
        self.assertFalse(Authenticator.objects.exists())

    def test_the_profile_says_on_or_off(self):
        confirmed()
        sign_in(self.client)
        profile = reverse('accounts:profile')
        self.assertContains(self.client.get(profile),
                            '<strong>off</strong>')
        turn_on_totp(self.client)
        self.assertContains(self.client.get(profile),
                            '<strong>on</strong>')

    def test_the_secret_is_stored_as_text(self):
        sai, secret = self.two_factor_on()
        stored = Authenticator.objects.get(
            user=sai, type=Authenticator.Type.TOTP)
        # Known risk until Chapter 59 encrypts it.
        self.assertEqual(stored.data['secret'], secret)

    def test_the_activation_code_cannot_sign_in(self):
        confirmed()
        sign_in(self.client)
        now = time.time()
        secret = turn_on_totp(self.client, at=now)
        self.client.post(reverse('account_logout'))
        sign_in(self.client)
        used = code_at(secret, now)
        self.assertFalse(
            self.second_factor(self.client, used, at=now))


class TwoFactorSignInTests(TwoFactorCase):
    """Signing in with a second factor."""

    def test_a_password_alone_is_not_enough(self):
        sai, secret = self.two_factor_on()
        response = sign_in(self.client)
        self.assertRedirects(
            response, reverse('mfa_authenticate'),
            fetch_redirect_response=False)
        self.assertNotIn(
            '_auth_user_id', self.client.session)
        later = time.time() + 31
        self.assertTrue(self.second_factor(
            self.client, code_at(secret, later), at=later))

    def test_a_recovery_code_works_once(self):
        sai, secret = self.two_factor_on()
        codes = Authenticator.objects.get(
            user=sai, type=Authenticator.Type.RECOVERY_CODES,
        ).wrap().get_unused_codes()
        self.assertEqual(len(codes), 10)
        sign_in(self.client)
        self.assertTrue(
            self.second_factor(self.client, codes[0]))
        other = Client()
        sign_in(other)
        self.assertFalse(self.second_factor(other, codes[0]))

    def test_a_used_code_waits_in_the_cache(self):
        sai, secret = self.two_factor_on()
        first, second, third = Client(), Client(), Client()
        for client in (first, second, third):
            sign_in(client)
        later = time.time() + 31
        code = code_at(secret, later)
        self.assertTrue(
            self.second_factor(first, code, at=later))
        self.assertFalse(
            self.second_factor(second, code, at=later))
        cache.clear()  # what a second process would see
        self.assertTrue(
            self.second_factor(third, code, at=later))

    def test_a_sign_in_code_still_asks_for_it(self):
        self.two_factor_on()
        mail.outbox.clear()
        self.client.post(
            reverse('account_request_login_code'),
            {'email': 'sai@example.org'})
        code = CODE.search(mail.outbox[0].body).group(1)
        response = self.client.post(
            reverse('account_confirm_login_code'),
            {'code': code})
        self.assertRedirects(
            response, reverse('mfa_authenticate'),
            fetch_redirect_response=False)
        self.assertNotIn(
            '_auth_user_id', self.client.session)


class AdminSignInTests(TwoFactorCase):
    """The admin sends staff to allauth's sign-in."""

    def test_the_admin_sends_staff_to_allauth(self):
        response = self.client.get(reverse('admin:login'))
        self.assertTrue(response.url.startswith(
            reverse('account_login')))

    def test_the_old_form_signs_nobody_in(self):
        member('sam@example.org', is_staff=True)
        self.client.post(reverse('admin:login'), {
            'username': 'sam@example.org',
            'password': PASSWORD})
        self.assertNotIn(
            '_auth_user_id', self.client.session)

    def test_staff_with_two_factor_give_the_code(self):
        confirmed('sam@example.org', is_staff=True)
        sign_in(self.client, 'sam@example.org')
        secret = turn_on_totp(self.client)
        self.client.post(reverse('account_logout'))
        sign_in(self.client, 'sam@example.org')
        index = reverse('admin:index')
        self.assertEqual(
            self.client.get(index).status_code, 302)
        later = time.time() + 31
        self.second_factor(
            self.client, code_at(secret, later), at=later)
        self.assertEqual(
            self.client.get(index).status_code, 200)


class SecretLogTests(ResetCase):
    """Logs never hold a password or a reset key."""

    def test_logs_hold_no_password_or_key(self):
        with self.assertLogs(level='DEBUG') as logs:
            logging.getLogger('otahque').debug('start')
            self.ask()
            link = self.link()
            self.set_new_password(self.client, link)
        text = '\n'.join(logs.output)
        self.assertNotIn(NEW_PASSWORD, text)
        self.assertNotIn(link.split('/')[-2], text)


# Chapter 30: the two groups the migration creates.
GROUPS = {
    'Administrators': [
        'accounts.change_user', 'accounts.view_user',
        'admin.view_logentry', 'audit.view_auditevent',
        'events.change_event',
        'events.add_organizerassignment',
        'events.change_organizerassignment',
        'events.view_organizerassignment',
        'events.delete_event', 'events.manage_organizers',
        'events.view_event',
        'registrations.view_registration',
    ],
    'Organizers': [
        'events.add_event', 'events.change_event',
    ],
}


class GroupTests(TestCase):
    """The two groups and the permissions they hold."""

    def test_two_groups_with_exactly_these_permissions(self):
        found = {
            group.name: sorted(
                f'{p.content_type.app_label}.{p.codename}'
                for p in group.permissions.all()
            )
            for group in Group.objects.all()
        }
        expected = {name: sorted(perms)
                    for name, perms in GROUPS.items()}
        self.assertEqual(found, expected)


class ProfilePhoneTests(TestCase):
    """A phone number on the profile, checked and kept."""

    url = '/accounts/profile/'

    @classmethod
    def setUpTestData(cls):
        cls.sai = User.objects.create_user(
            'sai@example.org', PASSWORD, display_name='Sai'
        )

    def setUp(self):
        self.client.force_login(self.sai)

    def save(self, phone):
        """Send the profile form with this phone number."""
        return self.client.post(self.url, {
            'display_name': 'Sai', 'timezone': '',
            'phone': phone,
        })

    def test_a_national_number_is_kept_in_full(self):
        self.save('098765 43210')
        self.assertEqual(Profile.of(self.sai).phone,
                         '+919876543210')
        page = self.client.get(self.url)
        self.assertContains(page, 'type="tel"')

    def test_another_country_needs_its_code(self):
        self.save('+44 113 496 0000')
        self.assertEqual(Profile.of(self.sai).phone.as_e164,
                         '+441134960000')

    def test_a_wrong_number_is_refused(self):
        response = self.save('12345')
        self.assertContains(response, 'Enter a valid phone')
        self.assertEqual(Profile.of(self.sai).phone, '')

    def test_the_number_may_stay_blank(self):
        response = self.save('')
        self.assertEqual(response.status_code, 302)
