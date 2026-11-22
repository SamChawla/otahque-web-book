# Passwords, sign-in codes, and two factors: design

Status: Drafted in Chapter 29, for review. Not approved.

## Passwords

- At least 15 characters (NIST SP 800-63B-4, 3.1.1.2,
  for a password used alone), not like the email or
  name, not a common password, not all digits. No
  other composition rules; no forced periodic change.
- Existing shorter passwords keep working; the rule
  applies whenever a password is chosen, changed,
  reset, or set.
- Change: the browser that changes it stays signed in;
  every other browser is signed out.
- A member with no password (a GitHub sign-up) may set
  one from the profile, or through a reset.

## Reset

- Every address gets the same page. Only a member's
  address gets an email (ACCOUNT_EMAIL_UNKNOWN_ACCOUNTS
  is False); inactive accounts get none.
- The link works once and for one hour
  (PASSWORD_RESET_TIMEOUT). A new password, a new
  address, or a sign-in ends it.
- A reset does not sign the member in (OWASP Forgot
  Password Cheat Sheet); the new password does.

## Notices

- Password changed, set, or reset; email changed;
  two-factor turned on or off: one email each, with
  the IP address, browser, and time.

## Sign-in by code

- An emailed code, eight characters, for ten minutes,
  three tries, only in the browser that asked.
- It proves control of the mailbox, as a reset email
  does: a convenience, not a second factor (NIST
  SP 800-63B-4, 3.1.3.1). Two-factor still applies
  after it.

## Two-factor sign-in

- Optional for members; required for staff from
  Chapter 59. An authenticator app (TOTP, 30-second
  codes) and ten single-use recovery codes. Passkeys
  later, after HTTPS (Chapter 63), as an optional
  extra.
- Turning it on asks for the password again and needs
  a confirmed email address.
- A code is accepted once. allauth remembers used
  codes in the cache; OneUseActivateTOTPForm also
  marks the activation code. It calls the private
  TOTP._mark_code_used(): a test fails if an upgrade
  changes it.

## Known risks

- The authenticator secret, and the seed the
  recovery codes are made from, are stored as plain
  text in mfa_authenticator. A copy of the database,
  a backup, or an export gives every member's codes.
  Exports leave the table out (Chapter 41); Chapter
  59 encrypts it before any deployment (Chapter 63).
- Used codes and rate limits live in the local-memory
  cache, one per process. Before more than one
  process, a shared cache (Chapter 57, Redis in 62).
- Until Chapter 43, a known address may answer more
  slowly than an unknown one, because only it sends
  an email.

## Admin

- The admin's sign-in page sends staff to allauth's,
  so limits and two-factor apply. Staff without
  two-factor still enter until Chapter 59.
