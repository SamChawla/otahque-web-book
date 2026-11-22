"""How Otahque creates members and superusers."""
from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    """Create Otahque users, who sign in with an email."""

    use_in_migrations = True

    @classmethod
    def normalize_email(cls, email):
        """Store the whole address in lower case."""
        return super().normalize_email(email).lower()

    def get_by_natural_key(self, email):
        """Find the member with this email, in any case."""
        return super().get_by_natural_key(
            self.normalize_email(email)
        )

    def create_user(self, email, password=None,
                    **extra_fields):
        """Create and save a member with this email."""
        if not email:
            raise ValueError('An email address is required.')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None,
                         **extra_fields):
        """Create and save a member with every permission."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        for flag in ('is_staff', 'is_superuser'):
            if extra_fields[flag] is not True:
                raise ValueError(
                    f'A superuser needs {flag}=True.'
                )
        return self.create_user(
            email, password, **extra_fields
        )
