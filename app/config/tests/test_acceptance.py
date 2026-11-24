"""The acceptance trace names only tests that exist."""
import re
from importlib import import_module

from django.conf import settings
from django.test import SimpleTestCase

TRACE = settings.BASE_DIR / 'docs/acceptance/M2.md'
APPS = ['accounts', 'audit', 'config', 'events',
        'registrations']
NAME = re.compile(r'`(\w+Tests)\.(test_\w+)`')


def test_classes():
    """Yield every test class in the apps' tests packages."""
    for app in APPS:
        folder = settings.BASE_DIR / app / 'tests'
        for path in sorted(folder.glob('test*.py')):
            module = import_module(f'{app}.tests.{path.stem}')
            yield from vars(module).values()


class TraceTests(SimpleTestCase):
    """docs/acceptance/M2.md, checked against the tests."""

    def test_every_named_test_exists(self):
        names = NAME.findall(TRACE.read_text(encoding='utf-8'))
        self.assertGreater(len(names), 40)
        found = {(c.__name__, m) for c in test_classes()
                 if isinstance(c, type) for m in dir(c)}
        missing = [f'{c}.{m}' for c, m in names
                   if (c, m) not in found]
        self.assertEqual(missing, [])
