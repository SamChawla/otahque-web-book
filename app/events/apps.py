"""Configuration Django reads to load the events app."""
from django.apps import AppConfig


class EventsConfig(AppConfig):
    """The events app: events and their pages."""

    name = 'events'
