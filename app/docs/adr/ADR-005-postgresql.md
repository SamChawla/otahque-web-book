# ADR-005: PostgreSQL as Otahque's database

## Status

Proposed, November 2026 (Chapter 32). The choices follow
the user's decisions of 22 November 2026 (Chapter 32
D32.1-D32.7); this record is not yet reviewed or accepted.

## Context

Since Chapter 18 Otahque has stored its data in SQLite, a
single file that one process writes at a time. Chapter 33
must prove that two members cannot both take the last
place, which needs a database that runs separate
connections at once and locks rows (select_for_update).
SQLite does neither. Readers' practice data, including
members' two-factor rows, must survive the move.

## Options

- A: PostgreSQL 18, installed natively on each computer,
  reached through psycopg 3.
- B: PostgreSQL in Docker now (Docker arrives in
  Chapter 62).
- C: a hosted PostgreSQL service on a free tier.
- D: stay on SQLite and simulate the race.

## Decision

A. PostgreSQL 18 (18.7 was the newest patch on 22 November
2026; 19.0 was three days old), installed natively, with
psycopg[binary] 3.3.9. Settings read DB_ENGINE, DB_NAME,
DB_USER, DB_PASSWORD, DB_HOST, and DB_PORT through
python-decouple; with DB_ENGINE empty Django uses SQLite,
so earlier checkpoints still run. The database and an
empty template for tests use the builtin C.UTF-8
collation, so text sorts by code point on every computer,
as it did on SQLite. Data moved once, with dumpdata in XML
(JSON keeps times only to the millisecond) and natural
foreign keys, leaving out rows that migrations make again
and sessions, then checked by compare_databases.py.

## Consequences

- Each reader installs and runs a database server, with
  a role and password kept in .env, never in Git.
- Tests create test_otahque from otahque_template; the
  role needs CREATEDB. The whole suite runs with
  --parallel at checkpoints, one app within steps.
- contains lookups become case-sensitive; Chapter 56's
  search uses icontains or full-text search.
- The dump and backup files hold password hashes, phone
  numbers, and two-factor secrets: kept outside the
  project and deleted after use.
- Chapter 33 can lock rows; Chapter 62 moves the server
  into a container; Chapter 66 adds connection pooling.

## Revisit

At the Django 6.2 upgrade or in Chapter 62, whichever
comes first: PostgreSQL 19, once hosts and the official
image offer it. If many readers cannot install a server,
reconsider B.
