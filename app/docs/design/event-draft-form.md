# Event form: low-level design

Status: Drafted in Chapters 24 and 25, for review.
Who: members with events.add_event create drafts;
current organizers with events.change_event edit them.
Visitors cannot propose events.

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
  and current organizers; 404 for everyone else. An
  Edit event link for can_be_edited_by(user).
- GET and POST /events/<id>/edit/: login_required;
  404 unless is_visible_to(user); 403 unless
  can_be_edited_by(user) (change_event and a current
  assignment). EventForm(request.POST, instance=event):
  - invalid: 200, typed values kept, heading from the
    title read before validation, nothing saved;
  - valid: form.save(); "Changes saved."; 302 to the
    event page.

## Who may edit

| Person | Sees event | Edit page |
|---|---|---|
| Visitor | Published only | Sent to sign in |
| Member, no change_event | Published only | 403 or 404 |
| Staff, change_event, no assignment | All | 403 |
| Current organizer, change_event | All | Form |

## Validation layers, in the order they run

1. Fields: required values, lengths, whole numbers,
   the zone from the list.
2. clean_capacity(): 0 refused on Capacity.
3. EventForm.clean(): times read in the event's zone,
   except a time left as shown in an unchanged zone,
   which keeps its stored value; clock-change times
   refused; ends after starts, on Ends; a new zone
   needs the confirm_zone box, with both readings.
4. Model full_clean(): validate_timezone_name;
   Event.clean() refuses a capacity below the active
   registrations; Chapter 21's constraints.
5. Database: Chapter 21's constraints refuse a bad
   row from anywhere.

## Limits and later work

- Sign-in is the admin's page until Chapter 27, so
  only staff can sign in through a browser.
- Members holding places are not told of changes;
  the edit page says so. Open until Chapters 43-44.
- Last save wins: two organizers editing at once can
  undo each other. Chapter 33 adds a version check.
- The capacity floor reads, then writes; Chapter 33
  adds the lock that closes the gap.
- Publishing is Chapter 26.
- Once Chapter 28 activates each viewer's zone, clean
  the times under the event's zone instead.
- Widget templates copy Django 6.1's; check them when
  Django is upgraded.
- Fixed in Chapter 30: each widget writes one class
  attribute, Otahque's classes first, then the widget's
  own (the with_class filter), so the admin keeps its
  selectfilter and date and time shortcuts.
