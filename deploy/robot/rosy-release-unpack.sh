#!/usr/bin/env bash
# D-230: unpack a signed native release tarball into /opt/rosy/releases/<id>
# atomically (extract into a sibling temp directory, then rename). Run as
# root (rosy-release-push.ps1 invokes it with `sudo -n`).
#
# A release id that already exists is left alone when its SHA256SUMS bytes
# match the tarball's copy (the push is a safe repeat) and refused when they
# differ (a different release must never silently overwrite one already on
# the device). native_release.py itself still verifies the signature and
# manifest before activation; this script only places files.
set -euo pipefail

usage() {
  echo "usage: $0 RELEASE_ID TARBALL_PATH [RELEASES_DIR]" >&2
  exit 2
}

[[ $# -eq 2 || $# -eq 3 ]] || usage
RELEASE_ID="$1"
TARBALL="$2"
RELEASES_DIR="${3:-/opt/rosy/releases}"

[[ "$RELEASE_ID" =~ ^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$ ]] \
  || { echo "RELEASE_ID_INVALID: expected YYYY.MM.DD-NNN, got $RELEASE_ID" >&2; exit 2; }
[[ -f "$TARBALL" ]] || { echo "TARBALL_MISSING: $TARBALL is not a file" >&2; exit 2; }

mkdir -p "$RELEASES_DIR"
TARGET="$RELEASES_DIR/$RELEASE_ID"
TMP="$RELEASES_DIR/.tmp-$RELEASE_ID-$$"
cleanup() { rm -rf -- "$TMP"; }
trap cleanup EXIT

rm -rf -- "$TMP"
mkdir -p "$TMP"
tar -xzf "$TARBALL" -C "$TMP"

if [[ -e "$TARGET" ]]; then
  if [[ -L "$TARGET" ]] || [[ ! -d "$TARGET" ]]; then
    echo "NATIVE_RELEASE_PATH: $TARGET is not a plain directory" >&2
    exit 1
  fi
  if cmp -s "$TMP/SHA256SUMS" "$TARGET/SHA256SUMS" 2>/dev/null; then
    echo "release $RELEASE_ID already present with matching content" >&2
    rm -f -- "$TARBALL"
    exit 0
  fi
  echo "RELEASE_CONFLICT: $RELEASE_ID already exists with different content" >&2
  exit 1
fi

mv -T -- "$TMP" "$TARGET"
trap - EXIT
rm -f -- "$TARBALL"
echo "unpacked $RELEASE_ID"
