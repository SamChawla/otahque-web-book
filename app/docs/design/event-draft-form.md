# New event form: low-level design

Status: Drafted in Chapter 24, for review.
Who: members with events.add_event (Sam, on your
computer). Visitors cannot propose events.

## Request path

- GET /events/new/: login_required, then
  permission_required(add_event, raise 403); an unbound
  EventForm; events/form.html.
- POST /events/new/: the same checks; CsrfViewMiddleware
  refuses a missing or wrong token with 403 first.
  EventForm(request.POST).is_valid():
  - invalid: the same page, status 200, messages beside
    the fields, typed values kept, nothing saved;
  - valid: in one transaction, form.save() (status
    draft, as status is not a field) and
    event.add_organizer(user); message "Draft saved.";
    302 to the event page (Post/Redirect/Get).
- GET /events/<id>/: Event.is_visible_to(user):
  published for all; otherwise holders of view_event
  and current organizers; 404 for everyone else.

## Validation layers

1. Fields: required values, lengths, whole numbers,
   the zone from the list.
2. EventForm.clean(): starts and ends read in the
   event's zone (in_zone); times a clock change skips
   or repeats refused; ends after starts, on Ends.
3. Model full_clean(): validate_timezone_name and
   Chapter 21's constraints (capacity more than 0).
4. Database: Chapter 21's constraints refuse a bad
   row from anywhere.

## Limits and later work

- Sign-in is the admin's page until Chapter 27, so
  only staff can sign in through a browser.
- The edit form must show stored times in the event's
  zone (Chapter 25); publishing is Chapter 26.
- Once Chapter 28 activates each viewer's zone, clean
  the times under the event's zone instead.
- Widget templates copy Django 6.1's; check them when
  Django is upgraded.
