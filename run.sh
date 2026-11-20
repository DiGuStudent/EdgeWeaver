#!/usr/bin/env bash
# Launch EdgeWeaver.  Override PYTHON if your PyQt6 is in another interpreter.
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-/usr/bin/python3}"
exec "$PYTHON" -m edgeweaver "$@"
