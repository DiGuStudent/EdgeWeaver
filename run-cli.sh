#!/usr/bin/env bash
# Headless EdgeWeaver CLI.  Override PYTHON if your PyQt6 is elsewhere.
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-/usr/bin/python3}"
exec "$PYTHON" -m edgeweaver.cli "$@"
