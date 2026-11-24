# Release checklist

Run it before tagging a release. Every box must be ticked on
the commit you tag; a box you cannot tick stops the release.

## Checks

- [ ] `git status --short` prints nothing.
- [ ] `uv run python check.py` ends with "all checks passed"
      (system checks, migrations, the whole suite).
- [ ] `uv run python manage.py test --parallel --reverse`
      passes too: no test depends on the order.
- [ ] The race tests ran, not skipped: the suite used
      PostgreSQL.
- [ ] CI is green for this commit.
- [ ] docs/acceptance/M2.md matches what was tested, its
      known limits included.

## UI, at 390 and 1280 pixels wide

On the event list, an event page, My registrations, and the
new event and edit pages:
- [ ] Nothing scrolls sideways; text and buttons fit.
- [ ] Tab reaches "Skip to the main content" first, then
      every link, field, and button in order, each with a
      visible ring.
- [ ] Register and cancel can be done with the keyboard
      alone (Tab, Enter, Space).
- [ ] Messages say in words what happened; colour only
      repeats it.
- [ ] Text is readable at 200% zoom.

## Then

- [ ] Tag the commit: `git tag -a v0.1.0 -m "..."`.
- [ ] Push the tag: `git push origin v0.1.0`.
