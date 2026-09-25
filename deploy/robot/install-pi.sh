#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="${ROSY_SOURCE_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
INSTALL_ROOT="${ROSY_INSTALL_ROOT:-/opt/rosy}"
ROSY_CONFIG="${ROSY_CONFIG_PATH:-/etc/rosy/rosy.yaml}"
ROSY_DATA="${ROSY_DATA_PATH:-/var/lib/rosy}"
RUN_USER="${ROSY_RUN_USER:-${SUDO_USER:-rosy}}"
INITIAL_CREDENTIALS="/etc/rosy/initial-credentials.txt"
INITIAL_CREDENTIALS_CREATED=0
UPGRADE_GUARD_ACTIVE=0
INSTALL_REQUESTED_PRESET=""
INSTALL_REQUESTED_SLICES=""

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

# --preset names a catalog mode/alias; --slices names a set that must match a
# preset. Both are validated now and recorded as intent. First-boot runtime
# stays core; vision/omx/ai are not installable yet.
parse_install_cli() {
    local preset="" slices=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --preset)
                [[ $# -ge 2 && -n "${2:-}" && "$2" != --* ]] || fail "--preset requires a value"
                [[ -z "$slices" ]] || fail "--preset and --slices are mutually exclusive"
                [[ -z "$preset" ]] || fail "--preset specified more than once"
                preset="$2"
                shift 2
                ;;
            --slices)
                [[ $# -ge 2 && -n "${2:-}" && "$2" != --* ]] || fail "--slices requires a value"
                [[ -z "$preset" ]] || fail "--preset and --slices are mutually exclusive"
                [[ -z "$slices" ]] || fail "--slices specified more than once"
                slices="$2"
                shift 2
                ;;
            *)
                fail "unknown argument: $1"
                ;;
        esac
    done

    # shellcheck source=config/resolve-mode.sh
    source "$SCRIPT_DIR/config/resolve-mode.sh"
    local board="$SCRIPT_DIR/config/board.yaml"
    if [[ -n "$preset" ]]; then
        INSTALL_REQUESTED_PRESET="$(resolve_runtime_mode "$preset" "$board")" || exit $?
    elif [[ -n "$slices" ]]; then
        resolve_slices_to_mode "$slices" "$board" >/dev/null || exit $?
        INSTALL_REQUESTED_SLICES="$slices"
    fi
}

on_install_exit() {
    local exit_code="$?" quarantine_ok=1
    local -a project_containers=()

    if ((exit_code == 0 || UPGRADE_GUARD_ACTIVE == 0)); then
        return "$exit_code"
    fi

    set +e
    if systemctl list-unit-files rosy-runtime.service --no-legend 2>/dev/null \
        | grep -q '^rosy-runtime.service'; then
        systemctl disable --now rosy-runtime.service >/dev/null 2>&1 || quarantine_ok=0
    fi
    if command -v docker >/dev/null 2>&1; then
        if docker info >/dev/null 2>&1; then
            mapfile -t project_containers < <(
                docker ps -aq --filter label=com.docker.compose.project=rosy-runtime
            )
            if ((${#project_containers[@]} > 0)); then
                docker stop --time 10 "${project_containers[@]}" >/dev/null 2>&1 || quarantine_ok=0
                docker rm "${project_containers[@]}" >/dev/null 2>&1 || quarantine_ok=0
            fi
        else
            quarantine_ok=0
        fi
    fi

    echo "RECOVERY: Rosy installation failed after the runtime safety gate." >&2
    if ((quarantine_ok)); then
        echo "Rosy remains quarantined in core-off state; boot startup is disabled." >&2
    else
        echo "WARNING: quarantine could not be fully verified; keep the hardware E-stop engaged." >&2
    fi
    echo "After correcting the reported error, rerun:" >&2
    echo "  sudo bash $SOURCE_ROOT/deploy/robot/install-pi.sh" >&2
    echo "Or rerun deploy/robot/deploy-from-windows.ps1 from the release PC." >&2
    echo "Do not enable hardware mode until this installer reports PASS." >&2
    return "$exit_code"
}

trap on_install_exit EXIT

require_root() {
    [[ "${EUID:-$(id -u)}" -eq 0 ]] || fail "run with sudo: sudo bash deploy/robot/install-pi.sh"
}

preflight_host() {
    [[ "$INSTALL_ROOT" == "/opt/rosy" ]] || fail "ROSY_INSTALL_ROOT must be /opt/rosy"
    [[ "$ROSY_CONFIG" == "/etc/rosy/rosy.yaml" ]] || fail "ROSY_CONFIG_PATH must be /etc/rosy/rosy.yaml"
    [[ "$ROSY_DATA" == "/var/lib/rosy" ]] || fail "ROSY_DATA_PATH must be /var/lib/rosy"
    [[ "$RUN_USER" != "root" ]] || fail "Rosy must run as the non-root user created in Raspberry Pi Imager"
    [[ -r /proc/device-tree/model ]] || fail "Raspberry Pi model information is unavailable"
    local model
    model="$(tr -d '\0' </proc/device-tree/model)"
    [[ "$model" == *"Raspberry Pi 5"* ]] || fail "expected Raspberry Pi 5, found: $model"
    [[ "$(dpkg --print-architecture)" == "arm64" ]] || fail "Raspberry Pi OS Lite 64-bit (arm64/aarch64) is required"

    # shellcheck disable=SC1091
    source /etc/os-release
    [[ "${ID:-}" == "raspbian" || "${ID:-}" == "debian" ]] || fail "Raspberry Pi OS/Debian is required"
    [[ -n "${VERSION_CODENAME:-}" ]] || fail "VERSION_CODENAME is missing from /etc/os-release"
    id "$RUN_USER" >/dev/null 2>&1 || fail "runtime user '$RUN_USER' does not exist; create it in Raspberry Pi Imager"
    [[ -f "$SOURCE_ROOT/deploy/robot/compose.yaml" ]] || fail "Rosy release root is invalid: $SOURCE_ROOT"
}

install_host_packages() {
    local docker_key_tmp
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends ca-certificates curl gnupg openssl rsync

    install -m 0755 -d /etc/apt/keyrings
    (
        docker_key_tmp="$(mktemp)"
        trap 'rm -f "${docker_key_tmp:-}"' EXIT
        curl --fail --silent --show-error --location --max-time 20 \
            https://download.docker.com/linux/debian/gpg \
            --output "$docker_key_tmp" \
            || fail "Internet/DNS check failed while downloading Docker signing key"
        install -m 0644 "$docker_key_tmp" /etc/apt/keyrings/docker.asc
    )

    cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: ${VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker.service
    docker compose version >/dev/null
}

stop_existing_runtime() {
    local -a project_containers=()

    UPGRADE_GUARD_ACTIVE=1
    if systemctl is-active --quiet rosy-runtime.service 2>/dev/null; then
        systemctl stop rosy-runtime.service
    fi
    if systemctl list-unit-files rosy-runtime.service --no-legend 2>/dev/null \
        | grep -q '^rosy-runtime.service'; then
        systemctl disable rosy-runtime.service
    fi
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        mapfile -t project_containers < <(
            docker ps -aq --filter label=com.docker.compose.project=rosy-runtime
        )
        if ((${#project_containers[@]} > 0)); then
            docker stop --time 10 "${project_containers[@]}"
            docker rm "${project_containers[@]}"
        fi
    fi
}

install_release() {
    local source_real install_real
    source_real="$(readlink -f "$SOURCE_ROOT")"
    [[ ! -L "$INSTALL_ROOT" ]] || fail "$INSTALL_ROOT must not be a symbolic link"
    [[ ! -e "$INSTALL_ROOT" || -d "$INSTALL_ROOT" ]] || fail "$INSTALL_ROOT must be a directory"
    install -d -o root -g root -m 0755 "$INSTALL_ROOT"
    install_real="$(readlink -f "$INSTALL_ROOT")"
    [[ "$install_real" == "$INSTALL_ROOT" ]] || fail "$INSTALL_ROOT resolves outside its canonical path"
    [[ "$source_real" != "$INSTALL_ROOT/"* ]] || fail "release source must not be inside $INSTALL_ROOT"
    if [[ "$source_real" != "$install_real" ]]; then
        rsync -a --delete --chown=root:root \
            --exclude '.git/' --exclude '.pytest_cache/' \
            --exclude 'deploy/robot/.env' \
            "$source_real/" "$install_real/"
    fi
    chown -R root:root "$INSTALL_ROOT"
    chmod -R go-w "$INSTALL_ROOT"
    chmod 0755 "$INSTALL_ROOT/deploy/robot/entrypoint.sh" \
        "$INSTALL_ROOT/deploy/robot/runtime-mode.sh" \
        "$INSTALL_ROOT/deploy/robot/install-pi.sh" \
        "$INSTALL_ROOT/deploy/robot/verify/verify-pi.sh" \
        "$INSTALL_ROOT/deploy/robot/configure-uart-pi5.sh" \
        "$INSTALL_ROOT/deploy/robot/verify/verify-motors.sh" \
        "$INSTALL_ROOT/deploy/robot/verify/device-readback.sh" \
        "$INSTALL_ROOT/deploy/robot/commission-pinky.py" \
        "$INSTALL_ROOT/deploy/robot/commissioning_session.py"
}

write_initial_config() {
    local run_group config_tmp admin_token operator_token viewer_token
    run_group="$(id -gn "$RUN_USER")"
    [[ ! -L /etc/rosy ]] || fail "/etc/rosy must not be a symbolic link"
    install -d -o root -g "$run_group" -m 0750 /etc/rosy
    [[ "$(readlink -f /etc/rosy)" == "/etc/rosy" ]] || fail "/etc/rosy is not canonical"
    [[ ! -L "$ROSY_DATA" ]] || fail "$ROSY_DATA must not be a symbolic link"
    install -d -o "$RUN_USER" -g "$run_group" -m 0750 "$ROSY_DATA"
    install -d -o "$RUN_USER" -g "$run_group" -m 0750 "$ROSY_DATA/maps"
    [[ "$(readlink -f "$ROSY_DATA")" == "$ROSY_DATA" ]] || fail "$ROSY_DATA is not canonical"
    [[ ! -L "$ROSY_CONFIG" ]] || fail "$ROSY_CONFIG must not be a symbolic link"

    if [[ ! -f "$ROSY_CONFIG" ]]; then
        admin_token="$(openssl rand -hex 24)"
        operator_token="$(openssl rand -hex 24)"
        viewer_token="$(openssl rand -hex 24)"
        config_tmp="$(mktemp)"
        trap 'rm -f "${config_tmp:-}"' RETURN
        sed \
            -e "s/CHANGE_ME_ADMIN/$admin_token/" \
            -e "s/CHANGE_ME_OPERATOR/$operator_token/" \
            -e "s/CHANGE_ME_VIEWER/$viewer_token/" \
            "$INSTALL_ROOT/deploy/robot/config/rosy.pi5.example.yaml" >"$config_tmp"
        install -o root -g "$run_group" -m 0640 "$config_tmp" "$ROSY_CONFIG"
        [[ ! -L "$INITIAL_CREDENTIALS" ]] || fail "$INITIAL_CREDENTIALS must not be a symbolic link"
        install -o root -g root -m 0600 /dev/null "$INITIAL_CREDENTIALS"
        {
            echo "Rosy initial API credentials — remove this file after recording them"
            echo "administrator=$admin_token"
            echo "operator=$operator_token"
            echo "viewer=$viewer_token"
        } >"$INITIAL_CREDENTIALS"
        chmod 0600 "$INITIAL_CREDENTIALS"
        INITIAL_CREDENTIALS_CREATED=1
        rm -f "$config_tmp"
        trap - RETURN
    else
        echo "INFO: preserving existing $ROSY_CONFIG"
    fi
    [[ -f "$ROSY_CONFIG" ]] || fail "$ROSY_CONFIG must be a regular file"
    if grep -Eq "CHANGE_ME|rosy-dev-" "$ROSY_CONFIG"; then
        fail "$ROSY_CONFIG contains placeholder or development credentials"
    fi
    chown root:"$run_group" "$ROSY_CONFIG"
    chmod 0640 "$ROSY_CONFIG"
}

set_env_value() {
    local file="$1" key="$2" value="$3"
    if grep -q "^${key}=" "$file"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$file"
    else
        printf '%s=%s\n' "$key" "$value" >>"$file"
    fi
}

set_env_default() {
    local file="$1" key="$2" value="$3"
    if ! grep -q "^${key}=" "$file"; then
        printf '%s=%s\n' "$key" "$value" >>"$file"
    fi
}

get_env_value() {
    local file="$1" key="$2" value
    value="$(sed -n "s/^${key}=//p" "$file" | tail -n 1)"
    printf '%s' "${value%$'\r'}"
}

# 신원은 로봇 번호 하나에서 나온다 (ADR D-33). 예전에는 .env.example 이 42/rosy_01 을
# 값으로 들고 있어서 set_env_default 가 영영 발화하지 못했고, 모든 기기가 같은
# 도메인/네임스페이스로 출고됐다. 그래서 여기서 요구하고, 범위를 막고, 불일치를
# 소리내어 깬다.
require_robot_identity() {
    local env_file="$1" number domain namespace existing key
    declare -A derived
    number="${ROSY_ROBOT_NUMBER:-}"
    [[ -n "$number" ]] || fail "set ROSY_ROBOT_NUMBER=<n> — 로봇 번호가 없으면 신원을 만들 수 없다 (ADR D-33)"
    # 앞자리 0 을 허용하면 안 된다. bash 산술이 010 을 팔진수로 읽어 도메인 48 /
    # rosy_08 을 조용히 배정한다 — 도메인과 네임스페이스가 사이좋게 틀리므로
    # 아무것도 눈치채지 못하고 8호기와 충돌한다. 08 과 09 는 아예 bash 내부
    # 오류로 죽는다. 010 이 10 인지 8 인지는 우리가 정할 일이 아니라 거절할 일이다.
    [[ "$number" =~ ^(0|[1-9][0-9]*)$ ]] || fail "ROSY_ROBOT_NUMBER must be a decimal integer with no leading zero, got '$number'"
    domain=$((40 + 10#$number))
    # rosy_core 의 parse_domain_id (runtime/core/core/system/ros_graph.py) 가 주는 것과 같은 경계.
    (( domain >= 0 && domain <= 101 )) || fail "ROS_DOMAIN_ID must be in the Linux-safe range 0 to 101; ROSY_ROBOT_NUMBER=$number gives $domain"
    namespace="$(printf 'rosy_%02d' "$number")"

    # 이미 자리잡은 기기를 조용히 다른 번호로 바꾸지 않는다 — set_env_default 는 값이
    # 있으면 아무 말 없이 지나가므로, 불일치는 여기서 직접 잡아야 한다.
    derived[ROS_DOMAIN_ID]="$domain"
    derived[ROSY_NAMESPACE]="$namespace"
    derived[ROSY_ROBOT_NUMBER]="$number"
    # 검사를 먼저 다 하고 나서 쓴다. 한 키를 쓰고 다음 키에서 실패하면 도메인과
    # 네임스페이스가 어긋난 채로 남는데, 신원이 절반만 이주한 기기가 바로 이
    # 작업이 없애려는 상태다.
    for key in ROS_DOMAIN_ID ROSY_NAMESPACE ROSY_ROBOT_NUMBER; do
        existing="$(get_env_value "$env_file" "$key")"
        if [[ -n "$existing" && "$existing" != "${derived[$key]}" ]]; then
            fail "$env_file already has $key=$existing but ROSY_ROBOT_NUMBER=$number derives ${derived[$key]}. 이 기기는 이미 다른 번호로 자리잡았다 — 재번호 절차는 docs/deployment/raspberry-pi-runtime.md 를 따르라."
        fi
    done
    set_env_default "$env_file" ROS_DOMAIN_ID "$domain"
    set_env_default "$env_file" ROSY_NAMESPACE "$namespace"
    set_env_default "$env_file" ROSY_ROBOT_NUMBER "$number"
}

# First-boot unit always runs core. Requested preset/slices are commissioning
# intent, not the mode systemd starts now.
write_install_runtime_selection() {
    local env_file="$1"
    set_env_value "$env_file" ROSY_RUNTIME_MODE core
    if [[ -n "${INSTALL_REQUESTED_PRESET:-}" ]]; then
        set_env_value "$env_file" ROSY_REQUESTED_PRESET "$INSTALL_REQUESTED_PRESET"
    fi
    if [[ -n "${INSTALL_REQUESTED_SLICES:-}" ]]; then
        set_env_value "$env_file" ROSY_REQUESTED_SLICES "$INSTALL_REQUESTED_SLICES"
    fi
}

write_runtime_environment() {
    local env_file run_group dialout_gid video_gid i2c_gid
    env_file="$INSTALL_ROOT/deploy/robot/.env"
    run_group="$(id -gn "$RUN_USER")"
    dialout_gid="$(getent group dialout | cut -d: -f3)"
    [[ -n "$dialout_gid" ]] || fail "the dialout group is unavailable"
    video_gid="$(getent group video | cut -d: -f3)"
    i2c_gid="$(getent group i2c | cut -d: -f3)"
    [[ -n "$video_gid" ]] || video_gid=44
    [[ -n "$i2c_gid" ]] || i2c_gid=998
    if [[ ! -f "$env_file" ]]; then
        install -o root -g "$run_group" -m 0640 \
            "$INSTALL_ROOT/deploy/robot/.env.example" "$env_file"
    fi
    [[ ! -L "$env_file" && -f "$env_file" ]] || fail "$env_file must be a regular non-symlink file"
    require_robot_identity "$env_file"
    set_env_value "$env_file" ROSY_UID "$(id -u "$RUN_USER")"
    set_env_value "$env_file" ROSY_GID "$(id -g "$RUN_USER")"
    set_env_value "$env_file" ROSY_DIALOUT_GID "$dialout_gid"
    set_env_value "$env_file" ROSY_VIDEO_GID "$video_gid"
    set_env_value "$env_file" ROSY_I2C_GID "$i2c_gid"
    set_env_default "$env_file" ROSY_MOTOR_BAUDRATE 1000000
    set_env_default "$env_file" ROSY_MOTOR_IDS '[1,2]'
    set_env_default "$env_file" ROSY_MAX_LINEAR_MPS 0.20
    set_env_default "$env_file" ROSY_MAX_ANGULAR_RPS 0.80
    set_env_default "$env_file" ROSY_MAX_WHEEL_RPM 100.0
    set_env_default "$env_file" ROSY_MOTOR_PROFILE_ACCELERATION 200
    set_env_value "$env_file" ROSY_CONFIG_PATH "$ROSY_CONFIG"
    set_env_value "$env_file" ROSY_DATA_PATH "$ROSY_DATA"
    write_install_runtime_selection "$env_file"
    chown root:"$run_group" "$env_file"
    chmod 0640 "$env_file"
}

build_and_start_core() {
    local runtime_dir container_id status
    runtime_dir="$INSTALL_ROOT/deploy/robot"
    cd "$runtime_dir"
    ROSY_RUNTIME_MODE=core "$runtime_dir/runtime-mode.sh" down
    docker compose --env-file .env build rosy-core
    ROSY_RUNTIME_MODE=core "$runtime_dir/runtime-mode.sh" up
    container_id="$(docker compose --env-file .env ps -q rosy-core)"
    [[ -n "$container_id" ]] || fail "rosy-core container was not created"
    for _ in {1..45}; do
        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
        [[ "$status" == "healthy" ]] && break
        [[ "$status" == "exited" || "$status" == "dead" ]] && fail "rosy-core entered state: $status"
        sleep 2
    done
    [[ "${status:-}" == "healthy" ]] || fail "rosy-core did not become healthy within 90 seconds"
    curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8080/api/v1 >/dev/null \
        || fail "FastAPI health request failed"
}

enable_boot_service() {
    install -m 0644 "$INSTALL_ROOT/deploy/robot/rosy-release-recover.service" \
        /etc/systemd/system/rosy-release-recover.service
    chmod 0755 "$INSTALL_ROOT/deploy/robot/release-recover.sh"
    install -m 0644 "$INSTALL_ROOT/deploy/robot/rosy-runtime.service" \
        /etc/systemd/system/rosy-runtime.service

    # Low-battery guarded shutdown (D-27). Only the path unit is enabled: the
    # service has no [Install] section on purpose, because /var/lib/rosy is
    # persistent and a stale sentinel must not halt a fresh boot on its own.
    chmod 0755 "$INSTALL_ROOT/deploy/robot/rosy-lowbatt-shutdown.sh"
    install -m 0644 "$INSTALL_ROOT/deploy/robot/rosy-lowbatt-shutdown.service" \
        /etc/systemd/system/rosy-lowbatt-shutdown.service
    install -m 0644 "$INSTALL_ROOT/deploy/robot/rosy-lowbatt-shutdown.path" \
        /etc/systemd/system/rosy-lowbatt-shutdown.path

    systemctl daemon-reload
    systemctl enable --now rosy-runtime.service
    systemctl enable --now rosy-lowbatt-shutdown.path
}

main() {
    parse_install_cli "$@"
    require_root
    preflight_host
    stop_existing_runtime
    install_host_packages
    install_release
    write_initial_config
    write_runtime_environment
    build_and_start_core
    enable_boot_service
    UPGRADE_GUARD_ACTIVE=0
    echo "PASS: Rosy core-only runtime is installed and healthy"
    if [[ -n "${INSTALL_REQUESTED_PRESET:-}" ]]; then
        echo "INFO: requested preset ${INSTALL_REQUESTED_PRESET} recorded; ROSY_RUNTIME_MODE stays core until commissioning"
    fi
    if [[ -n "${INSTALL_REQUESTED_SLICES:-}" ]]; then
        echo "INFO: requested slices ${INSTALL_REQUESTED_SLICES} recorded; ROSY_RUNTIME_MODE stays core until commissioning"
    fi
    if ((INITIAL_CREDENTIALS_CREATED)); then
        echo "Credentials: sudo cat $INITIAL_CREDENTIALS"
        echo "After recording them: sudo rm -f $INITIAL_CREDENTIALS"
    else
        echo "INFO: existing credentials were preserved; no new credential file was created"
    fi
    echo "Verify Wi-Fi/dashboard: sudo $INSTALL_ROOT/deploy/robot/verify/verify-pi.sh --require-internet"
}

main "$@"
