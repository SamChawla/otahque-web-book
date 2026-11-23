"""Compare Otahque's database with a copy, table by table.

Run: uv run python compare_databases.py OTHER
OTHER is a SQLite file, such as db-before-32.sqlite3, or the
name of another PostgreSQL database on the same server.
"""
import os
import sys

import django
from django.conf import settings

# Rows that migrations make again, with new ids.
REMADE = {'contenttypes.contenttype', 'auth.permission',
          'auth.group', 'auth.group_permissions'}
# Rows left behind on purpose.
NOT_MOVED = {'sessions.session': 'everyone signs in again'}


def other_database(name):
    """Return settings for the database to compare with."""
    if name.endswith('.sqlite3'):
        return {'ENGINE': 'django.db.backends.sqlite3',
                'NAME': settings.BASE_DIR / name}
    return {**settings.DATABASES['default'], 'NAME': name}


def value(obj, field):
    """Return a field's value; a related row by natural key."""
    if field.is_relation:
        related = getattr(obj, field.name)
        if hasattr(related, 'natural_key'):
            return related.natural_key()
    return field.value_from_object(obj)


def rows(model, alias, limit):
    """Return up to limit rows of a model, as tuples."""
    remade = (model._meta.label_lower in REMADE
              or model._meta.auto_created)
    fields = [f for f in model._meta.concrete_fields
              if not (remade and f.primary_key)]
    found = [tuple(value(obj, f) for f in fields)
             for obj in model._default_manager.using(alias)
             .order_by('pk')[:limit]]
    return sorted(found, key=repr) if remade else found


def main():
    """Print one line per table; return how many differ."""
    from django.apps import apps
    from django.db import connections

    here = connections['default']
    print(f'here:  {here.vendor} {here.settings_dict["NAME"]}')
    print(f'other: {sys.argv[1]}')
    differ = 0
    for model in apps.get_models(include_auto_created=True):
        label = model._meta.label_lower
        table = model._meta.db_table
        if label in NOT_MOVED:
            print(f'skip  {table}: {NOT_MOVED[label]}')
            continue
        a = model._default_manager.using('default').count()
        b = model._default_manager.using('other').count()
        # Ten rows each, or every row that migrations remake.
        limit = 10 if label not in REMADE else None
        same = a == b and (rows(model, 'default', limit)
                           == rows(model, 'other', limit))
        differ += not same
        mark = 'ok  ' if same else 'DIFF'
        print(f'{mark}  {table}: {a} / {b}')
    print('every table matches' if not differ
          else f'{differ} table(s) differ')
    return differ


if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE',
                          'config.settings')
    # Add the second database before Django reads the list.
    settings.DATABASES['other'] = other_database(sys.argv[1])
    django.setup()
    sys.exit(1 if main() else 0)
