#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

CONFIG_FILE="${ROSY_BOOT_CONFIG:-/boot/firmware/config.txt}"
OVERLAY="dtoverlay=uart4-pi5"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
UDEV_RULE="99-rosy-motor.rules"
UDEV_SOURCE="${SCRIPT_DIR}/udev/${UDEV_RULE}"
UDEV_TARGET="/etc/udev/rules.d/${UDEV_RULE}"

fail() {
    echo "FAIL UART_CONFIG $*" >&2
    exit 1
}

install_motor_udev_rule() {
    # The native runtime addresses the bus as /dev/rosy-motor
    # (DeviceAllow / motor_device:=); this alias is meaningless without the
    # UART4 overlay this script owns, so the rule is installed here on every
    # run — including the already-configured path below.
    [[ -f "$UDEV_SOURCE" ]] || fail "udev rule missing: $UDEV_SOURCE"
    if [[ ! -f "$UDEV_TARGET" ]] || ! cmp -s "$UDEV_SOURCE" "$UDEV_TARGET"; then
        install -o root -g root -m 0644 "$UDEV_SOURCE" "$UDEV_TARGET"
        udevadm control --reload >/dev/null 2>&1 || true
        udevadm trigger --sysname-match=ttyAMA4 >/dev/null 2>&1 || true
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

[[ "${EUID:-$(id -u)}" -eq 0 ]] || fail "run with sudo"
[[ "$CONFIG_FILE" == "/boot/firmware/config.txt" ]] \
    || fail "ROSY_BOOT_CONFIG must be /boot/firmware/config.txt"
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

cp --preserve=mode,ownership "$CONFIG_FILE" "$config_tmp"
printf '\n[all]\n# Rosy motor bus on Raspberry Pi 5 GPIO12/GPIO13\n%s\n' "$OVERLAY" >>"$config_tmp"
grep -Fqx "$OVERLAY" "$config_tmp" || fail "unable to stage UART4 overlay"
if [[ ! -e "${CONFIG_FILE}.rosy-backup" ]]; then
    install -o root -g root -m 0644 "$CONFIG_FILE" "${CONFIG_FILE}.rosy-backup"
fi
install -o root -g root -m 0644 "$config_tmp" "$CONFIG_FILE"

echo "PASS UART_CONFIG added $OVERLAY"
echo "REBOOT_REQUIRED sudo reboot"
