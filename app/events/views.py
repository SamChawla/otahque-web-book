"""The events app's views: one function per page."""
from functools import wraps

from allauth.account.decorators import (
    reauthentication_required,
)
from django.contrib import messages
from django.contrib.auth.decorators import (
    login_required, permission_required,
)
from django.core.exceptions import (
    PermissionDenied, ValidationError,
)
from django.db import models, transaction
from django.forms.models import model_to_dict
from django.http import Http404
from django.shortcuts import (
    get_object_or_404, redirect, render,
)
from django.utils import timezone
from django.views.decorators.http import (
    require_http_methods, require_POST,
)

from audit.models import AuditEvent, record

from .forms import (
    CopyForm, EventForm, OrganizerForm, RemoveOrganizerForm,
)
from .models import REASONS, Event, OrganizerAssignment

Action = AuditEvent.Action


def deny(request, action, event=None, hidden=False):
    """Record a refused attempt, then refuse it.

    Only a signed-in person's attempt is recorded. The answer
    is 404 if the event is hidden, else 403.
    """
    if request.user.is_authenticated:
        record(request.user, action, event,
               AuditEvent.Outcome.REFUSED)
    if hidden:
        raise Http404('No event matches the given query.')
    raise PermissionDenied


def home(request):
    """Welcome visitors to Otahque."""
    return render(request, 'events/home.html')


def event_list(request):
    """List published events; remember the places filter."""
    choice = request.GET.get('places')
    if choice in ('0', '1'):
        # Saved only when the visitor changes the filter.
        request.session['places_only'] = choice == '1'
    places_only = request.session.get('places_only', False)
    now = timezone.now()
    events = Event.objects.published().with_places()
    upcoming = events.upcoming(now)
    if places_only:
        upcoming = upcoming.filter(places_left__gt=0)
    return render(request, 'events/list.html', {
        'upcoming': upcoming,
        'past': events.past(now),
        'now': now,
        'places_only': places_only,
    })


def event_detail(request, event_id):
    """Show an event its viewer may see, or 404."""
    event = get_object_or_404(
        Event.objects.with_places(), pk=event_id
    )
    if not event.is_visible_to(request.user):
        deny(request, Action.VIEW_EVENT, event, hidden=True)
    now = timezone.now()
    return render(request, 'events/detail.html', {
        'event': event,
        'now': now,
        'can_edit': event.can_be_edited_by(request.user),
    } | registration_panel(event, request.user, now))


def registration_panel(event, user, now):
    """Return what the event page says about registering."""
    if not user.is_authenticated:
        codes = event.open_problems(now)
        return {'reasons': [REASONS[c] for c in codes]}
    place = event.place_of(user)
    codes = [] if place else event.registration_problems(
        user, now
    )
    return {
        'place': place,
        'reasons': [REASONS[c] for c in codes
                    if c != 'phone_missing'],
        'needs_phone': 'phone_missing' in codes,
        'unverified': 'unverified' in codes,
        'can_see_attendees': event.can_see_attendees(user),
    }


@login_required
def event_create(request):
    """Create an event, for members who may add events."""
    if not request.user.has_perm('events.add_event'):
        deny(request, Action.CREATE_EVENT)
    if request.method == 'POST':
        form = EventForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                event = form.save()
                event.add_organizer(request.user)
                record(request.user, Action.CREATE_EVENT,
                       event)
            messages.success(request, 'Draft saved.')
            return redirect(event)
    else:
        form = EventForm()
    return render(request, 'events/form.html',
                  {'form': form})


def event_to_manage(request, event_id, action):
    """Return the event, if this member may change it.

    A refusal is recorded as an attempt at action.
    """
    event = get_object_or_404(Event, pk=event_id)
    if not event.is_visible_to(request.user):
        deny(request, action, event, hidden=True)
    if not event.can_be_edited_by(request.user):
        deny(request, action, event)
    return event


@login_required
def event_edit(request, event_id):
    """Edit the event, for those who may change it."""
    event = event_to_manage(request, event_id,
                            Action.EDIT_EVENT)
    title = event.title
    if request.method == 'POST':
        before = model_to_dict(event)
        form = EventForm(request.POST, instance=event)
        if form.is_valid():
            with transaction.atomic():
                form.save()
                after = model_to_dict(event)
                changed = [name for name in form.fields
                           if before[name] != after[name]]
                record(request.user, Action.EDIT_EVENT,
                       event, fields=changed)
            messages.success(request, 'Changes saved.')
            return redirect(event)
    else:
        form = EventForm(instance=event)
    return render(request, 'events/edit.html', {
        'form': form,
        'title': title,
        'event_id': event.pk,
        'taken': event.places_taken(),
    })


@login_required
@permission_required(
    'events.change_event', raise_exception=True
)
def event_manage(request):
    """My events: what this member organizes now."""
    events = Event.objects.organized_by(
        request.user
    ).with_places()
    return render(request, 'events/manage.html',
                  {'events': events})


