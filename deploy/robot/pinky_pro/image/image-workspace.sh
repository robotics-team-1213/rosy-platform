#!/usr/bin/env bash
# Create a disposable, mounted copy of a Canonical Raspberry Pi disk image,
# run one customizer inside it, then publish an uncompressed raw image.
set -euo pipefail

BASE_IMAGE=""
OUTPUT_IMAGE=""
WORK_ROOT=""
EXPAND_MIB=""
CALLBACK=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --base-image) BASE_IMAGE="${2:-}"; shift 2 ;;
        --output-image) OUTPUT_IMAGE="${2:-}"; shift 2 ;;
        --work-root) WORK_ROOT="${2:-}"; shift 2 ;;
        --expand-mib) EXPAND_MIB="${2:-}"; shift 2 ;;
        --) shift; CALLBACK=("$@"); break ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

fail() { echo "FAIL: $*" >&2; exit 1; }

[[ -n "$BASE_IMAGE" ]] || fail "--base-image is required"
[[ -n "$OUTPUT_IMAGE" ]] || fail "--output-image is required"
[[ -n "$WORK_ROOT" ]] || fail "--work-root is required"
[[ "$EXPAND_MIB" =~ ^[1-9][0-9]*$ ]] || fail "--expand-mib must be a positive integer"
(( ${#CALLBACK[@]} > 0 )) || fail "a customizer command is required after --"

[[ $EUID -eq 0 ]] || fail "image workspace requires root"
ARCH="$(uname -m)"
[[ "$ARCH" == "aarch64" ]] \
    || fail "release image workspace requires native arm64; this host is $ARCH"

for command in xz truncate losetup lsblk blkid udevadm growpart partprobe resize2fs mount umount \
        mktemp realpath cp mv rm mkdir awk wc; do
    command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

[[ -f "$BASE_IMAGE" ]] || fail "base image does not exist: $BASE_IMAGE"
[[ "$BASE_IMAGE" == *.img.xz ]] || fail "base image must be a compressed .img.xz"
[[ ! -e "$OUTPUT_IMAGE" ]] || fail "refusing to overwrite output image: $OUTPUT_IMAGE"

mkdir -p -- "$WORK_ROOT" "$(dirname "$OUTPUT_IMAGE")"
WORK_ROOT_REAL="$(realpath -e "$WORK_ROOT")"
BASE_IMAGE_REAL="$(realpath -e "$BASE_IMAGE")"
OUTPUT_IMAGE_REAL="$(realpath -m "$OUTPUT_IMAGE")"
[[ "$BASE_IMAGE_REAL" != "$OUTPUT_IMAGE_REAL" ]] \
    || fail "output image must not replace the cached base image"

WORK_DIR=""
IMAGE_FILE=""
LOOP_DEVICE=""
ROOT_MOUNTED=0
BOOT_MOUNTED=0
OUTPUT_PART="$OUTPUT_IMAGE.part.$$"

deactivate_image() {
    local cleanup_failed=0
    if (( BOOT_MOUNTED )); then
        if umount -- "$ROSY_IMAGE_BOOT"; then
            BOOT_MOUNTED=0
        else
            echo "FAIL: could not unmount boot partition: $ROSY_IMAGE_BOOT" >&2
            cleanup_failed=1
        fi
    fi
    if (( ROOT_MOUNTED )); then
        if umount -- "$ROSY_IMAGE_ROOT"; then
            ROOT_MOUNTED=0
        else
            echo "FAIL: could not unmount root partition: $ROSY_IMAGE_ROOT" >&2
            cleanup_failed=1
        fi
    fi
    if [[ -n "$LOOP_DEVICE" ]]; then
        if losetup --detach "$LOOP_DEVICE"; then
            LOOP_DEVICE=""
        else
            echo "FAIL: could not detach loop device: $LOOP_DEVICE" >&2
            cleanup_failed=1
        fi
    fi
    return "$cleanup_failed"
}

remove_workspace() {
    [[ -z "$WORK_DIR" ]] && return
    case "$WORK_DIR" in
        "$WORK_ROOT_REAL"/rosy-image.*)
            rm -rf -- "$WORK_DIR"
            WORK_DIR=""
            ;;
        *)
            echo "FAIL: refusing to remove unexpected workspace path: $WORK_DIR" >&2
            return 1
            ;;
    esac
}

cleanup_on_exit() {
    local status=$?
    trap - EXIT
    set +e
    deactivate_image
    remove_workspace
    rm -f -- "$OUTPUT_PART"
    exit "$status"
}
trap cleanup_on_exit EXIT
trap 'exit 130' INT TERM

WORK_DIR="$(mktemp -d "$WORK_ROOT_REAL/rosy-image.XXXXXX")"
IMAGE_FILE="$WORK_DIR/rosy-working.img"
ROSY_IMAGE_ROOT="$WORK_DIR/root"
ROSY_IMAGE_BOOT="$ROSY_IMAGE_ROOT/boot/firmware"
mkdir -p -- "$ROSY_IMAGE_ROOT"

xz --decompress --stdout -- "$BASE_IMAGE_REAL" > "$IMAGE_FILE"
truncate -s "+${EXPAND_MIB}M" "$IMAGE_FILE"
LOOP_DEVICE="$(losetup --find --show --partscan "$IMAGE_FILE")"
[[ "$LOOP_DEVICE" == /dev/loop* ]] || fail "losetup returned an unexpected device: $LOOP_DEVICE"

partprobe "$LOOP_DEVICE"
udevadm settle
PARTITIONS="$(lsblk -nrpo NAME,PARTN "$LOOP_DEVICE")"
BOOT_DEVICE="$(printf '%s\n' "$PARTITIONS" | awk '$2 == "1" { print $1 }')"
ROOT_DEVICE="$(printf '%s\n' "$PARTITIONS" | awk '$2 == "2" { print $1 }')"
[[ -n "$BOOT_DEVICE" && "$(printf '%s\n' "$BOOT_DEVICE" | wc -l)" -eq 1 ]] \
    || fail "expected exactly one boot partition 1 on $LOOP_DEVICE"
[[ -n "$ROOT_DEVICE" && "$(printf '%s\n' "$ROOT_DEVICE" | wc -l)" -eq 1 ]] \
    || fail "expected exactly one root partition 2 on $LOOP_DEVICE"

BOOT_FSTYPE="$(blkid -p -s TYPE -o value -- "$BOOT_DEVICE" || true)"
ROOT_FSTYPE="$(blkid -p -s TYPE -o value -- "$ROOT_DEVICE" || true)"
[[ "${BOOT_FSTYPE,,}" =~ ^(vfat|fat|fat16|fat32)$ ]] \
    || fail "expected a FAT filesystem on $BOOT_DEVICE; found ${BOOT_FSTYPE:-unknown}"
[[ "${ROOT_FSTYPE,,}" =~ ^ext[234]$ ]] \
    || fail "expected an ext filesystem on $ROOT_DEVICE; found ${ROOT_FSTYPE:-unknown}"

growpart "$LOOP_DEVICE" 2
partprobe "$LOOP_DEVICE"
udevadm settle
resize2fs "$ROOT_DEVICE"

mount "$ROOT_DEVICE" "$ROSY_IMAGE_ROOT"
ROOT_MOUNTED=1
mkdir -p -- "$ROSY_IMAGE_BOOT"
mount "$BOOT_DEVICE" "$ROSY_IMAGE_BOOT"
BOOT_MOUNTED=1

export ROSY_IMAGE_WORK_DIR="$WORK_DIR"
export ROSY_IMAGE_FILE="$IMAGE_FILE"
export ROSY_IMAGE_ROOT
export ROSY_IMAGE_BOOT
export ROSY_IMAGE_LOOP="$LOOP_DEVICE"
export ROSY_IMAGE_ROOT_DEVICE="$ROOT_DEVICE"
export ROSY_IMAGE_BOOT_DEVICE="$BOOT_DEVICE"

if ! "${CALLBACK[@]}"; then
    fail "image customizer failed"
fi

deactivate_image || fail "workspace cleanup failed; raw image will not be published"
cp -- "$IMAGE_FILE" "$OUTPUT_PART"
mv -- "$OUTPUT_PART" "$OUTPUT_IMAGE"
remove_workspace
trap - EXIT
echo "RAW_IMAGE_READY $OUTPUT_IMAGE"
