from django.contrib.auth.models import (
    AbstractBaseUser,
    PermissionsMixin,
)
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

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
        super().clean()
        self.email = UserManager.normalize_email(self.email)
