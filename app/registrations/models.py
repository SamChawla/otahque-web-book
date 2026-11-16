from django.conf import settings
from django.db import models
from django.utils import timezone


class RegistrationQuerySet(models.QuerySet):
    """Named questions about registrations."""

    def active(self):
        """Places that members currently hold."""
        return self.filter(status=Registration.Status.ACTIVE)


class Registration(models.Model):
    """A member's place in an event, from the ERD."""

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        CANCELLED = 'cancelled', 'Cancelled'

    event = models.ForeignKey(
        'events.Event',
        on_delete=models.PROTECT,
        related_name='registrations',
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='registrations',
    )
    status = models.CharField(
        max_length=20,
        choices=Status,
        default=Status.ACTIVE,
    )
    registered_at = models.DateTimeField(
        default=timezone.now
    )
    cancelled_at = models.DateTimeField(
        null=True, blank=True
    )

    objects = RegistrationQuerySet.as_manager()

    class Meta:
        ordering = ['registered_at']
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'member'],
                condition=models.Q(status='active'),
                name='registration_one_active',
                violation_error_message=(
                    'This member already has a place at '
                    'this event.'
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=[
                    'active', 'cancelled',
                ]),
                name='registration_status_valid',
                violation_error_message=(
                    'Status must be active or cancelled.'
                ),
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status='active',
                             cancelled_at__isnull=True)
                    | models.Q(status='cancelled',
                               cancelled_at__isnull=False)
                ),
                name='cancelled_at_matches_status',
                violation_error_message=(
                    'A cancelled registration needs a '
                    'cancellation time; an active one has '
                    'none.'
                ),
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(cancelled_at__isnull=True)
                    | models.Q(cancelled_at__gte=models.F(
                        'registered_at'
                    ))
                ),
                name='cancelled_after_registered',
                violation_error_message=(
                    'A registration cannot be cancelled '
                    'before it was made.'
                ),
            ),
        ]

    def __str__(self):
        return f'{self.member} at {self.event}'
