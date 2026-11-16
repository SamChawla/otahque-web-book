# ADR-002: A custom user model that signs in by email

## Status

Proposed, November 2026. Not yet reviewed or accepted.

## Context

Members sign in with a unique email address and are shown
by a display name; the ERD (docs/design/erd.md) gives a
member no username. Django's default user signs in with a
username and does not require a unique email. The user
model must be chosen before the first migration, because
Django cannot switch it automatically once tables exist.

## Options

- A: Django's default user, with an extra sign-in backend
  that accepts an email address.
- B: AbstractUser, with username removed and email unique.
- C: AbstractBaseUser with PermissionsMixin, declaring each
  remaining field.

## Decision

Option C. accounts.User signs in with a unique email, has
a required display_name, and is created through
UserManager. AUTH_USER_MODEL names it. It implements the
ERD's Member entity.

## Consequences

Every stored field is declared or comes from a small,
documented class. There is more code than option B, no
get_full_name() or email_user(), and the admin site
(Chapter 23) needs a custom user admin. Other code refers
to the model through settings.AUTH_USER_MODEL or
get_user_model(). is_staff and is_superuser are Django
flags, not Otahque's organizer or administrator roles.

## Open questions

Whether addresses that differ only in letter case are one
account is decided in Chapter 21, before sign-up. Until
then, only the domain is lowercased.

## Revisit if

Members need a public username, or sign-in moves to an
outside identity provider. Changing the model after the
first migration needs a planned data migration.

## Related

ADR-001; docs/design/erd.md; PR-4 and PR-6 (Chapter 2).
