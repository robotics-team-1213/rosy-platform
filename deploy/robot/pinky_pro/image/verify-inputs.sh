#!/usr/bin/env bash
# Refuse to build from inputs nobody has verified.
#
# Every `verified: false` in the lock file is an assumption the design rests
# on and no one has checked. Building on them produces an image whose
# provenance cannot be stated, which is the one thing section 7.2 asks for.
set -euo pipefail

LOCK="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/inputs.lock.yaml}"
[[ -f "$LOCK" ]] || { echo "missing lock file: $LOCK" >&2; exit 1; }

# Comment lines explain the markers; only settings count.
settings="$(grep -vE '^[[:space:]]*#' "$LOCK" || true)"
unverified="$(echo "$settings" | grep -n 'verified: false' || true)"
nulls="$(echo "$settings" | grep -nE ': *null$' || true)"

status=0
if [[ -n "$unverified" ]]; then
    echo "unverified assumptions in $LOCK:" >&2
    echo "$unverified" >&2
    status=1
fi
if [[ -n "$nulls" ]]; then
    echo "unpinned inputs in $LOCK:" >&2
    echo "$nulls" >&2
    status=1
fi

if ((status == 0)); then
    echo "all inputs pinned and verified"
fi
exit "$status"
