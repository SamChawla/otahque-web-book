# ADR-003: Member accounts with django-allauth

## Status

Proposed, November 2026 (Chapter 27). The choice of
django-allauth is the user's decision of 13 November 2026;
this record is not yet reviewed or accepted.

## Context

Members need to sign up, sign in, and sign out on Otahque's
own pages, with the email-only user of ADR-002, and to sign
in with Google or GitHub. Accounts must not be linked by an
email address alone, temporary addresses are refused, and
two-factor sign-in follows in Chapter 29.

## Options

- A: Django's own views (LoginView, LogoutView) and forms
  written for sign-up; social sign-in added later by hand.
- B: social-auth-app-django for providers, with Django's
  views for everything else.
- C: django-allauth for sign-up, sign-in, sign-out, email
  addresses, providers, rate limits, and later two-factor
  sign-in.

## Decision

Option C: `django-allauth[socialaccount]==65.22.1`, with
`disposable-email-domains==0.0.295` for refusing temporary
addresses. Email-only settings (no username field); an
extra sign-up form for the display name and time zone; an
account adapter that refuses disposable domains; provider
credentials read from .env; automatic sign-up through a
provider turned off, so every member gives a display name;
an email already registered is never connected without
signing in to that account first.

## Consequences

- Eleven more packages (the social extra brings requests,
  pyjwt, cryptography, and their dependencies); each pin is
  upgraded on purpose, with the test suite run first.
- allauth's templates are overridden in templates/allauth/
  to use Otahque's layout and field styles.
- The admin's own sign-in page bypassed allauth until
  Chapter 29 wrapped it with secure_admin_login.
- Chapter 29 adds the mfa extra:
  `django-allauth[socialaccount,mfa]==65.22.1`, with
  qrcode, fido2, and (on Windows) colorama.
- Rate limits use the cache; one process is enough locally,
  and a shared cache is needed in production (Chapter 57).

## Upgrade checklist

- Run the whole test suite before and after.
- accounts.forms.OneUseActivateTOTPForm calls allauth's
  private TOTP._mark_code_used(); TwoFactorTests must
  still pass, or remove the form if allauth now marks
  the activation code itself.

## Revisit when

allauth stops supporting the pinned Django series, a
provider changes its sign-in rules, or the community needs
sign-in that allauth cannot provide.
