"""Run the checks every change must pass, as CI does.

Usage: uv run python check.py
Runs Django's system checks, the migration check, and the
whole test suite, in that order. It stops at the first
check that fails and exits with that check's code, so CI
marks the run as failed.
"""
import subprocess
import sys

CHECKS = [
    ['manage.py', 'check'],
    ['manage.py', 'makemigrations', '--check', '--dry-run'],
    ['manage.py', 'test', '--parallel'],
]


def main():
    """Run each check; return the first failure's code."""
    for args in CHECKS:
        print('== python', ' '.join(args), flush=True)
        result = subprocess.run([sys.executable, *args])
        if result.returncode:
            print('== failed:', ' '.join(args))
            return result.returncode
    print('== all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
