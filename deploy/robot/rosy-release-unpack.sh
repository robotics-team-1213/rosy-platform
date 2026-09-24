#!/usr/bin/env bash
# D-225: unpack a signed native release tarball into /opt/rosy/releases/<id>
# atomically (extract into a sibling temp directory, then rename). Run as
# root (rosy-release-push.ps1 invokes it with `sudo -n`).
#
# rosy-release-push.ps1 only re-checks the signature and file hashes locally,
# on the operator PC, before scp'ing; native_release.py's own verify() (the
# full manifest/target/runtime check) does not run until activation. Between
# unpack and activate the payload sits on disk as root, so this script treats
# the tarball as untrusted content and, on top of the copy itself:
#   - lists every member's type and name (via python3's tarfile module, not
#     line-oriented `tar -t` text, which a newline embedded in a member name
#     can split across lines and dodge a per-line check) before writing
#     anything, and allowlists only regular files and directories -- a
#     symlink, hardlink, fifo, device node, or any other type is refused
#     outright, along with an absolute path, a ".." component, or a control
#     character (including a newline) anywhere in a name;
#   - extracts with --no-same-owner/--no-same-permissions and then reasserts
#     root:root ownership and strips setuid/setgid/group-or-other-write bits,
#     so an unsigned tar header cannot hand the payload a mode or owner that
#     survives past this script.
#
# A release id that already exists is left alone when its SHA256SUMS bytes
# match the tarball's copy AND the files on disk still hash to that list (the
# push is a safe repeat), refused when the SHA256SUMS differ (a different
# release must never silently overwrite one already on the device), and
# reported as damaged -- with a repair hint -- when the SHA256SUMS match but
# a file on disk no longer does.
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

# A run that died mid-extract (killed session, power loss) leaves its scratch
# directory behind under its own dotted name; nothing else in RELEASES_DIR is
# named .tmp-*, so clearing them here at the start is always safe.
find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -name '.tmp-*' -exec rm -rf -- {} + 2>/dev/null || true

TARGET="$RELEASES_DIR/$RELEASE_ID"
TMP="$RELEASES_DIR/.tmp-$RELEASE_ID-$$"
cleanup() { rm -rf -- "$TMP"; }
trap cleanup EXIT

rm -rf -- "$TMP"
mkdir -p "$TMP"

# Refuse before writing a single byte. Allowlisted, not denylisted: only a
# regular file or a directory passes; a symlink, hardlink, fifo, char/block
# device, or anything else is rejected regardless of its name. python3's
# tarfile module parses the real member table (name, type) rather than the
# line-oriented text `tar -t`/`tar -tv` print, so a name containing a
# newline cannot split across two lines and slip past an absolute-path or
# ".." check the way it could with a line-by-line text scan.
python3 - "$TARBALL" <<'PY'
import re
import sys
import tarfile

CONTROL = re.compile(r"[\x00-\x1f\x7f]")
KIND = {
    tarfile.SYMTYPE: "symlink",
    tarfile.LNKTYPE: "hardlink",
    tarfile.FIFOTYPE: "fifo",
    tarfile.CHRTYPE: "character device",
    tarfile.BLKTYPE: "block device",
}


def reject(reason: str) -> None:
    print(f"TARBALL_ENTRY_UNSAFE: {reason}", file=sys.stderr)
    sys.exit(1)


with tarfile.open(sys.argv[1], "r:gz") as tar:
    for member in tar.getmembers():
        name = member.name
        if CONTROL.search(name):
            reject(f"control character in entry name: {name!r}")
        if name.startswith("/"):
            reject(f"absolute path entry: {name}")
        if any(part == ".." for part in name.split("/")):
            reject(f"path traversal entry: {name}")
        if not (member.isreg() or member.isdir()):
            reject(f"{KIND.get(member.type, f'type {member.type!r}')} entry: {name}")
PY

tar --no-same-owner --no-same-permissions -xzf "$TARBALL" -C "$TMP"

# Reassert ownership/mode rather than trust either the tarball or
# --no-same-owner's umask-derived result: this is what native_release.py's
# verify() on activation ends up trusting was never changed after signing.
# chown needs real root; a non-root caller (this script's own tests) still
# gets the mode normalization below.
if [[ "$(id -u)" -eq 0 ]]; then
  chown -R root:root -- "$TMP"
fi
chmod -R go-w,u-s,g-s -- "$TMP"

if [[ -e "$TARGET" ]]; then
  if [[ -L "$TARGET" ]] || [[ ! -d "$TARGET" ]]; then
    echo "NATIVE_RELEASE_PATH: $TARGET is not a plain directory" >&2
    exit 1
  fi
  if cmp -s "$TMP/SHA256SUMS" "$TARGET/SHA256SUMS" 2>/dev/null; then
    if (cd "$TARGET" && sha256sum -c SHA256SUMS --status) 2>/dev/null; then
      echo "release $RELEASE_ID already present with matching content" >&2
      rm -f -- "$TARBALL"
      exit 0
    fi
    echo "RELEASE_DAMAGED: $RELEASE_ID on disk no longer matches its own SHA256SUMS; repair hint: rm -rf $TARGET and re-run this push to reinstall it" >&2
    exit 1
  fi
  echo "RELEASE_CONFLICT: $RELEASE_ID already exists with different content" >&2
  exit 1
fi

mv -T -- "$TMP" "$TARGET"
trap - EXIT
sync -f -- "$TARGET" 2>/dev/null || sync
rm -f -- "$TARBALL"
echo "unpacked $RELEASE_ID"
