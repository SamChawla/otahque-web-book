"""Configuration Django reads to load the registrations app."""
from django.apps import AppConfig


class RegistrationsConfig(AppConfig):
    """The registrations app: members' places at events."""

    name = 'registrations'
