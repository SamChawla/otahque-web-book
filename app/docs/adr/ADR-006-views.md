# ADR-006: Function views and class views

## Status

Proposed, November 2026 (Chapter 35). The choices follow
the user's decisions of 24 November 2026 (Chapter 35
D35.1-D35.4); this record is not yet reviewed or accepted.

## Context

For 34 chapters every Otahque view was a function. Many
of them repeat one shape: load an event the viewer may
see, refuse with 404 or 403, render. Django's generic
views (Chapters 36 and 37) remove that repetition, but
they are classes, and a class answers some requests on
its own: HEAD, OPTIONS, and 405 with an Allow header.
Converting a view can change what it answers, and the
existing tests did not notice (Chapter 35, Step 3).

## Options

- A: convert every view to a class.
- B: keep every view a function.
- C: classes where a generic view fits or a page has
  several handlers; small functions for one-off actions.

## Decision

C, with four rules.

1. Before a view is converted, a method table pins its
   answer to every method, signed in and signed out.
2. A conversion keeps every answer the function chose.
   The function's decorators move, in the same order, to
   one method_decorator list on dispatch().
3. Where the function chose nothing, Django's defaults
   are accepted and the table says so (D35.4: the event
   page answers 405 to methods other than GET and HEAD,
   and OPTIONS itself).
4. Nothing that needs sign-in or visibility goes in
   setup(): it runs before the decorators. Load objects
   in dispatch() or in the handlers.

## Inventory (19 views)

Kind now, then where each view goes and why.

events
- home: function, stays (one template, nothing shared).
- event_list: function, ListView in 36.
- EventDetailView: View class since 35; DetailView in 36.
- event_create: function, CreateView in 37.
- event_edit: function, UpdateView in 37.
- event_manage (My events): function, ListView in 36.
- event_publish: function, stays (one-off POST action).
- event_cancel: function, stays (one-off POST action).
- event_delete: function, DeleteView in 37.
- event_copy: function, FormView in 37.
- organizer_events: function, stays until Chapter 67
  makes organizer roles per community.
- event_organizers: function, stays until Chapter 67
  (add-by-email form behind re-authentication).
- remove_organizer: function, stays (one-off POST).

registrations
- register: function, stays (one-off POST action).
- RegistrationDetailsView: View class since 35; gains
  the event's questions in 38.
- my_registrations: function, ListView in 36.
- cancel_registration: function, a class in 37.
- attendees: function, stays until Chapter 41 adds the
  download (a report, not a list of one model).

accounts
- profile: function, FormView in 37 (proposed; not yet
  in Chapter 37's plan).

## Consequences

- Eleven views become classes by Chapter 37; eight stay
  functions, each with a reason above.
- Each converted page's table shows any change in its
  answers, so a change is a decision, not an accident.
- The event page no longer records a refused POST to a
  hidden draft: the method is refused (405) before the
  event is loaded. 405 is the same for every number.
- Chapter 37's LoginRequiredMixin and Chapter 39's
  LoginRequiredMiddleware put sign-in before the method
  check; the tables will show it, and those chapters say
  so.

## Revisit

Chapter 49 (the API), where OPTIONS matters for browsers'
cross-origin checks, and whenever a page in the "stays"
list gains a second handler.
