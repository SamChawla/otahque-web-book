from zoneinfo import available_timezones

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def validate_timezone_name(value):
    """Refuse names missing from the time-zone database."""
    if value not in available_timezones():
        raise ValidationError(
            '%(value)s is not a known time zone.',
            code='unknown_timezone',
            params={'value': value},
        )


class EventQuerySet(models.QuerySet):
    """Named questions about events."""

    def published(self):
        """Events that visitors may see."""
        return self.filter(status=Event.Status.PUBLISHED)

    def upcoming(self, now):
        """Events not yet ended at now, soonest first."""
        return self.filter(ends_at__gt=now).order_by(
            'starts_at'
        )

    def past(self, now):
        """Events ended by now, the latest first."""
        return self.filter(ends_at__lte=now).order_by(
            '-ends_at'
        )

    def with_places(self):
        """Add places_left: capacity minus active places."""
        taken = models.Count(
            'registrations',
            filter=models.Q(registrations__status='active'),
        )
        return self.annotate(
            places_left=models.F('capacity') - taken
        )


class Event(models.Model):
    """A proposed Otahque event, from the Chapter 15 ERD."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PUBLISHED = 'published', 'Published'
        CANCELLED = 'cancelled', 'Cancelled'

    title = models.CharField(max_length=200)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    timezone = models.CharField(
        max_length=64, validators=[validate_timezone_name]
    )
    location = models.CharField(max_length=200)
    capacity = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=Status,
        default=Status.DRAFT,
    )

    objects = EventQuerySet.as_manager()

    class Meta:
        ordering = ['starts_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(capacity__gt=0),
                name='event_capacity_gt_0',
                violation_error_message=(
                    'Capacity must be more than 0.'
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(
                    ends_at__gt=models.F('starts_at')
                ),
                name='event_ends_after_start',
                violation_error_message=(
                    'An event must end after it starts.'
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=[
                    'draft', 'published', 'cancelled',
                ]),
                name='event_status_valid',
                violation_error_message=(
                    'Status must be draft, published, '
                    'or cancelled.'
                ),
            ),
        ]

    def __str__(self):
        return self.title

    def add_organizer(self, member):
        """Make member a current organizer of this event."""
        return self.organizer_assignments.create(
            member=member
        )

    def is_visible_to(self, user):
        """Published: everyone. Otherwise: organizers and
        holders of the view_event permission."""
        if self.status == self.Status.PUBLISHED:
            return True
        if user.has_perm('events.view_event'):
            return True
        if not user.is_authenticated:
            return False
        return self.organizer_assignments.filter(
            member=user, revoked_at__isnull=True
        ).exists()


class OrganizerAssignment(models.Model):
    """Which member organizes which event, from the ERD."""

    event = models.ForeignKey(
        Event,
        on_delete=models.PROTECT,
        related_name='organizer_assignments',
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='organizer_assignments',
    )
    assigned_at = models.DateTimeField(
        default=timezone.now
    )
    revoked_at = models.DateTimeField(
        null=True, blank=True
    )

    class Meta:
        ordering = ['assigned_at']
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'member'],
                condition=models.Q(revoked_at__isnull=True),
                name='assignment_one_current',
                violation_error_message=(
                    'This member already organizes this '
                    'event.'
                ),
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(revoked_at__isnull=True)
                    | models.Q(revoked_at__gte=models.F(
                        'assigned_at'
                    ))
                ),
                name='assignment_revoked_after_assigned',
                violation_error_message=(
                    'An assignment cannot be revoked before '
                    'it starts.'
                ),
            ),
        ]

    def __str__(self):
        return f'{self.member} organizes {self.event}'

    def validate_constraints(self, exclude=None):
        """Check every rule, even for fields a form omits."""
        super().validate_constraints(exclude=None)
