#!/usr/bin/env bash
# Validate, map and deterministically compress a completed raw Pi disk image.
set -euo pipefail

RAW=""
OUTPUT=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --raw-image) RAW="${2:-}"; shift 2 ;;
        --output) OUTPUT="${2:-}"; shift 2 ;;
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
ROOT_DEVICE="$(printf '%s\n' "$PARTITIONS" | awk '$2 == "2" {print $1}')"
[[ -n "$ROOT_DEVICE" && "$(printf '%s\n' "$ROOT_DEVICE" | wc -l)" -eq 1 ]] \
    || fail "expected exactly one root partition 2 on $LOOP"
ROOT_FSTYPE="$(blkid -p -s TYPE -o value -- "$ROOT_DEVICE" || true)"
[[ "${ROOT_FSTYPE,,}" =~ ^ext[234]$ ]] \
    || fail "expected an ext filesystem on $ROOT_DEVICE; found ${ROOT_FSTYPE:-unknown}"
e2fsck -fn "$ROOT_DEVICE"
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
