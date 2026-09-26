#!/usr/bin/env bash
# Make one boot line (usually a dtoverlay=) active for the Raspberry Pi 5 in
# config.txt, idempotently (D-247: the IMU bus and the WS2812 lamp driver).
#
#   sudo configure-boot-overlay-pi5.sh --overlay LINE [--comment TEXT]
#       retrofit a running device (reboot to apply; a runtime `dtoverlay`
#       does not work on the Ubuntu 6.8 raspi kernel, rosy_18 2026-09-26)
#   configure-boot-overlay-pi5.sh --image-root ROOT --overlay LINE [--comment TEXT]
#       bake it into a mounted image (deploy/image/customize-rootfs.sh)
#
# Same rule and same vfat-safe edit as configure-uart-pi5.sh: the line counts
# before any section header or under [all] / [pi5], comments stripped; a
# missing line is appended under a fresh [all] through a staged copy and a rename.
set -Eeuo pipefail
umask 077

IMAGE_ROOT=""
OVERLAY=""
COMMENT="Rosy board device (D-247)"
DISABLE_CAMERA_AUTO_DETECT=false

fail() {
    echo "FAIL BOOT_OVERLAY $*" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --image-root) IMAGE_ROOT="${2:-}"; shift 2 ;;
        --overlay) OVERLAY="${2:-}"; shift 2 ;;
        --comment) COMMENT="${2:-}"; shift 2 ;;
        --disable-camera-auto-detect) DISABLE_CAMERA_AUTO_DETECT=true; shift ;;
        *) fail "unknown argument: $1" ;;
    esac
done

# One config.txt line: key=value, no spaces, no comment, no section header.
[[ "$OVERLAY" =~ ^(dtoverlay|dtparam)=[A-Za-z0-9_.,=-]+$ ]] || fail "--overlay must be one dtoverlay=/dtparam= line"
[[ "$COMMENT" != *$'\n'* ]] || fail "--comment must be one line"
[[ "$DISABLE_CAMERA_AUTO_DETECT" == false || "$OVERLAY" == "dtoverlay=ov5647" ]] \
    || fail "--disable-camera-auto-detect requires dtoverlay=ov5647"

if [[ -n "$IMAGE_ROOT" ]]; then
    [[ "$IMAGE_ROOT" == /* && -d "$IMAGE_ROOT" ]] \
        || fail "--image-root must be an existing absolute directory"
    IMAGE_ROOT="$(realpath -e "$IMAGE_ROOT")"
    [[ "$IMAGE_ROOT" != "/" ]] || fail "--image-root must not be the running system"
    CONFIG_FILE="${IMAGE_ROOT}/boot/firmware/config.txt"
else
    [[ "${EUID:-$(id -u)}" -eq 0 ]] || fail "run with sudo"
    CONFIG_FILE="/boot/firmware/config.txt"
fi
[[ -f "$CONFIG_FILE" && ! -L "$CONFIG_FILE" ]] || fail "$CONFIG_FILE must be a regular non-symlink file"

applies_to_pi5() {
    awk -v wanted="$OVERLAY" '
        BEGIN { active = 1; found = 0 }
        /^[[:space:]]*\[[^]]+\][[:space:]]*$/ {
            section = $0
            gsub(/[[:space:]]/, "", section)
            active = (section == "[all]" || section == "[pi5]")
            next
        }
        {
            line = $0
            sub(/\r$/, "", line)
            sub(/[[:space:]]*#.*/, "", line)
            sub(/^[[:space:]]+/, "", line)
            sub(/[[:space:]]+$/, "", line)
            if (active && line == wanted) found = 1
        }
        END { exit(found ? 0 : 1) }
    ' "$1"
}

camera_auto_detect_disabled() {
    awk '
        BEGIN { active = 1; disabled = 0; enabled = 0 }
        /^[[:space:]]*\[[^]]+\][[:space:]]*$/ {
            section = $0
            gsub(/[[:space:]]/, "", section)
            active = (section == "[all]" || section == "[pi5]")
            next
        }
        {
            line = $0
            sub(/\r$/, "", line)
            sub(/[[:space:]]*#.*/, "", line)
            gsub(/[[:space:]]/, "", line)
            if (active && line == "camera_auto_detect=0") disabled = 1
            if (active && line == "camera_auto_detect=1") enabled = 1
        }
        END { exit(disabled && !enabled ? 0 : 1) }
    ' "$1"
}

if applies_to_pi5 "$CONFIG_FILE" && \
    { [[ "$DISABLE_CAMERA_AUTO_DETECT" == false ]] || camera_auto_detect_disabled "$CONFIG_FILE"; }; then
    echo "PASS BOOT_OVERLAY $OVERLAY is already configured"
    exit 0
fi

staged="$(mktemp --tmpdir="$(dirname "$CONFIG_FILE")" .rosy-boot-overlay.XXXXXX)"
trap 'rm -f "$staged"' EXIT
cat "$CONFIG_FILE" >"$staged"
chmod --reference="$CONFIG_FILE" "$staged" 2>/dev/null || true
if [[ "$DISABLE_CAMERA_AUTO_DETECT" == true ]]; then
    sed -i -E 's/^([[:space:]]*)camera_auto_detect=1([[:space:]]*(#.*)?)$/\1camera_auto_detect=0\2/' "$staged"
    if ! camera_auto_detect_disabled "$staged"; then
        printf '\n[all]\ncamera_auto_detect=0\n' >>"$staged"
    fi
fi
if ! applies_to_pi5 "$staged"; then
    printf '\n[all]\n# %s\n%s\n' "$COMMENT" "$OVERLAY" >>"$staged"
fi
applies_to_pi5 "$staged" || fail "unable to stage $OVERLAY"
if [[ "$DISABLE_CAMERA_AUTO_DETECT" == true ]]; then
    camera_auto_detect_disabled "$staged" || fail "unable to disable camera auto detection"
fi
if [[ -z "$IMAGE_ROOT" && ! -e "${CONFIG_FILE}.rosy-backup" ]]; then
    cp "$CONFIG_FILE" "${CONFIG_FILE}.rosy-backup"
fi
sync -f "$staged" 2>/dev/null || sync
mv -f "$staged" "$CONFIG_FILE"
sync -f "$CONFIG_FILE" 2>/dev/null || sync
echo "PASS BOOT_OVERLAY added $OVERLAY"
[[ -n "$IMAGE_ROOT" ]] || echo "REBOOT_REQUIRED sudo reboot"
