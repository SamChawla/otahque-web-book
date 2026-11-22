# ADR-004: Access rules in model methods and groups

## Status

Proposed, November 2026 (Chapter 30). The choice follows
the user's decisions of 18 November 2026 (Chapter 30
P2-P4); this record is not yet reviewed or accepted.

## Context

Otahque must answer "may this person do this to this
event?" on every page, in the admin, and later in the API.
The answer depends on a role (may organize) and on a
relationship (organizes this event). Django's model
permissions are per model, not per event, and its
ModelBackend returns no permissions for an object.

## Options

- A: model methods on Event (has_organizer,
  is_visible_to, can_be_edited_by), with Django groups
  for roles; every view calls one method.
- B: policy functions in a separate module.
- C: django-rules: predicates behind
  user.has_perm(perm, event).
- D: django-guardian: a permission row per member and
  event.

## Decision

Option A. Groups Organizers and Administrators are
created by a migration; events.manage_organizers guards
the Organizer access page.

## Consequences

- One place to read and test each rule; the matrix in
  docs/design/permissions.md has a test per row.
- has_perm(perm, obj) is not used: Django answers True
  for any active superuser before a backend is asked, so
  C would let every superuser manage every event.
- D would repeat OrganizerAssignment as permission rows.
- Changing a group's permissions needs a migration until
  Chapter 41 adds a command.

## Revisit when

- The API (Chapter 50) needs the rules in a shared
  module (option B).
- Communities (Chapters 67-68) make organizing rights
  per community.
