"""Allow ``python -m netalertz``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
