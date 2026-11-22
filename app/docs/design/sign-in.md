# Sign-up and sign-in: low-level design

Status: Drafted in Chapter 27, for review. Not approved.
Library: django-allauth (ADR-003), with accounts.User
(ADR-002).

## Pages

- /accounts/signup/: email, display name, time zone
  (optional), password twice. allauth's form plus
  accounts.forms.SignupForm. The email passes Django's
  validator, then AccountAdapter.clean_email(): refused if
  its domain is on the disposable-domains list and not in
  EMAIL_DOMAINS_ALLOWED. The address is stored in lower
  case (Chapter 21). A confirmation email is sent;
  verification is optional until Chapter 43.
- /accounts/login/: email (any letter case) and password.
  The session key changes on sign-in. Rate limits apply.
- /accounts/logout/: GET asks; POST signs out.
- /accounts/profile/: login required; edits the signed-in
  member's display name and Profile.timezone; reads no id
  from the address, so no other member can be reached.
  Profile.of(user) makes the profile the first time.
- /accounts/email/, /accounts/password/...: allauth's
  pages; taught in Chapter 29.

## Providers

- Google and GitHub, shown only when their client IDs are
  in .env; secrets never in Git or the database.
- A first sign-in shows the sign-up form (automatic
  sign-up is off), so a display name is always given.
- An email that already has an account: "An account already
  exists with this email address. Please sign in to that
  account first, then connect your ... account." Nothing is
  linked by email alone.
- A signed-in member connects a provider at
  /accounts/3rdparty/.

## Open

- Mandatory verification, with existing members marked
  verified: Chapter 43.
- Password change and reset, two-factor sign-in, and the
  admin's sign-in page: Chapter 29.
- Shared rate limits across processes: Chapter 57.
- Profile image: Chapter 42.
