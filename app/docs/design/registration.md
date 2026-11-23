# Registration and cancellation: low-level design

Status: Drafted in Chapter 31, for review. Not approved.
Rules: PR-1 (one active place each), PR-2 (cancel your
own place; history kept), PR-3 (no more places than
capacity), PR-4 (own places; organizers see their
events' lists). Timing: Chapter 2, decided 21 November
2026.

## Registration times (on Event)

- registration_opens_at: optional; blank means open as
  soon as the event is published. Inclusive.
- registration_closes_at: needed to publish. Exclusive:
  at that instant registration has closed.
- cancellation_deadline: needed to publish. Cancelling
  stays possible until the start; from the deadline on,
  a cancellation counts as late.
- Opening before closing; closing and deadline no later
  than the start (CHECK constraints). Typed in the
  event's own zone; moved with the start by a copy.

## Who may register, and why not

Event.registration_problems(member, now) returns codes,
checked in this order. Test: RegistrationRuleTests.

| Code               | When                                   |
|--------------------|----------------------------------------|
| already_registered | member holds an active place           |
| not_published      | a draft or a cancelled event           |
| not_open           | before registration_opens_at           |
| closed             | at or after registration_closes_at     |
| full               | active places reach capacity           |
| unverified         | the account email is not confirmed     |
| phone_missing      | phone_required, and no number on file  |

No code: Event.register() makes the place, inside a
transaction. A repeat finds the place and says "You
already have a place". The unique rule
registration_one_active (code already_registered) is the
backstop; only that error is read as a repeat.

## States of a place

| State     | Counts as taken | Shown to the member      |
|-----------|-----------------|--------------------------|
| active    | yes             | You have a place         |
| cancelled | no              | Cancelled, or Cancelled  |
|           |                 | late (from the deadline) |

Lateness is worked out from cancelled_at and the
deadline; no field stores it. Registering again after
cancelling makes a new row, under the same rules.
Registration.cancel(now) changes only an active row, in
one UPDATE: a repeat changes nothing.

## Pages

- POST events/<id>/register/: Register (signed in).
- GET/POST events/<id>/register/phone/: asks once for a
  phone number, keeps it on the Profile, then registers.
- GET registrations/: My registrations.
- GET/POST registrations/<id>/cancel/: confirm, cancel.
- GET events/<id>/registrations/: the attendee list.

## Who sees what

- A member: their own places only. Another member's
  place: 404, recorded as a refused AuditEvent.
- The attendee list (display name, email, phone, time
  of registration; counts of cancellations and late
  ones): the event's current organizers and the
  administrator. Members are told at registration.
- No public attendee list; contacts on no other page.

## Requests at the same moment (Chapter 33)

- register(), publish(), cancel(), and the edit save
  lock the event row (Event.locked(): select_for_update
  inside atomic) and check the locked row, never the
  copy a view loaded.
- Requests for one event take turns; requests for
  different events do not wait for each other.
- A request waits at most LOCK_TIMEOUT (3 s), then is
  told "Otahque is busy. Please try again." with
  nothing changed. Only PostgreSQL's lock-not-available
  error (55P03) means busy; no automatic retry.
- The same member twice: the one-active-place rule and
  the inner atomic() (Chapter 31) give one place.
- Cancelling a place does not lock the event: a count
  made while a place is being given back may still see
  it. That can only refuse a place, never oversell.
- Proved by RaceTests (TransactionTestCase, threads,
  PostgreSQL only; skipped on SQLite).

## Not here

- Emails to members: Chapters 43-44.
- Waitlist and check-in: Chapter 46.
- Registration questions: Chapter 38; download: 41.
