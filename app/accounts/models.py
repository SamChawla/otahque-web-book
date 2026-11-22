"""Otahque's member accounts."""
from django.conf import settings
from django.contrib.auth.models import (
    AbstractBaseUser,
    PermissionsMixin,
)
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from phonenumber_field.modelfields import PhoneNumberField

from events.models import validate_timezone_name

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """An Otahque member, who signs in with an email."""

    email = models.EmailField('email address', unique=True)
    display_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    EMAIL_FIELD = 'email'
    REQUIRED_FIELDS = ['display_name']

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(email=Lower('email')),
                name='user_email_lowercase',
                violation_error_message=(
                    'Email addresses are stored in lower '
                    'case.'
                ),
            ),
        ]

    def __str__(self):
        return self.email

    def clean(self):
        """Store the email in lower case before validating."""
        super().clean()
        self.email = UserManager.normalize_email(self.email)


class Profile(models.Model):
    """A member's own settings, one row per member."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    timezone = models.CharField(
        max_length=64, blank=True,
        validators=[validate_timezone_name],
        help_text='Blank means not set.',
    )
    phone = PhoneNumberField(
        blank=True,
        help_text='Shown only to the organizers of events '
                  'you register for.',
    )

    def __str__(self):
        return f'Profile of {self.user}'

    @classmethod
    def of(cls, user):
        """Return the member's profile, making it if new."""
        return cls.objects.get_or_create(user=user)[0]
