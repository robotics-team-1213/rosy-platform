#!/usr/bin/env bash
# Validate, map and deterministically compress a completed raw Pi disk image.
set -euo pipefail

RAW=""
OUTPUT=""
LAYOUT_FILE=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --raw-image) RAW="${2:-}"; shift 2 ;;
        --output) OUTPUT="${2:-}"; shift 2 ;;
        --layout-file) LAYOUT_FILE="${2:-}"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
fail() { echo "FAIL: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail "image finalization requires root"
[[ -f "$RAW" && "$RAW" == *.img ]] || fail "--raw-image must name an existing .img"
[[ "$OUTPUT" == *.img.xz && ! -e "$OUTPUT" ]] || fail "--output must be a new .img.xz"
for command in losetup lsblk blkid partprobe udevadm e2fsck bmaptool xz sync; do
    command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

FILESYSTEMS="2 ext"
if [[ -n "$LAYOUT_FILE" ]]; then
    for command in python3 fsck.vfat; do
        command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
    done
    FILESYSTEMS="$(python3 "$SCRIPT_DIR/ab_image_layout.py" filesystems \
        --raw-image "$RAW" --layout "$LAYOUT_FILE")" || fail "actual GPT differs from the assembly snapshot"
fi

LOOP=""
cleanup() {
    set +e
    [[ -z "$LOOP" ]] || losetup --detach "$LOOP"
    rm -f -- "$OUTPUT.part"
}
trap cleanup EXIT

sync
LOOP="$(losetup --find --show --partscan --read-only "$RAW")"
partprobe "$LOOP"
udevadm settle
PARTITIONS="$(lsblk -nrpo NAME,PARTN "$LOOP")"
while read -r number filesystem; do
    DEVICE="$(printf '%s\n' "$PARTITIONS" | awk -v wanted="$number" '$2 == wanted {print $1}')"
    [[ -n "$DEVICE" && "$(printf '%s\n' "$DEVICE" | wc -l)" -eq 1 ]] \
        || fail "expected exactly one partition $number on $LOOP"
    ACTUAL="$(blkid -p -s TYPE -o value -- "$DEVICE" || true)"
    if [[ "$filesystem" == ext ]]; then
        [[ "${ACTUAL,,}" =~ ^ext[234]$ ]] || fail "expected an ext filesystem on $DEVICE"
    else
        [[ "${ACTUAL,,}" == "$filesystem" ]] || fail "filesystem differs on $DEVICE"
    fi
    if [[ "$filesystem" == vfat ]]; then
        fsck.vfat -n "$DEVICE"
    else
        e2fsck -fn "$DEVICE"
    fi
done <<< "$FILESYSTEMS"
losetup --detach "$LOOP"
LOOP=""

bmaptool create -o "${OUTPUT%.xz}.bmap" "$RAW"
# The image contains already-compressed packages. A 256 MiB rootfs sample took
# 247 s with -6 versus 403 s with -9e for only 0.23% less output (2026-09-26).
# Keep the same CRC64 and full post-compression test; favor build throughput.
xz --threads=0 --check=crc64 -6 --stdout -- "$RAW" > "$OUTPUT.part"
xz --test "$OUTPUT.part"
mv -- "$OUTPUT.part" "$OUTPUT"
rm -f -- "$RAW"
trap - EXIT
echo "FLASHABLE_IMAGE_READY $OUTPUT"