def refuse(request, error):
    """Show why a change was refused; nothing changed."""
    for message in error.messages:
        messages.error(request, message)


@require_POST
@login_required
def event_publish(request, event_id):
    """Publish the event, or say why not."""
    event = event_to_manage(request, event_id,
                            Action.PUBLISH_EVENT)
    try:
        with transaction.atomic():
            event.publish()
            record(request.user, Action.PUBLISH_EVENT,
                   event)
    except ValidationError as error:
        refuse(request, error)
    else:
        messages.success(request, 'Published.')
    return redirect(event)


@require_POST
@login_required
def event_cancel(request, event_id):
    """Cancel the event, or say why not."""
    event = event_to_manage(request, event_id,
                            Action.CANCEL_EVENT)
    try:
        with transaction.atomic():
            event.cancel()
            record(request.user, Action.CANCEL_EVENT,
                   event)
    except ValidationError as error:
        refuse(request, error)
    else:
        messages.success(request, 'Event cancelled.')
    return redirect(event)


@require_http_methods(['GET', 'POST'])
@login_required
def event_delete(request, event_id):
    """Confirm, then delete a draft; or say why not."""
    event = event_to_manage(request, event_id,
                            Action.DELETE_EVENT)
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Recorded first: deleting clears event.pk.
                record(request.user, Action.DELETE_EVENT,
                       event, title=event.title)
                event.delete_draft()
        except ValidationError as error:
            refuse(request, error)
            return redirect(event)
        messages.success(request, 'Draft deleted.')
        return redirect('events:manage')
    if event.status != Event.Status.DRAFT:
        refuse(request, ValidationError(
            'Only a draft can be deleted.'
        ))
        return redirect(event)
    return render(request, 'events/delete.html',
                  {'event': event})


@require_http_methods(['GET', 'POST'])
@login_required
def event_copy(request, event_id):
    """Ask for a start, then copy the event as a draft."""
    event = event_to_manage(request, event_id,
                            Action.COPY_EVENT)
    if request.method == 'POST':
        form = CopyForm(request.POST, event=event)
        if form.is_valid():
            with transaction.atomic():
                copy = event.copy_as_draft(
                    request.user,
                    form.cleaned_data['starts_at'],
                )
                record(request.user, Action.COPY_EVENT,
                       copy, source=event.pk)
            messages.success(
                request, 'Copied as a new draft.'
            )
            return redirect('events:edit', copy.pk)
    else:
        form = CopyForm(event=event)
    return render(request, 'events/copy.html',
                  {'event': event, 'form': form})


def organizer_access(view):
    """Allow only holders of events.manage_organizers.

    Anyone else gets 403, and the attempt is recorded.
    """
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.has_perm(
                'events.manage_organizers'):
            deny(request, Action.MANAGE_ORGANIZERS)
        return view(request, *args, **kwargs)
    return wrapper


@login_required
@organizer_access
def organizer_events(request):
    """Every event with its current organizers."""
    current = OrganizerAssignment.objects.filter(
        revoked_at__isnull=True
    ).select_related('member')
    events = Event.objects.order_by(
        '-starts_at'
    ).prefetch_related(models.Prefetch(
        'organizer_assignments', queryset=current,
        to_attr='current_organizers',
    ))
    return render(request, 'events/organizer_events.html',
                  {'events': events})


@login_required
@organizer_access
@reauthentication_required(allow_get=True)
def event_organizers(request, event_id):
    """List an event's organizers; add one by email."""
    event = get_object_or_404(Event, pk=event_id)
    form = OrganizerForm(request.POST or None)
    if form.is_valid():
        try:
            event.grant_organizer(form.member, request.user)
        except ValidationError as error:
            form.add_error('email', error)
        else:
            messages.success(request, 'Organizer added.')
            return redirect('events:organizers', event.pk)
    # Current organizers first, on SQLite and PostgreSQL.
    assignments = event.organizer_assignments.order_by(
        models.F('revoked_at').asc(nulls_first=True),
        'assigned_at',
    ).select_related('member')
    return render(request, 'events/organizers.html', {
        'event': event,
        'form': form,
        'assignments': assignments,
    })


@require_POST
@login_required
@organizer_access
@reauthentication_required
def remove_organizer(request, event_id):
    """Remove one current organizer, if allowed."""
    event = get_object_or_404(Event, pk=event_id)
    form = RemoveOrganizerForm(request.POST, event=event)
    if not form.is_valid():
        raise Http404('No current organizer matches.')
    try:
        form.cleaned_data['assignment'].revoke(request.user)
    except ValidationError as error:
        refuse(request, error)
    else:
        messages.success(request, 'Organizer removed.')
    return redirect('events:organizers', event.pk)
