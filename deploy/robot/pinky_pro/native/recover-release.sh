#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLIC_KEY="${ROSY_RELEASE_PUBLIC_KEY:-/etc/rosy/trusted-release-keys/rosy-release-2026-01.pem}"

# This script is installed in /opt/rosy/native-runtime, outside the mutable
# current link.  It must still exist when an interrupted switch breaks current.
exec python3 -B "$SCRIPT_DIR/native_release.py" \
  --root "${ROSY_ROOT:-/}" \
  --public-key "$PUBLIC_KEY" \
  recover
