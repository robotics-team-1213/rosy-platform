#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 1 ]] || { echo "usage: activate-release.sh YYYY.MM.DD-NNN" >&2; exit 2; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLIC_KEY="${ROSY_RELEASE_PUBLIC_KEY:-/etc/rosy/trusted-release-keys/rosy-release-2026-01.pem}"

exec python3 -B "$SCRIPT_DIR/native_release.py" \
  --root "${ROSY_ROOT:-/}" \
  --public-key "$PUBLIC_KEY" \
  activate --release-id "$1"
