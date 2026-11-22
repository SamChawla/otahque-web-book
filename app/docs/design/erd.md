# Otahque data model (ERD)

Status: Proposed, for review. No table exists yet.
Scope: the first release (one community, free events).
Sources: Chapter 2 rules PR-1 to PR-6.

## Diagram

~~~mermaid
erDiagram
    MEMBER ||--o{ REGISTRATION : "makes"
    EVENT ||--o{ REGISTRATION : "has"
    MEMBER ||--o{ ORGANIZER_ASSIGNMENT : "holds"
    EVENT ||--o{ ORGANIZER_ASSIGNMENT : "is run through"
    MEMBER ||--o| PROFILE : "has"
    MEMBER {
        int id PK
        text email UK
        text display_name
    }
    PROFILE {
        int id PK
        int user_id FK
        text timezone "IANA name, blank = not set"
        text phone "E.164, blank = not given"
    }
    EVENT {
        int id PK
        text title
        text description "blank for a draft, needed to publish"
        datetime starts_at "an instant, in UTC"
        datetime ends_at "after starts_at, in UTC"
        text timezone "IANA name"
        text location
        int capacity "more than 0"
        text status "draft, published, cancelled"
        datetime registration_opens_at "blank = on publication"
        datetime registration_closes_at "needed to publish"
        datetime cancellation_deadline "needed to publish"
        bool phone_required
    }
    REGISTRATION {
        int id PK
        int event_id FK
        int member_id FK
        text status "active or cancelled"
        datetime registered_at
        datetime cancelled_at "empty until cancelled"
    }
    ORGANIZER_ASSIGNMENT {
        int id PK
        int event_id FK
        int member_id FK
        datetime assigned_at
        datetime revoked_at "empty while current"
    }
~~~

## Rules the structure holds

- PR-1: at most one active registration per member and
  event (partial unique index on event_id and member_id
  where status is active).
- PR-1, PR-2: a registration refers to a real event and
  a real member (foreign keys).
- PR-2: a cancelled registration keeps its row, with
  its status and cancelled_at; it is never deleted.
- PR-4: at most one current assignment per member and
  event (partial unique index where revoked_at is empty).
- Capacity is more than 0; an event ends after it
  starts; each status comes from its fixed list
  (CHECK constraints).
- PR-2: cancelled_at is filled exactly when status is
  cancelled (CHECK constraint).
- A cancellation is never earlier than its registration,
  and a revocation never earlier than its assignment
  (CHECK constraints).
- Registration opens before it closes; closing and the
  cancellation deadline are no later than the start
  (CHECK constraints, Chapter 31).
- Email addresses are stored in lower case, so two
  that differ only in letter case are one member
  (CHECK constraint; decided in Chapter 21).
- Intent: deleting an event or member that has
  registrations is refused, so history survives.

## Rules that need more than structure

- PR-3, never more active places than capacity:
  transactions, Chapter 33.
- PR-4, own registrations and assigned events only:
  Chapters 27 and 30.
- PR-5, valid details before publication; drafts hidden:
  Chapters 21, 25, and 26.
- PR-6, access administration: Chapters 23 and 30.

## Django implementation mapping (proposed)

The Member entity is implemented by the Django model
accounts.User, named by AUTH_USER_MODEL. Django's own
fields (password hash, last sign-in, active and staff
flags, permissions) serve the framework; they add no
product requirement to Member. See
docs/adr/ADR-002-user-model.md.

## Open questions

- Who appoints organizers, and must an event have one?
- What happens to active registrations when an event
  is cancelled? (Chapter 26: they stay as they are;
  Chapters 43-44 decide what members are told.)

Answered in Chapter 31: contact details are the email
and an optional phone number on the Profile, which an
event may require; registration times are on Event.

## Out of scope for this release

- Category and tag: not first-release requirements.
- Venue: the location is an attribute of the event;
  an online event records Virtual as its location.
- Attendance, check-in, and waitlists: Chapter 46.
- Communities and tenancy: Chapters 67 and 68.
- Audit records: Chapter 65.
