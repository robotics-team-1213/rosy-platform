#!/usr/bin/env bash
# Enable the Rosy motor bus (UART4 on Raspberry Pi 5) and its /dev/rosy-motor alias.
#
#   sudo configure-uart-pi5.sh                    retrofit a running device
#   sudo configure-uart-pi5.sh --image-root ROOT  bake it into a mounted image
#                                                 (deploy/image/customize-rootfs.sh, D-192)
#
# Both paths share the detection and the edit below; the image path only
# changes where the files are and skips what needs a running system.
set -Eeuo pipefail
umask 077

OVERLAY="dtoverlay=uart4-pi5"
IMAGE_ROOT=""

fail() {
    echo "FAIL UART_CONFIG $*" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --image-root) IMAGE_ROOT="${2:-}"; shift 2 ;;
        *) fail "unknown argument: $1" ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
UDEV_RULE="99-rosy-motor.rules"
UDEV_SOURCE="${SCRIPT_DIR}/udev/${UDEV_RULE}"

if [[ -n "$IMAGE_ROOT" ]]; then
    [[ "$IMAGE_ROOT" == /* && -d "$IMAGE_ROOT" ]] \
        || fail "--image-root must be an existing absolute directory"
    IMAGE_ROOT="$(realpath -e "$IMAGE_ROOT")"
    [[ "$IMAGE_ROOT" != "/" ]] || fail "--image-root must not be the running system"
    CONFIG_FILE="${IMAGE_ROOT}/boot/firmware/config.txt"
    UDEV_TARGET="${IMAGE_ROOT}/etc/udev/rules.d/${UDEV_RULE}"
else
    CONFIG_FILE="${ROSY_BOOT_CONFIG:-/boot/firmware/config.txt}"
    UDEV_TARGET="/etc/udev/rules.d/${UDEV_RULE}"
    [[ "$CONFIG_FILE" == "/boot/firmware/config.txt" ]] \
        || fail "ROSY_BOOT_CONFIG must be /boot/firmware/config.txt"
fi

install_motor_udev_rule() {
    # The native runtime addresses the bus as /dev/rosy-motor
    # (DeviceAllow / motor_device:=); this alias is meaningless without the
    # UART4 overlay this script owns, so the rule is installed here on every
    # run — including the already-configured path below.
    [[ -f "$UDEV_SOURCE" ]] || fail "udev rule missing: $UDEV_SOURCE"
    if [[ ! -f "$UDEV_TARGET" ]] || ! cmp -s "$UDEV_SOURCE" "$UDEV_TARGET"; then
        if [[ -n "$IMAGE_ROOT" ]]; then
            # Owned by the caller: root in customize-rootfs.sh.
            install -d -m 0755 "$(dirname "$UDEV_TARGET")"
            install -m 0644 "$UDEV_SOURCE" "$UDEV_TARGET"
        else
            install -o root -g root -m 0644 "$UDEV_SOURCE" "$UDEV_TARGET"
            udevadm control --reload >/dev/null 2>&1 || true
            udevadm trigger --sysname-match=ttyAMA4 >/dev/null 2>&1 || true
        fi
        echo "PASS UDEV_RULE installed $UDEV_TARGET (alias appears on reload/reboot)"
    else
        echo "PASS UDEV_RULE $UDEV_TARGET already current"
    fi
}

overlay_applies_to_pi5() {
    local file="$1"
    awk -v overlay="$OVERLAY" '
        BEGIN { active = 1; found = 0 }
        /^[[:space:]]*\[[^]]+\][[:space:]]*$/ {
            section = $0
            gsub(/[[:space:]]/, "", section)
            active = (section == "[all]" || section == "[pi5]")
            next
        }
        {
            line = $0
            sub(/[[:space:]]*#.*/, "", line)
            sub(/^[[:space:]]+/, "", line)
            sub(/[[:space:]]+$/, "", line)
            if (active && line == overlay) found = 1
        }
        END { exit(found ? 0 : 1) }
    ' "$file"
}

# The image path edits files under a mounted tree its caller (root) owns.
[[ -n "$IMAGE_ROOT" || "${EUID:-$(id -u)}" -eq 0 ]] || fail "run with sudo"
[[ -f "$CONFIG_FILE" && ! -L "$CONFIG_FILE" ]] \
    || fail "$CONFIG_FILE must be a regular non-symlink file"
[[ "$(readlink -f "$CONFIG_FILE")" == "$CONFIG_FILE" ]] \
    || fail "$CONFIG_FILE is not canonical"

install_motor_udev_rule

if grep -Fqx "$OVERLAY" "$CONFIG_FILE" && overlay_applies_to_pi5 "$CONFIG_FILE"; then
    echo "PASS UART_CONFIG $OVERLAY is already configured"
    exit 0
fi

config_tmp="$(mktemp --tmpdir="$(dirname "$CONFIG_FILE")" .rosy-uart.XXXXXX)"
trap 'rm -f "${config_tmp:-}"' EXIT

# /boot/firmware is vfat: it has no owners and refuses a chmod that drops the
# x bits its mount mask shows (EPERM), so no install -m / cp --preserve here.
# The staged copy lives in the same directory and replaces the file by rename.
cat "$CONFIG_FILE" >"$config_tmp"
# Keep the mode where the filesystem has one (a no-op on vfat).
chmod --reference="$CONFIG_FILE" "$config_tmp" 2>/dev/null || true
printf '\n[all]\n# Rosy motor bus on Raspberry Pi 5 GPIO12/GPIO13\n%s\n' "$OVERLAY" >>"$config_tmp"
if ! grep -Fqx "$OVERLAY" "$config_tmp" || ! overlay_applies_to_pi5 "$config_tmp"; then
    fail "unable to stage UART4 overlay"
fi
if [[ -z "$IMAGE_ROOT" && ! -e "${CONFIG_FILE}.rosy-backup" ]]; then
    cp "$CONFIG_FILE" "${CONFIG_FILE}.rosy-backup"
fi
sync -f "$config_tmp" 2>/dev/null || sync
mv -f "$config_tmp" "$CONFIG_FILE"
sync -f "$CONFIG_FILE" 2>/dev/null || sync

echo "PASS UART_CONFIG added $OVERLAY"
[[ -n "$IMAGE_ROOT" ]] || echo "REBOOT_REQUIRED sudo reboot"
