#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ca_project.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Make sure it's installed:\n"
            "    pip install django django aiofiles uvicorn\n"
            "    pip install tiny-ca tiny-ca-routes"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
