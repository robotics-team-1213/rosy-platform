#!/bin/sh
# D-179 bench clear. Removes the marker, drop-in, and dev compose file.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -B "$SCRIPT_DIR/core_dev_overlay.py" clear "$@"
