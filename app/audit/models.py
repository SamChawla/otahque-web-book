"""The audit trail: who did what, and whether allowed."""
from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditEvent(models.Model):
    """Who did what to which record, and whether allowed.

    Rows are added, never changed.
    """

    class Action(models.TextChoices):
        """What the person tried to do."""

        CREATE_EVENT = 'create_event', 'Create an event'
        VIEW_EVENT = 'view_event', 'View an event'
        EDIT_EVENT = 'edit_event', 'Edit an event'
        PUBLISH_EVENT = 'publish_event', 'Publish an event'
        CANCEL_EVENT = 'cancel_event', 'Cancel an event'
        DELETE_EVENT = 'delete_event', 'Delete a draft'
        COPY_EVENT = 'copy_event', 'Copy an event'
        MANAGE_ORGANIZERS = (
            'manage_organizers', 'Open organizer access'
        )
        ADD_ORGANIZER = 'add_organizer', 'Add an organizer'
        REMOVE_ORGANIZER = (
            'remove_organizer', 'Remove an organizer'
        )
        JOIN_ORGANIZERS = (
            'join_organizers', 'Join the Organizers group'
        )
        LEAVE_ORGANIZERS = (
            'leave_organizers', 'Leave the Organizers group'
        )
        VIEW_ATTENDEES = (
            'view_attendees', 'Open an attendee list'
        )
        CANCEL_REGISTRATION = (
            'cancel_registration', 'Cancel a registration'
        )

    class Outcome(models.TextChoices):
        """Whether Otahque allowed it."""

        ALLOWED = 'allowed', 'Allowed'
        REFUSED = 'refused', 'Refused'

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='audit_events',
    )
    action = models.CharField(max_length=40, choices=Action)
    outcome = models.CharField(
        max_length=10, choices=Outcome,
        default=Outcome.ALLOWED,
    )
    target_type = models.CharField(max_length=40, blank=True)
    target_id = models.BigIntegerField(null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at', '-id']
        default_permissions = ['view']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(outcome__in=[
                    'allowed', 'refused',
                ]),
                name='audit_outcome_valid',
                violation_error_message=(
                    'Outcome must be allowed or refused.'
                ),
            ),
        ]

    def __str__(self):
        return f'{self.get_action_display()}: {self.outcome}'


def record(actor, action, target=None,
           outcome=AuditEvent.Outcome.ALLOWED, **detail):
    """Add one audit row.

    Call it inside the action's own transaction, so a failed
    action leaves no row.
    """
    if actor is not None and not actor.is_authenticated:
        actor = None
    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        outcome=outcome,
        target_type=(target._meta.model_name
                     if target is not None else ''),
        target_id=target.pk if target is not None else None,
        detail=detail,
    )
