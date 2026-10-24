#!/usr/bin/env python
"""Django command-line utility."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Django o‘rnatilmagan. Virtual muhitni faollashtiring va "
            "`pip install -r requirements-dev.txt` ni bajaring."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
