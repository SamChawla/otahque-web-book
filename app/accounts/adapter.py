"""Otahque's changes to how allauth signs members up."""
from allauth.account.adapter import DefaultAccountAdapter
from disposable_email_domains import blocklist
from django import forms
from django.conf import settings

DISPOSABLE = 'Please use a permanent email address.'


class AccountAdapter(DefaultAccountAdapter):
    """Otahque's choices inside allauth's sign-up."""

    def clean_email(self, email):
        """Refuse disposable domains unless allowed."""
        email = super().clean_email(email)
        domain = email.rsplit('@', 1)[-1].lower()
        allowed = settings.EMAIL_DOMAINS_ALLOWED
        if domain in blocklist and domain not in allowed:
            raise forms.ValidationError(DISPOSABLE)
        return email
