# Sessions, cookies, and time zones: low-level design

Status: Drafted in Chapter 28, for review. Not approved.

## What each place holds

- sessionid cookie: the session key only. Two weeks;
  until the browser closes for a member who signs in
  without ticking Remember me. HttpOnly, SameSite=Lax.
- django_session row: who is signed in, and
  places_only. Two weeks from the last change.
- messages cookie: signed messages, until shown.
- otahque_tz cookie: the browser's zone, one year.
- Database: events, registrations, and profiles.

Registrations and places left are always read from the
database. The session holds only what may be lost.

## The places filter

- /events/?places=1 saves places_only = True in the
  session; ?places=0 saves False. A plain visit saves
  nothing, so no session is made for a visitor.
- Signing out flushes the session, and the filter with
  it. An expired session is the same as none.

## Time zones

- site.js writes otahque_tz on every page (path /,
  max-age one year, SameSite=Lax; not HttpOnly, not
  signed: the browser writes it).
- accounts.timezones.resolve_timezone(request): the
  profile's zone, then the cookie if it names a real
  zone, then UTC. to_user_time() converts one value.
- accounts.middleware.TimezoneMiddleware, after
  AuthenticationMiddleware, activates that zone; admin
  pages are skipped and stay in UTC (Chapter 23).
- events/when.html shows the venue's time, and "Your
  time" when Event.differs_for() finds another UTC
  offset at the start.
- EventForm and CopyForm clean under UTC (UtcCleaning);
  in_zone() reads typed times in the event's zone.

## Signing

Signed values (the messages cookie, signing.dumps())
can be read but not changed; TimestampSigner adds an
expiry; SECRET_KEY_FALLBACKS keeps old values valid
during a key change. Nothing is encrypted.

## Open

- Secure cookie settings: Chapter 63.
- Session timeouts and SameSite review: Chapter 59.
- Tokens for outside clients: Chapter 50.
- The zone cookie in a consent notice: a later chapter.
