#!/usr/bin/env bash
# Launch NetAlertZ without Docker. Creates .venv and installs dependencies once.
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "NetAlertZ: $PYTHON was not found. Install Python 3.10+ and try again." >&2
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo "Creating virtual environment in .venv …"
    "$PYTHON" -m venv .venv
fi

# Keep the environment in sync with requirements.txt. This is a no-op when the
# pinned Textual version is already installed.
if ! .venv/bin/python -c "import textual" >/dev/null 2>&1; then
    echo "Installing dependencies …"
    .venv/bin/python -m pip install --quiet --upgrade pip
    .venv/bin/python -m pip install --quiet -r requirements.txt
fi

exec .venv/bin/python -m netalertz "$@"
