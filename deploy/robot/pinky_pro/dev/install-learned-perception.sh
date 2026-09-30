#!/bin/bash
# D-373 decision 1: bench install of the learned-perception image layer on a
# card baked before it. Same hash-locked file, same pip target and same
# directory rule as the next image (customize-rootfs.sh, inputs.lock.yaml
# learned_perception_runtime, tmpfiles-rosy-state.conf); nothing here is a
# second copy of any of them. Idempotent. Run on the robot from a checkout copy:
#   sudo bash deploy/robot/pinky_pro/dev/install-learned-perception.sh [--dry-run]
# --dry-run prints what would be applied and changes nothing (any user).
# It never writes /usr/local and never touches the card's Python runtime record
# (python-runtime.sha256): the payload runtime id does not change.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PINKY=$(dirname -- "$SCRIPT_DIR")
LOCK="$PINKY/image/inputs.lock.yaml"
STATE_RULES="$PINKY/native/tmpfiles-rosy-state.conf"
# Directories this layer adds; mode and owner are read from STATE_RULES.
DIRECTORIES=(/var/lib/rosy/models)
BENCH_LOG=/var/log/rosy/bench-installs.log

fail() { echo "install-learned-perception: $*" >&2; exit 1; }

DRY_RUN=0
case "${1:-}" in
    "") ;;
    --dry-run) DRY_RUN=1 ;;
    *) fail "usage: $0 [--dry-run]" ;;
esac

# The lock's learned_perception_runtime section, as customize-rootfs.sh reads it.
lock_value() {
    tr -d '\r' < "$LOCK" | awk -v section="learned_perception_runtime:" -v wanted="$1" '
        /^[^[:space:]#]/ { inside = ($1 == section); next }
        inside { key = $1; sub(/:$/, "", key); if (key == wanted) { $1 = ""; sub(/^[[:space:]]+/, ""); print; exit } }'
}
requirements_name=$(lock_value requirements)
lock_sha=$(lock_value requirements_sha256)
TARGET=$(lock_value target)
[ -n "$requirements_name" ] || fail "inputs.lock.yaml has no learned_perception_runtime.requirements"
[[ "$lock_sha" =~ ^[0-9a-f]{64}$ ]] || fail "learned_perception_runtime.requirements_sha256 is invalid"
[[ "$TARGET" == /opt/rosy/* ]] || fail "learned_perception_runtime.target must be under /opt/rosy"
REQUIREMENTS="$PINKY/image/$requirements_name"

WORK=$(mktemp -d)
trap 'rm -rf -- "$WORK"' EXIT
# A checkout copied from Windows may carry CRLF; the lock pins LF bytes.
tr -d '\r' < "$REQUIREMENTS" > "$WORK/requirements.txt"
tr -d '\r' < "$STATE_RULES" > "$WORK/state.conf"
full_sha=$(sha256sum "$WORK/requirements.txt" | cut -d' ' -f1)
[ "$full_sha" = "$lock_sha" ] || fail "$requirements_name is $full_sha, inputs.lock.yaml pins $lock_sha"
wanted=$(sed -n 's/^onnxruntime==\([^ ]*\).*/\1/p' "$WORK/requirements.txt")
[ -n "$wanted" ] || fail "$requirements_name pins no onnxruntime"

rules=()
for path in "${DIRECTORIES[@]}"; do
    rule=$(awk -v p="$path" '$1 == "d" && $2 == p { print $1, $2, $3, $4, $5 }' "$WORK/state.conf")
    [ -n "$rule" ] || fail "no 'd $path' rule in tmpfiles-rosy-state.conf"
    rules+=("$rule")
done

if [ "$DRY_RUN" -eq 1 ]; then
    echo "requirements_sha256=$full_sha"
    echo "target=$TARGET"
    for rule in "${rules[@]}"; do echo "dir $rule"; done
    echo "--- requirements"
    cat "$WORK/requirements.txt"
    exit 0
fi

[ "$(id -u)" -eq 0 ] || fail "must run as root (sudo); pip and the directory owners need it"

# Its own prefix, root:root 0755: only the learned backend appends it to
# sys.path (learned/runner.py), so apt numpy/protobuf/packaging keep precedence.
install -d -m 0755 -o root -g root "$(dirname -- "$TARGET")" "$TARGET"
# umask 022: the camera user must be able to read what root installs.
(umask 022 && python3 -m pip install --no-cache-dir --upgrade \
    --require-hashes --no-deps --only-binary=:all: --target "$TARGET" \
    -r "$WORK/requirements.txt") \
    || fail "learned-perception runtime did not install from the hash lock"

installed=$(cd / && PYTHONNOUSERSITE=1 python3 -B -c \
    "import sys; sys.path.append('$TARGET'); import onnxruntime; print(onnxruntime.__version__)") \
    || fail "onnxruntime does not import from $TARGET"
[ "$installed" = "$wanted" ] || fail "onnxruntime $installed imported, lock pins $wanted"

for rule in "${rules[@]}"; do
    read -r _type path mode user group <<< "$rule"
    install -d -m "$mode" -o "$user" -g "$group" "$path"
done

install -d -m 0755 -o root -g root "$(dirname -- "$BENCH_LOG")"
record="$(date -u +%Y-%m-%dT%H:%M:%SZ) d373-learned-perception requirements_sha256=$full_sha onnxruntime=$installed target=$TARGET"
printf '%s\n' "$record" >> "$BENCH_LOG"
echo "$record"
