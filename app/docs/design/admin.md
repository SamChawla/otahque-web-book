# Otahque admin site

Status: Drafted in Chapter 23, for review.
Who: the community administrator only. Organizers use
Otahque's own pages (Chapter 26); visitors and members
never use the admin site.

## What the admin may do

- Events: view, add, and change; delete only an event
  with no registrations or assignments; no bulk actions.
  Times are typed in UTC; the list and the event page
  show the local start in the event's own zone.
- Registrations: view only. Places are created and
  cancelled by Otahque's own pages (Chapters 31, 33).
- Organizer assignments: view, add (active members of
  Organizers only), and remove with the Remove selected
  organizers action, which keeps the last organizer of a
  live event; never deleted (PR-6). Chapter 30.
- Users: view and change email, display name, active,
  staff, groups, and permissions. An administrator who is
  not a superuser changes only Organizers membership;
  staff and permissions are read-only (Chapter 30). No
  add page (accounts come from createsuperuser or
  create_user until Chapter 27), no delete (deactivate
  instead), and the password is never shown or set here.
- Log entries: view only. The audit log of admin saves.

## What the admin does not protect

- The admin log records admin saves only: not the
  shell, scripts, migrations, Otahque's own pages, or
  sign-ins. Its rows can be changed by anyone with
  database access. Business audit trail: AuditEvent from
  Chapter 30, completed in Chapter 65.
- Permissions are per model, not per event, so the
  admin cannot limit an account to its own events.
- A rule that is not in the model is not applied here.

## Best practices

- Done (Chapter 23): admin path from DJANGO_ADMIN_URL,
  not the guessable admin/, in each deployment.
- Done (Chapter 23): per-model limits in code, each
  proved by a test, superusers included.
- Done (Chapter 23): password never shown or set on
  the user page.
- Done (Chapter 23): read-only audit log page.
- Done (Chapter 30): an Administrators group with only
  the permissions the role needs, one staff account per
  person; no shared superuser accounts.
- Done (Chapter 29): sign-in through allauth's page
  (secure_admin_login), with its rate limits and
  two-factor sign-in for staff who turn it on.
- Planned (Chapter 59): two-factor required for every
  staff account.
- Planned (Chapters 59, 60): sign-in rate limits,
  HTTPS only, secure cookies, and security headers.
- Planned (Chapter 63): deployment review of the admin
  path, staff accounts, and access logs.
- Rule: the superuser password is used locally only;
  deployed accounts are created per person.
