from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase

from events.tests import admin_url

from .models import User


class UserModelTests(SimpleTestCase):
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
