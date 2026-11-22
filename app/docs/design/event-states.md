# Event states: low-level design

Status: Drafted in Chapter 26, for review. Not approved.
Who may act: current organizers who hold events.change_event
(Event.can_be_edited_by, Chapter 25), through the Organizers
group since Chapter 30; see permissions.md.

## States and moves

- publish: draft to published. Refused when it is not a
  draft, has no description, does not start in the future,
  has no current organizer, or has no registration closing
  time or cancellation deadline (Chapter 31).
- cancel: published to cancelled. Refused when not published.
- delete: a draft is removed. Refused when it is not a draft,
  or when any registration exists.
- copy: any state to a new draft. Refused when the new start
  is missing or unreadable.

- There is no unpublish. Cancelled is final: run the event
  again by copying it.
- Every move except the delete page's GET is a POST. The
  views for publish and cancel answer a GET with 405.
- A refused move changes nothing and tells the member why
  (one message per missing detail).

## What each state shows

- Draft: organizers and view_event holders; a Draft banner.
- Published: everyone; in the upcoming and past lists.
- Cancelled: everyone who has the address, with a
  Cancelled tag and no places line; not in either list.
  Registrations stay as they are.

## Request path

- POST events/<id>/publish/ and .../cancel/: require_POST,
  login_required, event_to_manage (404 hidden, 403
  refused), then event.publish() or event.cancel();
  ValidationError messages become error messages; 302 to
  the event.
- GET events/<id>/delete/: the confirmation page (a draft
  only). POST: event.delete_draft() removes the draft's
  organizer assignments, then the event, in one
  transaction; 302 to My events.
- GET/POST events/<id>/copy/: asks for the new start in the
  event's zone; event.copy_as_draft(user, starts_at) copies
  title, description, place, time zone, capacity, length,
  the phone setting, and the registration times, moved
  with the start; never registrations, status, or other
  organizers; 302 to the new draft's edit page.
- GET events/manage/: permission_required(change_event);
  Event.objects.organized_by(user): current assignments
  only, drafts first.

## Open

- Done (Chapter 30): each move, and each refused attempt,
  is an AuditEvent.
- Telling members of a cancellation: Chapters 43-44.
- A version check for two organizers acting at once:
  Chapter 33.
- The cover image joins what a copy carries: Chapter 42.
