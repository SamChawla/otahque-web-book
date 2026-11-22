# Who may do what: permissions and roles

Status: Drafted in Chapter 30, for review. Not approved.
Rules: PR-4 (organizers manage only assigned events),
PR-5 (publication), PR-6 (only the administrator grants
or removes organizer access). Decision: ADR-004.

## Two questions, two places

1. May this person organize at all? Membership of the
   Organizers group (add_event, change_event), set by
   the administrator in the admin.
2. Do they organize this event? A current
   OrganizerAssignment, added or removed by the
   administrator, on the admin or the Organizer access
   page.

Editing, publishing, cancelling, deleting, and copying
need both (Event.can_be_edited_by). An inactive account
answers no to both (Event.has_organizer).

## Roles

- Visitor: published and cancelled events only.
- Member: the same; their own account pages.
- Organizer: Organizers group; manages assigned events.
- Administrator: Administrators group, a staff account
  per person. The admin pages for accounts, assignments,
  events, registrations (view), and both logs; the
  Organizer access page (events.manage_organizers).
  Manages no event on Otahque's own pages; changes no
  group except Organizers.
- Superuser: every permission; a local setup tool only.
- Staff only: may open the admin; sees nothing there.

## Matrix: Sam's draft

| Person          | View | Edit    | Publish | Create  |
|-----------------|------|---------|---------|---------|
| Visitor         | 404  | sign in | sign in | sign in |
| Member          | 404  | 404     | 404     | 403     |
| Staff only      | 404  | 404     | 404     | 403     |
| Other organizer | 404  | 404     | 404     | ok      |
| Administrator   | ok   | 403     | 403     | 403     |
| Superuser       | ok   | 403     | 403     | ok      |
| Organizer       | ok   | ok      | ok      | ok      |

A published event shows to everyone, so a refused change
there is 403, not 404. Proved by PermissionMatrixTests.

## Refusals

- Hidden event: 404, so its number reveals nothing.
- Visible but not theirs: 403.
- Signed out: sent to sign in.
- A signed-in refusal is recorded as a refused
  AuditEvent; an unknown number is not.

## Organizer access

- Added only for active members of Organizers.
- The last current organizer of a draft or published
  event is not removed; a cancelled event may lose all.
- Add and Remove on the Organizer access page ask for
  the password again (allauth re-authentication, five
  minutes). The admin does not yet: Chapter 59.

## Audit

AuditEvent (app audit): actor, action, outcome (allowed
or refused), target, detail (field names, member ids),
time. Written in the action's own transaction. Rows are
ordinary database rows, not tamper-proof. Retention,
redaction, and alerts: Chapter 65.

## Registrations (Chapter 31)

- A member registers, sees, and cancels only their own
  places. Another member's place: 404, and the attempt
  is recorded.
- The attendee list shows contact details, so only the
  event's current organizers and the administrator
  (registrations.view_registration) may open it:

| Person          | Published event | Draft   |
|-----------------|-----------------|---------|
| Visitor         | sign in         | sign in |
| Member          | 403             | 404     |
| Staff only      | 403             | 404     |
| Other organizer | 403             | 404     |
| Administrator   | ok              | ok      |
| Superuser       | ok              | ok      |
| Organizer       | ok              | ok      |

Proved by AttendeeMatrixTests. See registration.md.

## Planned rows

- Chapter 46: check-in by assigned organizers; a token
  never replaces these checks.
- Chapter 50: the same rules behind the API.
- Chapter 70: volunteers, a role separate from
  organizers.
