"""Models for Otahque's events."""
from zoneinfo import ZoneInfo, available_timezones

from allauth.account.utils import has_verified_email
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent, record


def validate_timezone_name(value):
    """Refuse names missing from the time-zone database."""
    if value not in available_timezones():
        raise ValidationError(
            '%(value)s is not a known time zone.',
            code='unknown_timezone',
            params={'value': value},
        )


CAPACITY_MESSAGE = 'Capacity must be more than 0.'
ORGANIZERS = 'Organizers'
ADDED = AuditEvent.Action.ADD_ORGANIZER
REMOVED = AuditEvent.Action.REMOVE_ORGANIZER
REFUSED = AuditEvent.Outcome.REFUSED

# Why a member cannot register, by code (Chapter 31).
REASONS = {
    'not_published': 'This event is not open for '
                     'registration.',
    'not_open': 'Registration has not opened yet.',
    'closed': 'Registration has closed.',
    'full': 'This event is full.',
    'already_registered': 'You already have a place.',
    'unverified': 'Confirm your email address to '
                  'register.',
    'phone_missing': 'This event asks for your phone '
                     'number.',
}


def refusal(codes):
    """Return one ValidationError naming every reason."""
    return ValidationError([
        ValidationError(REASONS[code], code=code)
        for code in codes
    ])


def phone_of(member):
    """Return member's phone number, or '' if none."""
    # A member made outside sign-up may have no Profile.
    profile = getattr(member, 'profile', None)
    return profile.phone if profile else ''


def moved(moment, by):
    """Return moment moved by a timedelta; None stays."""
    return None if moment is None else moment + by


