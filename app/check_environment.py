"""Show the Python, environment, Django, and database in use."""
import os
import sys

import django


def database():
    """Return the database Django uses here, and its version."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE',
                          'config.settings')
    django.setup()
    from django.db import connection

    with connection.cursor() as cursor:
        if connection.vendor == 'postgresql':
            cursor.execute('SHOW server_version')
        else:
            cursor.execute('SELECT sqlite_version()')
        return f'{connection.vendor} {cursor.fetchone()[0]}'


print(sys.version.split()[0])
print(sys.executable)
print(sys.prefix != sys.base_prefix)
print(django.get_version())
print(database())
