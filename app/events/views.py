from django.contrib import messages
from django.contrib.auth.decorators import (
    login_required, permission_required,
)
from django.db import transaction
from django.http import Http404
from django.shortcuts import (
    get_object_or_404, redirect, render,
)
from django.utils import timezone

from .forms import EventForm
from .models import Event


def home(request):
    return render(request, 'events/home.html')


def event_list(request):
    now = timezone.now()
    events = Event.objects.published().with_places()
    return render(request, 'events/list.html', {
        'upcoming': events.upcoming(now),
        'past': events.past(now),
        'now': now,
    })


def event_detail(request, event_id):
    event = get_object_or_404(
        Event.objects.with_places(), pk=event_id
    )
    if not event.is_visible_to(request.user):
        raise Http404('No event matches the given query.')
    return render(request, 'events/detail.html', {
        'event': event,
        'now': timezone.now(),
    })


@login_required
@permission_required(
    'events.add_event', raise_exception=True
)
def event_create(request):
    if request.method == 'POST':
        form = EventForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                event = form.save()
                event.add_organizer(request.user)
            messages.success(request, 'Draft saved.')
            return redirect('events:detail', event.pk)
    else:
        form = EventForm()
    return render(request, 'events/form.html',
                  {'form': form})
