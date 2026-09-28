#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_ROOT="${ROSY_INSTALL_ROOT:-/opt/rosy}"
RUNTIME_DIR="$INSTALL_ROOT/deploy/robot"
ENV_FILE="${ROSY_ENV_FILE:-$RUNTIME_DIR/.env}"
CONFIG_FILE="${ROSY_BOOT_CONFIG:-/boot/firmware/config.txt}"

fail() {
    echo "FAIL MOTOR_PREFLIGHT $*" >&2
    exit 1
}

pass() {
    echo "PASS MOTOR_PREFLIGHT $*"
}

overlay_applies_to_pi5() {
    local file="$1" overlay="dtoverlay=uart4-pi5"
    awk -v overlay="$overlay" '
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

read_env_value() {
    local key="$1" fallback="$2" value
    value="$(sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1)"
    value="${value%$'\r'}"
    printf '%s' "${value:-$fallback}"
}

[[ "${EUID:-$(id -u)}" -eq 0 ]] || fail "run with sudo"
[[ -r /proc/device-tree/model ]] || fail "Raspberry Pi model information is unavailable"
model="$(tr -d '\0' </proc/device-tree/model)"
[[ "$model" == *"Raspberry Pi 5"* ]] || fail "expected Raspberry Pi 5, found: $model"
[[ "$CONFIG_FILE" == "/boot/firmware/config.txt" && -f "$CONFIG_FILE" ]] \
    || fail "missing /boot/firmware/config.txt"
overlay_applies_to_pi5 "$CONFIG_FILE" \
    || fail "UART4 overlay missing; run sudo $RUNTIME_DIR/configure-uart-pi5.sh and reboot"

cmdline_file="/boot/firmware/cmdline.txt"
if [[ -f "$cmdline_file" ]] && grep -Eq '(^| )console=ttyAMA4([, ]|$)' "$cmdline_file"; then
    fail "console=ttyAMA4 conflicts with the motor bus"
fi

[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "runtime environment is unavailable"
motor_device="$(read_env_value ROSY_MOTOR_DEVICE /dev/ttyAMA4)"
motor_baudrate="$(read_env_value ROSY_MOTOR_BAUDRATE 1000000)"
motor_ids_raw="$(read_env_value ROSY_MOTOR_IDS '[1,2]')"
dialout_gid="$(read_env_value ROSY_DIALOUT_GID 20)"

[[ "$motor_device" == /dev/* ]] || fail "ROSY_MOTOR_DEVICE must be an absolute /dev path"
[[ -c "$motor_device" ]] || fail "$motor_device is not a character device; reboot after enabling UART4"
[[ "$motor_baudrate" =~ ^[1-9][0-9]*$ ]] || fail "ROSY_MOTOR_BAUDRATE must be a positive integer"
[[ "$dialout_gid" =~ ^[0-9]+$ ]] || fail "ROSY_DIALOUT_GID must be numeric"
device_gid="$(stat -c '%g' "$motor_device")"
[[ "$device_gid" == "$dialout_gid" ]] \
    || fail "$motor_device group GID $device_gid does not match ROSY_DIALOUT_GID $dialout_gid"
[[ "$motor_ids_raw" =~ ^\[[0-9]+(,[0-9]+)+\]$ ]] \
    || fail "ROSY_MOTOR_IDS must use compact list syntax such as [1,2]"

motor_ids_text="${motor_ids_raw#[}"
motor_ids_text="${motor_ids_text%]}"
IFS=',' read -r -a motor_ids <<<"$motor_ids_text"

cd "$RUNTIME_DIR"
compose=(docker compose --env-file "$ENV_FILE")
# 게이트는 닫히는 쪽으로 실패해야 한다. 예전에는 compose 의 출력이 비었는지만
# 봤는데, compose 가 아예 실패해도 출력은 비므로 게이트가 통과해 버렸다 — 모터
# 런타임이 살아 있어도 프로브가 그대로 진행된다는 뜻이다. 신원 미설정은 그 실패의
# 한 가지 이유일 뿐이고 (ADR D-33), docker 부재나 잘못된 compose 파일도 같다.
# 그래서 종료 상태를 먼저 본다.
if ! running="$("${compose[@]}" --profile motor --profile hardware ps -q rosy-motor rosy-io)"; then
    fail "cannot tell whether the motor runtime is active — docker compose failed; fix that before probing the UART"
fi
if [[ -n "$running" ]]; then
    fail "motor runtime is active; switch to core mode before the read-only probe"
fi

pass "UART4 overlay, console isolation, and device node are ready"
"${compose[@]}" --profile motor build rosy-motor
"${compose[@]}" --profile motor run --rm --no-deps --entrypoint python3 rosy-motor \
    -m bringup.dynamixel_probe \
    --device /dev/rosy-motor \
    --baudrate "$motor_baudrate" \
    --ids "${motor_ids[@]}"
pass "all configured DYNAMIXEL IDs responded with drive torque disabled"

echo "NEXT sudo $RUNTIME_DIR/runtime-mode.sh down"
echo "NEXT sudoedit $ENV_FILE  # set ROSY_RUNTIME_MODE=motor"
echo "NEXT sudo systemctl restart rosy-runtime.service"