def organizer_problem(member):
    """Why member cannot organize events, or None."""
    if not member.is_active:
        return 'This member’s account is not active.'
    if not member.groups.filter(name=ORGANIZERS).exists():
        return ('Only members of the Organizers group can '
                'organize events.')
    return None


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

    def organized_by(self, user):
        """Events user organizes now, drafts first."""
        draft_first = models.Case(
            models.When(status=Event.Status.DRAFT, then=0),
            models.When(
                status=Event.Status.PUBLISHED, then=1
            ),
            default=2,
        )
        return self.filter(
            organizer_assignments__member=user,
            organizer_assignments__revoked_at__isnull=True,
        ).annotate(
            rank=draft_first
        ).order_by('rank', 'starts_at')

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
        """Where an event is: draft, published, or cancelled."""

        DRAFT = 'draft', 'Draft'
        PUBLISHED = 'published', 'Published'
        CANCELLED = 'cancelled', 'Cancelled'

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
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
    registration_opens_at = models.DateTimeField(
        'registration opens', null=True, blank=True,
        help_text='Blank: when the event is published.',
    )
    registration_closes_at = models.DateTimeField(
        'registration closes', null=True, blank=True,
        help_text='Needed to publish; by the start.',
    )
    cancellation_deadline = models.DateTimeField(
        null=True, blank=True,
        help_text='Needed to publish; by the start. Later '
                  'cancellations count as late.',
    )
    phone_required = models.BooleanField(
        'ask for a phone number', default=False,
    )

    objects = EventQuerySet.as_manager()

    class Meta:
        ordering = ['starts_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(capacity__gt=0),
                name='event_capacity_gt_0',
                violation_error_message=CAPACITY_MESSAGE,
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
            models.CheckConstraint(
                condition=(
                    models.Q(registration_opens_at=None)
                    | models.Q(registration_closes_at=None)
                    | models.Q(registration_opens_at__lt=(
                        models.F('registration_closes_at')
                    ))
                ),
                name='event_opens_before_closes',
                violation_error_message=(
                    'Registration must open before it '
                    'closes.'
                ),
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(registration_closes_at=None)
                    | models.Q(registration_closes_at__lte=(
                        models.F('starts_at')
                    ))
                ),
                name='event_closes_by_start',
                violation_error_message=(
                    'Registration must close by the start.'
                ),
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(cancellation_deadline=None)
                    | models.Q(cancellation_deadline__lte=(
                        models.F('starts_at')
                    ))
                ),
                name='event_deadline_by_start',
                violation_error_message=(
                    'The cancellation deadline must be by '
                    'the start.'
                ),
            ),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        """Return the address of the event's own page."""
        return reverse('events:detail', args=[self.pk])

    def add_organizer(self, member):
        """Make member a current organizer of this event."""
        return self.organizer_assignments.create(
            member=member
        )

    def has_organizer(self, user):
        """Return True for an active, current organizer."""
        if not (user.is_authenticated and user.is_active):
            return False
        return self.organizer_assignments.filter(
            member=user, revoked_at__isnull=True
        ).exists()

    def grant_organizer(self, member, by):
        """Make member an organizer at by's request.

        Otherwise raise ValidationError. Both are recorded.
        """
        problem = organizer_problem(member)
        if problem:
            record(by, ADDED, self, REFUSED,
                   member=member.pk)
            raise ValidationError(problem)
        if self.has_organizer(member):
            raise ValidationError(
                'This member already organizes this event.'
            )
        with transaction.atomic():
            assignment = self.add_organizer(member)
            record(by, ADDED, self, member=member.pk)
        return assignment

    def is_visible_to(self, user):
        """Whether user may see this event.

        Published and cancelled: everyone. A draft:
        organizers and holders of view_event.
        """
        if self.status != self.Status.DRAFT:
            return True
        if user.has_perm('events.view_event'):
            return True
        return self.has_organizer(user)

    def organizer_names(self):
        """List the current organizers' names, in order."""
        return list(self.organizer_assignments.filter(
            revoked_at__isnull=True
        ).values_list('member__display_name', flat=True))

    def differs_for(self, zone=None):
        """Return whether zone shows another start time.

        It is compared with the venue's zone; by default,
        zone is the viewer's.
        """
        zone = zone or timezone.get_current_timezone()
        start = self.starts_at
        venue = start.astimezone(ZoneInfo(self.timezone))
        return start.astimezone(zone).utcoffset() != (
            venue.utcoffset()
        )

    def can_be_edited_by(self, user):
        """Holders of change_event who organize it."""
        return (user.has_perm('events.change_event')
                and self.has_organizer(user))

    def can_see_attendees(self, user):
        """Return whether user may open the attendee list.

        Its current organizers may, and the administrator
        (registrations.view_registration).
        """
        if self.has_organizer(user):
            return True
        return user.has_perm(
            'registrations.view_registration'
        )

    def readiness_problems(self):
        """List what stops this draft being published."""
        problems = []
        if not self.description.strip():
            problems.append('Add a description.')
        if self.starts_at <= timezone.now():
            problems.append(
                'Move the start to a time in the future.'
            )
        if not self.organizer_assignments.filter(
                revoked_at__isnull=True).exists():
            problems.append(
                'Assign at least one current organizer.'
            )
        if self.registration_closes_at is None:
            problems.append('Set when registration closes.')
        if self.cancellation_deadline is None:
            problems.append('Set a cancellation deadline.')
        return problems

    def publish(self):
        """Draft to published, or ValidationError."""
        if self.status != self.Status.DRAFT:
            raise ValidationError(
                'Only a draft can be published.'
            )
        problems = self.readiness_problems()
        if problems:
            raise ValidationError(problems)
        self.status = self.Status.PUBLISHED
        self.save(update_fields=['status'])

    def cancel(self):
        """Cancel if published, or raise ValidationError."""
        if self.status != self.Status.PUBLISHED:
            raise ValidationError(
                'Only a published event can be cancelled.'
            )
        self.status = self.Status.CANCELLED
        self.save(update_fields=['status'])

    def delete_draft(self):
        """Delete a draft nobody registered for."""
        if self.status != self.Status.DRAFT:
            raise ValidationError(
                'Only a draft can be deleted.'
            )
        if self.registrations.exists():
            raise ValidationError(
                'This draft has registrations, so it '
                'is kept.'
            )
        with transaction.atomic():
            self.organizer_assignments.all().delete()
            self.delete()

    def copy_as_draft(self, member, starts_at):
        """Return a new draft with this event's details.

        It starts at starts_at, organized by member; its
        registration times move with the start.
        """
        shift = starts_at - self.starts_at
        with transaction.atomic():
            copy = Event.objects.create(
                title=self.title,
                description=self.description,
                timezone=self.timezone,
                location=self.location,
                capacity=self.capacity,
                phone_required=self.phone_required,
                starts_at=starts_at,
                ends_at=self.ends_at + shift,
                registration_opens_at=moved(
                    self.registration_opens_at, shift),
                registration_closes_at=moved(
                    self.registration_closes_at, shift),
                cancellation_deadline=moved(
                    self.cancellation_deadline, shift),
            )
            copy.add_organizer(member)
        return copy

    def places_taken(self):
        """How many members hold a place now."""
        return self.registrations.active().count()

    def place_of(self, member):
        """Return member's active place here, or None."""
        return self.registrations.active().filter(
            member=member
        ).first()

    def open_problems(self, now):
        """List, by code, what stops anyone registering.

        Opening is inclusive and closing exclusive: at the
        closing instant, registration has closed.
        """
        if self.status != self.Status.PUBLISHED:
            return ['not_published']
        problems = []
        opens = self.registration_opens_at
        if opens is not None and now < opens:
            problems.append('not_open')
        # Publishing needs a closing time; a row saved
        # without one closes at the start.
        closes = self.registration_closes_at or self.starts_at
        if now >= closes:
            problems.append('closed')
        if self.places_taken() >= self.capacity:
            problems.append('full')
        return problems

    def registration_problems(self, member, now):
        """List, by code, why member cannot register now.

        An empty list means member may register.
        """
        if self.place_of(member):
            return ['already_registered']
        problems = self.open_problems(now)
        if not has_verified_email(member, member.email):
            problems.append('unverified')
        if self.phone_required and not phone_of(member):
            problems.append('phone_missing')
        return problems

    def register(self, member, now):
        """Give member a place, or raise ValidationError.

        The unique rule is the backstop for a place made
        between the check and the insert. Chapter 33 locks
        the event before counting.
        """
        with transaction.atomic():
            problems = self.registration_problems(member, now)
            if problems:
                raise refusal(problems)
            try:
                with transaction.atomic():
                    return self.registrations.create(
                        member=member, registered_at=now
                    )
            except IntegrityError:
                # Only the one-active-place rule means a
                # repeat; any other failure is re-raised.
                if self.place_of(member) is None:
                    raise
            raise refusal(['already_registered'])

    def clean(self):
        """Check a saved event keeps room for its places.

        Zero is left to the event_capacity_gt_0 rule.
        """
        if self.pk is None or not self.capacity:
            return
        taken = self.places_taken()
        if self.capacity < taken:
            raise ValidationError({
                'capacity': ValidationError(
                    'Capacity cannot be below the places '
                    'already taken: %(taken)s.',
                    code='below_places_taken',
                    params={'taken': taken},
                ),
            })


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
        permissions = [
            ('manage_organizers',
             'Can manage organizer access'),
        ]
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

    def revoke(self, by):
        """End this assignment now at by's request.

        Otherwise raise ValidationError. Both are recorded.
        """
        event = self.event
        others = event.organizer_assignments.filter(
            revoked_at__isnull=True
        ).exclude(pk=self.pk)
        if (event.status != Event.Status.CANCELLED
                and not others.exists()):
            record(by, REMOVED, event, REFUSED,
                   member=self.member_id)
            raise ValidationError(
                'Assign another organizer before removing '
                'the last one.'
            )
        with transaction.atomic():
            self.revoked_at = timezone.now()
            self.save(update_fields=['revoked_at'])
            record(by, REMOVED, event, member=self.member_id)

    def validate_constraints(self, exclude=None):
        """Check every rule, even for fields a form omits."""
        super().validate_constraints(exclude=None)
