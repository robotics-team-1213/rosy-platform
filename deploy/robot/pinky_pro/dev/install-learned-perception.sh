#!/bin/bash
# D-373 decision 1: bench install of the learned-perception image layer on a
# card baked before it. Same hash-locked lines and same directory rule as the
# next image (customize-rootfs.sh + tmpfiles-rosy-state.conf); nothing here is
# a second copy of either. Idempotent. Run on the robot from a checkout copy:
#   sudo bash deploy/robot/pinky_pro/dev/install-learned-perception.sh [--dry-run]
# --dry-run prints what would be applied and changes nothing (any user).
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PINKY=$(dirname -- "$SCRIPT_DIR")
REQUIREMENTS="$PINKY/image/device-python-requirements.txt"
STATE_RULES="$PINKY/native/tmpfiles-rosy-state.conf"
LOCK="$PINKY/image/inputs.lock.yaml"
BEGIN='# BEGIN D-373 learned-perception runtime'
END='# END D-373 learned-perception runtime'
# Directories this layer adds; mode and owner are read from STATE_RULES.
DIRECTORIES=(/var/lib/rosy/models)
RUNTIME_RECORD=/usr/local/share/rosy/python-runtime.sha256
COMPATIBLE_RECORD=/usr/local/share/rosy/python-runtime-compatible.sha256
BENCH_LOG=/var/log/rosy/bench-installs.log

fail() { echo "install-learned-perception: $*" >&2; exit 1; }

DRY_RUN=0
case "${1:-}" in
    "") ;;
    --dry-run) DRY_RUN=1 ;;
    *) fail "usage: $0 [--dry-run]" ;;
esac

WORK=$(mktemp -d)
trap 'rm -rf -- "$WORK"' EXIT
# A checkout copied from Windows may carry CRLF; the lock pins LF bytes.
tr -d '\r' < "$REQUIREMENTS" > "$WORK/requirements.txt"
tr -d '\r' < "$STATE_RULES" > "$WORK/state.conf"

begin_line=$(grep -nxF -- "$BEGIN" "$WORK/requirements.txt" | cut -d: -f1)
[ -n "$begin_line" ] && [ "$(grep -cxF -- "$BEGIN" "$WORK/requirements.txt")" -eq 1 ] \
    || fail "requirements file has no single '$BEGIN' line"
[ "$(tail -n 1 "$WORK/requirements.txt")" = "$END" ] || fail "'$END' is not the last line"
[ -z "$(sed -n "$((begin_line - 1))p" "$WORK/requirements.txt")" ] \
    || fail "the block must follow one blank line"
sed -n "${begin_line},\$p" "$WORK/requirements.txt" > "$WORK/block.txt"
# What a card baked before D-373 recorded: the same file without the block.
head -n "$((begin_line - 2))" "$WORK/requirements.txt" > "$WORK/before.txt"
full_sha=$(sha256sum "$WORK/requirements.txt" | cut -d' ' -f1)
before_sha=$(sha256sum "$WORK/before.txt" | cut -d' ' -f1)
wanted=$(sed -n 's/^onnxruntime==\([^ ]*\).*/\1/p' "$WORK/block.txt")
[ -n "$wanted" ] || fail "the block pins no onnxruntime"
# The lock's python_runtime.compatible_predecessors, as customize-rootfs.sh reads it.
compatible=$(tr -d '\r' < "$LOCK" | sed -n 's/^  compatible_predecessors: *\[\(.*\)\]$/\1/p' | tr -d ' ' | tr ',' ' ')
case " $compatible " in
    *" $before_sha "*) ;;
    *) fail "inputs.lock.yaml compatible_predecessors does not list the pre-block runtime $before_sha" ;;
esac

rules=()
for path in "${DIRECTORIES[@]}"; do
    rule=$(awk -v p="$path" '$1 == "d" && $2 == p { print $1, $2, $3, $4, $5 }' "$WORK/state.conf")
    [ -n "$rule" ] || fail "no 'd $path' rule in tmpfiles-rosy-state.conf"
    rules+=("$rule")
done

if [ "$DRY_RUN" -eq 1 ]; then
    echo "requirements_sha256=$full_sha"
    echo "image_runtime_before=$before_sha"
    echo "compatible_predecessors=$compatible"
    for rule in "${rules[@]}"; do echo "dir $rule"; done
    echo "--- block"
    cat "$WORK/block.txt"
    exit 0
fi

[ "$(id -u)" -eq 0 ] || fail "must run as root (sudo); pip and the directory owners need it"

# The image records which runtime it carries and native_release.py refuses a
# release built for another. Only a card on the pre-D-373 set (or one already
# upgraded) may take this block; anything else needs a reflash.
present=$(tr -d '[:space:]' < "$RUNTIME_RECORD" 2>/dev/null || true)
case "$present" in
    "$before_sha"|"$full_sha") ;;
    *) fail "image runtime is ${present:-unrecorded}, not $before_sha or $full_sha; reflash with a matching image" ;;
esac

# umask 022: the service users must be able to read what root installs.
(umask 022 && python3 -m pip install --no-cache-dir --break-system-packages \
    --ignore-installed --require-hashes --no-deps --only-binary=:all: \
    -r "$WORK/block.txt") \
    || fail "learned-perception runtime did not install from the hash lock"

installed=$(cd / && PYTHONNOUSERSITE=1 python3 -B -c 'import onnxruntime; print(onnxruntime.__version__)') \
    || fail "onnxruntime does not import after install"
[ "$installed" = "$wanted" ] || fail "onnxruntime $installed imported, lock pins $wanted"

for rule in "${rules[@]}"; do
    read -r _type path mode user group <<< "$rule"
    install -d -m "$mode" -o "$user" -g "$group" "$path"
done

install -d -m 0755 "$(dirname -- "$RUNTIME_RECORD")"
printf '%s\n' "$full_sha" > "$RUNTIME_RECORD"
chmod 0644 "$RUNTIME_RECORD"
# native_release.py then still activates and rolls back to pre-D-373 releases.
printf '%s\n' $compatible > "$COMPATIBLE_RECORD"
chmod 0644 "$COMPATIBLE_RECORD"

install -d -m 0755 -o root -g root "$(dirname -- "$BENCH_LOG")"
record="$(date -u +%Y-%m-%dT%H:%M:%SZ) d373-learned-perception requirements_sha256=$full_sha onnxruntime=$installed from=${present:-unrecorded}"
printf '%s\n' "$record" >> "$BENCH_LOG"
echo "$record"
