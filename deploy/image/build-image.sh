#!/usr/bin/env bash
# Build a ROSY OS release image from the pinned Ubuntu Server 24.04 LTS arm64
# Raspberry Pi base image on a native ARM64 host.
#
# This has never been run. Every input it depends on is in inputs.lock.yaml,
# and the ones marked `verified: false` there are assumptions nobody has
# checked — run `verify-inputs.sh` first. Producing an image is not BUILD_GO;
# `verify-artifacts.sh` is.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOCK="$SCRIPT_DIR/inputs.lock.yaml"
DIST="${ROSY_DIST_DIR:-$REPO_ROOT/dist}"
WORKSPACE="$REPO_ROOT"
CACHE_DIR="${ROSY_IMAGE_CACHE:-$SCRIPT_DIR/cache}"
IMAGE_WORK_ROOT="${ROSY_IMAGE_WORK_ROOT:-}"

RELEASE_ID=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --release-id) RELEASE_ID="${2:-}"; shift 2 ;;
        --dist) DIST="${2:-}"; shift 2 ;;
        --workspace) WORKSPACE="${2:-}"; shift 2 ;;
        --cache-dir) CACHE_DIR="${2:-}"; shift 2 ;;
        --lock) LOCK="${2:-}"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

fail() { echo "FAIL: $*" >&2; exit 1; }
[[ -n "$IMAGE_WORK_ROOT" ]] || IMAGE_WORK_ROOT="$DIST/.image-work"

[[ -n "$RELEASE_ID" ]] || fail "--release-id is required (YYYY.MM.DD-NNN)"
[[ "$RELEASE_ID" =~ ^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$ ]] \
    || fail "release id must be YYYY.MM.DD-NNN, got '$RELEASE_ID'"

# The design is explicit that an x86 QEMU build is for development only and is
# never the basis of a release image. Refusing here rather than producing an
# artifact nobody may ship.
ARCH="$(uname -m)"
[[ "$ARCH" == "aarch64" ]] \
    || fail "release images are built on native arm64; this host is $ARCH (see design 7.1)"

[[ -f "$LOCK" ]] || fail "missing $LOCK"
"$SCRIPT_DIR/verify-inputs.sh" "$LOCK" \
    || fail "inputs are not pinned; see the 'verified: false' entries in $LOCK"

SOURCE_REVISION="$(awk '
    /^sources:[[:space:]]*$/ { in_sources=1; next }
    in_sources && /^[^[:space:]]/ { exit }
    in_sources && $1 == "rosy_revision:" {
        print $2
        exit
    }
' "$LOCK" | tr -d '\r')"
[[ "$SOURCE_REVISION" =~ ^[0-9a-f]{40}$ ]] \
    || fail "sources.rosy_revision is not a full Git commit"

"$SCRIPT_DIR/fetch-base-image.sh" \
    --lock "$LOCK" --cache-dir "$CACHE_DIR"

OUT="$DIST/$RELEASE_ID"
mkdir -p "$OUT"
PAYLOAD_ROOT="$IMAGE_WORK_ROOT/payload-$RELEASE_ID"
[[ ! -e "$PAYLOAD_ROOT" ]] || fail "payload workspace already exists: $PAYLOAD_ROOT"
mkdir -p "$IMAGE_WORK_ROOT"

"$SCRIPT_DIR/build-native-payload.sh" \
    --workspace "$WORKSPACE" \
    --release-root "$PAYLOAD_ROOT" \
    --source-revision "$SOURCE_REVISION" \
    --release-id "$RELEASE_ID" \
    --lock "$LOCK"

BASE_URL="$(awk '
    /^base_image:[[:space:]]*$/ { in_base=1; next }
    in_base && /^[^[:space:]]/ { exit }
    in_base && $1 == "url:" { print $2; exit }
' "$LOCK" | tr -d '\r')"
BASE_IMAGE="$CACHE_DIR/${BASE_URL##*/}"
EXPAND_MIB="$(awk '
    /^product_artifact:[[:space:]]*$/ { in_artifact=1; next }
    in_artifact && /^[^[:space:]]/ { exit }
    in_artifact && $1 == "rootfs_expansion_mib:" { print $2; exit }
' "$LOCK" | tr -d '\r')"
RAW_IMAGE="$OUT/rosy-os-pinky-pro-$RELEASE_ID-arm64.img"
CUSTOMIZER="$SCRIPT_DIR/customize-rootfs.sh"

[[ -x "$CUSTOMIZER" ]] || fail "rootfs customizer is not implemented; Task 3 workspace \
is ready but no raw product image may be published before Task 4"

"$SCRIPT_DIR/image-workspace.sh" \
    --base-image "$BASE_IMAGE" \
    --output-image "$RAW_IMAGE" \
    --work-root "$IMAGE_WORK_ROOT" \
    --expand-mib "$EXPAND_MIB" \
    -- "$CUSTOMIZER" \
        --payload "$PAYLOAD_ROOT" \
        --source-tree "$WORKSPACE/src" \
        --lock "$LOCK" \
        --release-id "$RELEASE_ID" \
        --source-revision "$SOURCE_REVISION"

COMPRESSED_IMAGE="$OUT/rosy-os-pinky-pro-$RELEASE_ID-arm64.img.xz"
"$SCRIPT_DIR/finalize-image.sh" \
    --raw-image "$RAW_IMAGE" \
    --output "$COMPRESSED_IMAGE"
python3 "$SCRIPT_DIR/create-image-manifest.py" \
    --dist "$OUT" \
    --payload "$PAYLOAD_ROOT" \
    --lock "$LOCK" \
    --release-id "$RELEASE_ID" \
    --source-revision "$SOURCE_REVISION"
IMAGE_WORK_ROOT_REAL="$(realpath -e "$IMAGE_WORK_ROOT")"
PAYLOAD_ROOT_REAL="$(realpath -e "$PAYLOAD_ROOT")"
case "$PAYLOAD_ROOT_REAL" in
    "$IMAGE_WORK_ROOT_REAL"/payload-*) rm -rf -- "$PAYLOAD_ROOT_REAL" ;;
    *) fail "refusing to remove unexpected payload workspace: $PAYLOAD_ROOT_REAL" ;;
esac
echo "==> unsigned flashable image completed for $RELEASE_ID in $OUT"
