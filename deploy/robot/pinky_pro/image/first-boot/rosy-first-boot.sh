#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# One run at a time: the boot unit, the retry timer and a manual start share
# the same files. 200 s outlasts a full run (120 s Wi-Fi budget plus file work).
exec flock -w 200 /run/rosy-first-boot.lock python3 "$SCRIPT_DIR/rosy-first-boot.py" \
  --root "${ROSY_ROOT:-/}" \
  --bundle "${ROSY_PROVISION_BUNDLE:-/boot/firmware/rosy-provision/provision.json}" \
  "$@"
