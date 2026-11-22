"""Pages for members' places and organizers' lists."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import (
    get_object_or_404, redirect, render,
)
from django.utils import timezone
from django.views.decorators.http import (
    require_http_methods, require_POST,
)

from accounts.forms import PhoneForm
from audit.models import AuditEvent
from events.models import REASONS, Event
from events.views import deny

from .models import Registration

Action = AuditEvent.Action


def event_for(request, event_id):
    """Return the event if the viewer may see it, or 404."""
    event = get_object_or_404(Event, pk=event_id)
    if not event.is_visible_to(request.user):
        deny(request, Action.VIEW_EVENT, event, hidden=True)
    return event


def take_place(request, event):
    """Register the member, then say what happened."""
    try:
        event.register(request.user, timezone.now())
    except ValidationError as error:
        codes = [e.code for e in error.error_list]
        if codes == ['phone_missing']:
            return redirect('registrations:phone', event.pk)
        if codes == ['already_registered']:
            messages.info(request, REASONS['already_registered'])
        else:
            for message in error.messages:
                messages.error(request, message)
    else:
        messages.success(request, 'You have a place.')
    return redirect(event)


@require_POST
@login_required
def register(request, event_id):
    """Register the signed-in member for the event."""
    return take_place(request, event_for(request, event_id))


@require_http_methods(['GET', 'POST'])
@login_required
def register_phone(request, event_id):
    """Ask for the number the event needs, then register."""
    event = event_for(request, event_id)
    form = PhoneForm(request.POST or None)
    if form.is_valid():
        form.save(request.user)
        return take_place(request, event)
    return render(request, 'registrations/phone.html',
                  {'event': event, 'form': form})


@login_required
def my_registrations(request):
    """Show the signed-in member's places, upcoming first."""
    now = timezone.now()
    mine = request.user.registrations.select_related('event')
    current = mine.active().filter(event__ends_at__gt=now)
    earlier = mine.exclude(pk__in=current)
    return render(request, 'registrations/mine.html', {
        'current': current.order_by('event__starts_at'),
        'earlier': earlier.order_by('-event__starts_at',
                                    '-registered_at'),
        'now': now,
    })


@require_http_methods(['GET', 'POST'])
@login_required
def cancel_registration(request, registration_id):
    """Confirm, then cancel the member's own place."""
    registration = get_object_or_404(
        Registration.objects.select_related('event'),
        pk=registration_id,
    )
    if registration.member_id != request.user.pk:
        # Someone else's place: answered as if missing.
        deny(request, Action.CANCEL_REGISTRATION,
             registration, hidden=True)
    now = timezone.now()
    if request.method == 'POST':
        try:
            changed = registration.cancel(now)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            say_cancelled(request, registration, changed)
        return redirect('registrations:mine')
    event = registration.event
    deadline = event.cancellation_deadline
    return render(request, 'registrations/cancel.html', {
        'registration': registration,
        'event': event,
        'started': now >= event.starts_at,
        'late': deadline is not None and now >= deadline,
    })


def say_cancelled(request, registration, changed):
    """Tell the member what their cancel request did."""
    if not changed:
        messages.info(request,
                      'This place was already cancelled.')
    elif registration.is_late():
        messages.success(request, 'Place cancelled. It '
                         'counts as a late cancellation.')
    else:
        messages.success(request, 'Place cancelled.')


@login_required
def attendees(request, event_id):
    """Show the attendee list to the event's organizers."""
    event = get_object_or_404(Event, pk=event_id)
    if not event.is_visible_to(request.user):
        deny(request, Action.VIEW_ATTENDEES, event,
             hidden=True)
    if not event.can_see_attendees(request.user):
        deny(request, Action.VIEW_ATTENDEES, event)
    places = event.registrations.active().with_people()
    return render(request, 'registrations/attendees.html', {
        'event': event,
        'places': places,
        'counts': event.registrations.cancellation_counts(),
    })
