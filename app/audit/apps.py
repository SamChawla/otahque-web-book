"""Configuration Django reads to load the audit app."""
from django.apps import AppConfig


class AuditConfig(AppConfig):
    """The audit app: who did what, and whether allowed."""

    name = 'audit'
