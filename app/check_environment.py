import sys

import django

print(sys.version.split()[0])
print(sys.executable)
print(sys.prefix != sys.base_prefix)
print(django.get_version())
