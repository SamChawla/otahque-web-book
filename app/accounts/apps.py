"""Configuration Django reads to load the accounts app."""
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """The accounts app: members and how they sign in."""

    name = 'accounts'
