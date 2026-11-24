# How Otahque is tested

## Where tests live

Each app has a `tests/` package. Its `test_<app>.py` holds
the tests of the earlier chapters; a new subject gets its
own `test_<subject>.py` beside it. Helpers that more
than one app's tests use live in `config/helpers.py`, which
the runner does not collect: its name does not start with
"test". Helpers for one app stay in that app's tests.

## Which tool for which question

| Question | Tool |
|---|---|
| Is this function right, no database? | `SimpleTestCase` |
| Is this rule right, with the database? | `TestCase` |
| Does this page answer as it should? | the test client |
| Does this middleware work alone? | `RequestFactory` |
| What if two requests overlap? | `TransactionTestCase` |
| Does a test class share costly rows? | `setUpTestData` |

`TestCase` undoes each test inside a transaction, so other
connections never see its rows; race tests need
`TransactionTestCase`, which commits and empties the tables
afterwards, and PostgreSQL.

## Commands

    uv run python check.py
    uv run python manage.py test --parallel --reverse
    uv run coverage run manage.py test --parallel
    uv run coverage combine
    uv run coverage report

Coverage is read, not targeted: a line that ran is not a
rule that was checked. docs/acceptance/M2.md names the
tests behind each rule.
